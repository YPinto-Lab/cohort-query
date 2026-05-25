import pandas as pd
from Engines.TaxonomyEngine.nested_set_lineage_resolver import NestedSetLineageResolver


def _tree():
    return pd.DataFrame({
        "acc": ["S", "S", "S"],
        "tax_id": [2, 1224, 561],
        "rank": ["superkingdom", "phylum", "genus"],
        "name": ["Bacteria", "Proteobacteria", "Escherichia"],
        "ileft": [1, 2, 3],
        "iright": [6, 5, 4],
    })


def test_genus_node_maps_to_bacteria_superkingdom():
    lineage_df = NestedSetLineageResolver().resolve(_tree())

    escherichia = lineage_df[lineage_df["tax_id"] == 561].iloc[0]
    assert escherichia["superkingdom"] == "Bacteria"
    assert escherichia["genus"] == "Escherichia"


def test_each_tax_id_appears_once():
    lineage_df = NestedSetLineageResolver().resolve(_tree())

    assert lineage_df["tax_id"].is_unique
