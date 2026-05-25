import pandas as pd
from Engines.TaxonomyEngine.abundance_matrix_builder import AbundanceMatrixBuilder
from Engines.TaxonomyEngine.profile_subset_builder import ProfileSubsetBuilder
from Common.contracts.selectors import SubsetCriteria, TaxaSelector, SampleSelector


def _matrix():
    long_df = pd.DataFrame({
        "acc": ["SRR1", "SRR1", "SRR2"],
        "tax_id": [2, 10239, 2],
        "rank": ["superkingdom", "superkingdom", "superkingdom"],
        "name": ["Bacteria", "Viruses", "Bacteria"],
        "total_count": [100, 40, 80],
        "ileft": [1, 3, 1],
        "iright": [2, 4, 2],
    })
    return AbundanceMatrixBuilder().build(long_df)


def _metadata():
    return pd.DataFrame({"acc": ["SRR1", "SRR2"], "Group": ["treatment", "control"]})


def test_taxa_filter_keeps_only_bacteria_columns():
    criteria = SubsetCriteria(taxa=TaxaSelector(rank="superkingdom", names=("Bacteria",)))

    subset = ProfileSubsetBuilder().build(_matrix(), _metadata(), criteria)

    assert list(subset.profile_df.columns) == ["superkingdom||Bacteria||2"]


def test_sample_filter_keeps_only_treatment_rows():
    criteria = SubsetCriteria(samples=SampleSelector(column="Group", values=("treatment",)))

    subset = ProfileSubsetBuilder().build(_matrix(), _metadata(), criteria)

    assert list(subset.profile_df.index) == ["SRR1"]


def test_combined_taxa_and_sample_filter():
    criteria = SubsetCriteria(
        taxa=TaxaSelector(rank="superkingdom", names=("Bacteria",)),
        samples=SampleSelector(column="Group", values=("treatment",)),
    )

    subset = ProfileSubsetBuilder().build(_matrix(), _metadata(), criteria)

    assert list(subset.profile_df.columns) == ["superkingdom||Bacteria||2"]
    assert list(subset.profile_df.index) == ["SRR1"]
