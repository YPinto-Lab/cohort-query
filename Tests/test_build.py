"""BiomFactory's per-sample metadata assembly: SRA's attributes/jattr flattening and
Timestamp-safe JSON, both found by hand-inspecting a real 258MB cohort.biom."""
import json

import numpy as np
import pandas as pd

from askslm.build import BiomFactory, CohortBuilder
from askslm.cohort import Accession
from askslm.metadata import ReconciledMetadata
from askslm.profiles import ProfileMatrix


def _matrix(columns: list[str]) -> ProfileMatrix:
    return ProfileMatrix(
        pd.DataFrame({column: [1] for column in columns}, index=["tax1"]),
        pd.DataFrame({"name": ["a"]}, index=["tax1"]),
        {column: Accession(column) for column in columns})


def test_attributes_flatten_into_real_fields_and_jattr_is_dropped():
    """jattr silently collapses a key with more than one raw value down to just the
    first -- verified against 20,000 real sra_metadata rows, it diverges from
    attributes on EVERY row that has primary_search. attributes is the lossless
    form, so it wins; jattr is just dropped."""
    row = {"attributes": [{"k": "primary_search", "v": "179142"},
                          {"k": "primary_search", "v": "SAMN01801807"},
                          {"k": "bmi_sam", "v": "22.5"}],
          "jattr": '{"primary_search": "179142"}',
          "environment_material": "fecal material"}      # a real, pre-existing column
    metadata = ReconciledMetadata(pd.DataFrame([row], index=["SAMN1"]))

    table = BiomFactory().build(_matrix(["SAMN1"]), metadata)
    md = table.metadata("SAMN1", axis="sample")

    assert "jattr" not in md and "attributes" not in md
    assert md["primary_search"] == ["179142", "SAMN01801807"]   # not collapsed to first
    assert md["bmi_sam"] == "22.5"
    assert md["environment_material"] == "fecal material"        # untouched, real column kept


def test_attributes_as_a_duckdb_ndarray_does_not_crash():
    """duckdb's fetch_df() returns a LIST(STRUCT) column as numpy.ndarray, not a plain
    list -- `not attributes` on a multi-element array raises 'ambiguous truth value'
    instead of testing emptiness."""
    row = {"attributes": np.array([{"k": "bases", "v": "7353065008"}], dtype=object)}
    metadata = ReconciledMetadata(pd.DataFrame([row], index=["SAMN1"]))

    table = BiomFactory().build(_matrix(["SAMN1"]), metadata)

    assert table.metadata("SAMN1", axis="sample")["bases"] == "7353065008"


def test_empty_attributes_array_just_drops_the_blobs():
    row = {"attributes": np.array([], dtype=object), "jattr": None}
    metadata = ReconciledMetadata(pd.DataFrame([row], index=["SAMN1"]))

    table = BiomFactory().build(_matrix(["SAMN1"]), metadata)
    md = table.metadata("SAMN1", axis="sample")

    assert "attributes" not in md and "jattr" not in md


def test_timestamp_values_become_iso_strings_not_json_nan():
    """biom's own JSON encoder has no case for pd.Timestamp -- some sra_metadata
    columns carry real datetimes, and to_json() died on the first one it met."""
    row = {"collection_date": pd.Timestamp("2020-03-01"), "bmi": None}
    metadata = ReconciledMetadata(pd.DataFrame([row], index=["SAMN1"]))

    table = BiomFactory().build(_matrix(["SAMN1"]), metadata)
    payload = json.loads(table.to_json("test"))     # must not raise TypeError
    md = {entry["id"]: entry["metadata"] for entry in payload["columns"]}["SAMN1"]

    assert md["collection_date"] == "2020-03-01T00:00:00"
    assert md["bmi"] is None


def test_written_creates_outs_parent_directory(tmp_path):
    """Job 29510021 discovered its cohort, read the profile matrix, and assembled
    the biom table -- ~56s of real work -- then crashed on the final write because
    'out's parent directory didn't exist. Every other writer in this codebase
    (Plan.save, settings_file, checkpoint) already mkdir's before writing."""
    metadata = ReconciledMetadata(pd.DataFrame({"x": [1]}, index=["SAMN1"]))
    table = BiomFactory().build(_matrix(["SAMN1"]), metadata)
    out = tmp_path / "does-not-exist-yet" / "cohort.biom"

    CohortBuilder.__new__(CohortBuilder)._written(table, out)

    assert out.exists()


def test_wide_format_visit_fields_resolve_by_study_week_not_silently_dropped():
    """Verified against a real cohort (bioproject PRJNA930767): 49/72 biosamples carry
    all six visit weeks' calprotectin values on one row, though each biosample is one
    sequenced run of one specimen. study_week_sam identifies which one is real for this
    specimen; the rest are the same subject's OTHER visits, not this specimen's data."""
    row = {"study_week_sam": "52",
          "calprotectin0_sam": "21", "calprotectin6_sam": "61", "calprotectin12_sam": "147",
          "calprotectin24_sam": "15", "calprotectin36_sam": "46", "calprotectin52_sam": "145",
          "environment_material": "fecal material"}
    metadata = ReconciledMetadata(pd.DataFrame([row], index=["SAMN1"]))

    table = BiomFactory().build(_matrix(["SAMN1"]), metadata)
    md = table.metadata("SAMN1", axis="sample")

    assert md["calprotectin_sam"] == "145"                      # this specimen's own week-52 value
    assert md["calprotectin_sam__other_visit_week0"] == "21"     # kept, not dropped
    assert md["calprotectin_sam__other_visit_week6"] == "61"
    assert md["calprotectin_sam__other_visit_week12"] == "147"
    assert md["calprotectin_sam__other_visit_week24"] == "15"
    assert md["calprotectin_sam__other_visit_week36"] == "46"
    for week in (0, 6, 12, 24, 36, 52):
        assert f"calprotectin{week}_sam" not in md    # raw per-week fields all resolved away
    assert md["environment_material"] == "fecal material"        # untouched


def test_a_lone_numbered_field_is_left_alone_not_treated_as_a_visit_collision():
    """Only >1 same-prefix numbered field on one row is the wide-format signature --
    a single one is just a normal field name, nothing to resolve."""
    row = {"study_week_sam": "6", "calprotectin6_sam": "61"}
    metadata = ReconciledMetadata(pd.DataFrame([row], index=["SAMN1"]))

    table = BiomFactory().build(_matrix(["SAMN1"]), metadata)
    md = table.metadata("SAMN1", axis="sample")

    assert md["calprotectin6_sam"] == "61"
    assert "calprotectin_sam" not in md


def test_no_study_week_means_visit_fields_pass_through_unchanged():
    row = {"calprotectin0_sam": "21", "calprotectin6_sam": "61"}
    metadata = ReconciledMetadata(pd.DataFrame([row], index=["SAMN1"]))

    table = BiomFactory().build(_matrix(["SAMN1"]), metadata)
    md = table.metadata("SAMN1", axis="sample")

    assert md["calprotectin0_sam"] == "21" and md["calprotectin6_sam"] == "61"
