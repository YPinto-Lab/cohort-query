"""
Rewrites `tax_raw` (13.6 BILLION rows, no index, `acc` unclustered) into a narrow
table sorted by `acc`. In a column store sort order IS the index: DuckDB zone maps
then let a cohort filter prune row groups instead of scanning all 13.6B rows every
time. See Docs/superpowers/plans/2026-08-18-taxonomy-sort.html for the full plan.

Never mutates the source. Writes a new file, source opened READ_ONLY throughout.

Usage:
    python Scripts/build_mirror/build_sorted_taxonomy.py \
        --sra-db /private/pinto-lab/STAT/sra_processed.duckdb \
        --out /private/pinto-lab/tools/just-ask/mirror/sra_taxonomy_sorted.duckdb \
        --threads 16 --memory-limit 380GB --temp-dir /path/to/spill
"""
from __future__ import annotations

import argparse
import time
from pathlib import Path

import duckdb

# No baked-in row count / coverage: this runs against whatever SRA download the user
# has. The invariant is that the rewrite lost nothing, which is checked against the
# source itself. (Counting 13.6B rows twice is minutes, against a multi-hour sort.)
SAMPLE_ACCS = 200  # random accs pulled from the source for the bit-identical check



def _staging_path(out_path: Path) -> Path:
    """A sibling of the target, so the final rename stays on one filesystem and is
    therefore atomic. Any leftover from a previous crashed run is discarded."""
    staging = out_path.with_name(out_path.name + ".building")
    staging.unlink(missing_ok=True)
    return staging

class SortedTaxonomyBuilder:
    """Builds and verifies the sorted tax_fact table. One method per build step."""

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
        """The five descriptive columns (rank, name, ilevel, ileft, iright) are simply
        not selected -- they are per-taxon, stale, and unread now that STAT lineage
        comes from ete3 (Docs plan, section 3)."""
        print("sorting tax_raw by acc -- this is a full external merge sort, hours not minutes")
        start = time.monotonic()
        con.execute("""
            CREATE TABLE tax_fact AS
            SELECT acc, tax_id, total_count, self_count
            FROM src.tax_raw
            ORDER BY acc
        """)
        print(f"sort finished in {time.monotonic() - start:.1f}s")

    def _verify(self, con: duckdb.DuckDBPyConnection) -> None:
        row_count = con.execute("SELECT count(*) FROM tax_fact").fetchone()[0]
        expected = con.execute("SELECT count(*) FROM src.tax_raw").fetchone()[0]
        print(f"row count: {row_count} (source has {expected})")
        assert row_count == expected, "row count changed across the rewrite"

        coverage = con.execute("SELECT count(DISTINCT acc) FROM tax_fact").fetchone()[0]
        expected_coverage = con.execute(
            "SELECT count(DISTINCT acc) FROM src.tax_raw").fetchone()[0]
        print(f"distinct acc: {coverage} (source has {expected_coverage})")
        assert coverage == expected_coverage, "stat_coverage no longer matches"

        accs = [r[0] for r in con.execute(
            f"SELECT DISTINCT acc FROM tax_fact USING SAMPLE {SAMPLE_ACCS} ROWS"
        ).fetchall()]
        only_new, only_old = con.execute("""
            WITH rebuilt AS (
                SELECT acc, tax_id, total_count, self_count FROM tax_fact
                WHERE acc IN (SELECT unnest(?::VARCHAR[]))
            ), original AS (
                SELECT acc, tax_id, total_count, self_count FROM src.tax_raw
                WHERE acc IN (SELECT unnest(?::VARCHAR[]))
            )
            SELECT (SELECT count(*) FROM (SELECT * FROM rebuilt EXCEPT SELECT * FROM original)),
                   (SELECT count(*) FROM (SELECT * FROM original EXCEPT SELECT * FROM rebuilt))
        """, [accs, accs]).fetchone()
        print(f"bit-identical check over {len(accs)} accs: only_new={only_new} only_old={only_old}")
        assert only_new == 0 and only_old == 0, "sorted rows do not match the source"

        start = time.monotonic()
        probe_accs = accs[:16]
        rows = con.execute("""
            SELECT count(*) FROM tax_fact WHERE acc IN (SELECT unnest(?::VARCHAR[]))
        """, [probe_accs]).fetchone()[0]
        elapsed = time.monotonic() - start
        print(f"probe read, {len(probe_accs)} accs: {elapsed:.1f}s -> {rows} rows")
        assert elapsed < 60, (
            f"probe took {elapsed:.1f}s -- the sort did not take, do not cut over"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sra-db", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--threads", type=int, default=None)
    parser.add_argument("--memory-limit", default=None, help="e.g. 380GB")
    parser.add_argument("--temp-dir", type=Path, default=None,
                        help="DuckDB spill directory -- NOT /tmp on a compute node")
    args = parser.parse_args()

    SortedTaxonomyBuilder(args.sra_db, args.out,
                          args.threads, args.memory_limit, args.temp_dir).build()


if __name__ == "__main__":
    main()
