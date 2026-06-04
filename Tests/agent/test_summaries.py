import numpy as np
import pandas as pd
from biom import Table

from agent.summaries import summarize_object


def test_feature_table_summary():
    t = Table(np.array([[1, 2], [3, 4]]), observation_ids=["10", "20"], sample_ids=["sA", "sB"])
    out = summarize_object(t)
    assert out["type"] == "FeatureTable"
    assert out["shape"] == [2, 2]
    assert out["features_preview"] == ["10", "20"]
    assert out["samples_preview"] == ["sA", "sB"]


def test_dataframe_summary():
    out = summarize_object(pd.DataFrame({"a": [1, 2], "b": [3, 4]}))
    assert out["type"] == "DataFrame"
    assert out["shape"] == [2, 2]


def test_unknown_object_falls_back():
    out = summarize_object(object())
    assert out["type"] == "object"
    assert "repr" in out
