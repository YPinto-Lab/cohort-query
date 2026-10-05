"""Build attribute_keys_index and attribute_values_index directly from jattr.

Supersedes the old attribute_keys / attribute_key_embeddings tables (removed --
see PR #49): those surfaced candidate key NAMES for the LLM to build SQL from and
then re-query. These two tables return matched BIOSAMPLES directly -- a nearest-
neighbor hit already carries its answer, no second query needed. See the
"Inverted Index Plan" design note.

  attribute_keys_index(key, embedding, biosample)     -- PRESENCE: has this field
                                                           at all, any value?
  attribute_values_index(value, embedding, biosample) -- CONTENT: has a value that
                                                           means X, under ANY key
                                                           (key is discarded by
                                                           design -- see the note).

Scope: two layers. (1) a key-level classifier (classify_key) picks which KEYS are
worth extracting from at all, using each key's own sampled values -- this drops
~78% of the raw key corpus before any embedding work happens, mainly for speed.
(2) VALUE_EXCLUDE_SQL then filters every individual VALUE pulled from a surviving
key -- a key can mix free text with numbers/dates/IDs (e.g. "5", "10", "unknown"
under the same key), and the key-level sample vote lets those through. This step
no longer reads the old attribute_keys table (deleted); it recomputes the key
census itself.

Correctness note: jattr wraps most values in a single-element JSON array
(`["IBD"]`, not `"IBD"`) -- confirmed on the live mirror 2026-09-08, ~52% of
values, 99.9% of arrays have exactly one element. Unwrapped via a SECOND, cheap
JSON parse on the already-extracted (small) string, not a second pass over the
28GB jattr column -- so this costs one full-table scan, not two. A multi-element
array (the rare 0.1% case) takes its first element; not exact, an accepted
simplification (see the design note).

    python Scripts/build_mirror/steps/step7_build_attribute_indexes.py --db cohortquery_mirror.duckdb
"""
from __future__ import annotations

import argparse
import re
import sys
import time
from pathlib import Path

import duckdb
import lancedb

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))
from cohortquery.adapters import attach_sidecars          # noqa: E402
from cohortquery.concept_search import EMBED_DIM, Embedder

SAMPLE_ROWS_FOR_CLASSIFICATION = 200_000    # matches the removed step4's sampling rate
MAX_SAMPLES_PER_KEY = 3

# Sized from live-mirror timing 2026-09-08: a 400-key batch over the full table
# (39.1M rows) with SQL-side dedup completed cleanly, sane memory. Kept well under
# that as a safety margin, not pushed to the observed ceiling.
EXTRACTION_BATCH_SIZE = 250

# How many values get embedded (and committed) per round-trip in
# _embed_values_in_chunks. Each chunk is a durability checkpoint -- a crash
# mid-embedding only re-embeds the chunk in flight, not the whole table. Not yet
# tuned against the real mirror's true scale (millions of distinct values); this
# is a starting point, not a measured optimum.
EMBED_CHUNK_SIZE = 50_000

# Search now goes through LanceDB/IVF_PQ, not DuckDB's vss/HNSW extension.
# HNSW's graph-walk rematerializes fully into RAM on every fresh connection
# (confirmed live: ~14min/~90GB RSS cold-query against the 14.9M-row values
# table, regardless of OS page-cache warmth); IVF_PQ's cluster-based access
# pattern is disk-friendly instead. The DuckDB tables below are now purely a
# computation staging area for extraction/dedup/embedding -- attribute_keys_index
# and attribute_values_index are read from here once and streamed into Lance;
# nothing queries them via DuckDB SQL anymore.

# rows written per Arrow batch when streaming a DuckDB table into Lance -- keeps
# peak memory bounded for the 14.9M-row values table without adding a second
# chunking scheme distinct from EMBED_CHUNK_SIZE above.
LANCE_WRITE_BATCH_ROWS = 100_000

