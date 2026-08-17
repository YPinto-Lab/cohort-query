"""Build a tiny DuckDB with the shape of the real askslm mirror.

The real mirror lives on the lab server and is ~41 GB. Development and the e2e test
(HLD H.2) need something with the same schema and the same *interesting structure*,
small enough to build in milliseconds. This constructs it from literals -- no raw
files, no network.

Schema follows Docs/superpowers/plans/2026-06-18-metalog-duckdb-build.md and
Scripts/build_mirror/build_duckdb.py, including the quirks that matter:

  - Metalog tables carry a build-stamped `biosample`, NULL for the orphan tail.
  - The Metalog profile lineage column differs per source: `clade_name` for
    MetaPhlAn, `species` for both mOTUs tables.
  - `sra_taxonomy` is keyed by run `acc`, NOT biosample, and one biosample can
    have several runs -- which per B.3 become several biom columns.

What the fixture is built to exercise:

  partition          8 shared · 6 SRA-only · 4 Metalog-only · 2 orphan (no biosample)
  family union       two MOTUS sources that overlap on 3 samples and each add their own
  head wins overlap  the 3 overlapping samples carry DIFFERENT values per source
  lineage union      spire has a species mOTUs3 has never seen
  multi-run STAT     SAMN00001 has two runs with distinct profiles -- per B.3 they
                     become two biom columns, never summed and never selected down
  value vocabulary   low-cardinality metadata columns with realistic literals

Build one:  python Tests/fixtures/mirror.py /tmp/fixture.duckdb
"""
from __future__ import annotations

import sys
from pathlib import Path

import duckdb

SHARED = [f"SAMN{n:05d}" for n in range(1, 9)]            # in both databases
SRA_ONLY = [f"SAMN{n:05d}" for n in range(9, 15)]         # SRA metadata only
METALOG_ONLY = [f"SAMN{n:05d}" for n in range(15, 19)]    # Metalog metadata only
ORPHANS = ["MG_ORPHAN_1", "MG_ORPHAN_2"]                  # Metalog, no BioSample

DISEASES = ["Crohn's disease", "ulcerative colitis", "healthy control"]
COUNTRIES = ["Germany", "United States", "Israel", "Japan"]


def build_fixture_mirror(path: Path) -> Path:
    """Create the fixture DuckDB at path, replacing any existing file."""
    if path.exists():
        path.unlink()
    con = duckdb.connect(str(path))
    _create_sra_metadata(con)
    _create_sra_taxonomy(con)
    _create_metalog_metadata(con)
    _create_metaphlan(con)
    _create_motus(con)
    con.close()
    return path


# --- SRA side -------------------------------------------------------------

def _create_sra_metadata(con: duckdb.DuckDBPyConnection) -> None:
    con.execute("""
        CREATE TABLE sra_metadata (
            acc TEXT, biosample TEXT, bioproject TEXT, assay_type TEXT,
            organism TEXT, librarysource TEXT, platform TEXT,
            geo_loc_name_country_calc TEXT, collection_date_sam TEXT, jattr TEXT
        )
    """)
    con.executemany(
        "INSERT INTO sra_metadata VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        _sra_metadata_rows(),
    )


def _sra_metadata_rows() -> list[tuple]:
    """ONE ROW PER RUN, like the real table -- so a two-run biosample has two rows and
    biosample -> runs is resolvable here without touching the huge taxonomy table."""
    return [_sra_metadata_row(run, biosample, index)
            for index, biosample in enumerate(_sra_biosamples())
            for run in _runs_of(biosample)]


def _sra_biosamples() -> list[str]:
    return SHARED + SRA_ONLY


def _sra_metadata_row(run: str, biosample: str, index: int) -> tuple:
    return (
        run,
        biosample,
        f"PRJNA{900 + index % 3}",
        "WGS",
        "human gut metagenome",
        "METAGENOMIC",
        "ILLUMINA",
        COUNTRIES[index % len(COUNTRIES)],
        f"2021-0{index % 9 + 1}-15",
        '{"host_age":"%d"}' % (25 + index),
    )


def _primary_run(biosample: str) -> str:
    return f"SRR{biosample[-5:]}A"


def _create_sra_taxonomy(con: duckdb.DuckDBPyConnection) -> None:
    """STAT profiles, keyed by RUN accession, with the build-stamped biosample alongside.

    Both columns matter: `acc` is what a STAT biom column IS, `biosample` is what makes
    it reachable by the canonical key. SAMN00001 deliberately has two runs.
    """
    con.execute("""
        CREATE TABLE sra_taxonomy (
            acc TEXT, tax_id BIGINT, rank TEXT, name TEXT,
            total_count BIGINT, self_count BIGINT, bioproject TEXT,
            biosample TEXT
        )
    """)
    con.executemany(
        "INSERT INTO sra_taxonomy VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        _stat_rows(),
    )


def _stat_rows() -> list[tuple]:
    rows = []
    for biosample in _stat_biosamples():
        for run in _runs_of(biosample):
            rows.extend(_stat_rows_for_run(run, biosample))
    return rows


def _stat_biosamples() -> list[str]:
    return SHARED + SRA_ONLY[:4]          # 12 of the 14 SRA samples carry a STAT profile


def _runs_of(biosample: str) -> list[str]:
    """SAMN00001 has two sequencing runs; every other sample has one."""
    if biosample == "SAMN00001":
        return ["SRR00001A", "SRR00001B"]
    return [_primary_run(biosample)]


