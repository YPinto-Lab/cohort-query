from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Workspace:
    root: Path

    @classmethod
    def open(cls, root: Path | str) -> "Workspace":
        root = Path(root)
        if not root.is_dir():
            raise FileNotFoundError(f"Workspace not found: {root}")
        ws = cls(root=root)
        ws.agent_log_dir.mkdir(parents=True, exist_ok=True)
        return ws

    @property
    def name(self) -> str:
        return self.root.name

    @property
    def inputs_dir(self) -> Path:
        return self.root / "inputs"

    @property
    def results_dir(self) -> Path:
        return self.root / "results"

    @property
    def agent_log_dir(self) -> Path:
        return self.results_dir / "agent_log"
