import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
INSTALLER = REPO_ROOT / "Scripts" / "git-guard" / "install.sh"


def test_install_creates_executable_pre_commit_hook(tmp_path: Path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    result = subprocess.run(
        ["bash", str(INSTALLER)],
        cwd=tmp_path, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    hook = tmp_path / ".git" / "hooks" / "pre-commit"
    assert hook.exists()
    assert hook.stat().st_mode & 0o111
    assert "pre_commit.py" in hook.read_text() or hook.is_symlink()


def test_install_is_idempotent(tmp_path: Path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    for _ in range(2):
        result = subprocess.run(
            ["bash", str(INSTALLER)],
            cwd=tmp_path, capture_output=True, text=True,
        )
        assert result.returncode == 0, result.stderr
