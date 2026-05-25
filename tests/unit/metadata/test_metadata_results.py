import pandas as pd
from Common.contracts.metadata_results import MetadataOverview


def _overview():
    one = pd.DataFrame({"metric": ["samples"], "value": [3]})
    return MetadataOverview(summary_df=one, projects_df=one, discovered_keys_df=one,
                            discovered_keys_unique_df=one, coverage_matrix_df=one)


def test_overview_bundles_five_frames():
    overview = _overview()

    assert overview.summary_df.loc[0, "value"] == 3
    assert overview.coverage_matrix_df.loc[0, "metric"] == "samples"


def test_write_emits_five_csvs(tmp_path):
    paths = _overview().write(tmp_path)

    assert {p.name for p in paths} == {
        "summary.csv", "projects.csv", "discovered_keys.csv",
        "discovered_keys_unique.csv", "coverage_matrix.csv",
    }
    assert all(p.exists() for p in paths)
