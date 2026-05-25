import pandas as pd
from Engines.MetadataEngine.metadata_overview_builder import MetadataOverviewBuilder


def _extracted():
    return pd.DataFrame({
        "acc": ["SRR1", "SRR2", "SRR3"],
        "bioproject": ["PRJ1", "PRJ1", "PRJ2"],
        "host": ["human", "human", "mouse"],
        "tissue": ["gut", "skin", ""],
    })


def test_overview_assembles_all_frames():
    overview = MetadataOverviewBuilder().build(_extracted())

    summary = dict(zip(overview.summary_df["metric"], overview.summary_df["value"]))
    assert summary["discovered_keys"] == 2
    projects = dict(zip(overview.projects_df["bioproject"], overview.projects_df["samples"]))
    assert projects == {"PRJ1": 2, "PRJ2": 1}
    assert set(overview.discovered_keys_unique_df["key_name"]) == {"host", "tissue"}


def test_overview_excludes_base_columns_from_discovered():
    overview = MetadataOverviewBuilder().build(_extracted())

    assert "bioproject" not in set(overview.discovered_keys_unique_df["key_name"])
