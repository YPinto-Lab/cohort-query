# Scripts/git-guard/tests/test_claude_guard.py
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
HOOK = REPO_ROOT / "Scripts" / "git-guard" / "claude_guard.py"


@pytest.fixture
def repo_on(tmp_path: Path):
    """Factory: returns a function that builds a temp repo on a given branch."""
    def _make(branch: str) -> Path:
        subprocess.run(["git", "init", "-q", "-b", "main", str(tmp_path)], check=True)
        subprocess.run(["git", "-C", str(tmp_path), "config", "user.email", "t@t"], check=True)
        subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", "T"], check=True)
        (tmp_path / "seed.txt").write_text("x")
        subprocess.run(["git", "-C", str(tmp_path), "add", "seed.txt"], check=True)
        subprocess.run(["git", "-C", str(tmp_path), "commit", "-q", "-m", "seed"], check=True)
        if branch != "main":
            subprocess.run(
                ["git", "-C", str(tmp_path), "switch", "-q", "-c", branch],
                check=True,
            )
        return tmp_path
    return _make


def run_hook(payload: dict) -> tuple[int, dict]:
    result = subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps(payload), capture_output=True, text=True,
    )
    out = json.loads(result.stdout) if result.stdout.strip() else {}
    return result.returncode, out


def test_bash_git_status_allowed_on_main(repo_on):
    repo = repo_on("main")
    rc, out = run_hook({
        "tool_name": "Bash",
        "tool_input": {"command": "git status"},
        "cwd": str(repo),
    })
    assert rc == 0
    assert out.get("decision") != "block"


def test_bash_git_commit_blocked_on_main(repo_on):
    repo = repo_on("main")
    rc, out = run_hook({
        "tool_name": "Bash",
        "tool_input": {"command": "git commit -m x"},
        "cwd": str(repo),
    })
    assert out["decision"] == "block"
    assert "main" in out["reason"].lower()


def test_bash_git_commit_allowed_on_feature(repo_on):
    repo = repo_on("feature/x")
    rc, out = run_hook({
        "tool_name": "Bash",
        "tool_input": {"command": "git commit -m x"},
        "cwd": str(repo),
    })
    assert out.get("decision") != "block"


def test_bash_checkout_main_blocked(repo_on):
    repo = repo_on("feature/x")
    rc, out = run_hook({
        "tool_name": "Bash",
        "tool_input": {"command": "git checkout main"},
        "cwd": str(repo),
    })
    assert out["decision"] == "block"


def test_bash_branch_delete_blocked_even_on_feature(repo_on):
    repo = repo_on("feature/x")
    rc, out = run_hook({
        "tool_name": "Bash",
        "tool_input": {"command": "git branch -D feature/old"},
        "cwd": str(repo),
    })
    assert out["decision"] == "block"
    assert "delete" in out["reason"].lower() or "never" in out["reason"].lower()


def test_edit_blocked_on_main(repo_on):
    repo = repo_on("main")
    rc, out = run_hook({
        "tool_name": "Edit",
        "tool_input": {"file_path": str(repo / "seed.txt")},
        "cwd": str(repo),
    })
    assert out["decision"] == "block"


def test_edit_allowed_on_feature(repo_on):
    repo = repo_on("feature/x")
    rc, out = run_hook({
        "tool_name": "Write",
        "tool_input": {"file_path": str(repo / "new.txt")},
        "cwd": str(repo),
    })
    assert out.get("decision") != "block"


def test_edit_outside_repo_is_allowed(tmp_path: Path):
    # Editing a file outside any git repo should not be our concern.
    rc, out = run_hook({
        "tool_name": "Edit",
        "tool_input": {"file_path": str(tmp_path / "foo.txt")},
        "cwd": str(tmp_path),
    })
    assert out.get("decision") != "block"
