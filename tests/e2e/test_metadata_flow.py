import pandas as pd
from askslm import metadata


def _raw():
    return pd.DataFrame({
        "acc": ["SRR1", "SRR2", "SRR3"],
        "bioproject": ["PRJ1", "PRJ1", "PRJ2"],
        "jattr": ['{"host": "human", "tissue": "gut"}', '{"host": "human", "tissue": "skin"}', '{"host": "mouse"}'],
        "attributes": ["k=sex, v=male}", "k=sex, v=female}", "k=sex, v=male}"],
    })


def test_extract_overview_and_write(tmp_path):
    extracted = metadata.extract(_raw())
    overview = metadata.overview(extracted)

    assert {"host", "tissue", "sex"}.issubset(extracted.columns)
    coverage = overview.coverage_matrix_df.set_index("bioproject")
    assert coverage.loc["PRJ2", "tissue"] == 0.0
    assert coverage.loc["PRJ1", "tissue"] == 1.0
    paths = overview.write(tmp_path)
    assert all(p.exists() for p in paths)
