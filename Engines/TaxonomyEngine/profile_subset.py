from __future__ import annotations

from functools import cached_property
from pathlib import Path

import pandas as pd


class ProfileSubset:
    """Filtered profile plus lazily aligned metadata, kept as two DataFrames."""

    def __init__(self, profile_df: pd.DataFrame, full_metadata_df: pd.DataFrame):
        self.profile_df = profile_df
        self._full_metadata_df = full_metadata_df

    @cached_property
    def metadata_df(self) -> pd.DataFrame:
        order = list(self.profile_df.index)
        indexed = self._full_metadata_df.set_index("acc")
        present = [acc for acc in order if acc in indexed.index]
        return indexed.reindex(present).reset_index()

    def write(self, out_dir: Path) -> list[Path]:
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        return [self._write(out_dir, "profile.csv", self.profile_df, True),
                self._write(out_dir, "metadata.csv", self.metadata_df, False)]

    def _write(self, out_dir: Path, name: str, frame: pd.DataFrame, index: bool) -> Path:
        path = out_dir / name
        frame.to_csv(path, index=index)
        return path
