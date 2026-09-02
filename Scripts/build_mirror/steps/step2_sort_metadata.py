"""
Rewrites `sra_metadata` (39.1M rows, `biosample` unclustered) into the same table
sorted by `biosample`. The mirror of step1_sort_taxonomy.py, one level down.

Why: in a column store sort order IS the index. The cohort's biosamples are scattered
across the current physical order, so a cohort filter touches ALL 319 row groups and
DuckDB decompresses every column -- including the 28GB `jattr` -- to pull out a few
thousand rows. Measured 2026-08-31 by simulating the sorted layout: the same cohort
touches only 20 of 319 row groups once sorted, and DuckDB's per-value zone-map pruning
was confirmed to exploit that (16 accessions drawn at random across the whole keyspace
still answered in ~0.15s against the already-sorted tax_fact).

ALL 37 columns are kept, `jattr` included. Discovery reads `jattr` in its WHERE clause
(prompt.py steers the LLM to json_extract_string) and cannot work without it -- the
separate proposal to stop PROJECTING jattr belongs in metadata.py, not here.

Reads `metadata_raw` straight from the STAT download, NOT from the mirror. The mirror
is built AFTER this file and holds `sra_metadata` as a view over it, so sourcing from
the mirror would be circular in a from-zero build. Same input as step1_sort_taxonomy.py.

Never mutates the source. Writes a new file, source opened READ_ONLY throughout.

Usage:
    python scripts/step2_sort_metadata.py \
        --sra-db /private/pinto-lab/STAT/sra_processed.duckdb \
        --out /private/pinto-lab/tools/just-ask/mirror/sra_metadata_sorted.duckdb \
        --threads 16 --memory-limit 380GB --temp-dir /path/to/spill
"""
from __future__ import annotations

import argparse
import time
from pathlib import Path

import duckdb

# No baked-in row count: the whole point of this script is that a customer runs it
# against THEIR SRA download. The invariant is "the rewrite lost nothing", which is a
# comparison against the source, not against the Pinto lab's numbers.
SAMPLE_KEYS = 200   # random biosamples pulled from the source for the bit-identical check
ROW_GROUP = 122_880  # DuckDB's fixed row group size; not tunable in 1.5.5



def _staging_path(out_path: Path) -> Path:
    """A sibling of the target, so the final rename stays on one filesystem and is
    therefore atomic. Any leftover from a previous crashed run is discarded."""
    staging = out_path.with_name(out_path.name + ".building")
    staging.unlink(missing_ok=True)
    return staging

