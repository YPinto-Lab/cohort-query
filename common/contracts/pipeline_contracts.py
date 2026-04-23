from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import pandas as pd

from Common.Logger import Logger
from Common.RunnerContext import RunnerContext
from Engines.MappingEngine.mapping_engine import MappingEngine


@dataclass(frozen=True)
class PipelineRequest:
    workspace: str
    workspace_root: Path = Path("Workspaces")
    strict_missing_configs: bool = False
    resolve_envo: bool = True
    build_lineage_db: bool = True
    taxon_key_sep: str = "||"
    merged_dump_path: Path = Path("Accessors/TaxonomyAccessor/merged.dmp")
    force_rebuild: bool = False
    lineage_db_path: Optional[Path] = None
    envo_candidate_columns: Optional[list[str]] = None

    def __post_init__(self) -> None:
        if not self.workspace.strip():
            raise ValueError("PipelineRequest.workspace must be a non-empty string")


@dataclass(frozen=True)
class MappingTemplateStatus:
    project_id: str
    config_exists: bool
    config_path: Path
    template_path: Path


@dataclass
class WorkspaceInitializationResult:
    context: RunnerContext
    logger: Logger


@dataclass
class WorkspaceInputsResult:
    metadata_table: pd.DataFrame
    taxonomy_table: pd.DataFrame
    metadata_source: Path
    taxonomy_source: Path


@dataclass
class MappingRefreshResult:
    processor: MappingEngine
    project_ids: list[str]
    project_statuses: list[MappingTemplateStatus]

    def as_dataframe(self) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {
                    "project_id": status.project_id,
                    "config_exists": status.config_exists,
                    "config_path": str(status.config_path),
                    "template_path": str(status.template_path),
                }
                for status in self.project_statuses
            ]
        )


@dataclass
class EnrichmentStageResult:
    enriched_metadata: pd.DataFrame
    mapped_cols: list[str]
    missing_mapping_projects: list[str]


@dataclass
class EnvoResolutionStageResult:
    enriched_metadata: pd.DataFrame
    envo_report_df: pd.DataFrame


@dataclass
class TaxonomyStageResult:
    abundance_matrix: pd.DataFrame
    taxon_lookup_df: pd.DataFrame


@dataclass
class MergeStageResult:
    abundance_metadata_matrix: pd.DataFrame
    metadata_columns: list[str]


@dataclass
class PipelineArtifacts:
    abundance_matrix_csv: Optional[Path] = None
    analysis_wide_dataset_csv: Optional[Path] = None
    taxon_lookup_csv: Optional[Path] = None
    metadata_columns_json: Optional[Path] = None
    taxonomy_stage_stamp_json: Optional[Path] = None
    merge_stage_stamp_json: Optional[Path] = None
    combined_stamp_json: Optional[Path] = None
    envo_dictionary_csv: Optional[Path] = None
    lineage_db_json: Optional[Path] = None


@dataclass
class PipelineMetrics:
    samples: int = 0
    projects: int = 0
    mapped_columns_count: int = 0
    projects_missing_mapping_config_count: int = 0
    envo_terms_resolved_count: int = 0


@dataclass
class PipelineResult:
    context: RunnerContext
    metadata_table: Optional[pd.DataFrame] = None
    taxonomy_table: Optional[pd.DataFrame] = None
    enriched_metadata: Optional[pd.DataFrame] = None
    abundance_matrix: Optional[pd.DataFrame] = None
    taxon_lookup_df: Optional[pd.DataFrame] = None
    abundance_metadata_matrix: Optional[pd.DataFrame] = None
    envo_report_df: Optional[pd.DataFrame] = None
    mapped_cols: list[str] = field(default_factory=list)
    missing_mapping_projects: list[str] = field(default_factory=list)
    metadata_columns: list[str] = field(default_factory=list)
    artifacts: PipelineArtifacts = field(default_factory=PipelineArtifacts)
    metrics: PipelineMetrics = field(default_factory=PipelineMetrics)
    stage_status: dict[str, str] = field(default_factory=dict)
