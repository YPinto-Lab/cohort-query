from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Tuple

import pandas as pd

from ..runtime_assembly_models import EnrichmentStageRequest
from .base import RuntimeAssemblyStageBase


class EnrichmentStageRunner(RuntimeAssemblyStageBase):
    STAGE_NAME = "enrichment"
    SCHEMA_VERSION = "enrichment_summary_v1"

    def run(self, request: EnrichmentStageRequest) -> Tuple[pd.DataFrame, List[str], List[str]]:
        stage_dir = self._stage_dir(self.STAGE_NAME)
        paths = self._paths(stage_dir)
        fingerprint = self._fingerprint(request)
        if self._summary_is_current(paths["summary"], self.SCHEMA_VERSION, self.STAGE_NAME, fingerprint, [paths["enriched"]]):
            return self._load(paths)
        return self._rebuild(request, paths, fingerprint)

    def _paths(self, stage_dir: Path) -> Dict[str, Path]:
        return {"enriched": stage_dir / "enriched_metadata.csv", "summary": stage_dir / "enrichment_summary.json"}

    def _fingerprint(self, request: EnrichmentStageRequest) -> str:
        payload = {
            "view_name": request.view_name,
            "metadata_df": self._dataframe_fingerprint(request.metadata_df),
            "config_dir": str(request.config_dir),
            "project_ids": sorted(request.project_ids),
            "strict_missing_configs": bool(request.strict_missing_configs),
        }
        return self._json_fingerprint(payload)

    def _json_fingerprint(self, payload: Dict[str, object]) -> str:
        import hashlib
        import json

        digest = hashlib.sha256()
        digest.update(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8"))
        return digest.hexdigest()

    def _load(self, paths: Dict[str, Path]) -> Tuple[pd.DataFrame, List[str], List[str]]:
        enriched = pd.read_csv(paths["enriched"])
        summary = self._read_json(paths["summary"])
        return enriched, list(summary.get("mapped_columns", [])), list(summary.get("missing_mapping_projects", []))

    def _rebuild(self, request: EnrichmentStageRequest, paths: Dict[str, Path], fingerprint: str) -> Tuple[pd.DataFrame, List[str], List[str]]:
        processed_parts, missing_configs = self._process_projects(request)
        if request.strict_missing_configs and missing_configs:
            missing = ", ".join(missing_configs)
            raise FileNotFoundError(f"Missing mapping config for: {missing}. Create configs in {request.config_dir} and rerun.")
        if not processed_parts:
            raise RuntimeError("No projects were processed")
        enriched = pd.concat(processed_parts, ignore_index=True)
        mapped_cols = [c for c in enriched.columns if c not in request.metadata_df.columns]
        self._write_csv(paths["enriched"], enriched, index=False)
        self._write_json(paths["summary"], self._summary_payload(request, fingerprint, enriched, mapped_cols, missing_configs, paths))
        self._log_stage(f"Enrichment rebuilt: {paths['enriched']}")
        return enriched, mapped_cols, missing_configs

    def _process_projects(self, request: EnrichmentStageRequest):
        processed_parts: List[pd.DataFrame] = []
        missing_configs: List[str] = []
        for project_id in request.project_ids:
            processed, missing = self._process_project(request, project_id)
            processed_parts.append(processed)
            if missing:
                missing_configs.append(project_id)
        if missing_configs:
            self._log_stage(f"Proceeding without mappings for {len(missing_configs)} project(s): {', '.join(missing_configs)}")
        return processed_parts, missing_configs

    def _process_project(self, request: EnrichmentStageRequest, project_id: str):
        project_metadata = request.metadata_df[request.metadata_df["bioproject"] == project_id].copy()
        project_config_path = Path(request.config_dir) / f"{project_id}.json"
        if project_config_path.exists():
            return request.processor.map(project_metadata, project_id, view_name=request.view_name), False
        request.processor.refresh_template(project_metadata, project_id, view_name=request.view_name)
        self._log_stage(
            f"Missing mapping config for {project_id}. Template refreshed at {Path(request.config_dir) / f'{project_id}.json.template'}; using raw metadata for this run."
        )
        return project_metadata, True

    def _summary_payload(
        self,
        request: EnrichmentStageRequest,
        fingerprint: str,
        enriched: pd.DataFrame,
        mapped_cols: List[str],
        missing_configs: List[str],
        paths: Dict[str, Path],
    ):
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        return {
            "schema_version": self.SCHEMA_VERSION,
            "stage_name": self.STAGE_NAME,
            "status": "ok",
            "input_fingerprint": fingerprint,
            "rows_in": int(len(request.metadata_df)),
            "rows_out": int(len(enriched)),
            "mapped_columns": mapped_cols,
            "missing_mapping_projects": missing_configs,
            "output_files": {
                "enriched_metadata_csv": str(paths["enriched"].relative_to(self.paths.results_dir)),
                "enrichment_summary_json": str(paths["summary"].relative_to(self.paths.results_dir)),
            },
            "started_at": now,
            "finished_at": now,
        }

