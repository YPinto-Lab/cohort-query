"""BiomFactory's per-sample metadata assembly: SRA's attributes/jattr flattening and
Timestamp-safe JSON, both found by hand-inspecting a real 258MB cohort.biom."""
import json

import numpy as np
import pandas as pd

from askslm.build import BiomFactory
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
