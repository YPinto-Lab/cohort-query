from __future__ import annotations

from pathlib import Path
from typing import List, Optional, Tuple

import pandas as pd

from Accessors.TaxonomyAccessor import TaxonomyAccessor
from Common.Logger import Logger
from Common.RunnerContext import RunnerContext
from Engines.MappingEngine.mapping_engine import MappingEngine
from managers.analysis_pipeline_manager import AnalysisPipelineManager


_manager = AnalysisPipelineManager()


def initialize_runner_context(workspace: str, workspace_root: Path = Path("Workspaces")) -> Tuple[RunnerContext, Logger]:
    result = _manager.initialize_workspace(workspace=workspace, workspace_root=workspace_root)
    return result.context, result.logger


def prepare_workspace_inputs(context: RunnerContext, logger: Logger) -> Tuple[pd.DataFrame, pd.DataFrame, Path, Path]:
    result = _manager.prepare_workspace_inputs(context=context, logger=logger)
    return result.metadata_table, result.taxonomy_table, result.metadata_source, result.taxonomy_source


def refresh_mapping_templates(metadata_df: pd.DataFrame, context: RunnerContext, logger: Logger) -> Tuple[MappingEngine, List[str], pd.DataFrame]:
    result = _manager.refresh_mapping_templates(metadata_df=metadata_df, context=context, logger=logger)
    return result.processor, result.project_ids, result.as_dataframe()


def run_enrichment_stage(
    metadata_df: pd.DataFrame,
    processor: MappingEngine,
    project_ids: List[str],
    context: RunnerContext,
    logger: Logger,
    assembly_db_dir: Path,
    strict_missing_configs: bool = False,
) -> Tuple[pd.DataFrame, List[str], List[str]]:
    result = _manager.run_enrichment_stage(
        metadata_df=metadata_df,
        processor=processor,
        project_ids=project_ids,
        context=context,
        logger=logger,
        assembly_db_dir=Path(assembly_db_dir),
        strict_missing_configs=strict_missing_configs,
    )
    return result.enriched_metadata, result.mapped_cols, result.missing_mapping_projects


def enrich_envo_columns(metadata_df: pd.DataFrame, context: RunnerContext, logger: Logger, candidate_columns: Optional[List[str]] = None) -> Tuple[pd.DataFrame, pd.DataFrame]:
    result = _manager.enrich_envo_columns(
        metadata_df=metadata_df,
        context=context,
        logger=logger,
        candidate_columns=candidate_columns,
    )
    return result.enriched_metadata, result.envo_report_df


def run_taxonomy_stage(
    taxonomy_df: pd.DataFrame,
    context: RunnerContext,
    logger: Logger,
    assembly_db_dir: Path,
    merged_dump_path: Path,
    taxon_key_sep: str,
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    result = _manager.run_taxonomy_stage(
        taxonomy_df=taxonomy_df,
        context=context,
        logger=logger,
        assembly_db_dir=Path(assembly_db_dir),
        merged_dump_path=Path(merged_dump_path),
        taxon_key_sep=taxon_key_sep,
    )
    return result.abundance_matrix, result.taxon_lookup_df


def run_merge_stage(
    enriched_metadata_df: pd.DataFrame,
    abundance_matrix: pd.DataFrame,
    context: RunnerContext,
    logger: Logger,
    assembly_db_dir: Path,
) -> Tuple[pd.DataFrame, List[str]]:
    result = _manager.run_merge_stage(
        enriched_metadata_df=enriched_metadata_df,
        abundance_matrix=abundance_matrix,
        context=context,
        logger=logger,
        assembly_db_dir=Path(assembly_db_dir),
    )
    return result.abundance_metadata_matrix, result.metadata_columns


def build_or_load_tax_accessor(
    taxon_lookup_df: pd.DataFrame,
    context: RunnerContext,
    logger: Logger,
    assembly_db_dir: Path,
    lineage_db_path: Path,
) -> TaxonomyAccessor:
    return _manager.build_or_load_tax_accessor(
        taxon_lookup_df=taxon_lookup_df,
        context=context,
        logger=logger,
        assembly_db_dir=Path(assembly_db_dir),
        lineage_db_path=Path(lineage_db_path),
    )
