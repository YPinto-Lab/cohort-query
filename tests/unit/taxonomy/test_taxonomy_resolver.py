import pandas as pd
from Engines.TaxonomyEngine.taxonomy_resolver import TaxonomyResolver


def test_resolve_remaps_deprecated_id_and_aggregates():
    taxonomy_df = pd.DataFrame({
        "acc": ["SRR1", "SRR1"],
        "tax_id": ["999", "561"],
        "total_count": [10, 5],
    })

    resolved = TaxonomyResolver({999: 561}).resolve(taxonomy_df)

    row = resolved[resolved["tax_id"] == "561"]
    assert int(row["total_count"].iloc[0]) == 15


def test_summarize_reports_updated_rows():
    taxonomy_df = pd.DataFrame({
        "acc": ["SRR1"],
        "tax_id": ["999"],
        "total_count": [10],
    })

    summary, changes_df = TaxonomyResolver({999: 561}).summarize_resolution(taxonomy_df)

    assert summary["rows_updated"] == 1
    assert changes_df.iloc[0]["resolved_tax_id"] == "561"
