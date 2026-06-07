from __future__ import annotations
import ast
import pickle
import subprocess
import sys

from agent.session import Session
from agent.tools.registry import Registry

run_python_registry = Registry()

DEFAULT_TIMEOUT_S = 60
MAX_TIMEOUT_S = 300


def _extract_imports(code: str) -> list[str]:
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return []
    mods: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for n in node.names:
                mods.add(n.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                mods.add(node.module.split(".")[0])
    return sorted(mods)


@run_python_registry.tool
def run_python(session: Session, code: str, timeout_s: int = DEFAULT_TIMEOUT_S) -> dict:
    """Execute a one-shot Python snippet in a fresh sandboxed subprocess.
    State does NOT persist between calls: imports and plain variables vanish
    afterward. Only recognized domain objects created at top level (biom.Table
    feature tables, MetadataOverview, DataFrame) survive as handles, pre-loaded
    by name into later calls. pandas/numpy/scipy/skbio/askslm are pre-imported
    each call. For multi-step or durable work, write a script with write_file
    and run it with run_script instead."""
    timeout_s = max(1, min(int(timeout_s), MAX_TIMEOUT_S))
    imports_used = _extract_imports(code)

    payload = pickle.dumps({
        "code": code,
        "workspace_path": str(session.workspace.root),
        "handles": {h: session.variables.get(h) for h in session.variables.list_handles()},
    })

    try:
        proc = subprocess.run(
            [sys.executable, "-m", "agent.tools._sandbox_worker"],
            input=payload,
            capture_output=True,
            timeout=timeout_s,
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"run_python timeout after {timeout_s}s")

    if proc.returncode != 0 or not proc.stdout:
        raise RuntimeError(
            f"sandbox worker failed (rc={proc.returncode}): {proc.stderr.decode(errors='replace')[:500]}"
        )

    response = pickle.loads(proc.stdout)
    if response["error"]:
        raise RuntimeError(response["error"] + "\n" + (response["traceback"] or ""))

    new_handles: list[str] = []
    for var_name, obj in response["new_handles"].items():
        h = session.variables.put(obj, hint=var_name)
        new_handles.append(h)

    stdout = response["stdout"][-4000:]  # cap for LLM context
    dropped = response.get("dropped_handles") or []
    if dropped:
        stdout += (
            "\n[note] not kept as handles (not picklable, e.g. biom.Table): "
            + ", ".join(dropped)
            + " — inspect such objects within a single run_python call, or write a script."
        )
    return {
        "stdout": stdout,
        "new_handles": new_handles,
        "imports_used": imports_used,
    }
