import pandas as pd
from askslm.metadata.metadata_summary_builder import MetadataSummaryBuilder


def _extracted():
    return pd.DataFrame({
        "acc": ["SRR1", "SRR2", "SRR3"],
        "bioproject": ["PRJ1", "PRJ1", "PRJ2"],
        "host": ["human", "human", "mouse"],
    })


def test_summary_reports_core_metrics():
    summary = MetadataSummaryBuilder().build(_extracted(), ["host"])

    lookup = dict(zip(summary["metric"], summary["value"]))
    assert lookup["samples"] == 3
    assert lookup["projects"] == 2
    assert lookup["discovered_keys"] == 1
    assert lookup["discovered_key_names"] == "host"
