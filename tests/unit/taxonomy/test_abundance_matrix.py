import pandas as pd
import pytest
from Engines.TaxonomyEngine.abundance_matrix import AbundanceMatrix


def _matrix():
    pivot = pd.DataFrame(
        {
            "superkingdom||Bacteria||2": [100, 80],
            "superkingdom||Viruses||10239": [40, 0],
        },
        index=pd.Index(["SRR1", "SRR2"], name="acc"),
    )
    total_reads = pd.Series([140, 80], index=pd.Index(["SRR1", "SRR2"], name="acc"))
    taxon_key_lookup = pd.DataFrame({
        "taxon_key": ["superkingdom||Bacteria||2", "superkingdom||Viruses||10239"],
        "tax_id": [2, 10239],
        "rank": ["superkingdom", "superkingdom"],
        "name": ["Bacteria", "Viruses"],
    })
    tax_id_lineage_lookup = pd.DataFrame({
        "tax_id": [2, 10239],
        "superkingdom": ["Bacteria", "Viruses"],
    })
    return AbundanceMatrix(
        matrix=pivot,
        total_reads=total_reads,
        taxon_key_lookup=taxon_key_lookup,
        tax_id_lineage_lookup=tax_id_lineage_lookup,
    )


def test_samples_returns_matrix_index_as_list():
    matrix = _matrix()

    samples = matrix.samples

    assert samples == ["SRR1", "SRR2"]


def test_relative_abundance_uses_total_reads_as_denominator():
    matrix = _matrix()

    relative = matrix.relative_abundance

    assert abs(relative.loc["SRR1"].sum() - 1.0) < 1e-9
    assert abs(relative.loc["SRR1", "superkingdom||Bacteria||2"] - 100 / 140) < 1e-9


def test_relative_abundance_handles_zero_total_reads():
    pivot = pd.DataFrame(
        {"superkingdom||Bacteria||2": [0, 5]},
        index=pd.Index(["SRR_empty", "SRR_ok"], name="acc"),
    )
    total_reads = pd.Series([0, 5], index=pd.Index(["SRR_empty", "SRR_ok"], name="acc"))
    taxon_key_lookup = pd.DataFrame({
        "taxon_key": ["superkingdom||Bacteria||2"], "tax_id": [2],
        "rank": ["superkingdom"], "name": ["Bacteria"],
    })
    tax_id_lineage_lookup = pd.DataFrame({"tax_id": [2], "superkingdom": ["Bacteria"]})
    matrix = AbundanceMatrix(
        matrix=pivot, total_reads=total_reads,
        taxon_key_lookup=taxon_key_lookup, tax_id_lineage_lookup=tax_id_lineage_lookup,
    )

    relative = matrix.relative_abundance

    assert relative.loc["SRR_empty"].sum() == 0.0


def test_taxa_lineage_joins_lookup_and_lineage():
    matrix = _matrix()

    taxa_lineage = matrix.taxa_lineage

    bacteria = taxa_lineage[taxa_lineage["taxon_key"] == "superkingdom||Bacteria||2"].iloc[0]
    assert bacteria["superkingdom"] == "Bacteria"


def test_filter_keeps_requested_samples_by_default():
    matrix = _matrix()

    subset = matrix.filter(["SRR1"])

    assert subset.samples == ["SRR1"]
    assert subset.total_reads.loc["SRR1"] == 140


def test_filter_with_exclude_drops_listed_samples():
    matrix = _matrix()

    subset = matrix.filter(["SRR1"], exclude=True)

    assert subset.samples == ["SRR2"]


def test_filter_ignores_unknown_sample_ids():
    matrix = _matrix()

    subset = matrix.filter(["SRR1", "SRR_NOT_THERE"])

    assert subset.samples == ["SRR1"]


def test_filter_preserves_taxa_lineage_columns():
    matrix = _matrix()

    subset = matrix.filter(["SRR1"])

    assert list(subset.taxa_lineage.columns) == list(matrix.taxa_lineage.columns)
