"""
Builds the shared `askslm_mirror.duckdb` from the raw Metalog downloads and the
existing SRA DuckDB. Run once (or on refresh), by the lab — never at package
runtime. See Docs/superpowers/plans/2026-06-18-metalog-duckdb-build.md.

The SRA side is ATTACHED, not re-ingested: `metadata_raw` (~39M rows) is copied in
as `sra_metadata`, but `tax_raw` (~13.6 BILLION rows) is exposed as a VIEW named
`sra_taxonomy`. Copying it would double hundreds of GB for no benefit. The mirror
records the source path in `mirror_config` so the package re-attaches on connect.

Usage:
    python Scripts/build_mirror/build_duckdb.py \
        --metalog-dir ~/Downloads/Metalog \
        --sra-db /path/to/sra.duckdb \
        --out askslm_mirror.duckdb
"""
from __future__ import annotations

import argparse
from pathlib import Path

import duckdb

# Long-format profile tables: table name -> (glob pattern, environment regex marker).
# metaphlan4 (all-levels) needs a glob that excludes the metaphlan4_species files.
#
# metalog_metaphlan4_species is deliberately NOT built. Measured against the real files
# on 2026-08-17, in all four environments: ZERO samples appear only in the species table,
# while 846 appear only in all-levels. It is a strict subset, so it would show +0 unique
# in the plan render and mislead. A single-rank MetaPhlAn view is a row filter on
# clade_name (HLD G.3.4), which the parsed `rank` in feature metadata now supports.
#
#   Human 79,514 / 78,668 · Animal 10,177 / 9,761 · Ocean 5,246 / 5,086
#   Environmental 21,679 / 16,958      (all-levels / species, only-in-species = 0)
#
PROFILE_SPECS = {
    "metalog_metaphlan4": ("*_metaphlan4_[0-9]*.tsv.gz", "metaphlan4"),
    "metalog_motus3": ("*_motus3_*.tsv.gz", "motus3"),
    "metalog_spire_motus": ("*_spire_motus_*.tsv.gz", "spire_motus"),
}


