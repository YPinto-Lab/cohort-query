import pandas as pd
from askslm.metadata.metadata_extractor import MetadataExtractor


def _raw():
    return pd.DataFrame({
        "acc": ["SRR1", "SRR2"],
        "bioproject": ["PRJ1", "PRJ1"],
        "jattr": ['{"host": "human", "tissue": "gut"}', '{"host": "human"}'],
        "attributes": ["k=sex, v=male}", "k=sex, v=female}"],
    })


def test_extract_expands_blobs_into_columns():
    out = MetadataExtractor().extract(_raw())

    assert {"host", "tissue", "sex"}.issubset(out.columns)
    assert "jattr" not in out.columns
    assert "attributes" not in out.columns
    srr1 = out[out["acc"] == "SRR1"].iloc[0]
    assert (srr1["host"], srr1["tissue"], srr1["sex"]) == ("human", "gut", "male")


def test_extract_fills_absent_keys_with_empty_string():
    out = MetadataExtractor().extract(_raw())

    srr2 = out[out["acc"] == "SRR2"].iloc[0]
    assert srr2["tissue"] == ""


def test_extract_without_blobs_returns_base_columns():
    raw = pd.DataFrame({"acc": ["SRR1"], "bioproject": ["PRJ1"]})

    out = MetadataExtractor().extract(raw)

    assert list(out.columns) == ["acc", "bioproject"]
