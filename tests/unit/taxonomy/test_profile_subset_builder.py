import pandas as pd
from Engines.TaxonomyEngine.abundance_matrix_builder import AbundanceMatrixBuilder
from Engines.TaxonomyEngine.profile_subset_builder import ProfileSubsetBuilder
from Common.contracts.selectors import SubsetCriteria, TaxaSelector, SampleSelector


def _matrix():
    long_df = pd.DataFrame({
        "acc": ["SRR1", "SRR1", "SRR2", "SRR3"],
        "tax_id": [2, 10239, 2, 2],
        "rank": ["superkingdom", "superkingdom", "superkingdom", "superkingdom"],
        "name": ["Bacteria", "Viruses", "Bacteria", "Bacteria"],
        "total_count": [100, 40, 80, 60],
        "self_count": [100, 40, 80, 60],
        "ileft": [1, 3, 1, 1],
        "iright": [2, 4, 2, 2],
    })
    return AbundanceMatrixBuilder().build(long_df, rank="superkingdom")


def _metadata():
    return pd.DataFrame({
        "acc": ["SRR1", "SRR2", "SRR3"],
        "Group": ["treatment", "control", "treatment"],
        "assay_type": ["WGS", "WGS", "AMPLICON"],
    })


def test_taxa_filter_keeps_only_bacteria_columns():
    criteria = SubsetCriteria(taxa=TaxaSelector(rank="superkingdom", names=("Bacteria",)))

    subset = ProfileSubsetBuilder().build(_matrix(), _metadata(), criteria)

    assert list(subset.profile_df.columns) == ["superkingdom||Bacteria||2"]


def test_sample_filter_keeps_only_treatment_rows():
    criteria = SubsetCriteria(samples=SampleSelector(column="Group", values=("treatment",)))

    subset = ProfileSubsetBuilder().build(_matrix(), _metadata(), criteria)

    assert set(subset.profile_df.index) == {"SRR1", "SRR3"}


def test_combined_taxa_and_sample_filter():
    criteria = SubsetCriteria(
        taxa=TaxaSelector(rank="superkingdom", names=("Bacteria",)),
        samples=SampleSelector(column="Group", values=("treatment",)),
    )

    subset = ProfileSubsetBuilder().build(_matrix(), _metadata(), criteria)

    assert list(subset.profile_df.columns) == ["superkingdom||Bacteria||2"]
    assert set(subset.profile_df.index) == {"SRR1", "SRR3"}


def test_sample_filters_applies_and_logic_across_two_columns():
    criteria = SubsetCriteria(
        sample_filters=(
            SampleSelector(column="Group", values=("treatment",)),
            SampleSelector(column="assay_type", values=("WGS",)),
        ),
    )

    subset = ProfileSubsetBuilder().build(_matrix(), _metadata(), criteria)

    assert list(subset.profile_df.index) == ["SRR1"]


def test_sample_filters_combined_with_samples_applies_all():
    criteria = SubsetCriteria(
        samples=SampleSelector(column="Group", values=("treatment",)),
        sample_filters=(SampleSelector(column="assay_type", values=("WGS",)),),
    )

    subset = ProfileSubsetBuilder().build(_matrix(), _metadata(), criteria)

    assert list(subset.profile_df.index) == ["SRR1"]


def test_empty_sample_filters_returns_full_profile():
    criteria = SubsetCriteria(sample_filters=())

    subset = ProfileSubsetBuilder().build(_matrix(), _metadata(), criteria)

    assert set(subset.profile_df.index) == {"SRR1", "SRR2", "SRR3"}
