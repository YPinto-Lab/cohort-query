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

Scope: only "useful text" jattr keys. numeric/date/id-like keys are excluded by a
key-level classifier using each key's own sampled values -- this drops ~45% of the
raw (row,key) corpus before any embedding work happens. This step no longer reads
the old attribute_keys table (deleted); it recomputes the key census itself.

Correctness note: jattr wraps most values in a single-element JSON array
(`["IBD"]`, not `"IBD"`) -- confirmed on the live mirror 2026-09-08, ~52% of
values, 99.9% of arrays have exactly one element. Unwrapped via a SECOND, cheap
JSON parse on the already-extracted (small) string, not a second pass over the
28GB jattr column -- so this costs one full-table scan, not two. A multi-element
array (the rare 0.1% case) takes its first element; not exact, an accepted
simplification (see the design note).

    python Scripts/build_mirror/steps/step7_build_attribute_indexes.py --db askslm_mirror.duckdb
"""
from __future__ import annotations

import argparse
import re
import sys
import time
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))
from askslm.concept_search import EMBED_DIM, Embedder

SAMPLE_ROWS_FOR_CLASSIFICATION = 200_000    # matches the removed step4's sampling rate
MAX_SAMPLES_PER_KEY = 3

# Sized from live-mirror timing 2026-09-08: a 400-key batch over the full table
# (39.1M rows) with SQL-side dedup completed cleanly, sane memory. Kept well under
# that as a safety margin, not pushed to the observed ceiling.
EXTRACTION_BATCH_SIZE = 250

NUMERIC_RE = re.compile(r"^-?\d+(\.\d+)?([eE]-?\d+)?$")
DATE_RE = re.compile(r"^\d{4}[-/]\d{1,2}([-/]\d{1,2})?$|^\d{1,2}[-/]\d{1,2}[-/]\d{2,4}$")
ID_NAME_RE = re.compile(
    r"(id|accession|barcode|uuid|guid|checksum|md5|url|_path$|filename|_name$|doi|isbn|"
    r"^ena_|^sra_|ncbi|_gid$|run_|index|number|code$)", re.IGNORECASE)
ID_VALUE_RE = re.compile(r"^[A-Za-z0-9]{16,}$")


def classify_key(key: str, samples: list[str]) -> str:
    """key-name pattern first (catches an ID column with no ID-shaped SAMPLE, e.g.
    only nulls sampled), then majority vote over the sampled values. Same heuristic
    used to size these tables on 2026-09-08 against the live mirror."""
    if not samples:
        return "empty"
    if all(NUMERIC_RE.match(s) for s in samples):
        return "numeric"
    if any(DATE_RE.match(s) for s in samples):
        return "date"
    if ID_NAME_RE.search(key):
        return "id_like_name"
    if all(ID_VALUE_RE.match(s.replace(" ", "")) for s in samples) and any(
        any(c.isdigit() for c in s) for s in samples
    ):
        return "id_like_value"
    return "useful_text"


class AttributeIndexBuilder:
    def __init__(self, db_path: Path, embedder: Embedder, dim: int = EMBED_DIM,
                 batch_size: int = EXTRACTION_BATCH_SIZE):
        self.db_path = db_path
        self.embedder = embedder
        self.dim = dim
        self.batch_size = batch_size

    def build(self) -> None:
        con = duckdb.connect(str(self.db_path))
        useful_keys = self._useful_text_keys(con)
        self._build_keys_index(con, useful_keys)
        self._build_values_index(con, useful_keys)
        self._report(con)
        con.close()

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
        value. Cheap -- reuses the key-only unnest, no value extraction."""
        start = time.monotonic()
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
        self._create_hnsw_index(con, "attribute_keys_index")
        con.execute("DROP TABLE key_presence")
        _log(f"  {len(keys)} keys indexed ({time.monotonic() - start:.1f}s)")

    def _build_values_index(self, con: duckdb.DuckDBPyConnection,
                            useful_keys: list[str]) -> None:
        """CONTENT table: distinct values, DEDUPED ACROSS ALL KEYS -- key is
        discarded by design (a value means the same thing regardless which field
        it came from). Batched: one json_extract_string(jattr, [paths...]) call
        per batch covers many keys in a single JSON parse per row."""
        start = time.monotonic()
        _log("building attribute_values_index (content)...")
        con.execute("DROP TABLE IF EXISTS attribute_values_index")
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
            con.execute("""
                INSERT INTO value_biosamples
                SELECT
                    CASE WHEN raw LIKE '[%]' THEN json_extract_string(raw, '$[0]')
                         ELSE raw END AS value,
                    biosample
                FROM (
                    SELECT biosample, UNNEST(json_extract_string(jattr, $paths)) AS raw
                    FROM sra_metadata
                    WHERE jattr IS NOT NULL
                )
                WHERE raw IS NOT NULL
            """, {"paths": paths})

        _log(f"  extraction done ({time.monotonic() - start:.1f}s), "
            f"deduping values across all keys...")
        dedup_start = time.monotonic()
        values_df = con.execute("""
            SELECT value, list(DISTINCT biosample) AS biosamples
            FROM value_biosamples
            GROUP BY value
        """).fetchdf()
        _log(f"  {len(values_df)} distinct values ({time.monotonic() - dedup_start:.1f}s)")

        con.execute(f"""
            CREATE TABLE attribute_values_index (
                value VARCHAR, embedding FLOAT[{self.dim}], biosample VARCHAR[])
        """)
        values = values_df["value"].tolist()
        vectors = self.embedder.embed(values)
        if len(vectors) != len(values):
            raise RuntimeError(
                f"embedder returned {len(vectors)} vectors for {len(values)} values")
        con.executemany(
            "INSERT INTO attribute_values_index VALUES (?, ?, ?)",
            [(value, vector, biosamples) for value, vector, biosamples
             in zip(values, vectors, values_df["biosamples"])])
        self._create_hnsw_index(con, "attribute_values_index")
        con.execute("DROP TABLE value_biosamples")
        _log(f"  attribute_values_index built ({time.monotonic() - start:.1f}s total)")

    def _create_hnsw_index(self, con: duckdb.DuckDBPyConnection, table: str) -> None:
        con.execute("INSTALL vss")
        con.execute("LOAD vss")
        con.execute("SET hnsw_enable_experimental_persistence = true")
        con.execute(f"CREATE INDEX {table}_idx ON {table} USING HNSW (embedding) "
                    "WITH (metric = 'cosine')")

    def _report(self, con: duckdb.DuckDBPyConnection) -> None:
        keys, values = con.execute(
            "SELECT (SELECT count(*) FROM attribute_keys_index), "
            "       (SELECT count(*) FROM attribute_values_index)").fetchone()
        print(f"attribute_keys_index: {keys} keys · "
              f"attribute_values_index: {values} values")


def _log(msg: str) -> None:
    print(msg, flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--dim", type=int, default=EMBED_DIM)
    parser.add_argument("--batch-size", type=int, default=EXTRACTION_BATCH_SIZE)
    args = parser.parse_args()

    from askslm.adapters import open_local_embedder

    AttributeIndexBuilder(args.db, open_local_embedder(), args.dim,
                          args.batch_size).build()


if __name__ == "__main__":
    main()
