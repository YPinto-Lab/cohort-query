from pathlib import Path
from Accessors.TaxonomyAccessor.taxonomy_file_accessor import TaxonomyFileAccessor

FIXTURE = Path(__file__).parent.parent.parent / "fixtures" / "taxonomy_tiny.csv"


def test_read_returns_validated_long_table():
    accessor = TaxonomyFileAccessor()

    df = accessor.read(FIXTURE)

    assert set(["acc", "tax_id", "rank", "name", "total_count", "ileft", "iright"]).issubset(df.columns)
    assert len(df) == 6
