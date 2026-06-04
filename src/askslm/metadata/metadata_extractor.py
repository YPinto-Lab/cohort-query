from __future__ import annotations

import pandas as pd

from .source_key_parser import SourceKeyParser

_BLOB_COLUMNS = ["jattr", "attributes"]


class MetadataExtractor:
    """Expands jattr/attributes blobs into real per-sample columns keyed by acc."""

    def __init__(self) -> None:
        self._parser = SourceKeyParser()

    def extract(self, raw_df: pd.DataFrame) -> pd.DataFrame:
        base = self._base(raw_df)
        parsed = self._parsed(raw_df)
        for key in self._discovered(parsed, base):
            base[key] = self._column(key, parsed, base.index)
        return base.reset_index()

    def _base(self, raw_df: pd.DataFrame) -> pd.DataFrame:
        present_blobs = [c for c in _BLOB_COLUMNS if c in raw_df.columns]
        dropped = raw_df.drop(columns=present_blobs)
        return dropped.drop_duplicates(subset=["acc"]).set_index("acc")

    def _parsed(self, raw_df: pd.DataFrame) -> pd.Series:
        unique = raw_df.drop_duplicates(subset=["acc"]).set_index("acc")
        return unique.apply(self._parser.parse, axis=1)

    def _discovered(self, parsed: pd.Series, base: pd.DataFrame) -> list[str]:
        keys = {key for entry in parsed for key in entry}
        return sorted(k for k in keys if k not in base.columns and k != "acc")

    def _column(self, key: str, parsed: pd.Series, index: pd.Index) -> pd.Series:
        values = parsed.apply(lambda entry: entry.get(key, ""))
        return values.reindex(index).fillna("")
