"""Attach source key values to minimal metadata tables."""

import re
from typing import List

import pandas as pd

from .source_key_extractor import SourceKeyExtractor


class SourceKeyAttacher:
    """Materialize requested source keys for each accession.

    Takes a metadata dataframe and extracts/expands source keys into a result table.
    """

    def __init__(self, metadata_df: pd.DataFrame) -> None:
        self._meta = metadata_df
        self._extractor = SourceKeyExtractor()

    def attach(self, source_keys: List[str]) -> pd.DataFrame:
        """Materialize source keys and return table with acc and requested keys."""
        meta = self._meta.drop_duplicates(subset=["acc"]).copy()
        meta = meta.set_index("acc")

        for source_key in source_keys:
            extracted = meta.apply(lambda row: self._extractor.extract(row, source_key), axis=1)
            meta[source_key] = extracted.apply(self._normalize_scalar)

        meta = self._drop_helper_columns(meta)
        return meta.reset_index()

    def _normalize_scalar(self, value) -> str:
        """Normalize a value to string with clean formatting."""
        if pd.isna(value):
            return ""
        text = str(value).strip()
        if text.lower() in {"", "nan", "none"}:
            return ""
        if re.fullmatch(r"-?\d+\.0", text):
            return text[:-2]
        return text

    def _drop_helper_columns(self, meta: pd.DataFrame) -> pd.DataFrame:
        """Drop jattr and attributes helper columns if present."""
        for c in ["jattr", "attributes"]:
            if c in meta.columns:
                meta = meta.drop(columns=[c])
        return meta

