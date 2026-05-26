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
