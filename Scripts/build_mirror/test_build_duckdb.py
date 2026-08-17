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

    # The SRA side is a real DuckDB now, not CSVs -- that is what the lab server has.
    # A1 and A2 are two RUNS of one BioSample (the B.3 case); A3 has no biosample.
    sra_db = tmp_path / "sra.duckdb"
    import duckdb
    source = duckdb.connect(str(sra_db))
    source.execute("CREATE TABLE metadata_raw (acc VARCHAR, biosample VARCHAR)")
    source.execute("INSERT INTO metadata_raw VALUES ('A1','SAMN001'),('A2','SAMN001'),('A3',NULL)")
    source.execute("CREATE TABLE tax_raw (acc VARCHAR, tax_id INTEGER)")
    source.execute("INSERT INTO tax_raw VALUES ('A1',9606),('A2',9606),('A3',9606)")
    source.close()

    return MirrorBuilder(
        metalog_dir=metalog_dir,
        sra_db=sra_db,
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


def test_taxonomy_is_a_view_over_the_attached_source_not_a_copy(tmp_path):
    """The 13.6B-row table must never be copied, and must never be stamped.

    Instead the mirror holds a VIEW plus `stat_coverage`, and records the source path so
    a read-only reopen can re-attach. Two runs of one BioSample stay two rows -- the ETL
    collapses nothing (HLD B.3).
    """
    builder = _build_fixture(tmp_path)
    builder.build()

    import duckdb
    con = duckdb.connect(str(builder.out_path), read_only=True)
    recorded = con.execute(
        "SELECT value FROM mirror_config WHERE key = 'sra_db_path'").fetchone()[0]
    con.execute(f"ATTACH '{recorded}' AS sra (READ_ONLY)")

    kinds = dict(con.execute(
        "SELECT table_name, table_type FROM information_schema.tables "
        "WHERE table_name IN ('sra_taxonomy', 'sra_metadata')").fetchall())
    taxonomy_columns = [row[0] for row in con.execute("DESCRIBE sra_taxonomy").fetchall()]
    covered = sorted(row[0] for row in con.execute("SELECT acc FROM stat_coverage").fetchall())
    runs_of_samn001 = con.execute(
        "SELECT count(DISTINCT acc) FROM sra_metadata WHERE biosample = 'SAMN001'").fetchone()[0]

    assert kinds["sra_taxonomy"] == "VIEW"          # not copied
    assert kinds["sra_metadata"] == "BASE TABLE"    # copied: small, and needs its own index
    assert "biosample" not in taxonomy_columns      # never stamped
    assert covered == ["A1", "A2", "A3"]
    assert runs_of_samn001 == 2

    con.close()
