from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Tuple

import pandas as pd

from Accessors.TaxonomyAccessor import TaxonomyDumpAccessor

from ..TaxonomyResolver import TaxonomyResolver
from ..runtime_assembly_models import TaxonomyStageRequest
from .base import RuntimeAssemblyStageBase


class TaxonomyStageRunner(RuntimeAssemblyStageBase):
    STAGE_NAME = "taxonomy_resolution"
    SCHEMA_VERSION = "taxonomy_resolution_summary_v1"

    def run(self, request: TaxonomyStageRequest) -> Tuple[pd.DataFrame, Dict[str, Any], pd.DataFrame]:
        merged_dump_path = Path(request.merged_dump_path)
        if not merged_dump_path.exists() or not merged_dump_path.is_file():
            raise FileNotFoundError(f"merged.dmp not found: {merged_dump_path}")
        stage_dir = self._stage_dir(self.STAGE_NAME)
        paths = self._paths(stage_dir)
        fingerprint = self._fingerprint(request, merged_dump_path)
        if self._summary_is_current(
            paths["summary"],
            self.SCHEMA_VERSION,
            self.STAGE_NAME,
            fingerprint,
            [paths["resolved"], paths["changes"]],
        ):
            return self._load(paths)
        return self._rebuild(request, merged_dump_path, paths, fingerprint)

    def _paths(self, stage_dir: Path) -> Dict[str, Path]:
        return {
            "resolved": stage_dir / "resolved_taxonomy.csv",
            "changes": stage_dir / "taxonomy_resolution_changes.csv",
            "summary": stage_dir / "taxonomy_resolution_summary.json",
        }

    def _fingerprint(self, request: TaxonomyStageRequest, merged_dump_path: Path) -> str:
        payload = {
            "view_name": request.view_name,
            "taxon_key_sep": request.taxon_key_sep,
            "taxonomy_df": self._dataframe_fingerprint(request.taxonomy_df),
            "merged_dump": self._file_fingerprint(merged_dump_path),
        }
        return self._json_fingerprint(payload)

    def _json_fingerprint(self, payload: Dict[str, object]) -> str:
        import hashlib
        import json

        digest = hashlib.sha256()
        digest.update(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8"))
        return digest.hexdigest()

    def _load(self, paths: Dict[str, Path]) -> Tuple[pd.DataFrame, Dict[str, Any], pd.DataFrame]:
        resolved_taxonomy_df = pd.read_csv(paths["resolved"])
        resolution_changes_df = pd.read_csv(paths["changes"])
        summary = self._read_json(paths["summary"])
        return resolved_taxonomy_df, summary, resolution_changes_df

    def _rebuild(
        self,
        request: TaxonomyStageRequest,
        merged_dump_path: Path,
        paths: Dict[str, Path],
        fingerprint: str,
    ) -> Tuple[pd.DataFrame, Dict[str, Any], pd.DataFrame]:
        merged_taxid_map, resolved_taxonomy_df, resolution_summary, resolution_changes_df = self._resolution_data(request, merged_dump_path)
        payload = self._resolution_payload(request, merged_dump_path, resolution_summary, resolved_taxonomy_df, merged_taxid_map, fingerprint, paths)
        self._write_csv(paths["resolved"], resolved_taxonomy_df, index=False)
        self._write_csv(paths["changes"], resolution_changes_df, index=False)
        self._write_json(paths["summary"], payload)
        self._log_stage(
            f"Taxonomy Resolution rebuilt: rows_updated={payload['rows_updated']}, changes={paths['changes']}"
        )
        return resolved_taxonomy_df, payload, resolution_changes_df

    def _resolution_data(self, request: TaxonomyStageRequest, merged_dump_path: Path):
        merged_taxid_map = TaxonomyDumpAccessor(merged_dump_path).load_merged_taxid_map()
        resolver = TaxonomyResolver(merged_taxid_map)
        resolution_summary, resolution_changes_df = resolver.summarize_resolution(
            taxonomy_df=request.taxonomy_df,
            sample_col="acc",
            tax_id_col="tax_id",
            count_col="total_count",
        )
        resolved_taxonomy_df = resolver.resolve(
            taxonomy_df=request.taxonomy_df,
            sample_col="acc",
            tax_id_col="tax_id",
            count_col="total_count",
        )
        return merged_taxid_map, resolved_taxonomy_df, resolution_summary, resolution_changes_df

    def _resolution_payload(
        self,
        request: TaxonomyStageRequest,
        merged_dump_path: Path,
        resolution_summary: Dict[str, Any],
        resolved_taxonomy_df: pd.DataFrame,
        merged_taxid_map,
        fingerprint: str,
        paths: Dict[str, Path],
    ):
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        return {
            "schema_version": self.SCHEMA_VERSION,
            "stage_name": self.STAGE_NAME,
            "status": "ok",
            "input_fingerprint": fingerprint,
            "merged_dump_path": str(merged_dump_path),
            "merged_dump_rule_count": int(len(merged_taxid_map)),
            "input_unique_tax_ids": int(request.taxonomy_df["tax_id"].astype(str).nunique()) if "tax_id" in request.taxonomy_df.columns else 0,
            "resolved_unique_tax_ids": int(resolved_taxonomy_df["tax_id"].astype(str).nunique()) if "tax_id" in resolved_taxonomy_df.columns else 0,
            "input_rows": int(len(request.taxonomy_df)),
            "resolved_rows": int(len(resolved_taxonomy_df)),
            "rows_updated": int(resolution_summary.get("rows_updated", 0)),
            "unique_old_tax_ids_updated": int(resolution_summary.get("unique_old_tax_ids_updated", 0)),
            "output_files": {
                "resolved_taxonomy_csv": str(paths["resolved"].relative_to(self.paths.results_dir)),
                "taxonomy_resolution_changes_csv": str(paths["changes"].relative_to(self.paths.results_dir)),
                "taxonomy_resolution_summary_json": str(paths["summary"].relative_to(self.paths.results_dir)),
            },
            "started_at": now,
            "finished_at": now,
        }


TaxonomyResolutionStageRunner = TaxonomyStageRunner

