# Thin Web Shell Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the MVP web UI — a thin shell over the existing FastAPI skeleton with two surfaces, a chat that drives the agent and a biom viewer, while delegating code reading/editing/running/results to the user's own apps.

**Architecture:** Extend `src/web` (FastAPI + Jinja + htmx + SSE). Four new backend modules with clear single responsibilities (`biom_view`, `workspace_diff`, `biom_index`, `os_open`), a handful of new routes in `app.py`, and rewritten/added templates for the dark two-column shell. Big matrices are windowed server-side; nothing else is rebuilt that the user's own tools already do.

**Tech Stack:** Python 3.12, FastAPI, Jinja2, htmx 1.9, `biom`, `pandas`, pytest + `fastapi.testclient.TestClient`.

**Spec:** `Docs/superpowers/specs/2026-06-05-thin-web-shell-design.html`

---

## File Structure

**New backend modules (`src/web/`):**
- `workspace_diff.py` — snapshot a workspace's files by mtime; diff two snapshots into a tagged files-changed list. Pure functions, no I/O beyond `stat`.
- `biom_view.py` — load a `.biom` (mtime-cached) and return a windowed slice of one of three views (Counts / Samples / Lineage) as a `TableWindow`.
- `biom_index.py` — walk a workspace for `.biom` files, group them under their phase (build/transform/analyze) with shape labels → a `BiomTree`.
- `os_open.py` — open a filesystem path in the OS default app, with a path-string fallback when no handler exists.

**Changed backend:**
- `src/askslm/cli.py` — `workspace_new` gains an optional `root` parameter so the web layer can scaffold into `WORKSPACES_ROOT`.
- `src/web/app.py` — new routes: `POST /workspaces`, `POST /w/{ws}/open`, `GET /w/{ws}/biom`, `GET /w/{ws}/biom/table`; extend `POST /w/{ws}/messages` to append a files-changed fragment; `GET /` and `GET /w/{ws}` render the new templates.

**New / rewritten templates (`src/web/templates/`):**
- `home.html` (rewrite) — workspace cards + create form.
- `chat.html` (rewrite) — dark two-column shell + streaming JS.
- `_files.html` (new) — files-changed list fragment.
- `_biom.html` (new) — viewer shell (tree + tabs + initial table).
- `_biom_tree.html` (new) — collapsible phase tree + filter.
- `_biom_table.html` (new) — one windowed table fragment (banner + grid + pagers).

**Tests (`Tests/web/`):**
- `test_workspace_diff.py`, `test_biom_view.py`, `test_biom_index.py`, `test_os_open.py`, and additions to `test_app.py`.

---

## Task 1: workspace_diff — detect files an agent turn touched

**Files:**
- Create: `src/web/workspace_diff.py`
- Test: `Tests/web/test_workspace_diff.py`

- [ ] **Step 1: Write the failing test**

```python
# Tests/web/test_workspace_diff.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest Tests/web/test_workspace_diff.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'web.workspace_diff'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/web/workspace_diff.py
"""Detect which workspace files an agent turn created or modified.

Pure functions: snapshot {relative-path: mtime} before a turn, snapshot again
after, diff into a list tagged by file kind. Decoupled from HOW the agent writes
files — it only observes the filesystem.
"""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ChangedFile:
    path: str   # workspace-relative, forward slashes
    kind: str   # "py" | "biom" | "other"


def snapshot(root: Path) -> dict[str, float]:
    out: dict[str, float] = {}
    for p in root.rglob("*"):
        if p.is_file():
            out[p.relative_to(root).as_posix()] = p.stat().st_mtime
    return out


def diff(before: dict[str, float], after: dict[str, float]) -> list[ChangedFile]:
    changed: list[ChangedFile] = []
    for path, mtime in sorted(after.items()):
        if before.get(path) != mtime:
            changed.append(ChangedFile(path, _kind(path)))
    return changed


def _kind(path: str) -> str:
    if path.endswith(".biom"):
        return "biom"
    if path.endswith(".py"):
        return "py"
    return "other"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest Tests/web/test_workspace_diff.py -q`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add src/web/workspace_diff.py Tests/web/test_workspace_diff.py
git commit -m "feat(web): workspace_diff — tagged files-changed detection"
```

---

## Task 2: biom_view — windowed Counts / Samples / Lineage views

**Files:**
- Create: `src/web/biom_view.py`
- Test: `Tests/web/test_biom_view.py`

**Context for the implementer:** A `biom.Table` is `observations (features) × samples`. `table.ids(axis="observation")` / `table.ids(axis="sample")` return id arrays (numpy str). `table.metadata(axis=...)` returns a tuple of per-id dicts aligned to those ids (or `None`). Feature metadata looks like `{"name": "Bacteria", "rank": "domain", "lineage": [1, 2]}`; sample metadata is a wide flat dict. We never merge feature and sample metadata — they are separate views (project rule).

- [ ] **Step 1: Write the failing test**

```python
# Tests/web/test_biom_view.py
from pathlib import Path

import numpy as np
from biom import Table

from web.biom_view import counts_window, samples_window, lineage_window


def _fixture_biom(path: Path) -> Path:
    data = np.array([
        [0, 12, 3, 0, 5],
        [5, 0, 9, 1, 0],
        [0, 7, 1, 0, 2],
    ], dtype=float)
    obs_ids = ["f1", "f2", "f3"]
    sample_ids = ["S1", "S2", "S3", "S4", "S5"]
    obs_md = [
        {"name": "Bacteria", "rank": "domain", "lineage": [1, 2]},
        {"name": "Firmicutes", "rank": "phylum", "lineage": [1, 2, 3]},
        {"name": "E. coli", "rank": "species", "lineage": [1, 2, 4]},
    ]
    sample_md = [
        {"subject": "A", "day": 1},
        {"subject": "A", "day": 2},
        {"subject": "B", "day": 1},
        {"subject": "B", "day": 2},
        {"subject": "C", "day": 1},
    ]
    table = Table(data, obs_ids, sample_ids,
                  observation_metadata=obs_md, sample_metadata=sample_md)
    path.write_text(table.to_json("test"))
    return path


