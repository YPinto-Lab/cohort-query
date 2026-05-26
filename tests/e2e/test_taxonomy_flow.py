from pathlib import Path
import pandas as pd
from askslm import taxonomy
from askslm.contracts import FilterCriteria, TaxaSelector, SampleSelector
from Engines.MetadataEngine.metadata import Metadata

_FIXTURES = Path(__file__).parent.parent / "fixtures"
TAX = _FIXTURES / "taxonomy_tiny.csv"
DMP = _FIXTURES / "merged_tiny.dmp"


def test_full_flow_subset_and_formats(tmp_path):
    taxonomy_df = taxonomy.load(TAX)
    resolved = taxonomy.resolve(taxonomy_df, merged_dmp=DMP)
    matrix = taxonomy.build_abundance_matrix(resolved.df)
    metadata = Metadata(df=pd.DataFrame({"acc": ["SRR1", "SRR2"], "Group": ["treatment", "control"]}))

    cohort = taxonomy.build_cohort(matrix, metadata).filter(
        FilterCriteria(
            taxa=TaxaSelector("superkingdom", ("Bacteria",)),
            samples=SampleSelector("Group", ("treatment",)),
        )
    )

    assert list(cohort.matrix.counts.index) == ["SRR1"]
    assert list(cohort.metadata.df["acc"]) == ["SRR1"]
    assert list(cohort.matrix.counts.columns) == ["genus||Escherichia||561"]
    for fmt, name in [("counts", "c.csv"), ("relative", "r.csv"), ("maaslin", "m.tsv"), ("biom", "t.biom")]:
        assert matrix.write(tmp_path / name, fmt=fmt).exists()
