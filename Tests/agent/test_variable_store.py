import pandas as pd
import pytest
from agent.variable_store import VariableStore


def test_put_returns_handle_and_get_returns_object():
    store = VariableStore()
    df = pd.DataFrame({"x": [1]})
    h = store.put(df, hint="df")
    assert h == "df_1"
    assert store.get(h) is df


def test_handles_increment_per_hint():
    store = VariableStore()
    store.put(pd.DataFrame(), hint="df")
    h2 = store.put(pd.DataFrame(), hint="df")
    assert h2 == "df_2"


def test_missing_handle_raises_with_available_list():
    store = VariableStore()
    store.put(pd.DataFrame(), hint="df")
    with pytest.raises(KeyError) as exc:
        store.get("missing_99")
    assert "df_1" in str(exc.value)


def test_summary_uses_summarize_object():
    store = VariableStore()
    h = store.put(pd.DataFrame({"a": [1, 2]}), hint="df")
    s = store.summary(h)
    assert s["handle"] == h
    assert s["type"] == "DataFrame"


def test_list_handles_returns_handle_to_summary_map():
    store = VariableStore()
    store.put(pd.DataFrame(), hint="df")
    listing = store.list_handles()
    assert "df_1" in listing
    assert listing["df_1"]["type"] == "DataFrame"
