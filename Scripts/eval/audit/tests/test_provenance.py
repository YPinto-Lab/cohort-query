import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from provenance import code_commit, mirror_build_id


def test_mirror_build_id_changes_when_file_content_changes(tmp_path):
    db_path = tmp_path / "mirror.duckdb"
    db_path.write_bytes(b"v1")
    first = mirror_build_id(db_path)
    db_path.write_bytes(b"v2-longer-content")
    second = mirror_build_id(db_path)
    assert first != second


def test_mirror_build_id_stable_for_unchanged_file(tmp_path):
    db_path = tmp_path / "mirror.duckdb"
    db_path.write_bytes(b"same")
    assert mirror_build_id(db_path) == mirror_build_id(db_path)


def test_code_commit_returns_a_short_sha(tmp_path):
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=tmp_path, check=True)
    (tmp_path / "f.txt").write_text("x")
    subprocess.run(["git", "add", "f.txt"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=tmp_path, check=True, capture_output=True)
    sha = code_commit(tmp_path)
    assert 7 <= len(sha) <= 40
    assert all(c in "0123456789abcdef" for c in sha)
