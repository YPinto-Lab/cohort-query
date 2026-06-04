from __future__ import annotations

from pathlib import Path

import pandas as pd

from askslm.sra_schema import SRAMetadataSchema


class MetadataFileAccessor:
    """Reads metadata.csv and validates it against SRAMetadataSchema."""

    def read(self, path: Path) -> pd.DataFrame:
        frame = pd.read_csv(Path(path))
        return SRAMetadataSchema.validate(frame)
