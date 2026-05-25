from __future__ import annotations

from pathlib import Path

import pandas as pd

from Common.contracts.sra_schema import SRATaxonomySchema


class TaxonomyFileAccessor:
    """Reads taxonomy.csv and validates it against SRATaxonomySchema."""

    def read(self, path: Path) -> pd.DataFrame:
        frame = pd.read_csv(Path(path))
        return SRATaxonomySchema.validate(frame)
