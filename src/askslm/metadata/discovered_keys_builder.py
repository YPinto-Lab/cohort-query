from __future__ import annotations

import pandas as pd

from ._populated import populated_mask

_TOP_N = 5
_COLUMNS = ["bioproject", "key_name", "populated_samples", "unique_values", "top_values"]
_UNIQUE_COLUMNS = ["key_name", "projects", "populated_samples", "unique_values"]


class DiscoveredKeysBuilder:
    """Summarizes discovered metadata keys, per project and deduplicated."""

    def by_project(self, metadata_df: pd.DataFrame, discovered_keys: list[str]) -> pd.DataFrame:
        rows = [self._row(project, key, frame)
                for project, frame in self._projects(metadata_df)
                for key in discovered_keys]
        return pd.DataFrame(rows, columns=_COLUMNS)

    def unique(self, metadata_df: pd.DataFrame, discovered_keys: list[str]) -> pd.DataFrame:
        rows = [self._unique_row(key, metadata_df) for key in discovered_keys]
        return pd.DataFrame(rows, columns=_UNIQUE_COLUMNS)

    def _projects(self, metadata_df: pd.DataFrame) -> list:
        if "bioproject" not in metadata_df.columns:
            return [("", metadata_df)]
        return list(metadata_df.groupby("bioproject"))

    def _row(self, project: str, key: str, frame: pd.DataFrame) -> dict:
        populated = self._populated(frame[key])
        return {"bioproject": project, "key_name": key,
                "populated_samples": int(len(populated)),
                "unique_values": int(populated.nunique()),
                "top_values": self._top(populated)}

    def _unique_row(self, key: str, metadata_df: pd.DataFrame) -> dict:
        kept = metadata_df[populated_mask(metadata_df[key])]
        return {"key_name": key,
                "projects": self._nunique(kept, "bioproject"),
                "populated_samples": int(len(kept)),
                "unique_values": self._nunique(kept, key)}

    def _populated(self, series: pd.Series) -> pd.Series:
        return series[populated_mask(series)].astype(str).str.strip()

    def _nunique(self, frame: pd.DataFrame, column: str) -> int:
        if column not in frame.columns:
            return 0
        return int(frame[column].nunique())

    def _top(self, populated: pd.Series) -> str:
        counts = populated.value_counts().head(_TOP_N)
        return " | ".join(f"{value} ({count})" for value, count in counts.items())
