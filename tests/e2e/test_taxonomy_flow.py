"""e2e: load a taxonomy report, build feature metadata, assemble a biom feature table."""
from pathlib import Path

from biom import Table

from askslm import taxonomy

TAX = Path(__file__).parent.parent / "fixtures" / "taxonomy_tiny.csv"


def test_load_lineage_and_assemble():
    tax = taxonomy.load(str(TAX))
    counts = tax.pivot_table(index="tax_id", columns="acc", values="self_count",
                             aggfunc="sum", fill_value=0)
    features = taxonomy.lineage_table(counts.index)

    table = Table(counts.values,
                  observation_ids=counts.index.astype(str),
                  sample_ids=counts.columns.astype(str))
    table.add_metadata({str(t): row for t, row in features.to_dict("index").items()},
                       axis="observation")

    assert table.shape[0] == len(counts.index)
    assert table.shape[1] == len(counts.columns)
    fm = table.metadata_to_dataframe("observation")
    assert {"name", "rank", "lineage_0", "ranks"}.issubset(fm.columns)
