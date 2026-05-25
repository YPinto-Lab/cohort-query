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
    AggregationStageResult,
    EnrichmentStageResult,
    EnvoResolutionStageResult,
    MappingRefreshResult,
    MappingTemplateStatus,
    MergeStageResult,
    TaxonomyResolutionStageResult,
    TaxonomyStageResult,
    WorkspaceInitializationResult,
    WorkspaceInputsResult,
)
from Engines.DatasetAssemblyEngine import DatasetAssemblyRuntimeEngine
from Engines.DatasetAssemblyEngine.runtime_assembly_models import (
    AggregationStageRequest,
    EnrichmentStageRequest,
    MergeStageRequest,
    RuntimeAssemblyPaths,
    TaxonomyAccessorRequest,
    TaxonomyStageRequest,
)
from Engines.DownstreamAnalysis.AlphaDiversity.alpha_diversity_engine import AlphaDiversityEngine
from Engines.DownstreamAnalysis.TaxonomicAbundance import TaxonomicAbundanceEngine, TaxonomicAbundanceInputs
from Engines.EnvoResolutionEngine import resolve_envo_columns
from Engines.MappingEngine.mapping_engine import MappingEngine
from Engines.MetadataOverviewEngine import MetadataOverviewEngine, MetadataOverviewResult


