"""A biosample matched by only one metadata source used to carry the OTHER source's
entire schema as explicit nulls (`combine_first` unions both sources' columns onto
every row) -- not missing data, a foreign schema that was never looked up for this
sample. Found on a real 16,721-column build: 992 samples had metalog_metadata's ~180
columns stamped on as null, purely because metalog_metadata had no row for them at all.
"""
import pandas as pd

import askslm
from askslm.adapters import CannedLlmBackend, DuckDbConnection
from askslm.cohort import Accession
from askslm.metadata import MetadataReader
from askslm.sources import Source
from askslm.translation import SourceQuery, Translation

from fixtures.mirror import METALOG_ONLY, SHARED, SRA_ONLY, build_fixture_mirror

IBD_TRANSLATION = Translation(
    interpretation="body_site = stool · disease = IBD",
    queries=(
        SourceQuery(askslm.Source.SRA_METADATA, "SELECT * FROM sra_metadata"),
        SourceQuery(askslm.Source.METALOG_METADATA, "SELECT * FROM metalog_metadata"),
    ),
)


def test_sra_only_biosamples_dont_get_metalog_schema_stamped_as_null(tmp_path):
    path = build_fixture_mirror(tmp_path / "fixture.duckdb")
    connection = DuckDbConnection(path)
    askslm.config(db=path, database=connection, backend=CannedLlmBackend(IBD_TRANSLATION))
    plan = askslm.ask("fecal metagenomes from adults with IBD, Western countries")

    # SRA_TAXONOMY columns resolve through sra_metadata, so both SHARED and SRA_ONLY
    # biosamples get columns here -- METALOG_ONLY and orphans never do (HLD B.3).
    table, _ = plan.run(profile_sources=askslm.Source.SRA_TAXONOMY)

    sra_only_columns = [sid for sid in table.ids("sample")
                        if table.metadata(sid, axis="sample")["biosample"] in SRA_ONLY]
    shared_columns = [sid for sid in table.ids("sample")
                      if table.metadata(sid, axis="sample")["biosample"] in SHARED]
    assert sra_only_columns and shared_columns

    for sid in sra_only_columns:
        md = table.metadata(sid, axis="sample")
        assert "study_code" not in md                 # metalog-exclusive, never absent-as-null
        assert "subject_disease_status" not in md

    for sid in shared_columns:
        md = table.metadata(sid, axis="sample")
        assert md["study_code"] is not None           # a real metalog row backs this sample
        assert md["subject_disease_status"] is not None

    connection.close()


def test_metalog_only_biosamples_still_get_no_sra_columns_since_none_exist_for_them(tmp_path):
    """METALOG_ONLY/orphan biosamples never produce a STAT column at all (no sra_metadata
    row to resolve an acc from), so this is really confirming the fixture's own shape --
    the interesting asymmetry is entirely on the SRA_TAXONOMY side, tested above."""
    path = build_fixture_mirror(tmp_path / "fixture.duckdb")
    connection = DuckDbConnection(path)
    askslm.config(db=path, database=connection, backend=CannedLlmBackend(IBD_TRANSLATION))
    plan = askslm.ask("fecal metagenomes from adults with IBD, Western countries")

    table, _ = plan.run(profile_sources=askslm.Source.SRA_TAXONOMY)

    biosamples_present = {table.metadata(sid, axis="sample")["biosample"]
                          for sid in table.ids("sample")}
    assert not biosamples_present & set(METALOG_ONLY)

    connection.close()


def test_the_assembly_read_never_fetches_jattr_but_metalog_is_untouched():
    """`jattr` is 60% of sra_metadata's bytes and `build._flattened` discards it on both
    return paths -- `attributes` is the lossless form of the same key/value data. Fetching
    it costs a 2.8x slowdown to produce byte-identical output.

    DISCOVERY still filters on it (`json_extract_string(jattr, ...)`, see prompt.py); this
    covers only the assembly-time read, where the cohort is already known. The metalog
    tables have no such column and must not have it named.
    """
    captured = []

    class _Recorder:
        def query(self, sql, params=None):
            captured.append(sql)
            return pd.DataFrame()

    reader = MetadataReader(_Recorder())
    reader.read(Source.SRA_METADATA, frozenset({Accession("SAMN1")}))
    reader.read(Source.METALOG_METADATA, frozenset({Accession("SAMN1")}))

    assert "EXCLUDE (jattr)" in captured[0]
    assert "jattr" not in captured[1]
