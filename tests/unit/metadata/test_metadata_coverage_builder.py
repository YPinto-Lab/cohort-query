import pandas as pd
from Engines.MetadataEngine.metadata_coverage_builder import MetadataCoverageBuilder


def _extracted():
    return pd.DataFrame({
        "acc": ["SRR1", "SRR2", "SRR3"],
        "bioproject": ["PRJ1", "PRJ1", "PRJ2"],
        "host": ["human", "human", "mouse"],
        "tissue": ["gut", "skin", ""],
    })


def test_coverage_fractions_per_project():
    coverage = MetadataCoverageBuilder().build(_extracted(), ["host", "tissue"])

    prj2 = coverage[coverage["bioproject"] == "PRJ2"].iloc[0]
    assert prj2["host"] == 1.0
    assert prj2["tissue"] == 0.0
    prj1 = coverage[coverage["bioproject"] == "PRJ1"].iloc[0]
    assert prj1["tissue"] == 1.0
    assert prj1["host"] == 1.0
