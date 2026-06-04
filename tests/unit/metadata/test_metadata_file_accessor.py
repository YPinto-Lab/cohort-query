import pandas as pd
from askslm.sra_schema import SRAMetadataSchema
from askslm.accessors.metadata_file_accessor import MetadataFileAccessor


def _write_csv(tmp_path):
    columns = list(SRAMetadataSchema.__fields__.keys())
    frame = pd.DataFrame({c: ["", ""] for c in columns})
    frame["acc"] = ["SRR1", "SRR2"]
    frame["bioproject"] = ["PRJ1", "PRJ1"]
    # Set integer columns to valid values (nullable, so empty strings won't work)
    frame["mbytes"] = [100, 200]
    frame["avgspotlen"] = [75, 75]
    frame["mbases"] = [1000, 2000]
    path = tmp_path / "metadata.csv"
    frame.to_csv(path, index=False)
    return path


def test_read_returns_validated_frame(tmp_path):
    accessor = MetadataFileAccessor()

    frame = accessor.read(_write_csv(tmp_path))

    assert list(frame["acc"]) == ["SRR1", "SRR2"]
    assert "bioproject" in frame.columns
