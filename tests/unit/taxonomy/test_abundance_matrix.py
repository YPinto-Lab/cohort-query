import pandas as pd
from Engines.TaxonomyEngine.abundance_matrix import AbundanceMatrix


def _matrix():
    counts = pd.DataFrame(
        {"superkingdom||Bacteria||2": [100, 80], "superkingdom||Viruses||10239": [40, 0]},
        index=pd.Index(["SRR1", "SRR2"], name="acc"),
    )
    lookup = pd.DataFrame({
        "taxon_key": ["superkingdom||Bacteria||2", "superkingdom||Viruses||10239"],
        "tax_id": [2, 10239],
        "rank": ["superkingdom", "superkingdom"],
        "name": ["Bacteria", "Viruses"],
    })
    lineage = pd.DataFrame({"tax_id": [2, 10239], "superkingdom": ["Bacteria", "Viruses"]})
    return AbundanceMatrix(counts=counts, lookup=lookup, lineage_df=lineage)


def test_relative_rows_sum_to_one():
    matrix = _matrix()

    relative = matrix.relative

    assert abs(relative.loc["SRR1"].sum() - 1.0) < 1e-9


def test_taxa_join_carries_superkingdom():
    matrix = _matrix()

    taxa = matrix.taxa

    bacteria = taxa[taxa["taxon_key"] == "superkingdom||Bacteria||2"].iloc[0]
    assert bacteria["superkingdom"] == "Bacteria"


def test_relative_all_zero_row_is_zero_and_float():
    counts = pd.DataFrame(
        {"superkingdom||Bacteria||2": [0, 5]},
        index=pd.Index(["SRR_empty", "SRR_ok"], name="acc"),
    )
    lookup = pd.DataFrame({"taxon_key": ["superkingdom||Bacteria||2"], "tax_id": [2],
                           "rank": ["superkingdom"], "name": ["Bacteria"]})
    lineage = pd.DataFrame({"tax_id": [2], "superkingdom": ["Bacteria"]})
    matrix = AbundanceMatrix(counts=counts, lookup=lookup, lineage_df=lineage)

    relative = matrix.relative

    assert relative.loc["SRR_empty"].sum() == 0.0
    assert all(dtype == float for dtype in relative.dtypes)


def test_for_samples_keeps_only_requested_rows():
    matrix = _matrix()

    subset = matrix.for_samples(["SRR1"])

    assert list(subset.counts.index) == ["SRR1"]


def test_for_samples_ignores_unknown_ids():
    matrix = _matrix()

    subset = matrix.for_samples(["SRR1", "SRR_NOT_THERE"])

    assert list(subset.counts.index) == ["SRR1"]


def test_for_samples_preserves_taxa_lookup():
    matrix = _matrix()

    subset = matrix.for_samples(["SRR1"])

    assert list(subset.taxa.columns) == list(matrix.taxa.columns)
