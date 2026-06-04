import pandas as pd
from askslm.metadata.discovered_keys_builder import DiscoveredKeysBuilder


def _extracted():
    return pd.DataFrame({
        "acc": ["SRR1", "SRR2", "SRR3"],
        "bioproject": ["PRJ1", "PRJ1", "PRJ2"],
        "host": ["human", "human", "mouse"],
        "tissue": ["gut", "skin", ""],
    })


def test_by_project_reports_population_and_uniqueness():
    by_project = DiscoveredKeysBuilder().by_project(_extracted(), ["host", "tissue"])

    prj1_host = by_project[(by_project["bioproject"] == "PRJ1") & (by_project["key_name"] == "host")].iloc[0]
    assert prj1_host["populated_samples"] == 2
    assert prj1_host["unique_values"] == 1
    prj2_tissue = by_project[(by_project["bioproject"] == "PRJ2") & (by_project["key_name"] == "tissue")].iloc[0]
    assert prj2_tissue["populated_samples"] == 0


def test_unique_rolls_up_true_global_across_projects():
    builder = DiscoveredKeysBuilder()

    unique = builder.unique(_extracted(), ["host", "tissue"])

    host = unique[unique["key_name"] == "host"].iloc[0]
    assert host["projects"] == 2
    assert host["populated_samples"] == 3
    assert host["unique_values"] == 2


def test_populated_excludes_null_and_marker_values():
    frame = pd.DataFrame({
        "acc": ["A", "B", "C", "D", "E", "F"],
        "bioproject": ["P"] * 6,
        "host": ["human", None, float("nan"), "", "nan", "none"],
    })

    by_project = DiscoveredKeysBuilder().by_project(frame, ["host"])

    row = by_project.iloc[0]
    assert row["populated_samples"] == 1
    assert row["unique_values"] == 1
