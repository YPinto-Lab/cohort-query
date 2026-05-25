from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from Engines.TaxonomyEngine.abundance_matrix import AbundanceMatrix


class MatrixFormatWriter(Protocol):
    def write(self, matrix: "AbundanceMatrix", path: Path) -> Path: ...
