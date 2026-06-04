import pandas as pd
import askslm.metadata as metadata


def _raw():
    return pd.DataFrame({
        "acc": ["SRR1", "SRR2"],
        "bioproject": ["PRJ1", "PRJ1"],
        "jattr": ['{"host": "human"}', '{"host": "mouse"}'],
        "attributes": ["k=sex, v=male}", "k=sex, v=female}"],
    })


def test_extract_then_overview():
    extracted = metadata.extract(_raw())
    overview = metadata.overview(extracted)

    assert "host" in extracted.columns
    assert set(overview.discovered_keys_unique_df["key_name"]) == {"host", "sex"}
