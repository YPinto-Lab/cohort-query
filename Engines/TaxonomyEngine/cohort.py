from __future__ import annotations

from dataclasses import dataclass

from Engines.MetadataEngine.metadata import Metadata
from .abundance_matrix import AbundanceMatrix


@dataclass(frozen=True, eq=False)
class Cohort:
    matrix: AbundanceMatrix
    metadata: Metadata

    def __post_init__(self) -> None:
        aligned = self.metadata.reindex_to(self.matrix.counts.index)
        object.__setattr__(self, "metadata", aligned)
