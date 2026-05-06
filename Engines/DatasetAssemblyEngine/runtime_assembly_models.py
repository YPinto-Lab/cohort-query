from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List

import pandas as pd

from Engines.MappingEngine.mapping_engine import MappingEngine


@dataclass(frozen=True)
class RuntimeAssemblyPaths:
    workspace_input_dir: Path
    results_dir: Path
    assembly_db_dir: Path


@dataclass(frozen=True)
class EnrichmentStageRequest:
    metadata_df: pd.DataFrame
    processor: MappingEngine
    project_ids: List[str]
    view_name: str
    config_dir: Path
    strict_missing_configs: bool = False


@dataclass(frozen=True)
class TaxonomyStageRequest:
    taxonomy_df: pd.DataFrame
    view_name: str
    taxon_key_sep: str
    merged_dump_path: Path


@dataclass(frozen=True)
class MergeStageRequest:
    enriched_metadata_df: pd.DataFrame
    abundance_matrix: pd.DataFrame
    view_name: str


@dataclass(frozen=True)
class TaxonomyAccessorRequest:
    taxon_lookup_df: pd.DataFrame
    lineage_db_path: Path

