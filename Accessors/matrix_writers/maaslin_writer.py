from __future__ import annotations

from pathlib import Path


class MaaslinWriter:
    """Writes the samples x taxa matrix as a MaAsLin2-ready TSV (samples as rows)."""

    def write(self, matrix, path: Path) -> Path:
        matrix.matrix.to_csv(path, sep="\t")
        return path