# num_sub_vectors for IVF_PQ: dim(768) / 8, a common starting ratio for product
# quantization. Placeholder, not yet tuned -- same convention as this file's own
# TOP_K-style placeholders elsewhere in the codebase (e.g. jattr_concepts.py's
# TOP_K = 5). Revisit once the full 14.9M-row build actually runs.
LANCE_NUM_SUB_VECTORS = 96

# LanceDB's own rule of thumb wants a few hundred training vectors per IVF
# partition; below that it warns or errors about insufficient training data.
# Used to clamp num_partitions down for small tables (the 21,430-row keys
# table) instead of crashing the whole build.
LANCE_MIN_ROWS_PER_PARTITION = 256


def _ivf_num_partitions(row_count: int) -> int:
    """sqrt(row_count) is the textbook IVF starting point -- ~146 partitions for
    the 21,430-row keys table, ~3,860 for a 14.9M-row values table. Unverified,
    needs real tuning once the full build runs (see LANCE_NUM_SUB_VECTORS).
    Clamped so a table never asks for more partitions than it has training
    vectors for at LANCE_MIN_ROWS_PER_PARTITION each."""
    heuristic = max(1, int(row_count ** 0.5))
    max_supported = max(1, row_count // LANCE_MIN_ROWS_PER_PARTITION)
    return min(heuristic, max_supported)


NUMERIC_RE = re.compile(r"^-?\d+(\.\d+)?([eE]-?\d+)?$")
ID_NAME_RE = re.compile(
    r"(id|accession|barcode|uuid|guid|checksum|md5|url|_path$|filename|_name$|doi|isbn|"
    r"^ena_|^sra_|ncbi|_gid$|run_|index|number|code$)", re.IGNORECASE)
ID_VALUE_RE = re.compile(r"^[A-Za-z0-9]{16,}$")

# Submission/lab-process bookkeeping, not sample biology -- found live 2026-09-14
# investigating attribute_keys_index's most-skewed rows (primary_search alone
# touches all 39.1M sra_metadata rows). Deliberately narrow: broad-but-real
# biological fields (host_disease_sam, tissue_sam, collection_date_sam...) also
# have huge biosample counts and stay IN the index -- high coverage means "many
# samples record this fact", not "worthless". Precision for a specific query
# like "IBD" vs. a generic key like host_disease_sam is a similarity-threshold
# problem at query time (see jattr_concepts.py's TOP_K), not a build-time
# deletion -- this denylist is only for keys that carry no biological signal at
# all, regardless of coverage.
ADMIN_KEY_RE = re.compile(
    r"^primary_search$|^insdc_|collector_name|collected_by|collecting_institution|"
    r"broker_name|sequenced_by|project_name|study_name|research_project|"
    r"sample_center|experiment_center|work_request|^phs$|gap_parent_phs|"
    r"submission_tool|processing_robot|extraction_robot|_tool_exp$|extractionkit_lot|"
    r"water_lot|^plating_exp$|instrument_name|library_type|alignment_software|"
    r"^lane_run$|avgreadlength|^coverage_run$|nominal_length", re.IGNORECASE)

# Per-VALUE filter applied at extraction time, in SQL, on every individual value
# regardless of which key it came from -- classify_key's per-KEY sample vote lets
# numeric/date/id values through whenever they're mixed into an otherwise-textual
# key (confirmed on the live mirror 2026-09-09: 54% of a 200K sample of the
# resulting table were bare numbers). No space-stripping before the id-value
# check here (unlike classify_key) -- stripping spaces first would misclassify
# multi-word free text like "human sperm individual 3" as an opaque ID.
# "No information recorded" placeholders -- found live 2026-09-14 investigating
# attribute_values_index's most-skewed rows. Mostly the INSDC/MIxS controlled
# "missing value" vocabulary (not_applicable/missing/not_collected/not_provided/
# restricted_access), plus observed variants. These can never be a meaningful
# match for any real search concept, unlike common-but-real content (Homo
# sapiens, male, United Kingdom...) which stays regardless of coverage -- exact
# match only, so free text like "reason not applicable to controls" is untouched.
NO_INFO_VALUE_TOKENS = (
    "not applicable", "missing", "not collected", "not provided",
    "restricted access", "not determined", "not available", "none detected",
    "none", "na",
)

VALUE_EXCLUDE_SQL = r"""
    regexp_matches(value, '^-?[0-9]+(\.[0-9]+)?([eE]-?[0-9]+)?$')
    OR regexp_matches(value, '^[0-9]{4}[-/][0-9]{1,2}([-/][0-9]{1,2})?$')
    OR regexp_matches(value, '^[0-9]{1,2}[-/][0-9]{1,2}[-/][0-9]{2,4}$')
    OR (regexp_matches(value, '^[A-Za-z0-9]{16,}$') AND regexp_matches(value, '[0-9]'))
    OR lower(trim(value)) IN (""" + ", ".join(f"'{token}'" for token in NO_INFO_VALUE_TOKENS) + r""")
"""


def classify_key(key: str, samples: list[str]) -> str:
    """Coarse, fast pre-filter over which KEYS are worth extracting from at all
    (an "any sample looks like a date -> drop the whole key" rule used to live
    here too, but that drops legitimate free text sharing a key with one
    date-shaped sample -- date-ness, like numeric-ness and id-ness, is now a
    per-VALUE decision, see VALUE_EXCLUDE_SQL). key-name pattern first (catches
    an ID column with no ID-shaped SAMPLE, e.g. only nulls sampled), then
    majority vote over the sampled values."""
    if not samples:
        return "empty"
    if all(NUMERIC_RE.match(s) for s in samples):
        return "numeric"
    if ID_NAME_RE.search(key):
        return "id_like_name"
    if ADMIN_KEY_RE.search(key):
        return "administrative_metadata"
    if all(ID_VALUE_RE.match(s.replace(" ", "")) for s in samples) and any(
        any(c.isdigit() for c in s) for s in samples
    ):
        return "id_like_value"
    return "useful_text"


class AttributeIndexBuilder:
    def __init__(self, db_path: Path, embedder: Embedder, dim: int = EMBED_DIM,
                 batch_size: int = EXTRACTION_BATCH_SIZE,
                 embed_chunk_size: int = EMBED_CHUNK_SIZE,
                 threads: int | None = None, memory_limit: str | None = None,
                 temp_dir: Path | None = None):
        self.db_path = db_path
        self.embedder = embedder
        self.dim = dim
        self.batch_size = batch_size
        self.embed_chunk_size = embed_chunk_size
        self.threads = threads
        self.memory_limit = memory_limit
        self.temp_dir = temp_dir

    def build(self) -> None:
        con = duckdb.connect(str(self.db_path))
        self._configure(con)
        attach_sidecars(con)
        useful_keys = self._useful_text_keys(con)
        self._build_keys_index(con, useful_keys)
        self._build_values_index(con, useful_keys)
        self._write_lance_table(con, "attribute_keys_index", "key", self._lance_keys_dir)
        self._write_lance_table(con, "attribute_values_index", "value", self._lance_values_dir)
        self._report(con)
        con.close()

    @property
    def _lance_keys_dir(self) -> Path:
        return self.db_path.parent / "attribute_keys_index.lance"

    @property
    def _lance_values_dir(self) -> Path:
        return self.db_path.parent / "attribute_values_index.lance"

    def _configure(self, con: duckdb.DuckDBPyConnection) -> None:
        """Same convention as step3_assemble_mirror.py: this touches millions of
        rows with biosample lists attached, so the default temp directory (/tmp --
        small, shared on this cluster) and unbounded memory are not safe defaults
        for an unattended multi-hour job."""
        if self.threads:
            con.execute(f"SET threads = {self.threads}")
        if self.memory_limit:
            con.execute(f"SET memory_limit = '{self.memory_limit}'")
        if self.temp_dir:
            Path(self.temp_dir).mkdir(parents=True, exist_ok=True)
            con.execute(f"SET temp_directory = '{self.temp_dir}'")

    def _useful_text_keys(self, con: duckdb.DuckDBPyConnection) -> list[str]:
        """Census + classify, replacing the removed attribute_keys table's job."""
        start = time.monotonic()
        _log("census: counting every jattr key over the full table...")
        census = con.execute("""
            SELECT k, count(*) AS occurrences
            FROM (SELECT unnest(json_keys(jattr)) AS k FROM sra_metadata)
            GROUP BY k
        """).fetchdf()
        _log(f"  {len(census)} distinct keys ({time.monotonic() - start:.1f}s)")

        _log(f"sampling {SAMPLE_ROWS_FOR_CLASSIFICATION} rows for classification...")
        samples = con.execute(f"""
            SELECT k, list(DISTINCT v)[1:{MAX_SAMPLES_PER_KEY}] AS vs
            FROM (
                SELECT k, json_extract_string(jattr, '$.' || k) AS v
                FROM (SELECT jattr, unnest(json_keys(jattr)) AS k
                      FROM sra_metadata USING SAMPLE {SAMPLE_ROWS_FOR_CLASSIFICATION} ROWS)
                WHERE json_extract_string(jattr, '$.' || k) IS NOT NULL
            )
            GROUP BY k
        """).fetchdf()
        # DuckDB LIST columns arrive from fetchdf() as numpy arrays, not plain
        # lists -- `if not numpy_array:` raises ValueError for length > 1, so
        # normalize to plain lists here rather than at every call site.
        samples_by_key = {k: list(v) for k, v in zip(samples["k"], samples["vs"])}

        classes = [classify_key(k, samples_by_key.get(k, [])) for k in census["k"]]
        census["klass"] = classes
        useful = census[census["klass"] == "useful_text"].sort_values(
            "occurrences", ascending=False)
        _log(f"  {len(useful)} keys classified useful_text of {len(census)} total")
        return useful["k"].tolist()

    def _build_keys_index(self, con: duckdb.DuckDBPyConnection,
                          useful_keys: list[str]) -> None:
        """PRESENCE table: which biosamples have this key at all, regardless of
        value. Cheap -- reuses the key-only unnest, no value extraction.

        Resumable the same way as attribute_values_index: if the table already
        has rows, skip rebuilding entirely. Without this check a script restart
        (SLURM requeue, or a retry after attribute_values_index fails downstream)
        silently drops and redoes ~60-70min of already-correct work every time --
        confirmed wasted 2026-09-10/11 across three restarts of the real build."""
        start = time.monotonic()
        if self._table_has_rows(con, "attribute_keys_index"):
            _log("attribute_keys_index already built (resuming) -- skipping")
            return
        _log("building attribute_keys_index (presence)...")
        con.execute("DROP TABLE IF EXISTS attribute_keys_index")
        con.execute(f"""
            CREATE TABLE attribute_keys_index (
                key VARCHAR, embedding FLOAT[{self.dim}], biosample VARCHAR[])
        """)
        con.execute("""
            CREATE OR REPLACE TEMP TABLE key_presence AS
            SELECT k, list(DISTINCT biosample) AS biosamples
            FROM (SELECT biosample, unnest(json_keys(jattr)) AS k FROM sra_metadata)
            WHERE k = ANY(?)
            GROUP BY k
        """, [useful_keys])
        rows = con.execute("SELECT k, biosamples FROM key_presence").fetchall()
        keys = [row[0] for row in rows]
        vectors = self.embedder.embed(keys)
        if len(vectors) != len(keys):
            raise RuntimeError(
                f"embedder returned {len(vectors)} vectors for {len(keys)} keys")
        con.executemany(
            "INSERT INTO attribute_keys_index VALUES (?, ?, ?)",
            [(key, vector, row[1]) for key, vector, row in zip(keys, vectors, rows)])
        con.execute("DROP TABLE key_presence")
        _log(f"  {len(keys)} keys indexed ({time.monotonic() - start:.1f}s)")

    def _build_values_index(self, con: duckdb.DuckDBPyConnection,
                            useful_keys: list[str]) -> None:
        """CONTENT table: distinct values, DEDUPED ACROSS ALL KEYS -- key is
        discarded by design (a value means the same thing regardless which field
        it came from). Batched: one json_extract_string(jattr, [paths...]) call
        per batch covers many keys in a single JSON parse per row.

        Durability: the extraction+dedup pass (the expensive, hours-long part) is
        committed to a real table BEFORE embedding starts -- a crash during the
        embedding step must not cost that work again. Embedding itself runs in
        chunks, each committed as it completes and re-querying `WHERE embedding
        IS NULL` fresh rather than caching row identifiers up front (DuckDB's
        `rowid` is reassigned on UPDATE, confirmed directly 2026-09-09 -- caching
        rowids across chunks would silently target the wrong rows after the first
        chunk). This also makes the step naturally resumable: rerunning after a
        crash picks up wherever embedding left off instead of restarting."""
        start = time.monotonic()
        _log("building attribute_values_index (content)...")
        if not self._values_extracted(con):
            self._extract_and_persist_values(con, useful_keys, start)
        else:
            _log("  values already extracted and persisted (resuming) -- "
                f"skipping extraction+dedup")
        self._embed_values_in_chunks(con, self.embed_chunk_size)
        _log(f"  attribute_values_index built ({time.monotonic() - start:.1f}s total)")

    def _values_extracted(self, con: duckdb.DuckDBPyConnection) -> bool:
        return self._table_has_rows(con, "attribute_values_index")

    def _table_has_rows(self, con: duckdb.DuckDBPyConnection, table: str) -> bool:
        exists = con.execute(
            "SELECT count(*) FROM duckdb_tables() WHERE table_name = ?", [table]
        ).fetchone()[0]
        return bool(exists) and con.execute(
            f"SELECT count(*) FROM {table}").fetchone()[0] > 0

    def _extract_and_persist_values(self, con: duckdb.DuckDBPyConnection,
                                    useful_keys: list[str], start: float) -> None:
        con.execute("DROP TABLE IF EXISTS attribute_values_index")
        con.execute(f"""
            CREATE TABLE attribute_values_index (
                value VARCHAR, embedding FLOAT[{self.dim}], biosample VARCHAR[])
        """)
        con.execute("""
            CREATE OR REPLACE TEMP TABLE value_biosamples (
                value VARCHAR, biosample VARCHAR)
        """)

        for batch_start in range(0, len(useful_keys), self.batch_size):
            batch = useful_keys[batch_start:batch_start + self.batch_size]
            batch_no = batch_start // self.batch_size + 1
            total_batches = (len(useful_keys) + self.batch_size - 1) // self.batch_size
            _log(f"  batch {batch_no}/{total_batches} ({len(batch)} keys)...")
            paths = [f"$.{k}" for k in batch]
            con.execute(f"""
                INSERT INTO value_biosamples
                SELECT value, biosample FROM (
                    SELECT
                        CASE WHEN json_valid(raw) AND json_type(raw) = 'ARRAY'
                             THEN json_extract_string(raw, '$[0]')
                             ELSE raw END AS value,
                        biosample
                    FROM (
                        SELECT biosample, UNNEST(json_extract_string(jattr, $paths)) AS raw
                        FROM sra_metadata
                        WHERE jattr IS NOT NULL
                    )
                    WHERE raw IS NOT NULL
                )
                WHERE NOT ({VALUE_EXCLUDE_SQL})
            """, {"paths": paths})

        _log(f"  extraction done ({time.monotonic() - start:.1f}s), "
            f"deduping values across all keys...")
        dedup_start = time.monotonic()
        con.execute("""
            INSERT INTO attribute_values_index (value, biosample)
            SELECT value, list(DISTINCT biosample)
            FROM value_biosamples
            GROUP BY value
        """)
        n_values = con.execute("SELECT count(*) FROM attribute_values_index").fetchone()[0]
        _log(f"  {n_values} distinct values ({time.monotonic() - dedup_start:.1f}s) "
            f"-- persisted, safe from here")
        con.execute("DROP TABLE value_biosamples")

    def _embed_values_in_chunks(self, con: duckdb.DuckDBPyConnection,
                                chunk_size: int = EMBED_CHUNK_SIZE) -> None:
        total_remaining = con.execute(
            "SELECT count(*) FROM attribute_values_index WHERE embedding IS NULL"
        ).fetchone()[0]
        total = con.execute("SELECT count(*) FROM attribute_values_index").fetchone()[0]
        already_done = total - total_remaining
        _log(f"  embedding values in chunks of {chunk_size} "
            f"({already_done} already done, {total_remaining} remaining)...")
        embed_start = time.monotonic()
        done_this_run = 0
        while True:
            chunk = con.execute(
                "SELECT value FROM attribute_values_index "
                "WHERE embedding IS NULL LIMIT ?", [chunk_size]).fetchall()
            if not chunk:
                break
            values = [row[0] for row in chunk]
            vectors = self.embedder.embed(values)
            if len(vectors) != len(values):
                raise RuntimeError(
                    f"embedder returned {len(vectors)} vectors for {len(values)} values")
            con.execute("CREATE OR REPLACE TEMP TABLE chunk_vectors "
                       f"(value VARCHAR, vector FLOAT[{self.dim}])")
            con.executemany("INSERT INTO chunk_vectors VALUES (?, ?)",
                           list(zip(values, vectors)))
            con.execute("""
                UPDATE attribute_values_index a SET embedding = c.vector
                FROM chunk_vectors c WHERE a.value = c.value
            """)
            done_this_run += len(values)
            _log(f"    embedded {already_done + done_this_run}/{total} "
                f"({time.monotonic() - embed_start:.1f}s elapsed this run)")
        con.execute("DROP TABLE IF EXISTS chunk_vectors")

    def _write_lance_table(self, con: duckdb.DuckDBPyConnection, duckdb_table: str,
                           text_column: str, lance_dir: Path) -> None:
        """Reads the already-embedded rows straight out of the DuckDB table built
        above (extraction, dedup, and embedding are NOT redone here) and streams
        them into a sibling LanceDB dataset with an IVF_PQ index. See this file's
        module-level LanceDB comment for why IVF_PQ instead of HNSW.

        Resumable the same way as the DuckDB tables: if the Lance dataset already
        has the expected row count, skip the (expensive, full-table) rewrite."""
        expected_rows = con.execute(f"SELECT count(*) FROM {duckdb_table}").fetchone()[0]
        if self._lance_table_built(lance_dir, expected_rows):
            _log(f"  {lance_dir.name} already built ({expected_rows} rows, "
                "resuming) -- skipping")
            return
        _log(f"  writing {lance_dir.name} ({expected_rows} rows)...")
        start = time.monotonic()
        # A single 100K-row batch can hold a row like "Homo sapiens" (11M+
        # biosamples) whose serialized biosample-list string data alone
        # approaches Arrow's classic 2GB (int32-offset) string buffer limit --
        # confirmed live on the real attribute_values_index build 2026-09-14.
        # 64-bit offsets remove that ceiling.
        con.execute("SET arrow_large_buffer_size=true")
        reader = con.execute(
            f"SELECT {text_column}, embedding, biosample FROM {duckdb_table}"
        ).fetch_record_batch(rows_per_batch=LANCE_WRITE_BATCH_ROWS)
        db = lancedb.connect(str(lance_dir.parent))
        # No explicit schema: arrow_large_buffer_size makes DuckDB emit
        # large_string/large_list types for this data, and a hand-declared
        # regular-string schema forces a cast that fails on the very data too
        # big to fit without large buffers in the first place (confirmed live
        # 2026-09-14: "Failed casting from large_string to string: input array
        # too large"). Infer from the reader's own (correct) schema instead.
        table = db.create_table(lance_dir.stem, data=reader, mode="overwrite")
        self._create_ivf_pq_index(table, expected_rows)
        _log(f"  {lance_dir.name} written ({time.monotonic() - start:.1f}s)")

    def _lance_table_built(self, lance_dir: Path, expected_rows: int) -> bool:
        if not lance_dir.exists():
            return False
        db = lancedb.connect(str(lance_dir.parent))
        if lance_dir.stem not in db.table_names():
            return False
        return db.open_table(lance_dir.stem).count_rows() == expected_rows

    def _create_ivf_pq_index(self, table: "lancedb.table.Table", row_count: int) -> None:
        num_partitions = _ivf_num_partitions(row_count)
        if num_partitions < 2:
            _log(f"    skipping IVF_PQ index: {row_count} rows is too few to "
                "partition meaningfully -- revisit once real row counts are known")
            return
        try:
            table.create_index(index_type="IVF_PQ", num_partitions=num_partitions,
                              num_sub_vectors=LANCE_NUM_SUB_VECTORS, metric="cosine",
                              vector_column_name="embedding")
        except Exception as exc:
            # LanceDB errors (rather than degrades) when a table has too few
            # rows to train the requested number of partitions -- the table
            # itself is still written and usable via brute-force scan, so a
            # failed index build here must not crash the whole step.
            _log(f"    IVF_PQ index build failed ({exc}) -- table written but "
                "unindexed, revisit once real row counts are known")

    def _report(self, con: duckdb.DuckDBPyConnection) -> None:
        keys, values = con.execute(
            "SELECT (SELECT count(*) FROM attribute_keys_index), "
            "       (SELECT count(*) FROM attribute_values_index)").fetchone()
        print(f"attribute_keys_index: {keys} keys · "
              f"attribute_values_index: {values} values")


def _log(msg: str) -> None:
    print(msg, flush=True)


def main() -> None:
    import os

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--dim", type=int, default=EMBED_DIM)
    parser.add_argument("--batch-size", type=int, default=EXTRACTION_BATCH_SIZE)
    parser.add_argument("--embed-chunk-size", type=int, default=EMBED_CHUNK_SIZE,
                        help="values embedded (and committed) per checkpoint")
    parser.add_argument("--threads", type=int, default=None,
                        help="default: SLURM_CPUS_PER_TASK, else DuckDB's own default")
    parser.add_argument("--memory-limit", type=str, default=None,
                        help="e.g. 120GB; default: 80%% of SLURM_MEM_PER_NODE if set, "
                             "else DuckDB's own default")
    parser.add_argument("--temp-dir", type=Path, default=None,
                        help="default: unset (DuckDB's own default, /tmp)")
    args = parser.parse_args()

    threads = args.threads or (int(os.environ["SLURM_CPUS_PER_TASK"])
                               if "SLURM_CPUS_PER_TASK" in os.environ else None)
    memory_limit = args.memory_limit
    if memory_limit is None and "SLURM_MEM_PER_NODE" in os.environ:
        memory_limit = f"{int(os.environ['SLURM_MEM_PER_NODE']) * 8 // 10}MB"

    from cohortquery.adapters import open_local_embedder

    AttributeIndexBuilder(args.db, open_local_embedder(), args.dim, args.batch_size,
                          args.embed_chunk_size, threads=threads,
                          memory_limit=memory_limit, temp_dir=args.temp_dir).build()


if __name__ == "__main__":
    main()
