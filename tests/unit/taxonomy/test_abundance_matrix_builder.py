import pandas as pd
from Engines.TaxonomyEngine.abundance_matrix_builder import AbundanceMatrixBuilder


def _long():
    return pd.DataFrame({
        "acc": ["SRR1", "SRR1", "SRR2"],
        "tax_id": [2, 561, 2],
        "rank": ["superkingdom", "genus", "superkingdom"],
        "name": ["Bacteria", "Escherichia", "Bacteria"],
        "total_count": [100, 60, 80],
        "ileft": [1, 3, 1],
        "iright": [8, 4, 4],
    })


def test_build_returns_samples_by_taxa_counts():
    matrix = AbundanceMatrixBuilder().build(_long())

    assert matrix.counts.shape[0] == 2
    assert matrix.counts.index.name == "acc"


def test_build_attaches_lineage_to_taxa():
    matrix = AbundanceMatrixBuilder().build(_long())

    genus_row = matrix.taxa[matrix.taxa["tax_id"] == 561].iloc[0]
    assert genus_row["superkingdom"] == "Bacteria"
