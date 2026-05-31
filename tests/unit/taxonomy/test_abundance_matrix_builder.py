import pandas as pd
import pytest
from Engines.TaxonomyEngine.abundance_matrix import AbundanceMatrix
from Engines.TaxonomyEngine.abundance_matrix_builder import AbundanceMatrixBuilder


def _long():
    return pd.DataFrame({
        "acc":         ["SRR1", "SRR1", "SRR2", "SRR2"],
        "tax_id":      [2,      561,    2,      561],
        "rank":        ["superkingdom", "genus", "superkingdom", "genus"],
        "name":        ["Bacteria", "Escherichia", "Bacteria", "Escherichia"],
        "total_count": [100, 60, 80, 70],
        "self_count":  [40,  60, 10, 70],
        "ileft":       [1, 3, 1, 3],
        "iright":      [8, 4, 8, 4],
    })


def test_build_from_df_pivots_every_taxon_row_with_self_count():
    matrix = AbundanceMatrixBuilder().build(_long())

    assert isinstance(matrix, AbundanceMatrix)
    assert set(matrix.matrix.columns) == {
        "superkingdom||Bacteria||2",
        "genus||Escherichia||561",
    }
    assert matrix.matrix.loc["SRR1", "superkingdom||Bacteria||2"] == 40
    assert matrix.matrix.loc["SRR1", "genus||Escherichia||561"] == 60


def test_build_from_df_total_reads_is_row_sum_of_self_counts():
    matrix = AbundanceMatrixBuilder().build(_long())

    assert matrix.total_reads.loc["SRR1"] == 100  # 40 + 60
    assert matrix.total_reads.loc["SRR2"] == 80   # 10 + 70


def test_build_from_df_relative_abundance_rows_sum_to_one():
    matrix = AbundanceMatrixBuilder().build(_long())

    assert abs(matrix.relative_abundance.loc["SRR1"].sum() - 1.0) < 1e-9
    assert abs(matrix.relative_abundance.loc["SRR2"].sum() - 1.0) < 1e-9


def test_build_from_matrix_collapses_to_rank_via_lineage():
    full = AbundanceMatrixBuilder().build(_long())

    genus = AbundanceMatrixBuilder().build(full, "genus")

    assert set(genus.matrix.columns) == {"genus||Escherichia||561"}
    assert genus.matrix.loc["SRR1", "genus||Escherichia||561"] == 60
    assert genus.matrix.loc["SRR2", "genus||Escherichia||561"] == 70


def test_build_from_matrix_drops_columns_without_ancestor_at_rank():
    full = AbundanceMatrixBuilder().build(_long())

    species = AbundanceMatrixBuilder().build(full, "species")

    assert list(species.matrix.columns) == []


def test_build_from_matrix_total_reads_equals_row_sum_of_collapsed_matrix():
    full = AbundanceMatrixBuilder().build(_long())

    superkingdom = AbundanceMatrixBuilder().build(full, "superkingdom")

    assert superkingdom.total_reads.loc["SRR1"] == superkingdom.matrix.loc["SRR1"].sum()


def test_build_from_matrix_at_same_rank_is_idempotent():
    full = AbundanceMatrixBuilder().build(_long())
    genus_once = AbundanceMatrixBuilder().build(full, "genus")

    genus_twice = AbundanceMatrixBuilder().build(genus_once, "genus")

    pd.testing.assert_frame_equal(genus_twice.matrix, genus_once.matrix)


def test_build_from_matrix_collapses_when_tax_id_is_string_typed():
    long_df = _long().astype({"tax_id": str})

    full = AbundanceMatrixBuilder().build(long_df)
    genus = AbundanceMatrixBuilder().build(full, "genus")

    assert set(genus.matrix.columns) == {"genus||Escherichia||561"}


def test_build_rejects_unsupported_source_type():
    with pytest.raises(TypeError):
        AbundanceMatrixBuilder().build(42)
