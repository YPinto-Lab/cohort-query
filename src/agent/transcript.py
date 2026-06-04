from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class TranscriptWriter:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.touch(exist_ok=True)

    def _append(self, record: dict) -> None:
        with self.path.open("a") as f:
            f.write(json.dumps(record) + "\n")

    def user(self, content: str) -> None:
        self._append({"ts": _now(), "type": "user", "content": content})

    def assistant(self, content: str) -> None:
        self._append({"ts": _now(), "type": "assistant", "content": content})

    def tool_call(
        self,
        tool: str,
        args: dict,
        *,
        tool_use_id: str,
        code: str | None = None,
        imports_used: list[str] | None = None,
    ) -> None:
        rec: dict[str, Any] = {
            "ts": _now(),
            "type": "tool_call",
            "tool": tool,
            "args": args,
            "tool_use_id": tool_use_id,
        }
        if code is not None:
            rec["code"] = code
        if imports_used is not None:
            rec["imports_used"] = imports_used
        self._append(rec)

    def tool_result_ok(
        self,
        tool_use_id: str,
        result_summary: dict,
        *,
        latency_ms: int,
        new_handles: list[str] | None = None,
    ) -> None:
        rec: dict[str, Any] = {
            "ts": _now(),
            "type": "tool_result",
            "tool_use_id": tool_use_id,
            "result_summary": result_summary,
            "is_error": False,
            "latency_ms": latency_ms,
        }
        if new_handles is not None:
            rec["new_handles"] = new_handles
        self._append(rec)

    def tool_result_err(
        self, tool_use_id: str, error: str, traceback: str, *, latency_ms: int
    ) -> None:
        self._append({
            "ts": _now(),
            "type": "tool_result",
            "tool_use_id": tool_use_id,
            "error": error,
            "traceback": traceback,
            "is_error": True,
            "latency_ms": latency_ms,
        })

    def error(self, message: str) -> None:
        self._append({"ts": _now(), "type": "error", "message": message})
