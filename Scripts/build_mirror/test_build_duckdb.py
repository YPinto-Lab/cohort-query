"""Runnable check for build_duckdb.py: builds the mirror from a tiny synthetic
Metalog + SRA fixture and asserts the biosample-stamping and join invariants."""
import csv
import gzip
from pathlib import Path

from build_duckdb import MirrorBuilder


def _write_tsv_gz(path: Path, rows: list[list[str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", newline="") as fh:
        csv.writer(fh, delimiter="\t").writerows(rows)


def _build_fixture(tmp_path: Path) -> MirrorBuilder:
    metalog_dir = tmp_path / "Metalog"
    profiles_dir = metalog_dir / "Taxonomic Profiles" / "Human"

    _write_tsv_gz(profiles_dir / "human_metaphlan4_species_2026-06-07.tsv.gz", [
        ["sample_alias", "species", "rel_abund"],
        ["s1", "s__Bacteroides_ovatus", "0.5"],
        ["s2", "s__Bacteroides_ovatus", "0.5"],
        ["s3_unknown", "s__Bacteroides_ovatus", "0.5"],
    ])
    _write_tsv_gz(profiles_dir / "human_metaphlan4_2026-06-07.tsv.gz", [
        ["sample_alias", "clade_name", "rel_abund"],
        ["s1", "t__SGB1", "0.5"],
    ])
    _write_tsv_gz(profiles_dir / "human_motus3_2026-06-07.tsv.gz", [
        ["sample_alias", "species", "rel_abund", "insert_count"],
        ["s1", "Some sp.", "0.5", "10"],
    ])
    _write_tsv_gz(profiles_dir / "human_spire_motus_2026-06-07.tsv.gz", [
        ["sample_alias", "species", "rel_abund", "insert_count"],
        ["s1", "Some sp.", "0.5", "10"],
    ])
    _write_tsv_gz(metalog_dir / "Metadata" / "human_extended_wide_2026-06-07.tsv.gz", [
        ["sample_alias", "spire_sample_name"],
        ["s1", "SAMN001"],
        ["s2", "SRS_not_a_biosample"],
    ])

    # A1 and A2 are two RUNS of one BioSample -- the B.3 case. A3 has no biosample.
    sra_metadata_csv = tmp_path / "metadata.csv"
    sra_metadata_csv.write_text("acc,biosample\nA1,SAMN001\nA2,SAMN001\nA3,\n")
    sra_taxonomy_csv = tmp_path / "taxonomy.csv"
    sra_taxonomy_csv.write_text("acc,tax_id\nA1,9606\nA2,9606\nA3,9606\n")

    return MirrorBuilder(
        metalog_dir=metalog_dir,
        sra_metadata_csv=sra_metadata_csv,
        sra_taxonomy_csv=sra_taxonomy_csv,
        out_path=tmp_path / "mirror.duckdb",
    )


def test_build_stamps_biosample_and_joins(tmp_path, capsys):
    builder = _build_fixture(tmp_path)
    builder.build()

    import duckdb
    con = duckdb.connect(str(builder.out_path), read_only=True)

    rows = dict(con.execute("SELECT sample_alias, biosample FROM metalog_metadata").fetchall())
    assert rows == {"s1": "SAMN001", "s2": None}

    profile_rows = dict(con.execute(
        "SELECT sample_alias, biosample FROM metalog_metaphlan4_species"
    ).fetchall())
    assert profile_rows == {"s1": "SAMN001", "s2": None, "s3_unknown": None}

    environment = con.execute(
        "SELECT DISTINCT environment FROM metalog_metaphlan4_species"
    ).fetchone()[0]
    assert environment == "human"

    con.close()


def test_sra_taxonomy_is_stamped_with_biosample_but_keeps_its_runs(tmp_path):
    """B.3: STAT becomes reachable by the canonical key WITHOUT losing the run.
    Two runs of one BioSample stay two rows -- the ETL never collapses them."""
    builder = _build_fixture(tmp_path)
    builder.build()

    import duckdb
    con = duckdb.connect(str(builder.out_path), read_only=True)

    stamped = sorted(con.execute("SELECT acc, biosample FROM sra_taxonomy").fetchall())
    runs_of_samn001 = con.execute("""
        SELECT count(DISTINCT acc) FROM sra_taxonomy WHERE biosample = 'SAMN001'
    """).fetchone()[0]

    assert stamped == [("A1", "SAMN001"), ("A2", "SAMN001"), ("A3", None)]
    assert runs_of_samn001 == 2

    con.close()
