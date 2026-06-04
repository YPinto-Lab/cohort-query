from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd


@dataclass(frozen=True, eq=False)
class MetadataOverview:
    summary_df: pd.DataFrame
    projects_df: pd.DataFrame
    discovered_keys_df: pd.DataFrame
    discovered_keys_unique_df: pd.DataFrame
    coverage_matrix_df: pd.DataFrame

    def write(self, out_dir: Path) -> list[Path]:
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        return [self._write(out_dir, name, frame) for name, frame in self._frames()]

    def _frames(self) -> list[tuple[str, pd.DataFrame]]:
        return [
            ("summary.csv", self.summary_df),
            ("projects.csv", self.projects_df),
            ("discovered_keys.csv", self.discovered_keys_df),
            ("discovered_keys_unique.csv", self.discovered_keys_unique_df),
            ("coverage_matrix.csv", self.coverage_matrix_df),
        ]

    def _write(self, out_dir: Path, name: str, frame: pd.DataFrame) -> Path:
        path = out_dir / name
        frame.to_csv(path, index=False)
        return path
