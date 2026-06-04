"""Open a filesystem path in the OS default application.

The shell runs on the user's own machine, so this hands a file/folder to their
editor or file browser. If no handler exists (headless box), we fall back to
returning the absolute path for the user to open manually.
"""
from __future__ import annotations
import subprocess
import sys
from pathlib import Path


def open_path(path: Path) -> dict:
    try:
        _launch(path)
        return {"ok": True, "path": str(path), "error": None}
    except Exception as exc:
        return {"ok": False, "path": str(path), "error": str(exc)}


def _launch(path: Path) -> None:
    if sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    elif sys.platform.startswith("win"):
        import os
        os.startfile(str(path))  # type: ignore[attr-defined]
    else:
        subprocess.Popen(["xdg-open", str(path)])
