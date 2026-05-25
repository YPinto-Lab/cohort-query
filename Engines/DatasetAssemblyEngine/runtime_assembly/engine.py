from __future__ import annotations

from pathlib import Path

from .accessor import TaxonomyAccessorRunner
from .aggregation import AggregationStageRunner
from .base import RuntimeAssemblyStageBase
from .enrichment import EnrichmentStageRunner
from .merge import FinalAssemblyStageRunner
from .taxonomy import TaxonomyStageRunner
from ..runtime_assembly_models import AggregationStageRequest, MergeStageRequest, RuntimeAssemblyPaths


class DatasetAssemblyRuntimeEngine(RuntimeAssemblyStageBase):
    def __init__(self, paths: RuntimeAssemblyPaths, logger=None):
        self.paths = self._validate_paths(paths)
        super().__init__(self.paths, logger=logger)
        self._enrichment = EnrichmentStageRunner(self.paths, logger=logger)
        self._taxonomy = TaxonomyStageRunner(self.paths, logger=logger)
        self._aggregation = AggregationStageRunner(self.paths, logger=logger)
        self._final_assembly = FinalAssemblyStageRunner(self.paths, logger=logger)
        self._accessor = TaxonomyAccessorRunner(self.paths, logger=logger)

    def _validate_paths(self, paths: RuntimeAssemblyPaths) -> RuntimeAssemblyPaths:
        workspace_input_dir = Path(paths.workspace_input_dir)
        results_dir = Path(paths.results_dir)
        root_dir = results_dir if results_dir.name == "abundance_matrices" else results_dir / "abundance_matrices"
        manifests_dir = root_dir / "manifests"
        if not workspace_input_dir.exists():
            raise FileNotFoundError(f"Required runtime directory does not exist: {workspace_input_dir}")
        root_dir.mkdir(parents=True, exist_ok=True)
        manifests_dir.mkdir(parents=True, exist_ok=True)
        return RuntimeAssemblyPaths(workspace_input_dir, root_dir, manifests_dir)

    def run_enrichment_stage(self, request):
        return self._enrichment.run(request)

    def run_taxonomy_resolution_stage(self, request):
        return self._taxonomy.run(request)

    def run_aggregation_stage(self, request: AggregationStageRequest):
        return self._aggregation.run(request)

    def run_final_assembly_stage(self, request: MergeStageRequest):
        return self._final_assembly.run(request)

    def run_taxonomy_stage(self, request):
        resolved_taxonomy_df, _, _ = self.run_taxonomy_resolution_stage(request)
        aggregation_request = AggregationStageRequest(resolved_taxonomy_df, request.view_name, request.taxon_key_sep)
        return self.run_aggregation_stage(aggregation_request)

    def run_merge_stage(self, request):
        return self.run_final_assembly_stage(request)

    def build_or_load_tax_accessor(self, request):
        accessor = self._accessor.run(request)
        self._write_pipeline_manifest()
        return accessor

    def _write_pipeline_manifest(self):
        payload = self._manifest_payload()
        if payload is None:
            return None
        manifest_path = self.paths.assembly_db_dir / "pipeline_manifest.json"
        self._write_json(manifest_path, payload)
        return manifest_path

    def _manifest_payload(self):
        stage_order = ["enrichment", "taxonomy_resolution", "aggregation", "final_assembly", "accessor"]
        stage_summaries = {stage: self._stage_summary_path(stage) for stage in stage_order}
        summaries = {stage: self._read_summary(path) for stage, path in stage_summaries.items()}
        if not all(summary and summary.get("status") == "ok" for summary in summaries.values()):
            return None
        artifact_paths = self._manifest_artifact_paths(summaries)
        artifact_paths["pipeline_manifest_json"] = "manifests/pipeline_manifest.json"
        return {
            "schema_version": "pipeline_manifest_v1",
            "pipeline_version": "1.0.0",
            "input_fingerprint": self._input_folder_fingerprint(),
            "workspace_input_dir": str(self.paths.workspace_input_dir),
            "results_root_dir": str(self.paths.results_dir),
            "stage_order": stage_order,
            "stage_status": {stage: summary["status"] for stage, summary in summaries.items()},
            "stage_summaries": {stage: str(path.relative_to(self.paths.results_dir)) for stage, path in stage_summaries.items()},
            "artifact_paths": artifact_paths,
            "run_started_at": summaries["enrichment"]["started_at"],
            "run_finished_at": summaries["accessor"]["finished_at"],
        }

    def _stage_summary_path(self, stage: str):
        mapping = {
            "enrichment": self.paths.results_dir / "stage_01_enrichment" / "enrichment_summary.json",
            "taxonomy_resolution": self.paths.results_dir / "stage_02_taxonomy_resolution" / "taxonomy_resolution_summary.json",
            "aggregation": self.paths.results_dir / "stage_03_aggregation" / "aggregation_summary.json",
            "final_assembly": self.paths.results_dir / "stage_04_final_assembly" / "merge_summary.json",
            "accessor": self.paths.results_dir / "stage_05_accessor" / "accessor_summary.json",
        }
        return mapping[stage]

    def _read_summary(self, path: Path):
        if not path.exists():
            return None
        return self._accessor._read_json(path)

    def _manifest_artifact_paths(self, summaries):
        artifact_paths = {}
        for summary in summaries.values():
            artifact_paths.update(summary.get("output_files", {}))
        return artifact_paths

