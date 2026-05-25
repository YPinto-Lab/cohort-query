"""Extract source key values from metadata rows."""

import json
import re
from typing import Any

import pandas as pd


class SourceKeyExtractor:
    """Extract a source key value from a metadata row.

    Precedence: direct column -> case-insensitive column match -> jattr JSON -> attributes text.
    Returns empty string when not found or on parse failures.
    """

    def extract(self, row: pd.Series, key: str) -> str:
        """Extract value for key from row, checking all sources in order."""
        requested_key = str(key).strip()
        requested_key_lower = requested_key.lower()

        value = self._lookup_direct_column(row, requested_key, requested_key_lower)
        if value:
            return value

        value = self._lookup_jattr(row, requested_key, requested_key_lower)
        if value:
            return value

        return self._lookup_attributes(row, requested_key, requested_key_lower)

    def _lookup_direct_column(self, row: pd.Series, requested_key: str, requested_key_lower: str) -> str:
        """Look up key as a direct column in row."""
        if requested_key in row.index and pd.notna(row.get(requested_key)):
            return str(row.get(requested_key))
        for col in row.index:
            if str(col).strip().lower() == requested_key_lower and pd.notna(row.get(col)):
                return str(row.get(col))
        return ""

    def _lookup_jattr(self, row: pd.Series, requested_key: str, requested_key_lower: str) -> str:
        """Look up key in parsed jattr JSON."""
        if "jattr" not in row.index or pd.isna(row.get("jattr")):
            return ""
        try:
            parsed = json.loads(row["jattr"])
            return self._extract_from_dict(parsed, requested_key, requested_key_lower)
        except (json.JSONDecodeError, TypeError):
            return ""

    def _lookup_attributes(self, row: pd.Series, requested_key: str, requested_key_lower: str) -> str:
        """Look up key in attributes text regex."""
        if "attributes" not in row.index or pd.isna(row.get("attributes")):
            return ""
        try:
            for attr_key, attr_val in re.findall(r"k\s*=\s*([^,]+),\s*v\s*=\s*([^}]+)", str(row["attributes"])):
                if str(attr_key).strip().lower() == requested_key_lower:
                    return str(attr_val).strip()
            return ""
        except Exception:
            return ""

    def _extract_from_dict(self, d: dict, requested_key: str, requested_key_lower: str) -> str:
        """Extract value from dict with exact or case-insensitive key match."""
        if not isinstance(d, dict):
            return ""
        if requested_key in d:
            raw = d[requested_key]
            return " ".join(raw) if isinstance(raw, list) else str(raw)
        for k, v in d.items():
            if str(k).strip().lower() == requested_key_lower:
                return " ".join(v) if isinstance(v, list) else str(v)
        return ""

