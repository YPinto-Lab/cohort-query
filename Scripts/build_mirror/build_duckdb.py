"""
Builds the shared `askslm_mirror.duckdb` from the raw Metalog downloads and the
SRA metadata/taxonomy CSVs. Run once (or on refresh), by the lab — never at
package runtime. See Docs/superpowers/plans/2026-06-18-metalog-duckdb-build.md.

Usage:
    python Scripts/build_mirror/build_duckdb.py \
        --metalog-dir ~/Desktop/Metalog \
        --sra-metadata Workspaces/IBDProjects/inputs/metadata.csv \
        --sra-taxonomy Workspaces/IBDProjects/inputs/taxonomy.csv \
        --out askslm_mirror.duckdb
"""
from __future__ import annotations

import argparse
from pathlib import Path

import duckdb

# Long-format profile tables: table name -> (glob pattern, environment regex marker).
# metaphlan4 (all-levels) needs a glob that excludes the metaphlan4_species files.
PROFILE_SPECS = {
    "metalog_metaphlan4_species": ("*_metaphlan4_species_*.tsv.gz", "metaphlan4_species"),
    "metalog_metaphlan4": ("*_metaphlan4_[0-9]*.tsv.gz", "metaphlan4"),
    "metalog_motus3": ("*_motus3_*.tsv.gz", "motus3"),
    "metalog_spire_motus": ("*_spire_motus_*.tsv.gz", "spire_motus"),
}


class MirrorBuilder:
    """Builds and verifies the SRA x Metalog DuckDB mirror. One method per build step."""

    def __init__(self, metalog_dir: Path, sra_metadata_csv: Path, sra_taxonomy_csv: Path, out_path: Path):
        self.metalog_dir = metalog_dir
        self.sra_metadata_csv = sra_metadata_csv
        self.sra_taxonomy_csv = sra_taxonomy_csv
        self.out_path = out_path

    def build(self) -> None:
        out_path = self.out_path
        if out_path.exists():
            out_path.unlink()
        con = duckdb.connect(str(out_path))
        self._load_profiles(con)
        self._load_metadata(con)
        self._load_sra(con)
        self._stamp_biosample(con)
        self._create_indexes(con)
        self._verify(con)
        con.close()

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
        con.execute(f"CREATE TABLE sra_metadata AS SELECT * FROM read_csv_auto('{self.sra_metadata_csv}')")
        con.execute(f"CREATE TABLE sra_taxonomy AS SELECT * FROM read_csv_auto('{self.sra_taxonomy_csv}')")

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

    def _create_indexes(self, con: duckdb.DuckDBPyConnection) -> None:
        con.execute("CREATE INDEX idx_metalog_metadata_alias ON metalog_metadata (sample_alias)")
        con.execute("CREATE INDEX idx_metalog_metadata_spire ON metalog_metadata (spire_sample_name)")
        con.execute("CREATE INDEX idx_metalog_metadata_biosample ON metalog_metadata (biosample)")
        con.execute("CREATE INDEX idx_sra_metadata_biosample ON sra_metadata (biosample)")
        con.execute("CREATE INDEX idx_sra_metadata_acc ON sra_metadata (acc)")
        con.execute("CREATE INDEX idx_sra_taxonomy_acc ON sra_taxonomy (acc)")
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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--metalog-dir", type=Path, required=True)
    parser.add_argument("--sra-metadata", type=Path, required=True)
    parser.add_argument("--sra-taxonomy", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    MirrorBuilder(args.metalog_dir, args.sra_metadata, args.sra_taxonomy, args.out).build()


if __name__ == "__main__":
    main()
