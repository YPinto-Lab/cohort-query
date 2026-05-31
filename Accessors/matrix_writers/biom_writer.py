from __future__ import annotations

from pathlib import Path

from biom import Table


class BiomWriter:
    def write(self, matrix, path: Path) -> Path:
        observations = list(matrix.matrix.columns)
        samples = list(matrix.matrix.index)
        table = Table(matrix.matrix.to_numpy().T, observations, samples)
        path.write_text(table.to_json(generated_by="ask-slm"))
        return path
