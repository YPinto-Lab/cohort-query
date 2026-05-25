from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Dict, Iterable

import pandas as pd

from ..runtime_assembly_models import RuntimeAssemblyPaths


class RuntimeAssemblyStageBase:
    STAGE_DIRS = {
        "enrichment": "stage_01_enrichment",
        "taxonomy_resolution": "stage_02_taxonomy_resolution",
        "aggregation": "stage_03_aggregation",
        "final_assembly": "stage_04_final_assembly",
        "accessor": "stage_05_accessor",
    }

    def __init__(self, paths: RuntimeAssemblyPaths, logger=None):
        self.paths = paths
        self._log = logger.log if hasattr(logger, "log") else logger
        self._ensure_stage_roots()

    def _ensure_stage_roots(self) -> None:
        self.paths.results_dir.mkdir(parents=True, exist_ok=True)
        self.paths.assembly_db_dir.mkdir(parents=True, exist_ok=True)

    def _stage_dir(self, stage_name: str) -> Path:
        return self.paths.results_dir / self.STAGE_DIRS[stage_name]

    def _manifest_path(self) -> Path:
        return self.paths.assembly_db_dir / "pipeline_manifest.json"

    def _input_folder_fingerprint(self) -> str:
        return self._folder_fingerprint(self.paths.workspace_input_dir)

    def _folder_fingerprint(self, folder: Path) -> str:
        if not folder.exists():
            return "missing"
        digest = hashlib.sha256()
        for path in sorted(p for p in folder.rglob("*") if p.is_file()):
            digest.update(str(path.relative_to(folder)).encode("utf-8"))
            digest.update(b"\0")
            digest.update(self._file_fingerprint(path).encode("utf-8"))
            digest.update(b"\0")
        return digest.hexdigest()

    def _file_fingerprint(self, path: Path) -> str:
        if not path.exists():
            return "missing"
        digest = hashlib.sha256()
        digest.update(str(path.stat().st_size).encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        return digest.hexdigest()

    def _dataframe_fingerprint(self, df: pd.DataFrame) -> str:
        digest = hashlib.sha256()
        digest.update("|".join(map(str, df.columns)).encode("utf-8"))
        digest.update(b"\0")
        digest.update(pd.util.hash_pandas_object(df, index=True).values.tobytes())
        return digest.hexdigest()

    def _read_json(self, path: Path):
        return json.loads(path.read_text(encoding="utf-8"))

    def _write_json(self, path: Path, payload):
        self._atomic_write_text(path, json.dumps(payload, indent=2, ensure_ascii=False))

    def _write_csv(self, path: Path, df: pd.DataFrame, index: bool = False, sep: str = ",") -> None:
        temp_path = path.with_name(f"{path.name}.tmp")
        path.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(temp_path, index=index, sep=sep)
        os.replace(temp_path, path)

    def _write_parquet(self, path: Path, df: pd.DataFrame) -> None:
        try:
            import pyarrow  # noqa: F401
        except Exception as exc:
            raise RuntimeError("pyarrow is required to write parquet artifacts. Install pyarrow and rerun.") from exc
        temp_path = path.with_name(f"{path.name}.tmp")
        path.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(temp_path, index=False)
        os.replace(temp_path, path)

    def _atomic_write_text(self, path: Path, content: str) -> None:
        temp_path = path.with_name(f"{path.name}.tmp")
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path.write_text(content, encoding="utf-8")
        os.replace(temp_path, path)

    def _summary_is_current(
        self,
        summary_path: Path,
        schema_version: str,
        stage_name: str,
        input_fingerprint: str,
        required_paths: Iterable[Path] = (),
    ) -> bool:
        if not summary_path.exists():
            return False
        summary = self._read_json(summary_path)
        artifacts_present = all(path.exists() for path in required_paths)
        return (
            summary.get("schema_version") == schema_version
            and summary.get("stage_name") == stage_name
            and summary.get("status") == "ok"
            and summary.get("input_fingerprint") == input_fingerprint
            and artifacts_present
        )

    def _read_csv(self, path: Path, **kwargs) -> pd.DataFrame:
        return pd.read_csv(path, **kwargs)  # type: ignore[return-value]

    def _log_stage(self, message: str) -> None:
        if self._log is not None:
            self._log(message)

