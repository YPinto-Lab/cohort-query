import pandas as pd
import Engines.TaxonomyEngine as taxonomy
from Common.contracts.selectors import FilterCriteria, TaxaSelector
from Engines.MetadataEngine.metadata import Metadata
from Engines.TaxonomyEngine.cohort import Cohort


def _matrix():
    long_df = pd.DataFrame({
        "acc": ["SRR1", "SRR1", "SRR2"],
        "tax_id": [2, 10239, 2],
        "rank": ["superkingdom", "superkingdom", "superkingdom"],
        "name": ["Bacteria", "Viruses", "Bacteria"],
        "total_count": [100, 40, 80],
        "self_count": [100, 40, 80],
        "ileft": [1, 3, 1],
        "iright": [2, 4, 2],
    })
    builder = taxonomy.AbundanceMatrixBuilder()
    return builder.build(builder.build(long_df), "superkingdom")


def test_build_cohort_returns_cohort_pairing_matrix_and_metadata():
    matrix = _matrix()
    metadata = Metadata(df=pd.DataFrame({"acc": ["SRR1", "SRR2"], "Group": ["t", "c"]}))

    cohort = taxonomy.build_cohort(matrix, metadata)

    assert isinstance(cohort, Cohort)
    assert list(cohort.metadata.df["acc"]) == list(cohort.matrix.matrix.index)


def test_build_cohort_then_filter_narrows_by_taxa():
    matrix = _matrix()
    metadata = Metadata(df=pd.DataFrame({"acc": ["SRR1", "SRR2"], "Group": ["t", "c"]}))

    filtered = taxonomy.build_cohort(matrix, metadata).filter(
        FilterCriteria(taxa=TaxaSelector(rank="superkingdom", names=("Bacteria",)))
    )

    assert list(filtered.matrix.matrix.columns) == ["superkingdom||Bacteria||2"]
