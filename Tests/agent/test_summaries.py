import pandas as pd
from Engines.MetadataEngine.metadata import Metadata
from Agents.summaries import summarize_object


def test_summarize_metadata():
    df = pd.DataFrame({"acc": ["S1", "S2"], "group": ["a", "b"]})
    md = Metadata(df=df)
    s = summarize_object(md)
    assert s["type"] == "Metadata"
    assert s["n_samples"] == 2
    assert "group" in s["columns"]


def test_summarize_dataframe():
    df = pd.DataFrame({"x": [1, 2, 3]})
    s = summarize_object(df)
    assert s["type"] == "DataFrame"
    assert s["shape"] == [3, 1]


def test_summarize_unknown_falls_back_to_repr():
    s = summarize_object(object())
    assert s["type"] == "object"
    assert "repr" in s
