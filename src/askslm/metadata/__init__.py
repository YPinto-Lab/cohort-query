from __future__ import annotations

from pathlib import Path

import pandas as pd

from askslm.accessors.metadata_file_accessor import MetadataFileAccessor
from askslm.contracts import MetadataOverview
from .metadata_extractor import MetadataExtractor
from .metadata_overview_builder import MetadataOverviewBuilder


def extract(source: str | Path | pd.DataFrame) -> pd.DataFrame:
    raw_df = source if isinstance(source, pd.DataFrame) else MetadataFileAccessor().read(Path(source))
    return MetadataExtractor().extract(raw_df)


def overview(metadata_df: pd.DataFrame) -> MetadataOverview:
    return MetadataOverviewBuilder().build(metadata_df)
