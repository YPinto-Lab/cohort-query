from __future__ import annotations
from pathlib import Path
from agent.session import Session
from agent.tools.registry import Registry

session_registry = Registry()


@session_registry.tool
def summarize(session: Session, handle: str) -> dict:
    """Return the summary of a stored handle (does not modify state)."""
    return session.variables.summary(handle)


@session_registry.tool
def list_workspace_inputs(session: Session) -> dict:
    """List input files available in the current workspace's inputs/ directory."""
    out = []
    if session.workspace.inputs_dir.exists():
        for p in sorted(session.workspace.inputs_dir.rglob("*")):
            if p.is_file():
                out.append({
                    "name": p.name,
                    "relative_path": str(p.relative_to(session.workspace.inputs_dir)),
                    "size_bytes": p.stat().st_size,
                })
    return {"value": out}


_REPO_ROOT = Path(__file__).resolve().parents[3]
_READ_CAP_BYTES = 65536


@session_registry.tool
def list_dir(session: Session, path: str) -> dict:
    """List the entries of a directory inside the repository (read-only)."""
    target = _safe_repo_path(path)
    return {"value": [_entry(child) for child in sorted(target.iterdir())]}


@session_registry.tool
def read_file(session: Session, path: str) -> dict:
    """Read a text file inside the repository, capped at 64 KB (read-only)."""
    target = _safe_repo_path(path)
    raw = target.read_bytes()
    return {
        "value": raw[:_READ_CAP_BYTES].decode("utf-8", errors="replace"),
        "truncated": len(raw) > _READ_CAP_BYTES,
    }


def _safe_repo_path(path: str) -> Path:
    candidate = (_REPO_ROOT / path).resolve()
    if not candidate.is_relative_to(_REPO_ROOT):
        raise ValueError(f"path escapes repository root: {path}")
    if not candidate.exists():
        raise FileNotFoundError(f"path not found: {path}")
    return candidate


def _entry(child: Path) -> dict:
    return {
        "name": child.name,
        "kind": "dir" if child.is_dir() else "file",
        "size_bytes": child.stat().st_size if child.is_file() else None,
    }
