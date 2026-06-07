from __future__ import annotations
import subprocess
import sys
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


# session_tools.py lives at src/agent/tools/ — three parents up is the repo root.
_REPO_ROOT = Path(__file__).resolve().parents[3]
_READ_CAP_BYTES = 65536
_SCRIPT_OUTPUT_CAP = 4000
_SCRIPT_TIMEOUT_S = 300


@session_registry.tool
def list_dir(session: Session, path: str) -> dict:
    """List the entries of a directory (read-only). The path is resolved against the
    current workspace first, then the repository, so a plain workspace-relative path
    (e.g. "1_build") and a repo path (e.g. "Docs") both work."""
    target = _safe_read_path(session, path)
    return {"value": [_entry(child) for child in sorted(target.iterdir())]}


@session_registry.tool
def read_file(session: Session, path: str) -> dict:
    """Read a text file, capped at 64 KB (read-only). The path is resolved against the
    current workspace first, then the repository, so files you wrote into the workspace
    (e.g. "1_build/build.py") and repo files (e.g. "Docs/...", "src/askslm/...") both work."""
    target = _safe_read_path(session, path)
    with target.open("rb") as handle:
        raw = handle.read(_READ_CAP_BYTES + 1)   # one byte past the cap reveals truncation
    return {
        "value": raw[:_READ_CAP_BYTES].decode("utf-8", errors="replace"),
        "truncated": len(raw) > _READ_CAP_BYTES,
    }


@session_registry.tool
def write_file(session: Session, path: str, content: str) -> dict:
    """Write a text file into the current workspace, creating parent directories.
    The path is relative to the workspace root (e.g. "1_build/build.py"). This is
    how you author phase scripts; run them with run_script."""
    target = _safe_workspace_path(session, path)
    target.parent.mkdir(parents=True, exist_ok=True)
    data = content.encode("utf-8")
    target.write_bytes(data)
    return {"path": path, "bytes_written": len(data)}


@session_registry.tool
def run_script(session: Session, path: str) -> dict:
    """Run a Python script that lives in the current workspace as a subprocess,
    returning its exit code and captured output. The path is relative to the
    workspace root and must end in .py. A non-zero returncode means the script
    failed — read stdout to see why. A script's products are files on disk
    (e.g. feature_table.biom) that appear in the workspace, not as handles."""
    target = _safe_workspace_path(session, path)
    if target.suffix != ".py":
        raise ValueError(f"not a Python script: {path}")
    if not target.is_file():
        raise FileNotFoundError(f"script not found: {path}")
    proc = subprocess.run(
        [sys.executable, str(target)], cwd=str(session.workspace.root),
        capture_output=True, text=True, timeout=_SCRIPT_TIMEOUT_S)
    output = (proc.stdout + proc.stderr)[-_SCRIPT_OUTPUT_CAP:]
    return {"path": path, "returncode": proc.returncode, "stdout": output}


def _safe_workspace_path(session: Session, path: str) -> Path:
    root = session.workspace.root.resolve()
    candidate = (root / path).resolve()
    if not candidate.is_relative_to(root):
        raise ValueError(f"path escapes workspace root: {path}")
    return candidate


def _safe_read_path(session: Session, path: str) -> Path:
    # A path the agent reads may be workspace-relative (a file it just wrote) or
    # repo-relative (pointer-map docs, askslm source). Try the workspace first,
    # then the repo, so plain workspace paths resolve without a prefix. The
    # workspace lives inside the repo, so the repo is the outer security boundary.
    roots = (session.workspace.root.resolve(), _REPO_ROOT)
    if all(not (root / path).resolve().is_relative_to(root) for root in roots):
        raise ValueError(f"path escapes workspace and repository root: {path}")
    for root in roots:
        candidate = (root / path).resolve()
        if not candidate.is_relative_to(root):
            continue
        # Hidden files/dirs (.git, .venv, …) are plumbing, not study material — keep
        # the tools consistent with the workspace snapshot, which excludes them too.
        if any(part.startswith(".") for part in candidate.relative_to(root).parts):
            raise ValueError(f"path is hidden (dotfile/dir): {path}")
        if candidate.exists():
            return candidate
    raise FileNotFoundError(f"path not found: {path}")


def _entry(child: Path) -> dict:
    return {
        "name": child.name,
        "kind": "dir" if child.is_dir() else "file",
        "size_bytes": child.stat().st_size if child.is_file() else None,
    }
