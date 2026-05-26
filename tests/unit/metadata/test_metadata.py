import pandas as pd
import pytest

from Common.contracts.selectors import SampleSelector
from Engines.MetadataEngine.metadata import Metadata


def _df():
    return pd.DataFrame({
        "acc": ["SRR1", "SRR2", "SRR3"],
        "Group": ["treatment", "control", "treatment"],
        "assay_type": ["WGS", "WGS", "AMPLICON"],
    })


def test_construction_validates_acc_column_present():
    bad = pd.DataFrame({"sample_id": ["SRR1"], "Group": ["a"]})

    with pytest.raises(ValueError, match="acc"):
        Metadata(df=bad)


def test_construction_rejects_duplicate_acc():
    dup = pd.DataFrame({"acc": ["SRR1", "SRR1"], "Group": ["a", "b"]})

    with pytest.raises(ValueError, match="duplicate"):
        Metadata(df=dup)


def test_reindex_to_orders_rows_and_drops_missing():
    md = Metadata(df=_df())

    reindexed = md.reindex_to(["SRR3", "SRR1"])

    assert list(reindexed.df["acc"]) == ["SRR3", "SRR1"]


def test_reindex_to_drops_sample_ids_absent_from_metadata():
    md = Metadata(df=_df())

    reindexed = md.reindex_to(["SRR1", "SRR9"])

    assert list(reindexed.df["acc"]) == ["SRR1"]


def test_filter_keeps_matching_rows():
    md = Metadata(df=_df())

    filtered = md.filter(SampleSelector(column="Group", values=("treatment",)))

    assert list(filtered.df["acc"]) == ["SRR1", "SRR3"]


def test_filter_exclude_removes_matching_rows():
    md = Metadata(df=_df())

    filtered = md.filter(SampleSelector(column="Group", values=("control",), exclude=True))

    assert list(filtered.df["acc"]) == ["SRR1", "SRR3"]


def test_write_produces_csv_without_index(tmp_path):
    md = Metadata(df=_df())

    path = md.write(tmp_path / "metadata.csv")

    written = pd.read_csv(path)
    assert list(written.columns) == ["acc", "Group", "assay_type"]
    assert list(written["acc"]) == ["SRR1", "SRR2", "SRR3"]
