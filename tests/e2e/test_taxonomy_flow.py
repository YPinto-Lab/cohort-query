from pathlib import Path
import pandas as pd
from askslm import taxonomy
from askslm.contracts import SubsetCriteria, TaxaSelector, SampleSelector

TAX = Path("Tests/fixtures/taxonomy_tiny.csv")
DMP = Path("Tests/fixtures/merged_tiny.dmp")


def test_full_flow_subset_and_formats(tmp_path):
    taxonomy_df = taxonomy.load(TAX)
    resolved = taxonomy.resolve(taxonomy_df, merged_dmp=DMP)
    matrix = taxonomy.build_abundance_matrix(resolved.df)
    metadata = pd.DataFrame({"acc": ["SRR1", "SRR2"], "Group": ["treatment", "control"]})

    subset = taxonomy.get_profile_subset(
        matrix, metadata,
        SubsetCriteria(
            taxa=TaxaSelector("superkingdom", ("Bacteria",)),
            samples=SampleSelector("Group", ("treatment",)),
        ),
    )

    assert list(subset.profile_df.index) == ["SRR1"]
    assert list(subset.metadata_df["acc"]) == ["SRR1"]
    for fmt, name in [("counts", "c.csv"), ("relative", "r.csv"), ("maaslin", "m.tsv"), ("biom", "t.biom")]:
        assert matrix.write(tmp_path / name, fmt=fmt).exists()
