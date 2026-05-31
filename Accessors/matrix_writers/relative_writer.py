from __future__ import annotations

from pathlib import Path


class RelativeWriter:
    def write(self, matrix, path: Path) -> Path:
        matrix.relative_abundance.to_csv(path)
        return path
