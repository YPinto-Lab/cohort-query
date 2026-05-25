"""Metadata overview analysis engine.

Orchestrates discovery, summarization, and matrix building for metadata insights.
"""

from .metadata_overview_engine import MetadataOverviewEngine
from .metadata_overview_models import MetadataOverviewResult
from .source_key_extractor import SourceKeyExtractor
from .source_key_attacher import SourceKeyAttacher

__all__ = [
    "MetadataOverviewEngine",
    "MetadataOverviewResult",
    "SourceKeyExtractor",
    "SourceKeyAttacher",
]


