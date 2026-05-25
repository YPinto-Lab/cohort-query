from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Tuple

import pandas as pd

from ..dataset_assembly_engine import compute_analysis_wide_dataset, compute_maaslin_export
from ..runtime_assembly_models import MergeStageRequest
from .base import RuntimeAssemblyStageBase


class FinalAssemblyStageRunner(RuntimeAssemblyStageBase):
    STAGE_NAME = "final_assembly"
    SCHEMA_VERSION = "final_assembly_summary_v1"

    def run(self, request: MergeStageRequest) -> Tuple[pd.DataFrame, List[str]]:
        stage_dir = self._stage_dir(self.STAGE_NAME)
        paths = self._paths(stage_dir)
        fingerprint = self._fingerprint(request)
        if self._summary_is_current(
            paths["summary"],
            self.SCHEMA_VERSION,
            self.STAGE_NAME,
            fingerprint,
            [paths["abundance_matrix"], paths["abundance_maaslin"], paths["analysis_wide"]],
        ):
            return self._load(request, paths)
        return self._rebuild(request, paths, fingerprint)

    def _paths(self, stage_dir: Path) -> Dict[str, Path]:
        return {
            "abundance_matrix": stage_dir / "abundance_matrix.csv",
            "abundance_maaslin": stage_dir / "abundance_maaslin.tsv",
            "analysis_wide": stage_dir / "analysis_wide_dataset.csv",
            "summary": stage_dir / "merge_summary.json",
        }

    def _fingerprint(self, request: MergeStageRequest) -> str:
        payload = {
            "view_name": request.view_name,
            "enriched_metadata": self._dataframe_fingerprint(request.enriched_metadata_df),
            "abundance_matrix": self._dataframe_fingerprint(request.abundance_matrix),
            "taxon_lookup": self._dataframe_fingerprint(request.taxon_lookup_df) if request.taxon_lookup_df is not None else "missing",
        }
        return self._json_fingerprint(payload)

    def _json_fingerprint(self, payload: Dict[str, object]) -> str:
        import hashlib
        import json

        digest = hashlib.sha256()
        digest.update(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8"))
        return digest.hexdigest()

    def _load(self, request: MergeStageRequest, paths: Dict[str, Path]) -> Tuple[pd.DataFrame, List[str]]:
        abundance_metadata_matrix = pd.read_csv(paths["analysis_wide"])
        metadata_columns = list(request.enriched_metadata_df.columns)
        return abundance_metadata_matrix, metadata_columns

    def _rebuild(self, request: MergeStageRequest, paths: Dict[str, Path], fingerprint: str) -> Tuple[pd.DataFrame, List[str]]:
        taxon_lookup_df = request.taxon_lookup_df if request.taxon_lookup_df is not None else self._lookup_from_abundance(request.abundance_matrix)
        abundance_metadata_matrix, metadata_columns = compute_analysis_wide_dataset(
            enriched_metadata_df=request.enriched_metadata_df,
            abundance_matrix=request.abundance_matrix,
        )
        maaslin_df = compute_maaslin_export(request.abundance_matrix, taxon_lookup_df)
        wide_matrix = request.abundance_matrix.copy()
        wide_matrix.index.name = wide_matrix.index.name or "acc"
        self._write_csv(paths["abundance_matrix"], wide_matrix.reset_index(), index=False)
        self._write_csv(paths["abundance_maaslin"], maaslin_df, index=False, sep="\t")
        self._write_csv(paths["analysis_wide"], abundance_metadata_matrix, index=False)
        self._write_json(paths["summary"], self._summary_payload(request, fingerprint, abundance_metadata_matrix, paths))
        self._log_stage(f"Final assembly rebuilt: {paths['abundance_matrix']}")
        return abundance_metadata_matrix, metadata_columns

    def _lookup_from_abundance(self, abundance_matrix: pd.DataFrame) -> pd.DataFrame:
        rows = []
        for taxon_key in abundance_matrix.columns:
            parts = str(taxon_key).split("||")
            rows.append(
                {
                    "taxon_key": taxon_key,
                    "rank": parts[0] if len(parts) > 0 else None,
                    "name": parts[1] if len(parts) > 1 else None,
                    "tax_id": parts[2] if len(parts) > 2 else None,
                }
            )
        return pd.DataFrame(rows)

    def _summary_payload(
        self,
        request: MergeStageRequest,
        fingerprint: str,
        abundance_metadata_matrix: pd.DataFrame,
        paths: Dict[str, Path],
    ) -> Dict[str, object]:
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        return {
            "schema_version": self.SCHEMA_VERSION,
            "stage_name": self.STAGE_NAME,
            "status": "ok",
            "input_fingerprint": fingerprint,
            "metadata_rows": int(len(request.enriched_metadata_df)),
            "matrix_sample_rows": int(len(request.abundance_matrix)),
            "matrix_taxa_columns": int(len(request.abundance_matrix.columns)),
            "analysis_wide_rows": int(len(abundance_metadata_matrix)),
            "output_files": {
                "abundance_matrix_csv": str(paths["abundance_matrix"].relative_to(self.paths.results_dir)),
                "abundance_maaslin_tsv": str(paths["abundance_maaslin"].relative_to(self.paths.results_dir)),
                "analysis_wide_dataset_csv": str(paths["analysis_wide"].relative_to(self.paths.results_dir)),
            },
            "started_at": now,
            "finished_at": now,
        }


MergeStageRunner = FinalAssemblyStageRunner

