from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Tuple

import pandas as pd

from ..dataset_assembly_engine import compute_analysis_wide_dataset
from ..runtime_assembly_models import MergeStageRequest
from .base import RuntimeAssemblyStageBase


class MergeStageRunner(RuntimeAssemblyStageBase):
    def run(self, request: MergeStageRequest) -> Tuple[pd.DataFrame, List[str]]:
        paths = self._cache_paths()
        self._require_stage_stamps(paths)
        cached = self._load_cache(request, paths)
        if cached is not None:
            return cached
        return self._rebuild(request, paths)

    def _cache_paths(self):
        return {
            "canonical": self.paths.results_dir / "Ask_SLM_Analysis_Wide_Dataset.csv",
            "columns": self.paths.results_dir / "Ask_SLM_Metadata_Columns.json",
            "stamp": self.paths.assembly_db_dir / "merge_stage_stamp.json",
            "compat": self.paths.results_dir / "Ask_SLM_Cache_Stamp.json",
            "enrichment": self.paths.assembly_db_dir / "enrichment_stage_stamp.json",
            "taxonomy": self.paths.assembly_db_dir / "taxonomy_stage_stamp.json",
        }

    def _require_stage_stamps(self, paths: Dict[str, Path]):
        if paths["enrichment"].exists() and paths["taxonomy"].exists():
            return
        raise RuntimeError("Missing stage stamps for merge. Run enrichment and taxonomy stages successfully before merge.")

    def _current_stamp(self, request: MergeStageRequest, paths: Dict[str, Path]):
        return {
            "schema_version": "merge_v2",
            "view_name": request.view_name,
            "enrichment_stamp": self._read_json(paths["enrichment"]),
            "taxonomy_stamp": self._read_json(paths["taxonomy"]),
        }

    def _load_cache(self, request: MergeStageRequest, paths: Dict[str, Path]):
        if not self._has_cache(paths):
            return None
        if not self._cache_matches(paths["stamp"], self._current_stamp(request, paths)):
            return None
        abundance_metadata_matrix = pd.read_csv(paths["canonical"])
        metadata_columns = self._read_json(paths["columns"])
        self._write_json(paths["compat"], {"schema_version": "combined_v2", **self._current_stamp(request, paths)})
        self._log(f"Merge cache hit: loaded from {self.paths.results_dir}", echo=True)
        return abundance_metadata_matrix, metadata_columns

    def _has_cache(self, paths: Dict[str, Path]) -> bool:
        return all(paths[k].exists() for k in ["canonical", "columns", "stamp"])

    def _rebuild(self, request: MergeStageRequest, paths: Dict[str, Path]):
        abundance_metadata_matrix, metadata_columns = compute_analysis_wide_dataset(enriched_metadata_df=request.enriched_metadata_df, abundance_matrix=request.abundance_matrix)
        abundance_metadata_matrix.to_csv(paths["canonical"], index=False)
        self._write_json(paths["columns"], metadata_columns)
        self._write_json(paths["stamp"], self._current_stamp(request, paths))
        self._write_json(paths["compat"], {"schema_version": "combined_v2", **self._current_stamp(request, paths)})
        self._log(f"Merge cache miss: rebuilt merged dataset in {self.paths.results_dir}", echo=True)
        return abundance_metadata_matrix, metadata_columns

