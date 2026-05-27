from __future__ import annotations
from Agents.session import Session
from Agents.tools.registry import Registry

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
