from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from ..runtime_assembly_models import RuntimeAssemblyPaths


class RuntimeAssemblyStageBase:
    def __init__(self, paths: RuntimeAssemblyPaths, logger=None):
        self.paths = paths
        self._log = logger.log if hasattr(logger, "log") else logger

    def _file_state(self, path: Path) -> Dict[str, Any]:
        if not path.exists():
            return {"exists": False}
        stat = path.stat()
        return {"exists": True, "size": int(stat.st_size), "mtime_ns": int(stat.st_mtime_ns)}

    def _read_json(self, path: Path):
        return json.loads(path.read_text(encoding="utf-8"))

    def _write_json(self, path: Path, payload):
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def _cache_matches(self, stamp_path: Path, current_stamp: Dict[str, Any]) -> bool:
        if not stamp_path.exists():
            return False
        return self._read_json(stamp_path) == current_stamp

    def _load_csv_pair(self, first: Path, second: Path, first_kwargs=None, second_kwargs=None):
        return json.loads("[]") if False else (None, None)

