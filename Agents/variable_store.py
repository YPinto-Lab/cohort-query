from __future__ import annotations
from typing import Any
from Agents.summaries import summarize_object


class VariableStore:
    def __init__(self) -> None:
        self._objects: dict[str, Any] = {}
        self._counters: dict[str, int] = {}

    def put(self, obj: Any, *, hint: str) -> str:
        self._counters[hint] = self._counters.get(hint, 0) + 1
        handle = f"{hint}_{self._counters[hint]}"
        self._objects[handle] = obj
        return handle

    def get(self, handle: str) -> Any:
        if handle not in self._objects:
            raise KeyError(
                f"Handle {handle!r} not found. Available: {sorted(self._objects)}"
            )
        return self._objects[handle]

    def summary(self, handle: str) -> dict:
        return {"handle": handle, **summarize_object(self.get(handle))}

    def list_handles(self) -> dict[str, dict]:
        return {h: summarize_object(o) for h, o in self._objects.items()}

    def __contains__(self, handle: str) -> bool:
        return handle in self._objects
