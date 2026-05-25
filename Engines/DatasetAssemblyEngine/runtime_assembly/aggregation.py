from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Tuple

import pandas as pd

from ..dataset_assembly_engine import compute_taxonomy_matrices
from ..runtime_assembly_models import AggregationStageRequest
from .base import RuntimeAssemblyStageBase


class AggregationStageRunner(RuntimeAssemblyStageBase):
    STAGE_NAME = "aggregation"
    SCHEMA_VERSION = "aggregation_summary_v1"

    def run(self, request: AggregationStageRequest) -> Tuple[pd.DataFrame, pd.DataFrame]:
        stage_dir = self._stage_dir(self.STAGE_NAME)
        paths = self._paths(stage_dir)
        fingerprint = self._fingerprint(request)
        if self._summary_is_current(
            paths["summary"],
            self.SCHEMA_VERSION,
            self.STAGE_NAME,
            fingerprint,
            [paths["counts"], paths["taxon_lookup"]],
        ):
            return self._load(paths)
        return self._rebuild(request, paths, fingerprint)

    def _paths(self, stage_dir: Path) -> Dict[str, Path]:
        return {
            "counts": stage_dir / "counts.parquet",
            "taxon_lookup": stage_dir / "taxon_lookup.csv",
            "summary": stage_dir / "aggregation_summary.json",
        }

    def _fingerprint(self, request: AggregationStageRequest) -> str:
        payload = {
            "view_name": request.view_name,
            "taxon_key_sep": request.taxon_key_sep,
            "resolved_taxonomy": self._dataframe_fingerprint(request.resolved_taxonomy_df),
        }
        return self._json_fingerprint(payload)

    def _json_fingerprint(self, payload: Dict[str, object]) -> str:
        import hashlib
        import json

        digest = hashlib.sha256()
        digest.update(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8"))
        return digest.hexdigest()

    def _load(self, paths: Dict[str, Path]) -> Tuple[pd.DataFrame, pd.DataFrame]:
        counts_df = pd.read_parquet(paths["counts"])
        abundance_matrix = counts_df.pivot(index="acc", columns="taxon_key", values="total_count").fillna(0)
        abundance_matrix = abundance_matrix.astype(int)
        taxon_lookup_df = pd.read_csv(paths["taxon_lookup"])
        return abundance_matrix, taxon_lookup_df

    def _rebuild(self, request: AggregationStageRequest, paths: Dict[str, Path], fingerprint: str) -> Tuple[pd.DataFrame, pd.DataFrame]:
        abundance_matrix, taxon_lookup_df = compute_taxonomy_matrices(request.resolved_taxonomy_df, request.taxon_key_sep)
        counts_df = self._counts_frame(request.resolved_taxonomy_df, request.taxon_key_sep)
        self._write_parquet(paths["counts"], counts_df)
        self._write_csv(paths["taxon_lookup"], taxon_lookup_df, index=False)
        self._write_json(paths["summary"], self._summary_payload(request, fingerprint, counts_df, paths))
        self._log_stage(f"Aggregation rebuilt: {paths['counts']}")
        return abundance_matrix, taxon_lookup_df

    def _counts_frame(self, resolved_taxonomy_df: pd.DataFrame, taxon_key_sep: str) -> pd.DataFrame:
        lineage_columns = [c for c in ["ileft", "iright"] if c in resolved_taxonomy_df.columns]
        working = resolved_taxonomy_df[["acc", "tax_id", "rank", "name", "total_count"] + lineage_columns].copy()
        working["taxon_key"] = (
            working["rank"].astype(str)
            + taxon_key_sep
            + working["name"].astype(str)
            + taxon_key_sep
            + working["tax_id"].astype(str)
        )
        return working[["acc", "taxon_key", "total_count"]].groupby(["acc", "taxon_key"], as_index=False)["total_count"].sum()

    def _summary_payload(
        self,
        request: AggregationStageRequest,
        fingerprint: str,
        counts_df: pd.DataFrame,
        paths: Dict[str, Path],
    ) -> Dict[str, object]:
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        return {
            "schema_version": self.SCHEMA_VERSION,
            "stage_name": self.STAGE_NAME,
            "status": "ok",
            "input_fingerprint": fingerprint,
            "input_rows": int(len(request.resolved_taxonomy_df)),
            "unique_samples": int(counts_df["acc"].nunique()),
            "unique_taxa": int(counts_df["taxon_key"].nunique()),
            "taxon_key_separator": request.taxon_key_sep,
            "output_files": {
                "counts_parquet": str(paths["counts"].relative_to(self.paths.results_dir)),
                "taxon_lookup_csv": str(paths["taxon_lookup"].relative_to(self.paths.results_dir)),
            },
            "started_at": now,
            "finished_at": now,
        }


