from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd

from Accessors.OntologyAccessor import EnvoOntologyAccessor
from Accessors.SraAccessor import SRAWorkspaceInputAccessor
from Accessors.TaxonomyAccessor import TaxonomyAccessor
from Common.Logger import Logger
from Common.RunnerContext import RunnerContext
from Common.contracts.pipeline_contracts import (
    EnrichmentStageResult,
    EnvoResolutionStageResult,
    MappingRefreshResult,
    MappingTemplateStatus,
    MergeStageResult,
    TaxonomyStageResult,
    WorkspaceInitializationResult,
    WorkspaceInputsResult,
)
from Engines.DatasetAssemblyEngine import DatasetAssemblyRuntimeEngine
from Engines.EnvoResolutionEngine import resolve_envo_columns
from Engines.MappingEngine.mapping_engine import MappingEngine


class AnalysisPipelineManager:
    """Stage-oriented orchestration for runner and CLI entrypoints."""

    def initialize_workspace(self, workspace: str, workspace_root: Path = Path("Workspaces")) -> WorkspaceInitializationResult:
        workspace_dir = workspace_root / workspace
        workspace_input_dir = workspace_dir / "inputs"
        config_dir = workspace_dir / "mapping_configs"
        results_dir = workspace_dir / "results"
        logs_dir = workspace_dir / "Logs"
        cache_dir = results_dir / "_cache"

        workspace_input_dir.mkdir(parents=True, exist_ok=True)
        config_dir.mkdir(parents=True, exist_ok=True)
        results_dir.mkdir(parents=True, exist_ok=True)
        logs_dir.mkdir(parents=True, exist_ok=True)
        cache_dir.mkdir(parents=True, exist_ok=True)

        run_id = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        run_log_path = logs_dir / f"run_{run_id}.log"
        with run_log_path.open("w", encoding="utf-8") as f:
            f.write(f"Ask-SLM runner log for view={workspace}\n")
            f.write(f"run_id={run_id}\n")

        context = RunnerContext(
            view_name=workspace,
            workspace_dir=workspace_dir,
            workspace_input_dir=workspace_input_dir,
            config_dir=config_dir,
            results_dir=results_dir,
            logs_dir=logs_dir,
            cache_dir=cache_dir,
            run_log_path=run_log_path,
        )

        logger = Logger(run_log_path)
        logger.log(f"Workspace initialized: {workspace_dir}")
        logger.log(f"Canonical inputs will be written to: {workspace_input_dir}")
        logger.log(f"Log file path: {run_log_path}", echo=True)

        return WorkspaceInitializationResult(context=context, logger=logger)

    def prepare_workspace_inputs(self, context: RunnerContext, logger: Logger) -> WorkspaceInputsResult:
        metadata_df, taxonomy_df, metadata_source, taxonomy_source = SRAWorkspaceInputAccessor.prepare_workspace_inputs(
            context=context,
            logger=logger,
        )
        return WorkspaceInputsResult(
            metadata_table=metadata_df,
            taxonomy_table=taxonomy_df,
            metadata_source=metadata_source,
            taxonomy_source=taxonomy_source,
        )

    def refresh_mapping_templates(
        self,
        metadata_df: pd.DataFrame,
        context: RunnerContext,
        logger: Logger,
    ) -> MappingRefreshResult:
        processor = MappingEngine(config_dir=context.config_dir)
        project_ids, status_df = processor.refresh_templates(metadata_df=metadata_df, view_name=context.view_name)
        statuses = [
            MappingTemplateStatus(
                project_id=str(row["project_id"]),
                config_exists=bool(row["config_exists"]),
                config_path=Path(row["config_path"]),
                template_path=Path(row["template_path"]),
            )
            for _, row in status_df.iterrows()
        ]
        logger.log(f"Prepared mapping templates for {len(project_ids)} project(s)")
        return MappingRefreshResult(processor=processor, project_ids=project_ids, project_statuses=statuses)

    def run_enrichment_stage(
        self,
        metadata_df: pd.DataFrame,
        processor: MappingEngine,
        project_ids: List[str],
        context: RunnerContext,
        logger: Logger,
        assembly_db_dir: Path,
        strict_missing_configs: bool = False,
    ) -> EnrichmentStageResult:
        engine = DatasetAssemblyRuntimeEngine(
            workspace_input_dir=context.workspace_input_dir,
            results_dir=context.results_dir,
            assembly_db_dir=Path(assembly_db_dir),
            logger=logger,
        )
        enriched_metadata, mapped_cols, missing_mapping_projects = engine.run_enrichment_stage(
            metadata_df=metadata_df,
            processor=processor,
            project_ids=project_ids,
            view_name=context.view_name,
            config_dir=context.config_dir,
            strict_missing_configs=strict_missing_configs,
        )
        return EnrichmentStageResult(
            enriched_metadata=enriched_metadata,
            mapped_cols=mapped_cols,
            missing_mapping_projects=missing_mapping_projects,
        )

    def enrich_envo_columns(
        self,
        metadata_df: pd.DataFrame,
        context: RunnerContext,
        logger: Logger,
        candidate_columns: Optional[List[str]] = None,
    ) -> EnvoResolutionStageResult:
        cache_path = context.cache_dir / "ontology_envo_cache.json"
        report_path = context.results_dir / "ENVO_Term_Dictionary.csv"

        if cache_path.exists():
            try:
                envo_cache: Dict[str, Dict[str, str]] = json.loads(cache_path.read_text(encoding="utf-8"))
            except Exception:
                envo_cache = {}
        else:
            envo_cache = {}

        enriched = metadata_df.copy()
        if candidate_columns is None:
            candidate_columns = [
                c
                for c in enriched.columns
                if "env_" in c.lower() or "envo" in c.lower() or "material" in c.lower() or "biome" in c.lower()
            ]

        ontology_accessor = EnvoOntologyAccessor()
        resolution_result = resolve_envo_columns(
            metadata_df=enriched,
            envo_cache=envo_cache,
            candidate_columns=candidate_columns,
            fetch_term=ontology_accessor.fetch_term,
        )

        cache_path.write_text(json.dumps(resolution_result.envo_cache, indent=2), encoding="utf-8")

        if not resolution_result.found_ids:
            logger.log("ENVO decode: no ENVO-like IDs detected in metadata.")
            return EnvoResolutionStageResult(
                enriched_metadata=resolution_result.enriched_df,
                envo_report_df=resolution_result.report_df,
            )

        report_df = resolution_result.report_df
        report_df.to_csv(report_path, index=False)
        logger.log(
            f"ENVO decode: resolved {len(resolution_result.found_ids)} term(s) "
            f"across {len(resolution_result.used_columns)} column(s)"
        )
        logger.log(f"ENVO dictionary saved to: {report_path}")

        return EnvoResolutionStageResult(
            enriched_metadata=resolution_result.enriched_df,
            envo_report_df=report_df,
        )

    def run_taxonomy_stage(
        self,
        taxonomy_df: pd.DataFrame,
        context: RunnerContext,
        logger: Logger,
        assembly_db_dir: Path,
        merged_dump_path: Path,
        taxon_key_sep: str,
    ) -> TaxonomyStageResult:
        engine = DatasetAssemblyRuntimeEngine(
            workspace_input_dir=context.workspace_input_dir,
            results_dir=context.results_dir,
            assembly_db_dir=Path(assembly_db_dir),
            logger=logger,
        )
        abundance_matrix, taxon_lookup_df = engine.run_taxonomy_stage(
            taxonomy_df=taxonomy_df,
            view_name=context.view_name,
            taxon_key_sep=taxon_key_sep,
            merged_dump_path=Path(merged_dump_path),
        )
        return TaxonomyStageResult(abundance_matrix=abundance_matrix, taxon_lookup_df=taxon_lookup_df)

    def run_merge_stage(
        self,
        enriched_metadata_df: pd.DataFrame,
        abundance_matrix: pd.DataFrame,
        context: RunnerContext,
        logger: Logger,
        assembly_db_dir: Path,
    ) -> MergeStageResult:
        engine = DatasetAssemblyRuntimeEngine(
            workspace_input_dir=context.workspace_input_dir,
            results_dir=context.results_dir,
            assembly_db_dir=Path(assembly_db_dir),
            logger=logger,
        )
        abundance_metadata_matrix, metadata_columns = engine.run_merge_stage(
            enriched_metadata_df=enriched_metadata_df,
            abundance_matrix=abundance_matrix,
            view_name=context.view_name,
        )
        return MergeStageResult(
            abundance_metadata_matrix=abundance_metadata_matrix,
            metadata_columns=metadata_columns,
        )

    def build_or_load_tax_accessor(
        self,
        taxon_lookup_df: pd.DataFrame,
        context: RunnerContext,
        logger: Logger,
        assembly_db_dir: Path,
        lineage_db_path: Path,
    ) -> TaxonomyAccessor:
        engine = DatasetAssemblyRuntimeEngine(
            workspace_input_dir=context.workspace_input_dir,
            results_dir=context.results_dir,
            assembly_db_dir=Path(assembly_db_dir),
            logger=logger,
        )
        return engine.build_or_load_tax_accessor(
            taxon_lookup_df=taxon_lookup_df,
            lineage_db_path=Path(lineage_db_path),
        )
