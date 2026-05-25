from __future__ import annotations

from pathlib import Path


class CountsWriter:
    def write(self, matrix, path: Path) -> Path:
        matrix.counts.to_csv(path)
        return path