class MirrorBuilder:
    """Builds and verifies the SRA x Metalog DuckDB mirror. One method per build step."""

    def __init__(self, metalog_dir: Path, sra_db: Path, out_path: Path):
        self.metalog_dir = metalog_dir
        self.sra_db = sra_db
        self.out_path = out_path

    def build(self) -> None:
        out_path = self.out_path
        if out_path.exists():
            out_path.unlink()
        con = duckdb.connect(str(out_path))
        con.execute(f"ATTACH '{self.sra_db}' AS sra (READ_ONLY)")
        self._load_profiles(con)
        self._load_metadata(con)
        self._load_sra(con)
        self._stamp_biosample(con)
        self._stat_coverage(con)
        self._create_indexes(con)
        self._verify(con)
        con.close()

    def _stat_coverage(self, con: duckdb.DuckDBPyConnection) -> None:
        """One row per run that STAT actually profiled -- the ONLY taxonomy-side build step.

        Preview asks "how many cohort samples does STAT cover?". Against the real table
        (13.6 BILLION rows) that is not a cheap count, so the scan is paid once here and
        preview joins this instead.

        This replaces stamping a biosample column onto sra_taxonomy, which would have
        rewritten all 13.6B rows. It is unnecessary because a STAT biom column is a RUN
        (HLD B.3): the read path is cohort biosamples -> run accessions via sra_metadata
        (small, indexed) -> sra_taxonomy by its existing acc key. The big table is only
        ever filtered by acc, never joined on biosample.
        """
        con.execute("CREATE TABLE stat_coverage AS SELECT DISTINCT acc FROM sra_taxonomy")

    def _load_profiles(self, con: duckdb.DuckDBPyConnection) -> None:
        profiles_dir = self.metalog_dir / "Taxonomic Profiles" / "*"
        for table, (glob, marker) in PROFILE_SPECS.items():
            con.execute(f"""
                CREATE TABLE {table} AS
                SELECT * EXCLUDE (filename),
                       regexp_extract(filename, '([a-z]+)_{marker}', 1) AS environment
                FROM read_csv('{profiles_dir / glob}',
                              delim='\t', header=true, filename=true, compression='gzip')
            """)

    def _load_metadata(self, con: duckdb.DuckDBPyConnection) -> None:
        metadata_glob = self.metalog_dir / "Metadata" / "*_extended_wide_*.tsv.gz"
        con.execute(f"""
            CREATE TABLE metalog_metadata AS
            SELECT * EXCLUDE (filename),
                   regexp_extract(filename, '([a-z]+)_extended_wide', 1) AS environment
            FROM read_csv('{metadata_glob}',
                          delim='\t', header=true, filename=true, compression='gzip', union_by_name=true)
        """)

    def _load_sra(self, con: duckdb.DuckDBPyConnection) -> None:
        """Copy the metadata; do NOT copy the taxonomy.

        sra_metadata is ~39M rows -- small enough to own, and it needs an index on
        biosample that the source may not have. sra_taxonomy is ~13.6 BILLION rows;
        copying it would double hundreds of GB for nothing, so it is a VIEW over the
        attached source database. The view persists in the mirror file and resolves
        whenever the package re-attaches (see mirror_config below).
        """
        con.execute("CREATE TABLE sra_metadata AS SELECT * FROM sra.metadata_raw")
        con.execute("CREATE VIEW sra_taxonomy AS SELECT * FROM sra.tax_raw")
        con.execute("CREATE TABLE mirror_config (key VARCHAR, value VARCHAR)")
        con.execute("INSERT INTO mirror_config VALUES ('sra_db_path', ?)", [str(self.sra_db)])

    def _stamp_biosample(self, con: duckdb.DuckDBPyConnection) -> None:
        """Resolve the sample_alias -> biosample two-hop ONCE; every table gets a `biosample` column."""
        con.execute("ALTER TABLE metalog_metadata ADD COLUMN biosample TEXT")
        con.execute("""
            UPDATE metalog_metadata m
            SET biosample = m.spire_sample_name
            WHERE m.spire_sample_name IN (SELECT biosample FROM sra_metadata)
        """)
        for table in PROFILE_SPECS:
            con.execute(f"ALTER TABLE {table} ADD COLUMN biosample TEXT")
            con.execute(f"""
                UPDATE {table} p
                SET biosample = m.biosample
                FROM metalog_metadata m
                WHERE p.sample_alias = m.sample_alias
            """)
        # sra_taxonomy is deliberately NOT stamped -- see _stat_coverage.

    def _create_indexes(self, con: duckdb.DuckDBPyConnection) -> None:
        con.execute("CREATE INDEX idx_metalog_metadata_alias ON metalog_metadata (sample_alias)")
        con.execute("CREATE INDEX idx_metalog_metadata_spire ON metalog_metadata (spire_sample_name)")
        con.execute("CREATE INDEX idx_metalog_metadata_biosample ON metalog_metadata (biosample)")
        con.execute("CREATE INDEX idx_sra_metadata_biosample ON sra_metadata (biosample)")
        con.execute("CREATE INDEX idx_sra_metadata_acc ON sra_metadata (acc)")
        # sra_taxonomy is a VIEW over the attached source -- cannot be indexed here.
        # tax_raw is filtered only by its own `acc`, which the source database indexes.
        con.execute("CREATE INDEX idx_stat_coverage_acc ON stat_coverage (acc)")
        for table in PROFILE_SPECS:
            con.execute(f"CREATE INDEX idx_{table}_alias ON {table} (sample_alias)")
            con.execute(f"CREATE INDEX idx_{table}_biosample ON {table} (biosample)")

    def _verify(self, con: duckdb.DuckDBPyConnection) -> None:
        print("-- row counts --")
        for table in [*PROFILE_SPECS, "metalog_metadata", "sra_metadata", "sra_taxonomy"]:
            count = con.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            print(f"{table}: {count}")

        join_count = con.execute("""
            SELECT count(*) FROM
              (SELECT DISTINCT spire_sample_name FROM metalog_metadata) m
              JOIN sra_metadata s ON m.spire_sample_name = s.biosample
        """).fetchone()[0]
        print(f"smoke test spire_sample_name <-> sra biosample overlap: {join_count}")

        print("-- spire_sample_name prefix histogram --")
        for prefix, count in con.execute("""
            SELECT regexp_extract(spire_sample_name, '^([A-Za-z]+)', 1) AS prefix, count(*)
            FROM metalog_metadata GROUP BY 1 ORDER BY 2 DESC LIMIT 10
        """).fetchall():
            print(f"{prefix}: {count}")

        print("-- biosample stamping (non-null vs null tail) --")
        for table in [*PROFILE_SPECS, "metalog_metadata"]:
            non_null, null = con.execute(f"""
                SELECT count(biosample), count(*) - count(biosample) FROM {table}
            """).fetchone()
            print(f"{table}: non_null={non_null} null={null}")
            multi = con.execute(f"""
                SELECT count(*) FROM (
                    SELECT sample_alias FROM {table}
                    WHERE biosample IS NOT NULL
                    GROUP BY sample_alias HAVING count(DISTINCT biosample) > 1
                )
            """).fetchone()[0]
            assert multi == 0, f"{table}: {multi} sample_alias map to >1 biosample"

        self._report_stat_runs(con)

    def _report_stat_runs(self, con: duckdb.DuckDBPyConnection) -> None:
        """How much does the one-column-per-run decision (B.3) actually affect this data?

        Reads stat_coverage joined to sra_metadata, never sra_taxonomy itself -- the
        whole point of the precompute is that nothing has to touch 13.6B rows again.
        """
        print("-- STAT runs per biosample --")
        profiled = """
            SELECT m.biosample AS biosample, c.acc AS acc
            FROM stat_coverage c LEFT JOIN sra_metadata m ON m.acc = c.acc
        """
        biosamples, runs = con.execute(f"""
            SELECT count(DISTINCT biosample), count(DISTINCT acc)
            FROM ({profiled}) WHERE biosample IS NOT NULL
        """).fetchone()
        multi_run = con.execute(f"""
            SELECT count(*) FROM (
                SELECT biosample FROM ({profiled}) WHERE biosample IS NOT NULL
                GROUP BY biosample HAVING count(DISTINCT acc) > 1
            )
        """).fetchone()[0]
        orphan_runs = con.execute(
            f"SELECT count(DISTINCT acc) FROM ({profiled}) WHERE biosample IS NULL"
        ).fetchone()[0]
        print(f"biosamples={biosamples} runs={runs} multi_run_biosamples={multi_run} "
              f"runs_with_no_biosample={orphan_runs}")

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--metalog-dir", type=Path, required=True)
    parser.add_argument("--sra-db", type=Path, required=True,
                        help="the existing SRA DuckDB holding metadata_raw and tax_raw")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    MirrorBuilder(args.metalog_dir, args.sra_db, args.out).build()


if __name__ == "__main__":
    main()
