from __future__ import annotations

import pandas as pd

_TOP_N = 5
_COLUMNS = ["bioproject", "key_name", "populated_samples", "unique_values", "top_values"]


class DiscoveredKeysBuilder:
    """Summarizes discovered metadata keys, per project and deduplicated."""

    def by_project(self, metadata_df: pd.DataFrame, discovered_keys: list[str]) -> pd.DataFrame:
        rows = [self._row(project, key, frame)
                for project, frame in self._projects(metadata_df)
                for key in discovered_keys]
        return pd.DataFrame(rows, columns=_COLUMNS)

    def unique(self, by_project_df: pd.DataFrame) -> pd.DataFrame:
        if by_project_df.empty:
            return pd.DataFrame(columns=["key_name", "projects", "populated_samples", "unique_values"])
        grouped = by_project_df.groupby("key_name", as_index=False).agg(
            projects=("bioproject", "nunique"),
            populated_samples=("populated_samples", "sum"),
            unique_values=("unique_values", "max"),
        )
        return grouped.sort_values("key_name").reset_index(drop=True)

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

    def _populated(self, series: pd.Series) -> pd.Series:
        text = series.astype(str).str.strip()
        return text[(text != "") & (text.str.lower() != "nan")]

    def _top(self, populated: pd.Series) -> str:
        counts = populated.value_counts().head(_TOP_N)
        return " | ".join(f"{value} ({count})" for value, count in counts.items())
