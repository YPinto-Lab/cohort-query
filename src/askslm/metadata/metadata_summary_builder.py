from __future__ import annotations

import pandas as pd


class MetadataSummaryBuilder:
    """Builds the high-level metadata summary table."""

    def build(self, metadata_df: pd.DataFrame, discovered_keys: list[str]) -> pd.DataFrame:
        metrics = {
            "samples": len(metadata_df),
            "projects": self._projects(metadata_df),
            "columns": len(metadata_df.columns),
            "discovered_keys": len(discovered_keys),
            "discovered_key_names": ", ".join(discovered_keys),
        }
        return pd.DataFrame({"metric": list(metrics), "value": list(metrics.values())})

    def _projects(self, metadata_df: pd.DataFrame) -> int:
        if "bioproject" not in metadata_df.columns:
            return 0
        return int(metadata_df["bioproject"].nunique())
