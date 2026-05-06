from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Tuple

import pandas as pd

from Accessors.TaxonomyAccessor import TaxonomyDumpAccessor

from ..DeprecatedTaxonomyResolutionEngine import DeprecatedTaxonomyResolutionEngine
from ..dataset_assembly_engine import compute_taxonomy_matrices
from ..runtime_assembly_models import TaxonomyStageRequest
from .base import RuntimeAssemblyStageBase


class TaxonomyStageRunner(RuntimeAssemblyStageBase):
    def run(self, request: TaxonomyStageRequest) -> Tuple[pd.DataFrame, pd.DataFrame]:
        merged_dump_path = Path(request.merged_dump_path)
        if not merged_dump_path.exists() or not merged_dump_path.is_file():
            raise FileNotFoundError(f"merged.dmp not found: {merged_dump_path}")
        cached = self._load_cache(request, merged_dump_path)
        if cached is not None:
            return cached
        return self._rebuild(request, merged_dump_path)

    def _cache_paths(self):
        return {
            "matrix": self.paths.results_dir / "Ask_SLM_Taxon_Abundance_Matrix.csv",
            "lookup": self.paths.results_dir / "Ask_SLM_Taxon_Lookup.csv",
            "summary": self.paths.results_dir / "Ask_SLM_Taxonomy_Resolution_Summary.json",
            "changes": self.paths.results_dir / "Ask_SLM_Taxonomy_Resolution_Changes.csv",
            "stamp": self.paths.assembly_db_dir / "taxonomy_stage_stamp.json",
        }

    def _current_stamp(self, request: TaxonomyStageRequest, merged_dump_path: Path) -> Dict[str, Any]:
        return {
            "schema_version": "taxonomy_v3",
            "view_name": request.view_name,
            "taxonomy_source": self._file_state(self.paths.workspace_input_dir / "taxonomy.csv"),
            "taxon_key_sep": request.taxon_key_sep,
            "merged_dump_source": self._file_state(merged_dump_path),
        }

    def _load_cache(self, request: TaxonomyStageRequest, merged_dump_path: Path):
        paths = self._cache_paths()
        if not self._has_cache(paths) or not self._cache_matches(paths["stamp"], self._current_stamp(request, merged_dump_path)):
            return None
        abundance_matrix = pd.read_csv(paths["matrix"], index_col="acc")
        taxon_lookup_df = pd.read_csv(paths["lookup"])
        self._backfill_resolution_artifacts_if_needed(request, merged_dump_path, paths)
        self._log(f"Taxonomy cache hit: loaded from {self.paths.results_dir}", echo=True)
        self._log_cached_resolution_summary(paths)
        return abundance_matrix, taxon_lookup_df

    def _has_cache(self, paths: Dict[str, Path]) -> bool:
        return all(paths[k].exists() for k in ["matrix", "lookup", "stamp"])

    def _backfill_resolution_artifacts_if_needed(self, request: TaxonomyStageRequest, merged_dump_path: Path, paths: Dict[str, Path]):
        if paths["summary"].exists() and paths["changes"].exists():
            return
        self._write_resolution_artifacts(request, merged_dump_path, paths)

    def _log_cached_resolution_summary(self, paths: Dict[str, Path]):
        if not paths["summary"].exists():
            return
        try:
            self._log(self._cached_resolution_summary_message(paths))
        except Exception:
            self._log(f"Taxonomy cache hit but could not parse taxonomy resolution summary JSON. Expected at: {paths['summary']}")

    def _cached_resolution_summary_message(self, paths: Dict[str, Path]) -> str:
        resolution_summary = self._read_json(paths["summary"])
        return (
            "Taxonomy resolution summary (cached): "
            f"rows_updated={resolution_summary.get('rows_updated', 0)}, "
            f"unique_old_tax_ids_updated={resolution_summary.get('unique_old_tax_ids_updated', 0)}, "
            f"changes_file={paths['changes']}"
        )

    def _write_resolution_artifacts(self, request: TaxonomyStageRequest, merged_dump_path: Path, paths: Dict[str, Path]):
        merged_taxid_map, resolved_taxonomy_df, resolution_summary, resolution_changes_df = self._resolution_data(request, merged_dump_path)
        payload = self._resolution_payload(request, merged_dump_path, resolution_summary, resolved_taxonomy_df, merged_taxid_map)
        self._write_json(paths["summary"], payload)
        resolution_changes_df.to_csv(paths["changes"], index=False)
        self._log(f"Taxonomy cache hit and backfilled resolution artifacts: summary={paths['summary']}, changes={paths['changes']}")

    def _rebuild(self, request: TaxonomyStageRequest, merged_dump_path: Path):
        paths = self._cache_paths(); merged_taxid_map, resolved_taxonomy_df, resolution_summary, resolution_changes_df = self._resolution_data(request, merged_dump_path)
        payload = self._resolution_payload(request, merged_dump_path, resolution_summary, resolved_taxonomy_df, merged_taxid_map)
        self._write_json(paths["summary"], payload); resolution_changes_df.to_csv(paths["changes"], index=False)
        self._log(f"Taxonomy merge resolution applied using {merged_dump_path} ({len(merged_taxid_map)} merged ID rules).")
        self._log(f"Taxonomy resolution details: input_rows={payload['input_rows']}, rows_updated={payload['rows_updated']}, unique_old_tax_ids_updated={payload['unique_old_tax_ids_updated']}, resolved_rows={payload['resolved_rows']}")
        self._log(f"Taxonomy resolution artifacts saved: summary={paths['summary']}, changes={paths['changes']}")
        abundance_matrix, taxon_lookup_df = compute_taxonomy_matrices(taxonomy_df=resolved_taxonomy_df, taxon_key_sep=request.taxon_key_sep); self._persist(request, abundance_matrix, taxon_lookup_df, paths)
        return abundance_matrix, taxon_lookup_df

    def _resolution_data(self, request: TaxonomyStageRequest, merged_dump_path: Path):
        merged_taxid_map = TaxonomyDumpAccessor(merged_dump_path).load_merged_taxid_map(); resolver = DeprecatedTaxonomyResolutionEngine(merged_taxid_map)
        resolution_summary, resolution_changes_df = resolver.summarize_resolution(taxonomy_df=request.taxonomy_df, sample_col="acc", tax_id_col="tax_id", count_col="total_count")
        resolved_taxonomy_df = resolver.resolve(taxonomy_df=request.taxonomy_df, sample_col="acc", tax_id_col="tax_id", count_col="total_count")
        return merged_taxid_map, resolved_taxonomy_df, resolution_summary, resolution_changes_df

    def _resolution_payload(self, request: TaxonomyStageRequest, merged_dump_path: Path, resolution_summary: Dict[str, Any], resolved_taxonomy_df: pd.DataFrame, merged_taxid_map):
        return {"schema_version": "taxonomy_resolution_summary_v1", "view_name": request.view_name, "merged_dump_path": str(merged_dump_path), "merged_dump_rule_count": int(len(merged_taxid_map)), "input_unique_tax_ids": int(request.taxonomy_df["tax_id"].astype(str).nunique()) if "tax_id" in request.taxonomy_df.columns else 0, "resolved_unique_tax_ids": int(resolved_taxonomy_df["tax_id"].astype(str).nunique()) if "tax_id" in resolved_taxonomy_df.columns else 0, "input_rows": int(len(request.taxonomy_df)), "resolved_rows": int(len(resolved_taxonomy_df)), **resolution_summary}

    def _persist(self, request: TaxonomyStageRequest, abundance_matrix: pd.DataFrame, taxon_lookup_df: pd.DataFrame, paths: Dict[str, Path]):
        abundance_matrix.to_csv(paths["matrix"])
        taxon_lookup_df.to_csv(paths["lookup"], index=False)
        self._write_json(paths["stamp"], self._current_stamp(request, Path(request.merged_dump_path)))
        self._log(f"Taxonomy cache miss: rebuilt taxonomy features in {self.paths.results_dir}", echo=True)

