"""Resolve a phase script's paths from the numbered-folder workspace convention.

`workspace.phase(__file__)` self-locates inside `Workspaces/<name>/<N_phase>/...` and hands back
the inputs dir, the result dir, the phase's shared module, and the upstream feature table. Spec:
Docs/superpowers/specs/2026-06-03-workspace-tooling-design.html.
"""
import importlib.util
from functools import cached_property
from pathlib import Path

from biom import load_table

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
        """This script's output directory (its own folder), created on first access."""
        return _made(self._script.parent)

    @cached_property
    def shared(self):
        return _load_module(self.root / self._folder / "shared.py")

    def upstream(self):
        return load_table(str(self._upstream_path()))

    def _upstream_path(self) -> Path:
        if self.name == "transform":
            return _the_biom_in(self.root / "1_build")
        if self.name == "analyze":
            exploration = self._script.parent.parent.name
            return _the_biom_in(self.root / "2_transform" / exploration)
        raise ValueError("build reads from ws.inputs; it has no upstream")


def _the_biom_in(folder: Path) -> Path:
    """A phase folder holds exactly one biom, under whatever descriptive name it was given."""
    bioms = sorted(folder.glob("*.biom"))
    if len(bioms) != 1:
        raise ValueError(f"expected exactly one .biom in {folder}, found {[b.name for b in bioms]}")
    return bioms[0]


def _workspace_root(script_path: Path) -> Path:
    """The study folder directly above the phase folder the script sits in.

    Studies can sit either directly under `Workspaces/` or one group folder deeper
    (`Workspaces/<group>/<study>/`), so this looks for the phase folder itself rather
    than assuming a fixed nesting depth.
    """
    parts = script_path.parts
    for index, part in enumerate(parts):
        if part in _PHASES and "Workspaces" in parts[:index]:
            return Path(*parts[:index])
    raise ValueError(f"{script_path} is not inside a Workspaces/<name>/ tree")


def _phase_folder(script_path: Path, root: Path) -> str:
    folder = script_path.relative_to(root).parts[0]
    if folder not in _PHASES:
        raise ValueError(f"{script_path} is not under a known phase folder {sorted(_PHASES)}")
    return folder


def _made(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def _load_module(path: Path):
    spec = importlib.util.spec_from_file_location("shared", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
