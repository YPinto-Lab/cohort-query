from pathlib import Path
import Engines.TaxonomyEngine as taxonomy
from Common.contracts.selectors import FilterCriteria, TaxaSelector

_FIXTURES = Path(__file__).parent.parent.parent / "fixtures"
TAX = _FIXTURES / "taxonomy_tiny.csv"
DMP = _FIXTURES / "merged_tiny.dmp"


def test_load_then_build_then_subset():
    taxonomy_df = taxonomy.load(TAX)
    resolved = taxonomy.resolve(taxonomy_df, merged_dmp=DMP)
    matrix = taxonomy.build_abundance_matrix(resolved.df)

    subset = taxonomy.get_profile_subset(
        matrix,
        taxonomy_df[["acc"]].drop_duplicates().assign(Group="treatment"),
        FilterCriteria(taxa=TaxaSelector(rank="superkingdom", names=("Bacteria",))),
    )

    # genus-level matrix; Escherichia kept via lineage (superkingdom=Bacteria), Viruses excluded
    assert set(subset.profile_df.columns) == {"genus||Escherichia||561"}
