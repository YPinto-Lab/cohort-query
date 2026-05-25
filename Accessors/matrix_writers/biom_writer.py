from __future__ import annotations

from pathlib import Path

from biom import Table


class BiomWriter:
    def write(self, matrix, path: Path) -> Path:
        observations = list(matrix.counts.columns)
        samples = list(matrix.counts.index)
        table = Table(matrix.counts.to_numpy().T, observations, samples)
        path.write_text(table.to_json(generated_by="ask-slm"))
        return path
