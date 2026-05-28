# Scripts/git-guard/tests/test_pre_commit.py
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
GIT_GUARD_DIR = REPO_ROOT / "Scripts" / "git-guard"
HOOK_SRC = GIT_GUARD_DIR / "pre_commit.py"


@pytest.fixture
def tmp_git_repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init", "-q", "-b", "main", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", "T"], check=True)
    # seed an initial commit on main before installing the hook so the hook has a HEAD to read
    seed = tmp_path / "seed.txt"
    seed.write_text("seed\n")
    subprocess.run(["git", "-C", str(tmp_path), "add", "seed.txt"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-q", "-m", "seed"], check=True)
    # install the hook and its dependency into .git/hooks/
    hooks_dir = tmp_path / ".git" / "hooks"
    hook_dst = hooks_dir / "pre-commit"
    shutil.copy(HOOK_SRC, hook_dst)
    hook_dst.chmod(0o755)
    # branch_policy must live alongside the hook so sys.path.insert(__file__.parent) works
    shutil.copy(GIT_GUARD_DIR / "branch_policy.py", hooks_dir / "branch_policy.py")
    return tmp_path


def _stage_change(repo: Path, name: str = "f.txt") -> None:
    (repo / name).write_text("x\n")
    subprocess.run(["git", "-C", str(repo), "add", name], check=True)


def _commit(repo: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(repo), "commit", "-m", "msg"],
        capture_output=True, text=True,
    )


def test_commit_on_main_is_rejected(tmp_git_repo: Path):
    _stage_change(tmp_git_repo)
    result = _commit(tmp_git_repo)
    assert result.returncode != 0
    assert "main" in result.stderr.lower() or "main" in result.stdout.lower()


def test_commit_on_allowed_branch_succeeds(tmp_git_repo: Path):
    subprocess.run(
        ["git", "-C", str(tmp_git_repo), "switch", "-q", "-c", "feature-x"],
        check=True,
    )
    _stage_change(tmp_git_repo)
    result = _commit(tmp_git_repo)
    assert result.returncode == 0, result.stderr


def test_commit_on_disallowed_prefix_is_rejected(tmp_git_repo: Path):
    subprocess.run(
        ["git", "-C", str(tmp_git_repo), "switch", "-q", "-c", "wip-x"],
        check=True,
    )
    _stage_change(tmp_git_repo)
    result = _commit(tmp_git_repo)
    assert result.returncode != 0


def test_commit_on_subbranch_succeeds(tmp_git_repo: Path):
    subprocess.run(
        ["git", "-C", str(tmp_git_repo), "switch", "-q", "-c", "feature-x/auth"],
        check=True,
    )
    _stage_change(tmp_git_repo)
    result = _commit(tmp_git_repo)
    assert result.returncode == 0, result.stderr