def test_counts_window_full(tmp_path):
    p = _fixture_biom(tmp_path / "t.biom")
    w = counts_window(p)
    assert w.index == ["f1", "f2", "f3"]
    assert w.columns == ["S1", "S2", "S3", "S4", "S5"]
    assert w.rows[0] == [0, 12, 3, 0, 5]
    assert w.total_rows == 3 and w.total_cols == 5


def test_counts_window_paginates_rows_and_cols(tmp_path):
    p = _fixture_biom(tmp_path / "t.biom")
    w = counts_window(p, row_off=1, col_off=2, row_page=1, col_page=2)
    assert w.index == ["f2"]
    assert w.columns == ["S3", "S4"]
    assert w.rows == [[9, 1]]
    assert w.row_offset == 1 and w.col_offset == 2
    assert w.total_rows == 3 and w.total_cols == 5


def test_samples_window_is_metadata_table(tmp_path):
    p = _fixture_biom(tmp_path / "t.biom")
    w = samples_window(p)
    assert w.index == ["S1", "S2", "S3", "S4", "S5"]
    assert "subject" in w.columns and "day" in w.columns
    assert w.total_rows == 5


def test_lineage_window_is_feature_metadata_table(tmp_path):
    p = _fixture_biom(tmp_path / "t.biom")
    w = lineage_window(p)
    assert w.index == ["f1", "f2", "f3"]
    assert "name" in w.columns and "rank" in w.columns
    # nested values are stringified, not merged with sample metadata
    name_col = w.columns.index("name")
    assert w.rows[0][name_col] == "Bacteria"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest Tests/web/test_biom_view.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'web.biom_view'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/web/biom_view.py
"""Load a .biom and return a windowed slice of one of its three views.

Counts  = features (rows) x samples (cols) count matrix.
Samples = per-sample metadata table (sample id x metadata fields).
Lineage = per-feature metadata table (feature id x taxonomy fields).

Feature and sample metadata are kept as SEPARATE views — never merged.
Tables are large (tens of thousands of features), so callers always page;
the loaded table is cached by (path, mtime) to make paging cheap.
"""
from __future__ import annotations
import json
from dataclasses import dataclass
from pathlib import Path

from biom import Table, load_table

ROW_PAGE = 100
COL_PAGE = 60

_CACHE: dict[tuple[str, float], Table] = {}


@dataclass(frozen=True)
class TableWindow:
    index: list[str]          # row labels (feature or sample ids)
    columns: list[str]        # column labels
    rows: list[list]          # cell values, row-major, aligned to columns
    total_rows: int
    total_cols: int
    row_offset: int
    col_offset: int
    row_page: int
    col_page: int


def _load(path: Path) -> Table:
    key = (str(path), path.stat().st_mtime)
    table = _CACHE.get(key)
    if table is None:
        table = load_table(str(path))
        _CACHE[key] = table
    return table


def counts_window(path: Path, row_off: int = 0, col_off: int = 0,
                  row_page: int = ROW_PAGE, col_page: int = COL_PAGE) -> TableWindow:
    table = _load(path)
    obs_ids = [str(i) for i in table.ids(axis="observation")]
    sample_ids = [str(i) for i in table.ids(axis="sample")]
    row_ids = obs_ids[row_off:row_off + row_page]
    col_ids = sample_ids[col_off:col_off + col_page]

    sub = (table.filter(row_ids, axis="observation", inplace=False)
                .filter(col_ids, axis="sample", inplace=False))
    frame = sub.to_dataframe(dense=True).reindex(index=row_ids, columns=col_ids)

    return TableWindow(
        index=row_ids,
        columns=col_ids,
        rows=[[_num(v) for v in row] for row in frame.to_numpy().tolist()],
        total_rows=len(obs_ids),
        total_cols=len(sample_ids),
        row_offset=row_off,
        col_offset=col_off,
        row_page=row_page,
        col_page=col_page,
    )


def samples_window(path: Path, row_off: int = 0, row_page: int = ROW_PAGE) -> TableWindow:
    return _metadata_window(path, "sample", row_off, row_page)


def lineage_window(path: Path, row_off: int = 0, row_page: int = ROW_PAGE) -> TableWindow:
    return _metadata_window(path, "observation", row_off, row_page)


def _metadata_window(path: Path, axis: str, row_off: int, row_page: int) -> TableWindow:
    table = _load(path)
    all_ids = [str(i) for i in table.ids(axis=axis)]
    metadata = table.metadata(axis=axis)
    window_ids = all_ids[row_off:row_off + row_page]

    records: list[dict] = []
    columns: list[str] = []
    for pos in range(row_off, min(row_off + row_page, len(all_ids))):
        record = {} if metadata is None else {k: _scalar(v) for k, v in dict(metadata[pos]).items()}
        records.append(record)
        for key in record:
            if key not in columns:
                columns.append(key)

    rows = [[rec.get(col, "") for col in columns] for rec in records]
    return TableWindow(
        index=window_ids,
        columns=columns,
        rows=rows,
        total_rows=len(all_ids),
        total_cols=len(columns),
        row_offset=row_off,
        col_offset=0,
        row_page=row_page,
        col_page=row_page,
    )


def _num(value):
    number = float(value)
    return int(number) if number.is_integer() else number


def _scalar(value):
    if isinstance(value, (list, dict, tuple)):
        return json.dumps(value, default=str)
    return value
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest Tests/web/test_biom_view.py -q`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add src/web/biom_view.py Tests/web/test_biom_view.py
git commit -m "feat(web): biom_view — windowed counts/samples/lineage views"
```

---

## Task 3: biom_index — enumerate a workspace's .biom outputs as a phase tree

**Files:**
- Create: `src/web/biom_index.py`
- Test: `Tests/web/test_biom_index.py`

**Context:** Shape is read from the biom JSON `"shape"` field (`[n_features, n_samples]`) — much cheaper than fully loading a multi-MB table just to label the tree.

- [ ] **Step 1: Write the failing test**

