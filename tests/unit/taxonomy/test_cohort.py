import pytest
import pandas as pd

from Engines.MetadataEngine.metadata import Metadata
from Engines.TaxonomyEngine.abundance_matrix_builder import AbundanceMatrixBuilder
from Engines.TaxonomyEngine.cohort import Cohort


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


def _metadata_full():
    return Metadata(df=pd.DataFrame({
        "acc": ["SRR1", "SRR2", "SRR3", "SRR4"],
        "Group": ["treatment", "control", "treatment", "control"],
        "assay_type": ["WGS", "WGS", "AMPLICON", "WGS"],
    }))


def test_construction_aligns_metadata_to_matrix_sample_index():
    cohort = Cohort(matrix=_matrix(), metadata=_metadata_full())

    # SRR4 is in metadata but not the matrix -> dropped; order matches matrix
    assert list(cohort.metadata.df["acc"]) == list(cohort.matrix.counts.index)


def test_construction_preserves_matrix_sample_order_in_metadata():
    matrix = _matrix()
    shuffled_md = Metadata(df=pd.DataFrame({
        "acc": ["SRR3", "SRR1", "SRR2"],
        "Group": ["t", "t", "c"],
    }))

    cohort = Cohort(matrix=matrix, metadata=shuffled_md)

    assert list(cohort.metadata.df["acc"]) == list(matrix.counts.index)


from Common.contracts.selectors import FilterCriteria, SampleSelector, TaxaSelector


def test_filter_by_taxa_keeps_only_matching_clade_columns():
    cohort = Cohort(matrix=_matrix(), metadata=_metadata_full())

    filtered = cohort.filter(FilterCriteria(taxa=TaxaSelector(rank="superkingdom", names=("Bacteria",))))

    assert list(filtered.matrix.counts.columns) == ["superkingdom||Bacteria||2"]


def test_filter_by_samples_keeps_only_matching_rows_in_both_halves():
    cohort = Cohort(matrix=_matrix(), metadata=_metadata_full())

    filtered = cohort.filter(FilterCriteria(samples=SampleSelector(column="Group", values=("treatment",))))

    assert list(filtered.matrix.counts.index) == ["SRR1", "SRR3"]
    assert list(filtered.metadata.df["acc"]) == ["SRR1", "SRR3"]


def test_filter_combined_taxa_and_samples():
    cohort = Cohort(matrix=_matrix(), metadata=_metadata_full())

    filtered = cohort.filter(FilterCriteria(
        taxa=TaxaSelector(rank="superkingdom", names=("Bacteria",)),
        samples=SampleSelector(column="Group", values=("treatment",)),
    ))

    assert list(filtered.matrix.counts.columns) == ["superkingdom||Bacteria||2"]
    assert list(filtered.matrix.counts.index) == ["SRR1", "SRR3"]
    assert list(filtered.metadata.df["acc"]) == ["SRR1", "SRR3"]


def test_filter_sample_filters_applies_and_logic_across_columns():
    cohort = Cohort(matrix=_matrix(), metadata=_metadata_full())

    filtered = cohort.filter(FilterCriteria(sample_filters=(
        SampleSelector(column="Group", values=("treatment",)),
        SampleSelector(column="assay_type", values=("WGS",)),
    )))

    assert list(filtered.matrix.counts.index) == ["SRR1"]
    assert list(filtered.metadata.df["acc"]) == ["SRR1"]


def test_filter_samples_and_sample_filters_combine():
    cohort = Cohort(matrix=_matrix(), metadata=_metadata_full())

    filtered = cohort.filter(FilterCriteria(
        samples=SampleSelector(column="Group", values=("treatment",)),
        sample_filters=(SampleSelector(column="assay_type", values=("WGS",)),),
    ))

    assert list(filtered.matrix.counts.index) == ["SRR1"]


def test_filter_with_empty_criteria_is_identity_on_rows_and_cols():
    cohort = Cohort(matrix=_matrix(), metadata=_metadata_full())

    filtered = cohort.filter(FilterCriteria())

    assert list(filtered.matrix.counts.index) == list(cohort.matrix.counts.index)
    assert list(filtered.matrix.counts.columns) == list(cohort.matrix.counts.columns)


def test_filter_preserves_taxa_lookup_through_matrix():
    cohort = Cohort(matrix=_matrix(), metadata=_metadata_full())

    filtered = cohort.filter(FilterCriteria(taxa=TaxaSelector(rank="superkingdom", names=("Bacteria",))))

    assert "superkingdom||Bacteria||2" in set(filtered.matrix.taxa["taxon_key"])


def test_write_produces_abundance_matrix_csv_and_metadata_csv(tmp_path):
    cohort = Cohort(matrix=_matrix(), metadata=_metadata_full())

    paths = cohort.write(tmp_path)

    matrix_path = tmp_path / "abundance_matrix.csv"
    metadata_path = tmp_path / "metadata.csv"
    assert matrix_path.exists()
    assert metadata_path.exists()
    assert set(paths) == {matrix_path, metadata_path}


def test_write_metadata_csv_has_no_pandas_index_column(tmp_path):
    cohort = Cohort(matrix=_matrix(), metadata=_metadata_full())

    cohort.write(tmp_path)

    written = pd.read_csv(tmp_path / "metadata.csv")
    assert "Unnamed: 0" not in written.columns
    assert list(written.columns)[0] == "acc"