# tax_id, rank, name -- a few nodes at different ranks, so self_count is a real partition
STAT_TAXA = [
    (2, "superkingdom", "Bacteria"),
    (1239, "phylum", "Bacillota"),
    (561, "genus", "Escherichia"),
    (562, "species", "Escherichia coli"),
    (1680, "species", "Bifidobacterium adolescentis"),
]


def _stat_rows_for_run(run: str, biosample: str) -> list[tuple]:
    seed = sum(ord(c) for c in run)
    return [
        (run, tax_id, rank, name, 0, 100 + (seed + tax_id) % 400, "PRJNA900", biosample)
        for tax_id, rank, name in STAT_TAXA
    ]


# --- Metalog side ---------------------------------------------------------

def _create_metalog_metadata(con: duckdb.DuckDBPyConnection) -> None:
    con.execute("""
        CREATE TABLE metalog_metadata (
            sample_alias TEXT, spire_sample_name TEXT, biosample TEXT,
            study_code TEXT, geographic_location TEXT, sex TEXT,
            age_years DOUBLE, age_category TEXT, subject_disease_status TEXT,
            environment TEXT
        )
    """)
    con.executemany(
        "INSERT INTO metalog_metadata VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [_metalog_metadata_row(key, index) for index, key in enumerate(_metalog_keys())],
    )


def _metalog_keys() -> list[str]:
    return SHARED + METALOG_ONLY + ORPHANS


def _alias_of(key: str) -> str:
    """Metalog's internal id. Orphans are already aliases; biosamples get one derived."""
    if key in ORPHANS:
        return key
    return f"MG_{key}"


def _metalog_metadata_row(key: str, index: int) -> tuple:
    is_orphan = key in ORPHANS
    return (
        _alias_of(key),
        key if not is_orphan else f"ERS{index:06d}",   # orphan: not a BioSample accession
        None if is_orphan else key,                   # the build-stamped key, NULL for the tail
        f"STUDY_{index % 3}",
        COUNTRIES[index % len(COUNTRIES)],
        "female" if index % 2 else "male",
        float(20 + index * 2),
        "adult",
        DISEASES[index % len(DISEASES)],
        "human",
    )


def _create_metaphlan(con: duckdb.DuckDBPyConnection) -> None:
    con.execute("""
        CREATE TABLE metalog_metaphlan4 (
            sample_alias TEXT, clade_name TEXT, rel_abund DOUBLE,
            environment TEXT, biosample TEXT
        )
    """)
    con.executemany(
        "INSERT INTO metalog_metaphlan4 VALUES (?, ?, ?, ?, ?)",
        _profile_rows(METAPHLAN_SAMPLES, METAPHLAN_CLADES, base=0.10),
    )


def _create_motus(con: duckdb.DuckDBPyConnection) -> None:
    """Two MOTUS sources that overlap on 3 samples -- the union the design exists for."""
    for table, samples, species, base in _motus_specs():
        con.execute(f"""
            CREATE TABLE {table} (
                sample_alias TEXT, species TEXT, rel_abund DOUBLE,
                insert_count BIGINT, environment TEXT, biosample TEXT
            )
        """)
        con.executemany(
            f"INSERT INTO {table} VALUES (?, ?, ?, ?, ?, ?)",
            _motus_rows(samples, species, base),
        )


METAPHLAN_SAMPLES = SHARED[:5] + METALOG_ONLY[:1]
METAPHLAN_CLADES = [
    "k__Bacteria|p__Bacillota|c__Clostridia|s__Faecalibacterium_prausnitzii",
    "k__Bacteria|p__Bacteroidota|c__Bacteroidia|s__Bacteroides_uniformis",
]

MOTUS3_SAMPLES = SHARED[:6] + METALOG_ONLY[:2]
SPIRE_SAMPLES = SHARED[3:8] + METALOG_ONLY[2:3] + ORPHANS[:1]

SHARED_MOTUS_SPECIES = ["ref_mOTU_v3_00095 Escherichia coli",
                        "ref_mOTU_v3_01234 Bacteroides uniformis"]
SPIRE_ONLY_SPECIES = "ref_mOTU_v3_99999 Spire-only species"


def _motus_specs() -> list[tuple]:
    return [
        ("metalog_motus3", MOTUS3_SAMPLES, SHARED_MOTUS_SPECIES, 0.20),
        ("metalog_spire_motus", SPIRE_SAMPLES, SHARED_MOTUS_SPECIES + [SPIRE_ONLY_SPECIES], 0.50),
    ]


def _profile_rows(samples: list[str], features: list[str], base: float) -> list[tuple]:
    """MetaPhlAn shape: alias, feature, abundance, environment, biosample."""
    return [
        (_alias_of(key), feature, base + position / 100, "human", _biosample_of(key))
        for key in samples
        for position, feature in enumerate(features)
    ]


def _motus_rows(samples: list[str], features: list[str], base: float) -> list[tuple]:
    """mOTUs shape adds insert_count. `base` differs per source so head-wins-overlap is visible."""
    return [
        (_alias_of(key), feature, base + position / 100, 500 + position, "human", _biosample_of(key))
        for key in samples
        for position, feature in enumerate(features)
    ]


def _biosample_of(key: str) -> str | None:
    """The build-stamped key. Orphans resolve to nothing and stay addressable by alias."""
    if key in ORPHANS:
        return None
    return key


def main() -> None:
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("fixture_mirror.duckdb")
    build_fixture_mirror(target)
    print(f"{target}  ({target.stat().st_size / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
