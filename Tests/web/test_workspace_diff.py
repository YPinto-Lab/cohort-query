from pathlib import Path

from web.workspace_diff import snapshot, diff, ChangedFile


def _touch(path: Path, text: str = "x") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def test_diff_reports_created_and_modified_tagged_by_kind(tmp_path):
    _touch(tmp_path / "1_build" / "build.py")
    before = snapshot(tmp_path)

    # create a biom, modify the existing py
    _touch(tmp_path / "1_build" / "feature_table.biom")
    _touch(tmp_path / "1_build" / "build.py", "changed")

    changed = diff(before, snapshot(tmp_path))

    assert ChangedFile("1_build/feature_table.biom", "biom") in changed
    assert ChangedFile("1_build/build.py", "py") in changed


def test_diff_ignores_unchanged_files(tmp_path):
    _touch(tmp_path / "notes.txt")
    before = snapshot(tmp_path)
    after = snapshot(tmp_path)
    assert diff(before, after) == []


def test_diff_tags_other_kind(tmp_path):
    before = snapshot(tmp_path)
    _touch(tmp_path / "results" / "out.csv")
    changed = diff(before, snapshot(tmp_path))
    assert ChangedFile("results/out.csv", "other") in changed