```python
# Tests/web/test_biom_index.py
from pathlib import Path

import numpy as np
from biom import Table

from web.biom_index import biom_tree


def _write_biom(path: Path, n_obs: int, n_samp: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = np.ones((n_obs, n_samp), dtype=float)
    obs = [f"f{i}" for i in range(n_obs)]
    samp = [f"S{i}" for i in range(n_samp)]
    path.write_text(Table(data, obs, samp).to_json("test"))


def test_tree_groups_biom_by_phase_with_shape(tmp_path):
    _write_biom(tmp_path / "1_build" / "feature_table.biom", 3, 4)
    _write_biom(tmp_path / "2_transform" / "no-control" / "result" / "feature_table.biom", 2, 4)
    _write_biom(tmp_path / "3_analyze" / "no-control" / "braycurtis" / "data" / "braycurtis.biom", 4, 4)

    tree = biom_tree(tmp_path)
    phases = {group.phase: group for group in tree}

    assert phases["build"].entries[0].rel_path == "1_build/feature_table.biom"
    assert phases["build"].entries[0].shape == (3, 4)
    assert phases["transform"].entries[0].label == "no-control"
    assert phases["analyze"].entries[0].rel_path.endswith("braycurtis.biom")


def test_tree_skips_phases_with_no_biom(tmp_path):
    _write_biom(tmp_path / "1_build" / "feature_table.biom", 1, 1)
    tree = biom_tree(tmp_path)
    assert [group.phase for group in tree] == ["build"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest Tests/web/test_biom_index.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'web.biom_index'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/web/biom_index.py
"""Enumerate a workspace's .biom outputs, grouped by phase, for the viewer tree.

build -> 1_build/feature_table.biom
transform -> 2_transform/<exploration>/result/feature_table.biom
analyze -> 3_analyze/<exploration>/<analysis>/data/*.biom
Shape comes from the biom JSON header (cheap), not a full table load.
"""
from __future__ import annotations
import json
from dataclasses import dataclass
from pathlib import Path

_PHASE_DIRS = [("1_build", "build"), ("2_transform", "transform"), ("3_analyze", "analyze")]


@dataclass(frozen=True)
class BiomEntry:
    label: str           # human label (exploration / analysis / file stem)
    rel_path: str        # workspace-relative, forward slashes
    shape: tuple[int, int]   # (features, samples)


@dataclass(frozen=True)
class BiomGroup:
    phase: str
    entries: list[BiomEntry]


def biom_tree(root: Path) -> list[BiomGroup]:
    groups: list[BiomGroup] = []
    for folder, phase in _PHASE_DIRS:
        phase_dir = root / folder
        if not phase_dir.is_dir():
            continue
        entries = [_entry(root, p) for p in sorted(phase_dir.rglob("*.biom"))]
        if entries:
            groups.append(BiomGroup(phase=phase, entries=entries))
    return groups


def _entry(root: Path, path: Path) -> BiomEntry:
    rel = path.relative_to(root)
    shape = _shape(path)
    return BiomEntry(label=_label(rel), rel_path=rel.as_posix(), shape=shape)


def _label(rel: Path) -> str:
    # transform/analyze: name the exploration; otherwise the file stem.
    parts = rel.parts
    if parts[0] == "2_transform" and len(parts) >= 2:
        return parts[1]
    if parts[0] == "3_analyze" and len(parts) >= 3:
        return f"{parts[1]} · {parts[2]}"
    return rel.stem


def _shape(path: Path) -> tuple[int, int]:
    try:
        shape = json.loads(path.read_text())["shape"]
        return (int(shape[0]), int(shape[1]))
    except Exception:
        return (0, 0)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest Tests/web/test_biom_index.py -q`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add src/web/biom_index.py Tests/web/test_biom_index.py
git commit -m "feat(web): biom_index — workspace .biom outputs as a phase tree"
```

---

## Task 4: os_open — open a path in the user's default app

**Files:**
- Create: `src/web/os_open.py`
- Test: `Tests/web/test_os_open.py`

- [ ] **Step 1: Write the failing test**

```python
# Tests/web/test_os_open.py
from pathlib import Path

from web import os_open


def test_open_path_invokes_launcher_and_reports_ok(tmp_path, monkeypatch):
    target = tmp_path / "file.py"
    target.write_text("x")
    calls = []
    monkeypatch.setattr(os_open, "_launch", lambda p: calls.append(p))

    result = os_open.open_path(target)

    assert result["ok"] is True
    assert calls == [target]
    assert result["path"] == str(target)


