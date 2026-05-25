from __future__ import annotations

from functools import cached_property
from pathlib import Path

import pandas as pd


class AbundanceMatrix:
    """Samples x taxa counts with lazy relative values and lineage-bearing taxa lookup."""

    def __init__(self, counts: pd.DataFrame, lookup: pd.DataFrame, lineage_df: pd.DataFrame):
        self.counts = counts
        self._lookup = lookup
        self._lineage_df = lineage_df

    @cached_property
    def relative(self) -> pd.DataFrame:
        row_totals = self.counts.sum(axis=1).replace(0, float("nan"))
        return self.counts.div(row_totals, axis=0).fillna(0.0)

    @cached_property
    def taxa(self) -> pd.DataFrame:
        return self._lookup.merge(self._lineage_df, on="tax_id", how="left")

    def write(self, path: Path, fmt: str = "counts") -> Path:
        from Accessors.matrix_writers.matrix_writer_factory import MatrixWriterFactory

        return MatrixWriterFactory().create(fmt).write(self, Path(path))