def test_n_samples_returns_row_count():
    cohort = Cohort(matrix=_matrix(), metadata=_metadata_full())
    assert cohort.n_samples == 3


def test_n_taxa_returns_column_count():
    cohort = Cohort(matrix=_matrix(), metadata=_metadata_full())
    assert cohort.n_taxa == 3


def test_unique_returns_sorted_list_of_column_values():
    cohort = Cohort(matrix=_matrix(), metadata=_metadata_full())
    # cohort has SRR1 (WGS/treatment), SRR2 (WGS/control), SRR3 (AMPLICON/treatment)
    assert cohort.unique("assay_type") == ["AMPLICON", "WGS"]


def test_unique_raises_for_unknown_column():
    cohort = Cohort(matrix=_matrix(), metadata=_metadata_full())
    with pytest.raises(ValueError, match="not_a_col"):
        cohort.unique("not_a_col")


def test_enrich_adds_columns_from_df_to_metadata():
    cohort = Cohort(matrix=_matrix(), metadata=_metadata_full())
    extra = pd.DataFrame({
        "Group": ["treatment", "control"],
        "Score": [1.0, 2.0],
    })

    enriched = cohort.enrich(extra, left_on="Group", right_on="Group")

    assert "Score" in enriched.metadata.df.columns
    assert enriched.metadata.df.set_index("acc").loc["SRR1", "Score"] == 1.0
    assert enriched.metadata.df.set_index("acc").loc["SRR2", "Score"] == 2.0


def test_enrich_broadcasts_subject_level_data_to_samples():
    cohort = Cohort(matrix=_matrix(), metadata=_metadata_full())
    extra = pd.DataFrame({
        "SubjectID": ["treatment", "control"],
        "Cluster": ["A", "B"],
    })

    enriched = cohort.enrich(extra, left_on="Group", right_on="SubjectID")

    srr1_cluster = enriched.metadata.df.set_index("acc").loc["SRR1", "Cluster"]
    srr3_cluster = enriched.metadata.df.set_index("acc").loc["SRR3", "Cluster"]
    assert srr1_cluster == "A"
    assert srr3_cluster == "A"


def test_enrich_unmatched_samples_get_nan():
    cohort = Cohort(matrix=_matrix(), metadata=_metadata_full())
    extra = pd.DataFrame({
        "Group": ["treatment"],
        "Score": [99.0],
    })

    enriched = cohort.enrich(extra, left_on="Group", right_on="Group")

    srr2_score = enriched.metadata.df.set_index("acc").loc["SRR2", "Score"]
    import math
    assert math.isnan(srr2_score)


def test_enrich_preserves_matrix_unchanged():
    cohort = Cohort(matrix=_matrix(), metadata=_metadata_full())
    extra = pd.DataFrame({"Group": ["treatment", "control"], "Score": [1.0, 2.0]})

    enriched = cohort.enrich(extra, left_on="Group", right_on="Group")

    assert enriched.matrix is cohort.matrix


def test_enrich_raises_if_left_on_not_in_metadata():
    cohort = Cohort(matrix=_matrix(), metadata=_metadata_full())
    extra = pd.DataFrame({"Subject": ["x"], "Score": [1.0]})

    with pytest.raises(ValueError, match="missing_col"):
        cohort.enrich(extra, left_on="missing_col", right_on="Subject")


def test_enrich_raises_if_right_on_not_in_df():
    cohort = Cohort(matrix=_matrix(), metadata=_metadata_full())
    extra = pd.DataFrame({"Subject": ["x"], "Score": [1.0]})

    with pytest.raises(ValueError, match="missing_col"):
        cohort.enrich(extra, left_on="Group", right_on="missing_col")


def test_split_by_returns_one_cohort_per_unique_value():
    cohort = Cohort(matrix=_matrix(), metadata=_metadata_full())
    parts = cohort.split_by("Group")
    assert set(parts.keys()) == {"treatment", "control"}


def test_split_by_samples_are_correct_per_group():
    cohort = Cohort(matrix=_matrix(), metadata=_metadata_full())
    parts = cohort.split_by("Group")
    assert list(parts["treatment"].metadata.df["acc"]) == ["SRR1", "SRR3"]
    assert list(parts["control"].metadata.df["acc"]) == ["SRR2"]


def test_split_by_matrix_rows_match_metadata_per_group():
    cohort = Cohort(matrix=_matrix(), metadata=_metadata_full())
    parts = cohort.split_by("Group")
    for label, sub in parts.items():
        assert list(sub.matrix.counts.index) == list(sub.metadata.df["acc"])


def test_split_by_nan_rows_are_excluded():
    md = Metadata(df=pd.DataFrame({
        "acc": ["SRR1", "SRR2", "SRR3"],
        "Group": ["treatment", None, "treatment"],
        "assay_type": ["WGS", "WGS", "WGS"],
    }))
    cohort = Cohort(matrix=_matrix(), metadata=md)
    parts = cohort.split_by("Group")
    assert set(parts.keys()) == {"treatment"}
    assert list(parts["treatment"].metadata.df["acc"]) == ["SRR1", "SRR3"]


def test_split_by_raises_for_unknown_column():
    cohort = Cohort(matrix=_matrix(), metadata=_metadata_full())
    with pytest.raises(ValueError, match="no_such_col"):
        cohort.split_by("no_such_col")
