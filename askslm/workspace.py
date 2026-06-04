"""Resolve a phase script's paths from the numbered-folder workspace convention.

`workspace.phase(__file__)` self-locates inside `Workspaces/<name>/<N_phase>/...` and hands back
the inputs dir, the result dir, the phase's shared module, and the upstream community. Spec:
Docs/superpowers/specs/2026-06-03-workspace-tooling-design.html.
"""
from pathlib import Path

_PHASES = {"1_build": "build", "2_transform": "transform", "3_analyze": "analyze"}


def phase(script_file: str | Path) -> "_Phase":
    return _Phase(Path(script_file).resolve())


class _Phase:
    def __init__(self, script_path: Path):
        self._script = script_path
        self.root = _workspace_root(script_path)
        self._folder = _phase_folder(script_path, self.root)
        self.name = _PHASES[self._folder]

    @property
    def inputs(self) -> Path:
        return self.root / "0_inputs"

    @property
    def result(self) -> Path:
        """This script's output directory, created on first access."""
        return _made(self._result_dir())

    @property
    def data(self) -> Path:
        return _made(self.result / "data")

    @property
    def plots(self) -> Path:
        return _made(self.result / "plots")

    def _result_dir(self) -> Path:
        if self.name == "transform":
            return self._script.parent / "result"
        return self._script.parent


def _workspace_root(script_path: Path) -> Path:
    for parent in script_path.parents:
        if parent.parent.name == "Workspaces":
            return parent
    raise ValueError(f"{script_path} is not inside a Workspaces/<name>/ tree")


def _phase_folder(script_path: Path, root: Path) -> str:
    folder = script_path.relative_to(root).parts[0]
    if folder not in _PHASES:
        raise ValueError(f"{script_path} is not under a known phase folder {sorted(_PHASES)}")
    return folder


def _made(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path
