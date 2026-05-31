from __future__ import annotations

from collections.abc import Iterable
from functools import cached_property
from pathlib import Path

import pandas as pd


class AbundanceMatrix:
    """Samples x taxa counts at one collapsed view of a taxonomy."""

    def __init__(
        self,
        matrix: pd.DataFrame,
        total_reads: pd.Series,
        taxon_key_lookup: pd.DataFrame,
        tax_id_lineage_lookup: pd.DataFrame,
    ):
        self.matrix = matrix
        self.total_reads = total_reads
        self._taxon_key_lookup = taxon_key_lookup
        self._tax_id_lineage_lookup = tax_id_lineage_lookup

    @property
    def samples(self) -> list[str]:
        return list(self.matrix.index)

    @cached_property
    def relative_abundance(self) -> pd.DataFrame:
        denom = self.total_reads.reindex(self.matrix.index).replace(0, float("nan"))
        return self.matrix.div(denom, axis=0).fillna(0.0)

    @cached_property
    def taxa_lineage(self) -> pd.DataFrame:
        lookup = self._taxon_key_lookup.copy()
        lineage = self._tax_id_lineage_lookup.copy()
        lookup["tax_id"] = pd.to_numeric(lookup["tax_id"], errors="coerce")
        lineage["tax_id"] = pd.to_numeric(lineage["tax_id"], errors="coerce")
        return lookup.merge(lineage, on="tax_id", how="left")

    def filter(self, sample_ids: Iterable[str], exclude: bool = False) -> AbundanceMatrix:
        if exclude:
            return self._drop_samples(sample_ids)
        return self._keep_samples(sample_ids)

    def write(self, path: Path, fmt: str = "counts") -> Path:
        from Accessors.matrix_writers.matrix_writer_factory import MatrixWriterFactory

        return MatrixWriterFactory().create(fmt).write(self, Path(path))

    def _keep_samples(self, sample_ids: Iterable[str]) -> AbundanceMatrix:
        present = [s for s in sample_ids if s in self.matrix.index]
        return self._restrict(present)

    def _drop_samples(self, sample_ids: Iterable[str]) -> AbundanceMatrix:
        drop = set(sample_ids)
        kept = [s for s in self.matrix.index if s not in drop]
        return self._restrict(kept)

    def _restrict(self, sample_ids: list[str]) -> AbundanceMatrix:
        return AbundanceMatrix(
            matrix=self.matrix.reindex(sample_ids),
            total_reads=self.total_reads.reindex(sample_ids),
            taxon_key_lookup=self._taxon_key_lookup,
            tax_id_lineage_lookup=self._tax_id_lineage_lookup,
        )
