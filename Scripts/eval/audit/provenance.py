"""What state a verification run was checked against -- compared later, by
check_staleness.py, to decide whether a judgment might no longer hold."""
from __future__ import annotations

import subprocess
from pathlib import Path


def mirror_build_id(db_path: Path) -> str:
    """No build-id table exists in the mirror itself -- mirror_config only ever
    holds sidecar file paths (see adapters.py). The file's own mtime+size is
    cheap and sufficient: a rebuild changes at least one of them."""
    stat = db_path.stat()
    return f"{int(stat.st_mtime)}-{stat.st_size}"


def code_commit(repo_root: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        cwd=repo_root, capture_output=True, text=True, check=True)
    return result.stdout.strip()
