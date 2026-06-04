from __future__ import annotations
from typing import Any, Callable
import pandas as pd
from biom import Table

from askslm.contracts import MetadataOverview


def _biom_table(t: Table) -> dict:
    return {
        "type": "FeatureTable",
        "shape": list(t.shape),  # [n_features, n_samples]
        "features_preview": list(t.ids("observation"))[:5],
        "samples_preview": list(t.ids("sample"))[:5],
    }


def _metadata_overview(o: MetadataOverview) -> dict:
    return {"type": "MetadataOverview", "summary_available": True}


def _dataframe(df: pd.DataFrame) -> dict:
    return {
        "type": "DataFrame",
        "shape": list(df.shape),
        "columns": list(df.columns)[:30],
    }


_SUMMARIZERS: list[tuple[type, Callable[[Any], dict]]] = [
    (Table, _biom_table),
    (MetadataOverview, _metadata_overview),
    (pd.DataFrame, _dataframe),
]


def summarize_object(obj: Any) -> dict:
    for typ, fn in _SUMMARIZERS:
        if isinstance(obj, typ):
            return fn(obj)
    return {"type": "object", "repr": repr(obj)[:200]}