class AnalysisPipelineManager:
    """Stage-oriented orchestration for runner and CLI entrypoints."""

    def initialize_workspace(self, workspace: str, workspace_root: Path = Path("Workspaces")) -> WorkspaceInitializationResult:
        workspace_dir = workspace_root / workspace
        workspace_input_dir = workspace_dir / "inputs"
        config_dir = workspace_dir / "mapping_configs"
        results_dir = workspace_dir / "results"
        logs_dir = workspace_dir / "Logs"
        cache_dir = results_dir / "abundance_matrices" / "manifests"

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
        engine = self._build_runtime_engine(context, assembly_db_dir, logger)
        request = EnrichmentStageRequest(metadata_df, processor, project_ids, context.view_name, context.config_dir, strict_missing_configs)
        enriched_metadata, mapped_cols, missing_mapping_projects = engine.run_enrichment_stage(request)
        return EnrichmentStageResult(
            enriched_metadata=enriched_metadata,
            mapped_cols=mapped_cols,
            missing_mapping_projects=missing_mapping_projects,
        )

    def run_taxonomy_resolution_stage(
        self,
        taxonomy_df: pd.DataFrame,
        context: RunnerContext,
        logger: Logger,
        assembly_db_dir: Path,
        merged_dump_path: Path,
        taxon_key_sep: str,
    ) -> TaxonomyResolutionStageResult:
        engine = self._build_runtime_engine(context, assembly_db_dir, logger)
        request = TaxonomyStageRequest(taxonomy_df, context.view_name, taxon_key_sep, Path(merged_dump_path))
        resolved_taxonomy_df, resolution_summary, resolution_changes_df = engine.run_taxonomy_resolution_stage(request)
        return TaxonomyResolutionStageResult(
            resolved_taxonomy_df=resolved_taxonomy_df,
            resolution_summary=resolution_summary,
            resolution_changes_df=resolution_changes_df,
        )

    def run_aggregation_stage(
        self,
        resolved_taxonomy_df: pd.DataFrame,
        context: RunnerContext,
        logger: Logger,
        assembly_db_dir: Path,
        taxon_key_sep: str,
    ) -> AggregationStageResult:
        engine = self._build_runtime_engine(context, assembly_db_dir, logger)
        request = AggregationStageRequest(resolved_taxonomy_df, context.view_name, taxon_key_sep)
        abundance_matrix, taxon_lookup_df = engine.run_aggregation_stage(request)
        return AggregationStageResult(abundance_matrix=abundance_matrix, taxon_lookup_df=taxon_lookup_df)

    def enrich_envo_columns(
        self,
        metadata_df: pd.DataFrame,
        context: RunnerContext,
        logger: Logger,
        candidate_columns: Optional[List[str]] = None,
    ) -> EnvoResolutionStageResult:
        cache_path = context.results_dir / "abundance_matrices" / "stage_01_enrichment" / "ontology_envo_cache.json"
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
            resolved_candidate_columns = [
                c
                for c in enriched.columns
                if "env_" in c.lower() or "envo" in c.lower() or "material" in c.lower() or "biome" in c.lower()
            ]
        else:
            resolved_candidate_columns = candidate_columns

        ontology_accessor = EnvoOntologyAccessor()
        resolution_result = resolve_envo_columns(
            metadata_df=enriched,
            envo_cache=envo_cache,
            candidate_columns=resolved_candidate_columns,
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
        resolution_result = self.run_taxonomy_resolution_stage(
            taxonomy_df=taxonomy_df,
            context=context,
            logger=logger,
            assembly_db_dir=assembly_db_dir,
            merged_dump_path=merged_dump_path,
            taxon_key_sep=taxon_key_sep,
        )
        aggregation_result = self.run_aggregation_stage(
            resolved_taxonomy_df=resolution_result.resolved_taxonomy_df,
            context=context,
            logger=logger,
            assembly_db_dir=assembly_db_dir,
            taxon_key_sep=taxon_key_sep,
        )
        abundance_matrix = aggregation_result.abundance_matrix
        taxon_lookup_df = aggregation_result.taxon_lookup_df
        return TaxonomyStageResult(abundance_matrix=abundance_matrix, taxon_lookup_df=taxon_lookup_df)

    def run_final_assembly_stage(
        self,
        enriched_metadata_df: pd.DataFrame,
        abundance_matrix: pd.DataFrame,
        context: RunnerContext,
        logger: Logger,
        assembly_db_dir: Path,
        taxon_lookup_df: Optional[pd.DataFrame] = None,
    ) -> MergeStageResult:
        engine = self._build_runtime_engine(context, assembly_db_dir, logger)
        request = MergeStageRequest(enriched_metadata_df, abundance_matrix, context.view_name, taxon_lookup_df)
        abundance_metadata_matrix, metadata_columns = engine.run_final_assembly_stage(request)
        return MergeStageResult(
            abundance_metadata_matrix=abundance_metadata_matrix,
            metadata_columns=metadata_columns,
        )

    def run_merge_stage(
        self,
        enriched_metadata_df: pd.DataFrame,
        abundance_matrix: pd.DataFrame,
        context: RunnerContext,
        logger: Logger,
        assembly_db_dir: Path,
    ) -> MergeStageResult:
        return self.run_final_assembly_stage(
            enriched_metadata_df=enriched_metadata_df,
            abundance_matrix=abundance_matrix,
            taxon_lookup_df=None,
            context=context,
            logger=logger,
            assembly_db_dir=assembly_db_dir,
        )

    def build_or_load_tax_accessor(
        self,
        taxon_lookup_df: pd.DataFrame,
        context: RunnerContext,
        logger: Logger,
        assembly_db_dir: Path,
        lineage_db_path: Optional[Path] = None,
    ) -> TaxonomyAccessor:
        engine = self._build_runtime_engine(context, assembly_db_dir, logger)
        default_lineage_db_path = context.results_dir / "abundance_matrices" / "stage_05_accessor" / "taxon_query_db.json"
        resolved_lineage_db_path = Path(lineage_db_path) if lineage_db_path is not None else default_lineage_db_path
        request = TaxonomyAccessorRequest(taxon_lookup_df, resolved_lineage_db_path)
        return engine.build_or_load_tax_accessor(request)

    def run_alpha_diversity(
        self,
        analysis_wide_df: pd.DataFrame,
        taxon_lookup_df: pd.DataFrame,
        metadata_cols: List[str],
        tax_accessor: TaxonomyAccessor,
        logger: Logger,
    ) -> AlphaDiversityEngine:
        log_fn = logger.log if hasattr(logger, "log") else logger
        engine = AlphaDiversityEngine(
            analysis_wide_df=analysis_wide_df,
            taxon_lookup_df=taxon_lookup_df,
            metadata_cols=metadata_cols,
            tax_accessor=tax_accessor,
            logger=log_fn,  # type: ignore[arg-type]
        )
        engine.run()
        return engine

    def run_taxonomic_abundance(
        self,
        abundance_metadata_matrix: pd.DataFrame,
        taxon_lookup_df: pd.DataFrame,
        metadata_cols: List[str],
        logger: Logger,
    ) -> TaxonomicAbundanceEngine:
        log_fn = logger.log if hasattr(logger, "log") else logger
        inputs = TaxonomicAbundanceInputs(
            abundance_metadata_matrix=abundance_metadata_matrix,
            taxon_lookup_df=taxon_lookup_df,
            metadata_cols=metadata_cols,
        )
        engine = TaxonomicAbundanceEngine(
            inputs=inputs,
            logger=log_fn,  # type: ignore[arg-type]
        )
        engine.run()
        return engine

    def run_metadata_overview(
        self,
        metadata_df: pd.DataFrame,
        raw_metadata_df: pd.DataFrame,
        config_dir: str,
        logger: Logger,
    ) -> MetadataOverviewResult:
        """Run metadata overview engine to analyze and summarize metadata."""
        logger.log(
            "Metadata overview: manager dispatch "
            f"(metadata_rows={len(metadata_df)}, raw_metadata_rows={len(raw_metadata_df)}, config_dir={config_dir})"
        )
        engine = MetadataOverviewEngine(config_dir=config_dir, logger=logger)
        result = engine.run(metadata_df, raw_metadata_df)
        logger.log(
            "Metadata overview: manager completed "
            f"(summary_rows={len(result.summary_df)}, project_rows={len(result.projects_df)}, "
            f"matrix_shape={result.metadata_matrix_df.shape})"
        )
        return result

    def _build_runtime_engine(self, context: RunnerContext, assembly_db_dir: Path, logger: Logger) -> DatasetAssemblyRuntimeEngine:
        paths = RuntimeAssemblyPaths(context.workspace_input_dir, context.results_dir, Path(assembly_db_dir))
        return DatasetAssemblyRuntimeEngine(paths=paths, logger=logger)

