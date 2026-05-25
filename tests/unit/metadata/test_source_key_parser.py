import pandas as pd
from Engines.MetadataEngine.source_key_parser import SourceKeyParser


def test_parses_jattr_and_attributes():
    row = pd.Series({"jattr": '{"host": "human", "tags": ["a", "b"]}', "attributes": "k=sex, v=male}"})

    parsed = SourceKeyParser().parse(row)

    assert parsed["host"] == "human"
    assert parsed["tags"] == "a b"
    assert parsed["sex"] == "male"


def test_jattr_wins_on_key_collision():
    row = pd.Series({"jattr": '{"sex": "female"}', "attributes": "k=sex, v=male}"})

    parsed = SourceKeyParser().parse(row)

    assert parsed["sex"] == "female"


def test_missing_or_invalid_blobs_yield_empty():
    row = pd.Series({"jattr": float("nan"), "attributes": None})

    parsed = SourceKeyParser().parse(row)

    assert parsed == {}


def test_parses_multiple_brace_terminated_attribute_pairs():
    row = pd.Series({"jattr": float("nan"), "attributes": "k=sex, v=male}k=tissue, v=gut}"})

    parsed = SourceKeyParser().parse(row)

    assert parsed == {"sex": "male", "tissue": "gut"}