class SortedMetadataBuilder:
    """Builds and verifies the sorted metadata_fact table. One method per build step."""

    def __init__(self, sra_db: Path, out_path: Path,
                 threads: int | None = None, memory_limit: str | None = None,
                 temp_dir: Path | None = None):
        self.sra_db = sra_db
        self.out_path = out_path
        self.threads = threads
        self.memory_limit = memory_limit
        self.temp_dir = temp_dir

    def build(self) -> None:
        """Builds into a staging file and renames it over `out_path` only once every
        check has passed. Never unlink the target first: these builds take minutes to
        hours, so deleting up front leaves the lab with NOTHING for the whole run and
        forever if it fails. Path.replace is os.replace -- atomic within a filesystem,
        so readers see either the old file or the new one, never a half-written mirror.

        DuckDB will not CREATE TABLE into a file that already has them, which is what
        the unlink was really for; a fresh staging path solves that without risking the
        live artifact.
        """
        staging = _staging_path(self.out_path)
        try:
            con = duckdb.connect(str(staging))
            self._configure(con)
            con.execute(f"ATTACH '{self.sra_db}' AS src (READ_ONLY)")
            self._sort(con)
            self._index(con)
            self._verify(con)
            con.close()
        except BaseException:
            # never leave a partial artifact behind -- these run to 128GB
            staging.unlink(missing_ok=True)
            raise
        staging.replace(self.out_path)

    def _configure(self, con: duckdb.DuckDBPyConnection) -> None:
        if self.threads:
            con.execute(f"SET threads = {self.threads}")
        if self.memory_limit:
            con.execute(f"SET memory_limit = '{self.memory_limit}'")
        if self.temp_dir:
            Path(self.temp_dir).mkdir(parents=True, exist_ok=True)
            con.execute(f"SET temp_directory = '{self.temp_dir}'")

    def _sort(self, con: duckdb.DuckDBPyConnection) -> None:
        """SELECT * -- every column is kept. This is a reordering, not a narrowing."""
        print("sorting sra_metadata by biosample -- external merge sort over ~46GB",
              flush=True)
        start = time.monotonic()
        con.execute("""
            CREATE TABLE metadata_fact AS
            SELECT * FROM src.metadata_raw
            ORDER BY biosample
        """)
        print(f"sort finished in {time.monotonic() - start:.1f}s", flush=True)

    def _index(self, con: duckdb.DuckDBPyConnection) -> None:
        """The source carries these two; keep them so nothing regresses on point lookups.
        Zone-map pruning is what this rewrite is for, but `acc` equality still wants an index."""
        for column in ("biosample", "acc"):
            start = time.monotonic()
            con.execute(f"CREATE INDEX idx_metadata_fact_{column} ON metadata_fact ({column})")
            print(f"index on {column}: {time.monotonic() - start:.1f}s", flush=True)

    def _verify(self, con: duckdb.DuckDBPyConnection) -> None:
        rows = con.execute("SELECT count(*) FROM metadata_fact").fetchone()[0]
        expected = con.execute("SELECT count(*) FROM src.metadata_raw").fetchone()[0]
        print(f"row count: {rows} (source has {expected})")
        assert rows == expected, "row count changed across the rewrite"

        src_cols = [r[0] for r in con.execute("DESCRIBE src.metadata_raw").fetchall()]
        new_cols = [r[0] for r in con.execute("DESCRIBE metadata_fact").fetchall()]
        print(f"columns: {len(new_cols)} (expected {len(src_cols)})")
        assert new_cols == src_cols, f"column set/order changed: {set(src_cols) ^ set(new_cols)}"

        ordered = con.execute("""
            SELECT count(*) FROM (
                SELECT biosample, lag(biosample) OVER (ORDER BY rowid) AS prev
                FROM metadata_fact) WHERE prev IS NOT NULL AND biosample < prev
        """).fetchone()[0]
        print(f"rows out of sort order: {ordered} (expected 0)")
        assert ordered == 0, "the sort did not take"

        keys = [r[0] for r in con.execute(
            f"SELECT DISTINCT biosample FROM metadata_fact WHERE biosample IS NOT NULL "
            f"USING SAMPLE {SAMPLE_KEYS} ROWS").fetchall()]
        only_new, only_old = con.execute("""
            WITH rebuilt AS (SELECT * FROM metadata_fact
                             WHERE biosample IN (SELECT unnest(?::VARCHAR[]))),
                 original AS (SELECT * FROM src.metadata_raw
                              WHERE biosample IN (SELECT unnest(?::VARCHAR[])))
            SELECT (SELECT count(*) FROM (SELECT * EXCLUDE (attributes) FROM rebuilt
                                          EXCEPT SELECT * EXCLUDE (attributes) FROM original)),
                   (SELECT count(*) FROM (SELECT * EXCLUDE (attributes) FROM original
                                          EXCEPT SELECT * EXCLUDE (attributes) FROM rebuilt))
        """, [keys, keys]).fetchone()
        print(f"bit-identical check over {len(keys)} biosamples: "
              f"only_new={only_new} only_old={only_old}")
        assert only_new == 0 and only_old == 0, "sorted rows do not match the source"

        self._prune_probe(con, keys)

    def _prune_probe(self, con: duckdb.DuckDBPyConnection, keys: list[str]) -> None:
        """The whole point of the rewrite: does a cohort filter now prune row groups?
        Compares row groups touched, sorted vs the source's current order."""
        probe = keys[:64]
        for alias, table in (("sorted", "metadata_fact"), ("source", "src.metadata_raw")):
            touched = con.execute(
                f"SELECT count(DISTINCT rowid // {ROW_GROUP}) FROM {table} "
                f"WHERE biosample IN (SELECT unnest(?::VARCHAR[]))", [probe]).fetchone()[0]
            print(f"row groups touched by 64 biosamples, {alias}: {touched}")

        start = time.monotonic()
        rows = con.execute("SELECT * FROM metadata_fact "
                           "WHERE biosample IN (SELECT unnest(?::VARCHAR[]))",
                           [probe]).fetch_df()
        elapsed = time.monotonic() - start
        print(f"probe read (SELECT *, 64 biosamples): {elapsed:.1f}s -> {len(rows)} rows")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sra-db", type=Path, required=True,
                        help="the SRA DuckDB download holding metadata_raw")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--threads", type=int, default=None)
    parser.add_argument("--memory-limit", default=None, help="e.g. 150GB")
    parser.add_argument("--temp-dir", type=Path, default=None,
                        help="DuckDB spill directory")
    args = parser.parse_args()

    SortedMetadataBuilder(args.sra_db, args.out,
                          args.threads, args.memory_limit, args.temp_dir).build()


if __name__ == "__main__":
    main()