def test_open_path_falls_back_to_path_on_failure(tmp_path, monkeypatch):
    target = tmp_path / "file.py"
    target.write_text("x")

    def _boom(_p):
        raise OSError("no handler")

    monkeypatch.setattr(os_open, "_launch", _boom)

    result = os_open.open_path(target)

    assert result["ok"] is False
    assert result["path"] == str(target)
    assert "no handler" in result["error"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest Tests/web/test_os_open.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'web.os_open'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/web/os_open.py
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest Tests/web/test_os_open.py -q`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add src/web/os_open.py Tests/web/test_os_open.py
git commit -m "feat(web): os_open — open paths in the user's default app"
```

---

## Task 5: workspace create — refactor CLI + POST /workspaces route

**Files:**
- Modify: `src/askslm/cli.py:78-84` (`workspace_new`)
- Modify: `src/web/app.py` (add `POST /workspaces`)
- Test: `Tests/web/test_app.py` (append)

- [ ] **Step 1: Write the failing test**

```python
# append to Tests/web/test_app.py
def test_create_workspace_scaffolds_and_redirects(tmp_path, monkeypatch):
    from web import app as app_mod
    monkeypatch.setattr(app_mod, "WORKSPACES_ROOT", tmp_path)
    client = TestClient(app_mod.app)

    r = client.post("/workspaces", data={"name": "NewStudy"}, follow_redirects=False)

    assert r.status_code in (302, 303)
    assert r.headers["location"] == "/w/NewStudy"
    assert (tmp_path / "NewStudy" / "1_build" / "build.py").is_file()


def test_create_workspace_rejects_unsafe_name(tmp_path, monkeypatch):
    from web import app as app_mod
    monkeypatch.setattr(app_mod, "WORKSPACES_ROOT", tmp_path)
    client = TestClient(app_mod.app)
    r = client.post("/workspaces", data={"name": "../escape"})
    assert r.status_code == 400
    assert not (tmp_path.parent / "escape").exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest Tests/web/test_app.py -k create -q`
Expected: FAIL — 404/405 (route does not exist yet)

- [ ] **Step 3a: Let `workspace_new` target a chosen root**

In `src/askslm/cli.py`, replace the `workspace_new` function (currently lines 78-84):

```python
def workspace_new(name: str, root: Path = WORKSPACES) -> None:
    base = root / name
    _write(base / "0_inputs" / ".keep", "")
    _write(base / "1_build" / "build.py", BUILD_PY)
    _write(base / "1_build" / "build.md", BUILD_MD)
    _write(base / "2_transform" / "shared.py", SHARED_STUB.format(phase="transform"))
    _write(base / "3_analyze" / "shared.py", SHARED_STUB.format(phase="analyze"))
```

- [ ] **Step 3b: Add the create route**

In `src/web/app.py`, add the import near the other agent/web imports (top of file):

```python
from askslm.cli import workspace_new
from fastapi.responses import RedirectResponse
```

Then add this route (place it after the `index` route):

```python
@app.post("/workspaces")
def create_workspace(name: str = Form(...)):
    safe = name.strip()
    if not safe or "/" in safe or "\\" in safe or safe.startswith("."):
        raise HTTPException(status_code=400, detail="invalid workspace name")
    workspace_new(safe, root=WORKSPACES_ROOT)
    return RedirectResponse(url=f"/w/{safe}", status_code=303)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest Tests/web/test_app.py -k create -q`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add src/askslm/cli.py src/web/app.py Tests/web/test_app.py
git commit -m "feat(web): create workspaces via POST /workspaces (CLI reuse)"
```

---

## Task 6: biom table fragment — GET /w/{ws}/biom/table + _biom_table.html

**Files:**
- Modify: `src/web/app.py` (add path guard helper + route)
- Create: `src/web/templates/_biom_table.html`
- Test: `Tests/web/test_app.py` (append)

- [ ] **Step 1: Write the failing test**

```python
# append to Tests/web/test_app.py
def _ws_with_biom(tmp_path):
    import numpy as np
    from biom import Table
    root = tmp_path / "ABX"
    (root / "1_build").mkdir(parents=True)
    data = np.array([[0, 12, 3], [5, 0, 9]], dtype=float)
    table = Table(data, ["f1", "f2"], ["S1", "S2", "S3"],
                  observation_metadata=[{"name": "Bacteria"}, {"name": "E. coli"}],
                  sample_metadata=[{"subject": "A"}, {"subject": "B"}, {"subject": "C"}])
    (root / "1_build" / "feature_table.biom").write_text(table.to_json("t"))
    return root


def test_biom_table_counts_fragment_renders_cells_and_banner(tmp_path, monkeypatch):
    from web import app as app_mod
    monkeypatch.setattr(app_mod, "WORKSPACES_ROOT", tmp_path)
    _ws_with_biom(tmp_path)
    client = TestClient(app_mod.app)
    r = client.get("/w/ABX/biom/table",
                   params={"path": "1_build/feature_table.biom", "tab": "counts"})
    assert r.status_code == 200
    assert "f1" in r.text and "S1" in r.text and "12" in r.text
    assert "of 2" in r.text  # banner mentions total features


def test_biom_table_rejects_path_outside_workspace(tmp_path, monkeypatch):
    from web import app as app_mod
    monkeypatch.setattr(app_mod, "WORKSPACES_ROOT", tmp_path)
    _ws_with_biom(tmp_path)
    client = TestClient(app_mod.app)
    r = client.get("/w/ABX/biom/table",
                   params={"path": "../secret.biom", "tab": "counts"})
    assert r.status_code == 404
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest Tests/web/test_app.py -k biom_table -q`
Expected: FAIL — 404/405 (route not defined)

- [ ] **Step 3a: Add a path guard + route in `src/web/app.py`**

Add imports near the top:

```python
from web import biom_view
```

Add this helper after `_safe_session_path`:

```python
def _safe_biom_path(ws_dir: Path, rel: str) -> Path:
    candidate = (ws_dir / rel).resolve()
    if not candidate.is_relative_to(ws_dir.resolve()) or not candidate.is_file():
        raise HTTPException(status_code=404, detail="biom not found")
    return candidate


def _table_window(path: Path, tab: str, row_off: int, col_off: int):
    if tab == "samples":
        return biom_view.samples_window(path, row_off=row_off)
    if tab == "lineage":
        return biom_view.lineage_window(path, row_off=row_off)
    return biom_view.counts_window(path, row_off=row_off, col_off=col_off)
```

Add the route:

```python
@app.get("/w/{workspace}/biom/table", response_class=HTMLResponse)
def biom_table(workspace: str, request: Request, path: str,
               tab: str = "counts", row_off: int = 0, col_off: int = 0):
    ws_dir = _safe_workspace_dir(workspace)
    biom_path = _safe_biom_path(ws_dir, path)
    window = _table_window(biom_path, tab, row_off, col_off)
    return templates.TemplateResponse(request, "_biom_table.html", {
        "workspace": workspace, "path": path, "tab": tab, "w": window,
    })
```

- [ ] **Step 3b: Create the fragment template**

```html
<!-- src/web/templates/_biom_table.html -->
<div id="biom-table">
  <div class="banner">
    Showing <b>features {{ w.row_offset + 1 }}–{{ w.row_offset + w.index|length }}
    of {{ w.total_rows }}</b>{% if tab == "counts" %} and
    <b>samples {{ w.col_offset + 1 }}–{{ w.col_offset + w.columns|length }}
    of {{ w.total_cols }}</b>{% endif %}.
    Open the .biom in your own tools for the full matrix.
  </div>
  <div class="scrollbox">
    <table class="data">
      <thead><tr><th class="lab">{{ "feature" if tab != "samples" else "sample" }}</th>
        {% for col in w.columns %}<th>{{ col }}</th>{% endfor %}
      </tr></thead>
      <tbody>
        {% for label in w.index %}
        <tr><td class="lab">{{ label }}</td>
          {% for cell in w.rows[loop.index0] %}
          <td class="{{ 'zero' if cell == 0 else '' }}">{{ cell }}</td>
          {% endfor %}
        </tr>
        {% endfor %}
      </tbody>
    </table>
  </div>
  <div class="pagers">
    <span class="pg">rows <b>{{ w.row_offset + 1 }}–{{ w.row_offset + w.index|length }} / {{ w.total_rows }}</b>
      <button hx-get="/w/{{ workspace }}/biom/table?path={{ path|urlencode }}&tab={{ tab }}&row_off={{ [w.row_offset - w.row_page, 0]|max }}&col_off={{ w.col_offset }}"
              hx-target="#biom-table" hx-swap="outerHTML" {{ 'disabled' if w.row_offset == 0 else '' }}>‹</button>
      <button hx-get="/w/{{ workspace }}/biom/table?path={{ path|urlencode }}&tab={{ tab }}&row_off={{ w.row_offset + w.row_page }}&col_off={{ w.col_offset }}"
              hx-target="#biom-table" hx-swap="outerHTML" {{ 'disabled' if w.row_offset + w.row_page >= w.total_rows else '' }}>›</button>
    </span>
    {% if tab == "counts" %}
    <span class="pg">cols <b>{{ w.col_offset + 1 }}–{{ w.col_offset + w.columns|length }} / {{ w.total_cols }}</b>
      <button hx-get="/w/{{ workspace }}/biom/table?path={{ path|urlencode }}&tab={{ tab }}&row_off={{ w.row_offset }}&col_off={{ [w.col_offset - w.col_page, 0]|max }}"
              hx-target="#biom-table" hx-swap="outerHTML" {{ 'disabled' if w.col_offset == 0 else '' }}>‹</button>
      <button hx-get="/w/{{ workspace }}/biom/table?path={{ path|urlencode }}&tab={{ tab }}&row_off={{ w.row_offset }}&col_off={{ w.col_offset + w.col_page }}"
              hx-target="#biom-table" hx-swap="outerHTML" {{ 'disabled' if w.col_offset + w.col_page >= w.total_cols else '' }}>›</button>
    </span>
    {% endif %}
  </div>
</div>
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest Tests/web/test_app.py -k biom_table -q`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add src/web/app.py src/web/templates/_biom_table.html Tests/web/test_app.py
git commit -m "feat(web): windowed biom table fragment route + template"
```

---

## Task 7: viewer shell — GET /w/{ws}/biom + tree/tabs templates

**Files:**
- Modify: `src/web/app.py` (add route)
- Create: `src/web/templates/_biom_tree.html`, `src/web/templates/_biom.html`
- Test: `Tests/web/test_app.py` (append)

- [ ] **Step 1: Write the failing test**

```python
# append to Tests/web/test_app.py
def test_biom_shell_shows_tabs_tree_and_initial_table(tmp_path, monkeypatch):
    from web import app as app_mod
    monkeypatch.setattr(app_mod, "WORKSPACES_ROOT", tmp_path)
    _ws_with_biom(tmp_path)
    client = TestClient(app_mod.app)
    r = client.get("/w/ABX/biom", params={"path": "1_build/feature_table.biom"})
    assert r.status_code == 200
    assert "Counts" in r.text and "Samples" in r.text and "Lineage" in r.text
    assert "feature_table" in r.text          # tree entry
    assert "12" in r.text                       # initial counts table rendered inline
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest Tests/web/test_app.py -k biom_shell -q`
Expected: FAIL — 404 (route not defined)

- [ ] **Step 3a: Add the route in `src/web/app.py`**

Add import near the top:

```python
from web import biom_index
```

Add the route:

```python
@app.get("/w/{workspace}/biom", response_class=HTMLResponse)
def biom_shell(workspace: str, request: Request, path: str, tab: str = "counts"):
    ws_dir = _safe_workspace_dir(workspace)
    biom_path = _safe_biom_path(ws_dir, path)
    window = _table_window(biom_path, tab, 0, 0)
    return templates.TemplateResponse(request, "_biom.html", {
        "workspace": workspace, "path": path, "tab": tab, "w": window,
        "tree": biom_index.biom_tree(ws_dir),
    })
```

- [ ] **Step 3b: Create the tree template**

```html
<!-- src/web/templates/_biom_tree.html -->
<div class="rail" id="biom-tree">
  <div class="pane-h"><span>biom outputs</span>
    <span class="toggle" onclick="document.getElementById('data-pane').classList.toggle('tree-collapsed')">⟨</span>
  </div>
  <input class="filter" placeholder="🔍 filter…" oninput="filterTree(this.value)">
  <div class="tree">
    {% for group in tree %}
    <div class="node l1">▾ {{ group.phase }}</div>
    {% for entry in group.entries %}
    <div class="node l2 biom {{ 'cur' if entry.rel_path == path else '' }}"
         data-label="{{ entry.label|lower }}"
         hx-get="/w/{{ workspace }}/biom/table?path={{ entry.rel_path|urlencode }}&tab={{ tab }}"
         hx-target="#biom-table" hx-swap="outerHTML"
         onclick="setCurrent(this)">
      {{ entry.label }} <span class="shape">{{ entry.shape[0] }}×{{ entry.shape[1] }}</span>
    </div>
    {% endfor %}
    {% endfor %}
  </div>
</div>
```

- [ ] **Step 3c: Create the viewer shell template**

```html
<!-- src/web/templates/_biom.html -->
<div id="data-pane" class="data-pane">
  {% include "_biom_tree.html" %}
  <div class="viewer-main">
    <div class="tabs">
      {% for t in ["counts", "samples", "lineage"] %}
      <div class="t {{ 'on' if t == tab else '' }}"
           hx-get="/w/{{ workspace }}/biom/table?path={{ path|urlencode }}&tab={{ t }}"
           hx-target="#biom-table" hx-swap="outerHTML"
           onclick="setActiveTab(this)">{{ t|capitalize }}</div>
      {% endfor %}
    </div>
    {% include "_biom_table.html" %}
  </div>
</div>
<script>
  function filterTree(q) {
    q = q.toLowerCase();
    document.querySelectorAll('#biom-tree .node.l2').forEach(function (n) {
      n.style.display = n.dataset.label.indexOf(q) === -1 ? 'none' : '';
    });
  }
  function setCurrent(el) {
    document.querySelectorAll('#biom-tree .node.cur').forEach(function (n) { n.classList.remove('cur'); });
    el.classList.add('cur');
  }
  function setActiveTab(el) {
    document.querySelectorAll('.tabs .t.on').forEach(function (n) { n.classList.remove('on'); });
    el.classList.add('on');
  }
</script>
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest Tests/web/test_app.py -k biom_shell -q`
Expected: PASS (1 passed)

- [ ] **Step 5: Commit**

```bash
git add src/web/app.py src/web/templates/_biom_tree.html src/web/templates/_biom.html Tests/web/test_app.py
git commit -m "feat(web): biom viewer shell — collapsible tree + tabs"
```

---

## Task 8: files-changed + open-in-app — extend messages route, add open route

**Files:**
- Modify: `src/web/app.py` (extend `messages`, add `POST /w/{ws}/open`)
- Create: `src/web/templates/_files.html`
- Test: `Tests/web/test_app.py` (append)

- [ ] **Step 1: Write the failing test**

```python
# append to Tests/web/test_app.py
def test_messages_appends_files_changed_block(tmp_path, monkeypatch):
    from web import app as app_mod
    from agent.llm_client import FakeLLMClient, AssistantText
    monkeypatch.setattr(app_mod, "WORKSPACES_ROOT", tmp_path)
    monkeypatch.setattr(app_mod, "build_llm",
                        lambda: FakeLLMClient([[AssistantText(text="done")]]))
    _ws(tmp_path)

    # Simulate a file appearing during the turn: snapshot() (bound in app via
    # `from web.workspace_diff import snapshot`) returns empty before, one file after.
    snapshots = iter([{}, {"1_build/build.py": 1.0}])
    monkeypatch.setattr(app_mod, "snapshot", lambda _root: next(snapshots))

    client = TestClient(app_mod.app)
    client.get("/w/ABX")
    r = client.post("/w/ABX/messages", data={"message": "build it"})
    assert r.status_code == 200
    assert "files changed" in r.text.lower()
    assert "build.py" in r.text


def test_open_route_rejects_path_outside_workspace(tmp_path, monkeypatch):
    from web import app as app_mod
    monkeypatch.setattr(app_mod, "WORKSPACES_ROOT", tmp_path)
    _ws(tmp_path)
    client = TestClient(app_mod.app)
    r = client.post("/w/ABX/open", data={"path": "../../etc/passwd"})
    assert r.status_code == 404


def test_open_route_opens_file_inside_workspace(tmp_path, monkeypatch):
    from web import app as app_mod
    from web import os_open
    monkeypatch.setattr(app_mod, "WORKSPACES_ROOT", tmp_path)
    root = _ws(tmp_path)
    (root / "1_build").mkdir(parents=True, exist_ok=True)
    (root / "1_build" / "build.py").write_text("x")
    monkeypatch.setattr(os_open, "_launch", lambda p: None)
    client = TestClient(app_mod.app)
    r = client.post("/w/ABX/open", data={"path": "1_build/build.py"})
    assert r.status_code == 200
    assert r.json()["ok"] is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest Tests/web/test_app.py -k "files_changed or open_route" -q`
Expected: FAIL — files-changed block / open route missing

- [ ] **Step 3a: Extend the `messages` route in `src/web/app.py`**

Add imports near the top:

```python
from web import os_open
from web.workspace_diff import snapshot, diff
```

Replace the `event_stream` body inside `messages` so it snapshots around the turn and appends a files-changed fragment:

```python
    def event_stream() -> Iterator[bytes]:
        before = snapshot(ws_dir)
        for ev in agent.chat(message):
            data = json.dumps({"type": ev.type, **ev.payload})
            yield f"event: {ev.type}\ndata: {data}\n\n".encode()
            html = templates.get_template("_event.html").render(event=ev)
            yield f"event: html\ndata: {html}\n\n".encode()
        changed = diff(before, snapshot(ws_dir))
        if changed:
            files_html = templates.get_template("_files.html").render(
                workspace=workspace, changed=changed)
            yield f"event: html\ndata: {files_html}\n\n".encode()
```

- [ ] **Step 3b: Add the open route**

```python
@app.post("/w/{workspace}/open")
def open_in_app(workspace: str, path: str = Form(...)):
    ws_dir = _safe_workspace_dir(workspace)
    candidate = (ws_dir / path).resolve()
    if not candidate.is_relative_to(ws_dir.resolve()) or not candidate.exists():
        raise HTTPException(status_code=404, detail="path not found")
    return os_open.open_path(candidate)
```

- [ ] **Step 3c: Create the files-changed fragment**

```html
<!-- src/web/templates/_files.html -->
<div class="files">
  <div class="hd">files changed</div>
  {% for f in changed %}
  <div class="frow {{ f.kind }}">
    <span class="p">{{ f.path }}</span>
    {% if f.kind == "biom" %}
    <span class="pill view"
          hx-get="/w/{{ workspace }}/biom?path={{ f.path|urlencode }}"
          hx-target="#data-pane" hx-swap="outerHTML">view →</span>
    {% else %}
    <span class="pill open"
          hx-post="/w/{{ workspace }}/open" hx-vals='{"path": "{{ f.path }}"}'
          hx-swap="none">open ↗</span>
    {% endif %}
  </div>
  {% endfor %}
</div>
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest Tests/web/test_app.py -k "files_changed or open_route" -q`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add src/web/app.py src/web/templates/_files.html Tests/web/test_app.py
git commit -m "feat(web): files-changed fragment + open-in-app route"
```

---

## Task 9: the two-column shell + home page templates

**Files:**
- Rewrite: `src/web/templates/home.html` (the index template — note `index` route renders `index.html`; we rename to `home.html` and update the route)
- Rewrite: `src/web/templates/chat.html`
- Modify: `src/web/app.py:57-63` (render `home.html`)
- Test: `Tests/web/test_app.py` (append render smoke checks)

**Context:** The current `index` route renders `index.html`. Rename the template to `home.html` and point the route at it. The chat page hosts the dark two-column layout and the streaming JS that consumes the SSE from `POST /w/{ws}/messages`, appending each `event: html` fragment to the chat log.

- [ ] **Step 1: Write the failing test**

```python
# append to Tests/web/test_app.py
def test_home_has_create_form_and_cards(tmp_path, monkeypatch):
    from web import app as app_mod
    monkeypatch.setattr(app_mod, "WORKSPACES_ROOT", tmp_path)
    _ws(tmp_path)
    client = TestClient(app_mod.app)
    r = client.get("/")
    assert r.status_code == 200
    assert 'action="/workspaces"' in r.text   # create form
    assert "ABX" in r.text                       # workspace card


def test_chat_page_has_two_panes(tmp_path, monkeypatch):
    from web import app as app_mod
    monkeypatch.setattr(app_mod, "WORKSPACES_ROOT", tmp_path)
    _ws(tmp_path)
    client = TestClient(app_mod.app)
    r = client.get("/w/ABX")
    assert r.status_code == 200
    assert 'id="log"' in r.text and 'id="data-pane"' in r.text
    assert "Open workspace folder" in r.text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest Tests/web/test_app.py -k "home_has or two_panes" -q`
Expected: FAIL — current templates lack these elements

- [ ] **Step 3a: Point the index route at `home.html`**

In `src/web/app.py`, in the `index` function, change the rendered template name from `"index.html"` to `"home.html"`.

- [ ] **Step 3b: Rewrite the home template**

```html
<!-- src/web/templates/home.html -->
<!doctype html><html><head><meta charset="utf-8"><title>Ask-SLM</title>
<style>
  body{margin:0;background:#0d1117;color:#e6edf3;font:15px/1.5 -apple-system,Segoe UI,Roboto,sans-serif}
  .bar{background:#161b22;border-bottom:1px solid #30363d;padding:10px 16px;font-weight:700}
  .wrap{padding:24px}
  h3{margin:0 0 4px}.sub{color:#8b949e;font-size:13px;margin-bottom:16px}
  .cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:12px}
  .card{background:#161b22;border:1px solid #30363d;border-radius:10px;padding:14px;text-decoration:none;color:#e6edf3}
  .card:hover{border-color:#4a90e2}.card .nm{font-weight:600}
  form.new{margin-top:18px;display:flex;gap:8px}
  form.new input{background:#0d1117;border:1px solid #30363d;color:#e6edf3;border-radius:6px;padding:7px 10px}
  form.new button{background:#238636;color:#fff;border:none;border-radius:6px;padding:7px 14px;cursor:pointer}
</style></head><body>
  <div class="bar">Ask-SLM</div>
  <div class="wrap">
    <h3>Your studies</h3>
    <div class="sub">Open a workspace to chat with the agent, or start a new one.</div>
    <div class="cards">
      {% for ws in workspaces %}
      <a class="card" href="/w/{{ ws }}"><div class="nm">{{ ws }}</div></a>
      {% endfor %}
    </div>
    <form class="new" method="post" action="/workspaces">
      <input name="name" placeholder="new-study-name" required>
      <button>＋ New workspace</button>
    </form>
  </div>
</body></html>
```

- [ ] **Step 3c: Rewrite the chat shell**

```html
<!-- src/web/templates/chat.html -->
<!doctype html><html><head><meta charset="utf-8"><title>{{ workspace }} · Ask-SLM</title>
<script src="https://unpkg.com/htmx.org@1.9.12"></script>
<style>
  body{margin:0;background:#0d1117;color:#e6edf3;font:14px/1.5 -apple-system,Segoe UI,Roboto,sans-serif}
  .topbar{background:#161b22;border-bottom:1px solid #30363d;padding:9px 12px;display:flex;align-items:center;gap:8px}
  .topbar .sp{flex:1}
  .topbar a{color:#8b949e;text-decoration:none}
  .ows{background:#21262d;border:1px solid #30363d;border-radius:6px;padding:4px 9px;cursor:pointer}
  .body{display:flex;height:calc(100vh - 40px)}
  .chat{width:40%;display:flex;flex-direction:column;border-right:1px solid #30363d}
  #log{flex:1;overflow:auto;padding:12px}
  .composer{border-top:1px solid #30363d;padding:10px;display:flex;gap:8px}
  .composer input{flex:1;background:#0d1117;border:1px solid #30363d;color:#e6edf3;border-radius:8px;padding:8px 10px}
  .composer button{background:#238636;color:#fff;border:none;border-radius:8px;padding:8px 16px;cursor:pointer}
  .data-pane{flex:1;display:flex}
  .data-pane.tree-collapsed .rail{width:26px;overflow:hidden}
  .rail{width:42%;background:#0b0e13;border-right:1px solid #30363d;overflow:auto}
  .viewer-main{flex:1;display:flex;flex-direction:column;overflow:hidden}
  .pane-h{font-size:9px;text-transform:uppercase;letter-spacing:.6px;color:#7d8590;padding:7px 10px;display:flex;justify-content:space-between}
  .toggle{cursor:pointer;border:1px solid #30363d;border-radius:5px;padding:0 6px}
  .filter{margin:6px 8px;width:calc(100% - 16px);background:#161b22;border:1px solid #30363d;border-radius:6px;padding:4px 7px;color:#e6edf3}
  .tree{font:11px ui-monospace,Menlo,monospace;color:#c9d1d9}
  .tree .node{padding:3px 8px;cursor:pointer;white-space:nowrap}
  .tree .node:hover{background:#161b22}.tree .l1{color:#e6edf3;font-weight:600}.tree .l2{padding-left:16px}
  .tree .biom{color:#e3a36a}.tree .cur{background:#1c2a1c}.tree .shape{color:#7d8590}
  .tabs{display:flex;gap:2px;padding:7px 10px 0}
  .t{font-size:11px;padding:5px 11px;border-radius:6px 6px 0 0;background:#161b22;color:#8b949e;border:1px solid #30363d;border-bottom:none;cursor:pointer}
  .t.on{background:#e3a36a;color:#161b22;font-weight:600}
  .banner{margin:8px 10px;background:#1a2230;border:1px solid #2c3a52;color:#9fb4d6;font-size:11px;border-radius:6px;padding:6px 9px}
  .scrollbox{margin:0 10px;border:1px solid #30363d;border-radius:6px;overflow:auto;flex:1}
  table.data{border-collapse:separate;border-spacing:0;font:11px ui-monospace,monospace;color:#c9d1d9}
  table.data th,table.data td{border-right:1px solid #21262d;border-bottom:1px solid #21262d;padding:4px 9px;text-align:right;white-space:nowrap}
  table.data thead th{position:sticky;top:0;background:#1b2129;color:#e3a36a;z-index:2}
  table.data .lab{position:sticky;left:0;background:#161b22;color:#e6edf3;text-align:left;font-weight:600;z-index:1}
  table.data thead th.lab{z-index:3}.zero{color:#484f58}
  .pagers{display:flex;gap:18px;padding:9px 12px;font-size:11px;color:#8b949e}
  .pagers button{border:1px solid #30363d;background:#161b22;color:#e6edf3;border-radius:5px;padding:2px 8px;cursor:pointer}
  .you{text-align:right;margin-bottom:8px}.you b{color:#1f6feb}
  .files{margin-top:8px;background:#161b22;border:1px solid #30363d;border-radius:8px;padding:8px 10px;font-size:11px}
  .files .hd{font-size:9px;text-transform:uppercase;color:#7d8590;margin-bottom:4px}
  .frow{display:flex;gap:6px;font-family:ui-monospace,monospace;padding:2px 0}.frow .p{flex:1}
  .frow.py .p,.frow.other .p{color:#58a6ff}.frow.biom .p{color:#e3a36a;font-weight:600}
  .pill{font-size:10px;padding:1px 7px;border-radius:9px;border:1px solid;cursor:pointer}
  .pill.open{background:#11233f;color:#58a6ff;border-color:#1f4a86}
  .pill.view{background:#3a2a14;color:#e3a36a;border-color:#6b4a22}
</style></head><body>
  <div class="topbar">
    <b>Ask-SLM</b> · <a href="/">studies</a> · {{ workspace }}
    <span class="sp"></span>
    <span class="ows" hx-post="/w/{{ workspace }}/open" hx-vals='{"path": "."}' hx-swap="none">📁 Open workspace folder</span>
  </div>
  <div class="body">
    <div class="chat">
      <div id="log"></div>
      <form class="composer" onsubmit="send(event)">
        <input id="msg" placeholder="Ask the agent…" autocomplete="off">
        <button>Send</button>
      </form>
    </div>
    <div id="data-pane" class="data-pane">
      <div class="rail"><div class="pane-h">biom outputs</div>
        <div class="tree" style="padding:10px;color:#5a626b">Click a .biom in “files changed” to view it.</div>
      </div>
      <div class="viewer-main"></div>
    </div>
  </div>
<script>
  const log = document.getElementById('log');
  function append(html){ const d=document.createElement('div'); d.innerHTML=html; log.appendChild(d); htmx.process(d); log.scrollTop=log.scrollHeight; }
  async function send(e){
    e.preventDefault();
    const input=document.getElementById('msg'); const message=input.value.trim();
    if(!message) return;
    append('<div class="you"><b>You:</b> '+message+'</div>'); input.value='';
    const res=await fetch('/w/{{ workspace }}/messages',{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},body:'message='+encodeURIComponent(message)});
    const reader=res.body.getReader(); const dec=new TextDecoder(); let buf='';
    while(true){ const {value,done}=await reader.read(); if(done) break; buf+=dec.decode(value,{stream:true});
      let i; while((i=buf.indexOf('\n\n'))>=0){ const block=buf.slice(0,i); buf=buf.slice(i+2);
        const lines=block.split('\n'); let ev='',data='';
        for(const ln of lines){ if(ln.startsWith('event:')) ev=ln.slice(6).trim(); else if(ln.startsWith('data:')) data=ln.slice(5).trim(); }
        if(ev==='html' && data) append(data);
      }
    }
  }
</script>
</body></html>
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest Tests/web/test_app.py -k "home_has or two_panes" -q`
Expected: PASS (2 passed)

- [ ] **Step 5: Remove the now-unused template and commit**

```bash
git rm src/web/templates/index.html
git add src/web/templates/home.html src/web/templates/chat.html src/web/app.py Tests/web/test_app.py
git commit -m "feat(web): dark two-column shell + workspace home page"
```

---

## Task 10: full-suite verification + docs

**Files:**
- Modify: `README.md`, `AGENTS.md` (note the web UI surfaces)
- Test: whole suite

- [ ] **Step 1: Run the full test suite**

Run: `python -m pytest Tests -q`
Expected: PASS (all tests green, including the pre-existing ones)

- [ ] **Step 2: Manual smoke (optional but recommended)**

Run: `uvicorn web.app:app --app-dir src` then open `http://127.0.0.1:8000`, create a workspace, send a message, click a `.biom` to view it, toggle the tree collapse, page the table.

- [ ] **Step 3: Update docs**

In `README.md`, under a short "Web UI" note, add:

```markdown
## Web UI

Run the thin web shell:

    uvicorn web.app:app --app-dir src

Open `http://127.0.0.1:8000`: pick or create a workspace, chat with the agent
(left), and view any `.biom` it produces (right). Code, plots, and CSVs open in
your own apps via the open/Open-workspace-folder buttons.
```

In `AGENTS.md`, under the `src/web/` bullet, append: `The UI is a thin shell — chat + biom viewer; code/plots/results open in the user's own apps.`

- [ ] **Step 4: Commit**

```bash
git add README.md AGENTS.md
git commit -m "docs: note the thin web shell (chat + biom viewer)"
```

- [ ] **Step 5: Open the PR**

```bash
git push -u origin feature-web-ui
gh pr create --base main --title "Thin web shell: chat + biom viewer" \
  --body "Implements Docs/superpowers/specs/2026-06-05-thin-web-shell-design.html. See Docs/superpowers/plans/2026-06-05-thin-web-shell.md."
```

Then stop — the user squash-merges through GitHub.

---

## Self-Review Notes

- **Spec coverage:** Goal/philosophy → Tasks 1–9; who-owns-each-job → delegation via open routes (Task 8) + spec; architecture/modules → Tasks 1–4; layout → Task 9; chat pane (collapsed code via `_event.html`, files-changed) → Task 8; data pane (tree+tabs, separate views) → Tasks 2,7; large-data windowing+banner+sticky scroll → Tasks 2,6,9; workspaces home/switch/create → Tasks 5,9; routes table → Tasks 5–9; errors (path guards, fallback) → Tasks 4,6,8; testing → every task; out-of-scope respected (no editor/upload/plots).
- **Note on switcher:** the spec's top-bar workspace *switcher dropdown* is simplified in Task 9 to a "studies" link back to home (which lists + creates). A full in-top-bar dropdown can be a fast-follow; home covers switch/create for the MVP. Flag for the user.
- **Types consistent:** `ChangedFile(path, kind)`, `TableWindow(...)`, `BiomEntry`/`BiomGroup` used identically across modules, templates, and tests. `workspace_new(name, root=...)` signature matches its one new caller.
- **No placeholders:** every code/step block is concrete.
