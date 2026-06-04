"""Subprocess entrypoint for run_python. Reads pickled stdin, writes pickled stdout."""
from __future__ import annotations
import io
import os
import pickle
import sys
import traceback
from contextlib import redirect_stdout, redirect_stderr

WHITELIST_IMPORTS = ("pandas", "numpy", "scipy", "skbio")
# runtime type paths use the concrete module (type(obj).__module__), e.g. biom.table not biom
RECOGNIZED_TYPE_PATHS = (
    "biom.table.Table",
    "Common.contracts.metadata_results.MetadataOverview",
    "pandas.core.frame.DataFrame",
)


def _resolve_types() -> tuple[type, ...]:
    out: list[type] = []
    for path in RECOGNIZED_TYPE_PATHS:
        mod_name, _, cls_name = path.rpartition(".")
        try:
            mod = __import__(mod_name, fromlist=[cls_name])
            out.append(getattr(mod, cls_name))
        except Exception:
            pass
    return tuple(out)


def _build_namespace(workspace_path: str, handles: dict) -> dict:
    ns: dict = {}
    import askslm  # noqa: F401
    ns["askslm"] = askslm
    for mod_name in WHITELIST_IMPORTS:
        try:
            ns[mod_name] = __import__(mod_name)
        except ImportError:
            pass
    os.chdir(workspace_path)
    ns.update(handles)
    return ns


def main() -> None:
    payload = pickle.load(sys.stdin.buffer)
    code: str = payload["code"]
    workspace_path: str = payload["workspace_path"]
    handles: dict = payload["handles"]

    ns = _build_namespace(workspace_path, handles)
    stdout_buf = io.StringIO()
    stderr_buf = io.StringIO()
    recognized = _resolve_types()

    error = None
    tb = None
    try:
        with redirect_stdout(stdout_buf), redirect_stderr(stderr_buf):
            exec(compile(code, "<run_python>", "exec"), ns)
    except Exception as e:
        error = repr(e)
        tb = traceback.format_exc()

    new_handles: dict = {}
    if error is None:
        existing = set(handles)
        for name, val in ns.items():
            if name.startswith("_") or name in existing:
                continue
            if isinstance(val, recognized):
                new_handles[name] = val

    response = {
        "stdout": stdout_buf.getvalue() + stderr_buf.getvalue(),
        "new_handles": new_handles,
        "error": error,
        "traceback": tb,
    }
    sys.stdout.buffer.write(pickle.dumps(response))
    sys.stdout.buffer.flush()


if __name__ == "__main__":
    main()
