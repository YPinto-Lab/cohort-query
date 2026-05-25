import pandas as pd
from Common.contracts.taxonomy_results import ResolutionSummary, ResolvedTaxonomy


def test_resolution_summary_holds_counters():
    summary = ResolutionSummary(input_rows=10, rows_updated=2, unique_old_tax_ids_updated=1)

    assert summary.rows_updated == 2


def test_resolved_taxonomy_bundles_frames_and_summary():
    df = pd.DataFrame({"acc": ["a"], "tax_id": ["1"], "total_count": [5]})
    summary = ResolutionSummary(input_rows=1, rows_updated=0, unique_old_tax_ids_updated=0)

    result = ResolvedTaxonomy(df=df, changes_df=pd.DataFrame(), summary=summary)

    assert result.df.loc[0, "tax_id"] == "1"
    assert result.summary.input_rows == 1
