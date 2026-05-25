import pandas as pd
from Engines.TaxonomyEngine.abundance_matrix_builder import AbundanceMatrixBuilder


def _long():
    return pd.DataFrame({
        "acc": ["SRR1", "SRR1", "SRR2"],
        "tax_id": [2, 561, 2],
        "rank": ["superkingdom", "genus", "superkingdom"],
        "name": ["Bacteria", "Escherichia", "Bacteria"],
        "total_count": [100, 60, 80],
        "self_count": [40, 60, 80],
        "ileft": [1, 3, 1],
        "iright": [8, 4, 4],
    })


def test_build_collapses_to_genus_with_unclassified_bucket():
    matrix = AbundanceMatrixBuilder().build(_long())

    assert matrix.counts.index.name == "acc"
    assert set(matrix.counts.columns) == {"genus||Escherichia||561", "Unclassified_genus"}
    assert matrix.counts.loc["SRR1", "genus||Escherichia||561"] == 60
    assert matrix.counts.loc["SRR1", "Unclassified_genus"] == 40
    assert matrix.counts.loc["SRR2", "Unclassified_genus"] == 80


def test_genus_collapse_excludes_parent_ranks():
    matrix = AbundanceMatrixBuilder().build(_long())

    assert not any("Bacteria" in column for column in matrix.counts.columns)


def test_build_at_superkingdom_uses_clade_total_count():
    matrix = AbundanceMatrixBuilder().build(_long(), rank="superkingdom")

    assert set(matrix.counts.columns) == {"superkingdom||Bacteria||2", "Unclassified_superkingdom"}
    assert matrix.counts.loc["SRR1", "superkingdom||Bacteria||2"] == 100
    assert matrix.counts.loc["SRR2", "superkingdom||Bacteria||2"] == 80


def test_build_attaches_lineage_to_taxa():
    matrix = AbundanceMatrixBuilder().build(_long())

    genus_row = matrix.taxa[matrix.taxa["tax_id"] == 561].iloc[0]
    assert genus_row["superkingdom"] == "Bacteria"
