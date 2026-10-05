"""
Builds the shared `cohortquery_mirror.duckdb` from the raw Metalog downloads and the
existing SRA DuckDB. Run once (or on refresh), by the lab — never at package
runtime. See Docs/superpowers/plans/2026-06-18-metalog-duckdb-build.md.

NEITHER SRA table is copied in. Both are exposed as VIEWs over sorted sidecar files
built beforehand, and the mirror records their paths in `mirror_config` so the package
re-attaches on connect. Copying them would double hundreds of GB AND throw away the
sort order, which is the whole point: sorted by its read key, a cohort filter prunes
row groups instead of scanning the table. Measured on a 3,573-biosample cohort, the
metadata read went from 1,772s to 50s on sort alone (20 of 319 row groups touched).

This script is therefore step 3 of 3, and the first two must already have run:

    step1_sort_taxonomy.py  tax_raw      -> sra_taxonomy_sorted.duckdb  (~2 h)
    step2_sort_metadata.py  metadata_raw -> sra_metadata_sorted.duckdb  (~7 min)
    step3_assemble_mirror.py           this file    -> cohortquery_mirror.duckdb        (~1 h)

`build_all.sh` runs the three in order. The mirror itself stays small (~13 GB) and is
cheap to rebuild; the expensive sorted artifacts are built once per SRA download.

Usage:
    python Scripts/build_mirror/steps/step3_assemble_mirror.py \
        --metalog-dir ~/Downloads/Metalog \
        --sorted-taxonomy /path/to/sra_taxonomy_sorted.duckdb \
        --sorted-metadata /path/to/sra_metadata_sorted.duckdb \
        --out cohortquery_mirror.duckdb
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import duckdb

# The mirror_config key -> ATTACH alias contract. A view definition bakes in the alias
# it was written against, so the build and the runtime MUST agree; importing the single
# definition is what guarantees that. See cohortquery.adapters.
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))
from cohortquery.adapters import SIDECAR_ALIASES          # noqa: E402

TAXONOMY_ALIAS = SIDECAR_ALIASES["sra_db_path"]
METADATA_ALIAS = SIDECAR_ALIASES["sra_metadata_path"]

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



def _staging_path(out_path: Path) -> Path:
    """A sibling of the target, so the final rename stays on one filesystem and is
    therefore atomic. Any leftover from a previous crashed run is discarded."""
    staging = out_path.with_name(out_path.name + ".building")
    staging.unlink(missing_ok=True)
    return staging

class MirrorBuilder:
    """Builds and verifies the SRA x Metalog DuckDB mirror. One method per build step."""

    def __init__(self, metalog_dir: Path, sorted_taxonomy: Path, sorted_metadata: Path,
                 out_path: Path, threads: int | None = None,
                 memory_limit: str | None = None, temp_dir: Path | None = None):
        self.metalog_dir = metalog_dir
        self.sorted_taxonomy = sorted_taxonomy
        self.sorted_metadata = sorted_metadata
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
            con.execute(f"ATTACH '{self.sorted_taxonomy}' AS {TAXONOMY_ALIAS} (READ_ONLY)")
            con.execute(f"ATTACH '{self.sorted_metadata}' AS {METADATA_ALIAS} (READ_ONLY)")
            self._load_profiles(con)
            self._load_metadata(con)
            self._load_sra(con)
            self._stamp_biosample(con)
            self._stat_coverage(con)
            self._create_indexes(con)
            self._verify(con)
            self._report_partial()
            con.close()
        except BaseException:
            # never leave a partial artifact behind -- these run to 128GB
            staging.unlink(missing_ok=True)
            raise
        staging.replace(self.out_path)

    def _configure(self, con: duckdb.DuckDBPyConnection) -> None:
        """Cluster settings. Scanning 13.6B rows spills, and the default temp directory
        is /tmp -- small on a compute node, and shared. Point it at real storage."""
        if self.threads:
            con.execute(f"SET threads = {self.threads}")
        if self.memory_limit:
            con.execute(f"SET memory_limit = '{self.memory_limit}'")
        if self.temp_dir:
            Path(self.temp_dir).mkdir(parents=True, exist_ok=True)
            con.execute(f"SET temp_directory = '{self.temp_dir}'")

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
        """Copy NEITHER SRA table -- both are views over their sorted sidecar.

        Copying would double hundreds of GB and, worse, discard the sort order these
        files exist for. Sorted by its read key, each table lets a cohort filter prune
        row groups: the cohort touches 20 of sra_metadata's 319 groups instead of all
        319, and pays only for the rows it wants out of tax_fact's 13.6 BILLION.

        The views persist in the mirror file and resolve whenever the package
        re-attaches, which it does by reading the paths recorded below. Indexes live in
        the sidecars (built there), not here -- a view cannot be indexed.
        """
        con.execute(f"CREATE VIEW sra_taxonomy AS SELECT * FROM {TAXONOMY_ALIAS}.tax_fact")
        con.execute(f"CREATE VIEW sra_metadata AS SELECT * FROM {METADATA_ALIAS}.metadata_fact")
        con.execute("CREATE TABLE mirror_config (key VARCHAR, value VARCHAR)")
        con.execute("INSERT INTO mirror_config VALUES ('sra_db_path', ?), ('sra_metadata_path', ?)",
                    [str(self.sorted_taxonomy), str(self.sorted_metadata)])

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
        # Neither SRA table is indexed here: both are VIEWs over their sorted sidecar,
        # and a view cannot be indexed. step2_sort_metadata.py builds
        # idx_metadata_fact_{biosample,acc} inside its own file. Sort order is the
        # primary access path either way -- the indexes only serve point lookups.
        con.execute("CREATE INDEX idx_stat_coverage_acc ON stat_coverage (acc)")
        for table in PROFILE_SPECS:
            con.execute(f"CREATE INDEX idx_{table}_alias ON {table} (sample_alias)")
            con.execute(f"CREATE INDEX idx_{table}_biosample ON {table} (biosample)")

    def _report_partial(self) -> None:
        """This script builds SEVEN of the eleven tables the package needs. Saying so
        is the difference between a user noticing now and discovering it mid-question,
        which is exactly how this went wrong before."""
        print("\n-- NOTE: this is a PARTIAL mirror --")
        print("   attribute_keys_index/attribute_values_index, schema_catalog and")
        print("   column_value_embeddings still have to be built, or discovery has")
        print("   no vocabulary to work with:")
        print("     step7_build_attribute_indexes.py --db <out>")
        print("     step5_catalog_schema.py  --db <out>")
        print("     step6_embed_concepts.py --db <out>")
        print("   build_all.sh runs all of them in order.")

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
    parser.add_argument("--sorted-taxonomy", type=Path, required=True,
                        help="sra_taxonomy_sorted.duckdb from step1_sort_taxonomy.py")
    parser.add_argument("--sorted-metadata", type=Path, required=True,
                        help="sra_metadata_sorted.duckdb from step2_sort_metadata.py")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--threads", type=int, default=None)
    parser.add_argument("--memory-limit", default=None, help="e.g. 400GB")
    parser.add_argument("--temp-dir", type=Path, default=None,
                        help="DuckDB spill directory -- NOT /tmp on a compute node")
    args = parser.parse_args()

    MirrorBuilder(args.metalog_dir, args.sorted_taxonomy, args.sorted_metadata, args.out,
                  args.threads, args.memory_limit, args.temp_dir).build()


if __name__ == "__main__":
    main()
