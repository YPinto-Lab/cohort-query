from __future__ import annotations
from pathlib import Path

from agent.workspace import Workspace

# results/ holds agent run output (logs, generated artifacts), not workspace source;
# __pycache__/.git are noise. None belong in the snapshot the agent reads.
_SKIP_DIRS = {"results", "__pycache__", ".git"}


class WorkspaceSnapshot:
    """Renders the live on-disk state of a workspace for the agent's system prompt."""

    def __init__(self, workspace: Workspace) -> None:
        self._root = workspace.root

    def render(self) -> str:
        files = self._files()
        lines = [f"# Workspace: {self._root.name}", "", "## Files"]
        lines.extend(self._tree_lines(files))
        lines.extend(self._intent_blocks(files))
        return "\n".join(lines)

    def _files(self) -> list[Path]:
        return [p for p in sorted(self._root.rglob("*")) if self._included(p)]

    def _included(self, path: Path) -> bool:
        if path.is_symlink() or not path.is_file() or path.name.startswith("."):
            return False
        return not (set(path.relative_to(self._root).parts) & _SKIP_DIRS)

    def _tree_lines(self, files: list[Path]) -> list[str]:
        return [f"- {p.relative_to(self._root).as_posix()}" for p in files]

    def _intent_blocks(self, files: list[Path]) -> list[str]:
        return [self._intent_block(p) for p in files if p.suffix == ".md"]

    def _intent_block(self, path: Path) -> str:
        return f"\n## {path.relative_to(self._root).as_posix()}\n{path.read_text()}"
