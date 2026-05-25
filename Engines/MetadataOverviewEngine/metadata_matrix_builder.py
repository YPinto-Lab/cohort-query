"""Builder for canonical metadata matrix with discovered key expansion."""

import json
import re
from typing import List

import pandas as pd


class MetadataMatrixBuilder:
    """Build a canonical metadata matrix indexed by accession (acc).

    This class expands discovered source keys using raw metadata helper
    columns (`jattr`, `attributes`) with precedence: direct column -> jattr -> attributes.
    """

    def build(self, metadata_df: pd.DataFrame, raw_metadata_df: pd.DataFrame, discovered_by_project_df: pd.DataFrame) -> pd.DataFrame:
        """Build canonical metadata matrix indexed by acc with expanded discovered keys."""
        base_df = self._prepare_base_dataframe(metadata_df)
        raw_lookup = self._prepare_raw_lookup(raw_metadata_df, base_df)
        jattr_dicts = self._prepare_jattr_dicts(raw_lookup, base_df)
        attributes_dicts = self._prepare_attributes_dicts(raw_lookup, base_df)
        discovered_keys = self._get_discovered_keys(discovered_by_project_df)
        for key in discovered_keys:
            self._expand_key_in_matrix(key, base_df, raw_lookup, jattr_dicts, attributes_dicts)
        base_df.index.name = "acc"
        return base_df

    def _parse_jattr_cell(self, x) -> dict:
        if pd.isna(x):
            return {}
        try:
            parsed = json.loads(x)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}

    def _parse_attributes_cell(self, x) -> dict:
        if pd.isna(x):
            return {}
        try:
            pairs = re.findall(r"k\s*=\s*([^,}]+),\s*v\s*=\s*([^}]+)", str(x))
            return {k.strip(): v.strip() for k, v in pairs}
        except Exception:
            return {}

    def _prepare_base_dataframe(self, metadata_df: pd.DataFrame) -> pd.DataFrame:
        """Drop helper columns, deduplicate by acc, and set index."""
        base_df = metadata_df.drop(columns=[c for c in ["jattr", "attributes"] if c in metadata_df.columns], errors="ignore").copy()
        base_df = base_df.drop_duplicates(subset=["acc"]).set_index("acc")
        return base_df

    def _prepare_raw_lookup(self, raw_metadata_df: pd.DataFrame, base_df: pd.DataFrame) -> pd.DataFrame:
        """Create raw metadata lookup indexed by acc, or empty if acc not present."""
        if "acc" not in raw_metadata_df.columns:
            return pd.DataFrame(index=base_df.index)
        return raw_metadata_df.drop_duplicates(subset=["acc"]).set_index("acc")

    def _prepare_jattr_dicts(self, raw_lookup: pd.DataFrame, base_df: pd.DataFrame) -> pd.Series:
        """Parse jattr column if present, otherwise return empty dicts for all rows."""
        if "jattr" not in raw_lookup.columns:
            return pd.Series({i: {} for i in raw_lookup.index})
        return raw_lookup["jattr"].apply(self._parse_jattr_cell)

    def _prepare_attributes_dicts(self, raw_lookup: pd.DataFrame, base_df: pd.DataFrame) -> pd.Series:
        """Parse attributes column if present, otherwise return empty dicts for all rows."""
        if "attributes" not in raw_lookup.columns:
            return pd.Series({i: {} for i in raw_lookup.index})
        return raw_lookup["attributes"].apply(self._parse_attributes_cell)

    def _get_discovered_keys(self, discovered_by_project_df: pd.DataFrame) -> List[str]:
        """Extract and sort unique discovered key names."""
        if discovered_by_project_df.empty or "key_name" not in discovered_by_project_df.columns:
            return []
        return sorted({
            str(k).strip()
            for k in discovered_by_project_df["key_name"].dropna().astype(str).tolist()
            if str(k).strip()
        })

    def _extract_dict_value(self, d: dict, key: str) -> str:
        """Extract value from dict with case-insensitive key matching."""
        if key in d:
            value = d[key]
            return " ".join(value) if isinstance(value, list) else str(value)
        for k, v in d.items():
            if str(k).strip().lower() == key.strip().lower():
                return " ".join(v) if isinstance(v, list) else str(v)
        return ""

    def _lookup_jattr(self, key: str, jattr_dicts: pd.Series) -> pd.Series:
        """Extract key value from parsed jattr dicts."""
        return jattr_dicts.apply(lambda d: self._extract_dict_value(d, key) if isinstance(d, dict) else "")

    def _lookup_attributes(self, key: str, attributes_dicts: pd.Series) -> pd.Series:
        """Extract key value from parsed attributes dicts."""
        return attributes_dicts.apply(lambda d: d.get(key, "") if isinstance(d, dict) else "")

    def _get_key_series(self, key: str, raw_lookup: pd.DataFrame, jattr_dicts: pd.Series) -> pd.Series:
        """Get series for key: try direct column first, fall back to jattr."""
        if key in raw_lookup.columns:
            return raw_lookup[key].astype(str).where(raw_lookup[key].notna(), "")
        return self._lookup_jattr(key, jattr_dicts)

    def _expand_key_in_matrix(self, key: str, base_df: pd.DataFrame, raw_lookup: pd.DataFrame, jattr_dicts: pd.Series, attributes_dicts: pd.Series) -> None:
        """Expand a single discovered key into the matrix with proper precedence."""
        if key == "acc":
            return
        if key in base_df.columns:
            return
        series = self._get_key_series(key, raw_lookup, jattr_dicts)
        series = series.where(series != "", self._lookup_attributes(key, attributes_dicts))
        base_df[key] = series.reindex(base_df.index).fillna("")







