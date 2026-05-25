from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Dict

import pandas as pd

from Accessors.TaxonomyAccessor import TaxonomyAccessor

from ..runtime_assembly_models import TaxonomyAccessorRequest
from .base import RuntimeAssemblyStageBase


class TaxonomyAccessorRunner(RuntimeAssemblyStageBase):
    STAGE_NAME = "accessor"
    SCHEMA_VERSION = "accessor_summary_v1"

    def run(self, request: TaxonomyAccessorRequest) -> TaxonomyAccessor:
        stage_dir = self._stage_dir(self.STAGE_NAME)
        paths = self._paths(stage_dir, Path(request.lineage_db_path))
        fingerprint = self._fingerprint(request)
        if self._summary_is_current(paths["summary"], self.SCHEMA_VERSION, self.STAGE_NAME, fingerprint, [paths["lineage_db"]]):
            return TaxonomyAccessor(lineage_db_path=paths["lineage_db"])
        return self._rebuild(request, paths, fingerprint)

    def _paths(self, stage_dir: Path, lineage_db_path: Path) -> Dict[str, Path]:
        return {"summary": stage_dir / "accessor_summary.json", "lineage_db": lineage_db_path}

    def _fingerprint(self, request: TaxonomyAccessorRequest) -> str:
        payload = {
            "taxon_lookup": self._dataframe_fingerprint(request.taxon_lookup_df),
            "lineage_db_path": str(request.lineage_db_path),
        }
        return self._json_fingerprint(payload)

    def _json_fingerprint(self, payload: Dict[str, object]) -> str:
        import hashlib
        import json

        digest = hashlib.sha256()
        digest.update(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8"))
        return digest.hexdigest()

    def _rebuild(self, request: TaxonomyAccessorRequest, paths: Dict[str, Path], fingerprint: str) -> TaxonomyAccessor:
        lineage_db_path = paths["lineage_db"]
        accessor = TaxonomyAccessor()
        lineage_df = self._lineage_frame(request.taxon_lookup_df)
        accessor.build_from_dataframe(lineage_df)
        accessor.save_database(lineage_db_path)
        self._write_json(paths["summary"], self._summary_payload(request, fingerprint, lineage_df, paths))
        self._log_stage(f"Accessor rebuilt: {lineage_db_path}")
        return accessor

    def _lineage_frame(self, taxon_lookup_df: pd.DataFrame) -> pd.DataFrame:
        lineage_df = taxon_lookup_df.copy()
        for col in ["ileft", "iright"]:
            if col not in lineage_df.columns:
                lineage_df[col] = 0
        lineage_df = lineage_df[[c for c in ["tax_id", "rank", "name", "ileft", "iright"] if c in lineage_df.columns]].drop_duplicates(subset=["tax_id"])
        lineage_df["acc"] = "__global__"
        return lineage_df

    def _summary_payload(self, request: TaxonomyAccessorRequest, fingerprint: str, lineage_df: pd.DataFrame, paths: Dict[str, Path]):
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        return {
            "schema_version": self.SCHEMA_VERSION,
            "stage_name": self.STAGE_NAME,
            "status": "ok",
            "input_fingerprint": fingerprint,
            "source_lookup_rows": int(len(request.taxon_lookup_df)),
            "indexed_records": int(len(lineage_df)),
            "index_backend": "json",
            "output_files": {
                "taxon_query_db": str(paths["lineage_db"].relative_to(self.paths.results_dir)),
                "accessor_summary_json": str(paths["summary"].relative_to(self.paths.results_dir)),
            },
            "started_at": now,
            "finished_at": now,
        }

