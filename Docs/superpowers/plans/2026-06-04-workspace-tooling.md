# Workspace Tooling Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the locked phase-workspace structure reproducible by any agent — a one-line `askslm.workspace` import that ends the path boilerplate, a scaffold CLI that stamps the tree, an agent-agnostic `AGENTS.md` section, proven by migrating the `ABX_new` scripts.

**Architecture:** A new `askslm/workspace.py` module exposes `phase(__file__)`, which self-locates inside `Workspaces/<name>/<N_phase>/...` from the numbered-folder convention and returns a handle (`inputs`, `result`, `data`, `plots`, `shared`, `upstream()`). A new `Clients/cli.py` (exposed as the `askslm` console script) stamps the folder tree + template scripts that already use the import. The four `ABX_new` scripts are migrated onto it as the acceptance test.

**Tech Stack:** Python 3.12, `biom` (2.1.17, JSON tables), `pytest` (9.0.3, `tmp_path`/`monkeypatch`), `argparse`, setuptools editable install.

**Spec:** `Docs/superpowers/specs/2026-06-03-workspace-tooling-design.html`

---

## File Structure

| File | Responsibility |
|---|---|
| `askslm/workspace.py` (create) | `phase(file)` + `_Phase` handle: path resolution, `upstream()`, `shared` |
| `Tests/workspace/test_phase.py` (create) | path-resolution tests (root/phase/inputs/result/data/plots) |
| `Tests/workspace/test_upstream.py` (create) | `upstream()` loading + `shared` module loading |
| `Clients/cli.py` (create) | `main()` + `workspace new` / `transform add` / `analysis add` + templates |
| `Tests/cli/test_scaffold.py` (create) | scaffold tree + template-content tests |
| `pyproject.toml` (modify) | add `[project.scripts] askslm = "Clients.cli:main"` |
| `AGENTS.md` (modify) | add the agent-agnostic phase-workflow section |
| `Workspaces/ABX_new/**/*.py` (modify, gitignored) | migrate the 4 scripts onto the import (acceptance only) |

**Note on `askslm` package import:** `askslm/__init__.py` already exists, so `from askslm import workspace` resolves the new submodule automatically — no `__init__.py` edit needed. The editable install (`pip install -e .`) already on disk picks up the new module file; only the new console script (Task 3) needs a reinstall.

---

### Task 1: `workspace.phase` path resolution

**Files:**
- Create: `askslm/workspace.py`
- Test: `Tests/workspace/test_phase.py`

- [ ] **Step 1: Write the failing tests**

```python
# Tests/workspace/test_phase.py
import pytest

from askslm import workspace


def _make_tree(tmp_path):
    root = tmp_path / "Workspaces" / "ABX"
    (root / "0_inputs").mkdir(parents=True)
    (root / "1_build").mkdir()
    (root / "2_transform" / "no-control_bacteria").mkdir(parents=True)
    (root / "3_analyze" / "no-control_bacteria" / "braycurtis").mkdir(parents=True)
    return root


def test_build_phase_resolves_inputs_and_result(tmp_path):
    root = _make_tree(tmp_path)

    ws = workspace.phase(root / "1_build" / "build.py")

    assert ws.name == "build"
    assert ws.inputs == root / "0_inputs"
    assert ws.result == root / "1_build"


def test_transform_result_is_result_subdir(tmp_path):
    root = _make_tree(tmp_path)

    ws = workspace.phase(root / "2_transform" / "no-control_bacteria" / "explore.py")

    assert ws.name == "transform"
    assert ws.result == root / "2_transform" / "no-control_bacteria" / "result"
    assert ws.result.is_dir()


def test_analyze_makes_data_and_plots(tmp_path):
    root = _make_tree(tmp_path)
    script = root / "3_analyze" / "no-control_bacteria" / "braycurtis" / "analysis.py"

    ws = workspace.phase(script)

    assert ws.name == "analyze"
    assert ws.data == script.parent / "data"
    assert ws.plots == script.parent / "plots"
    assert ws.data.is_dir() and ws.plots.is_dir()


def test_script_outside_workspaces_raises(tmp_path):
    loose = tmp_path / "loose" / "build.py"
    loose.parent.mkdir(parents=True)

    with pytest.raises(ValueError):
        workspace.phase(loose)


def test_unknown_phase_folder_raises(tmp_path):
    root = tmp_path / "Workspaces" / "ABX"
    (root / "9_weird").mkdir(parents=True)

    with pytest.raises(ValueError):
        workspace.phase(root / "9_weird" / "x.py")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest Tests/workspace/test_phase.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'askslm.workspace'`

- [ ] **Step 3: Write minimal implementation**

```python
# askslm/workspace.py
"""Resolve a phase script's paths from the numbered-folder workspace convention.

`workspace.phase(__file__)` self-locates inside `Workspaces/<name>/<N_phase>/...` and hands back
the inputs dir, the result dir, the phase's shared module, and the upstream community. Spec:
Docs/superpowers/specs/2026-06-03-workspace-tooling-design.html.
"""
from pathlib import Path

_PHASES = {"1_build": "build", "2_transform": "transform", "3_analyze": "analyze"}


def phase(script_file: str | Path) -> "_Phase":
    return _Phase(Path(script_file).resolve())


class _Phase:
    def __init__(self, script_path: Path):
        self._script = script_path
        self.root = _workspace_root(script_path)
        self._folder = _phase_folder(script_path, self.root)
        self.name = _PHASES[self._folder]

    @property
    def inputs(self) -> Path:
        return self.root / "0_inputs"

    @property
    def result(self) -> Path:
        return _made(self._result_dir())

    @property
    def data(self) -> Path:
        return _made(self.result / "data")

    @property
    def plots(self) -> Path:
        return _made(self.result / "plots")

    def _result_dir(self) -> Path:
        if self.name == "transform":
            return self._script.parent / "result"
        return self._script.parent


def _workspace_root(script_path: Path) -> Path:
    for parent in script_path.parents:
        if parent.parent.name == "Workspaces":
            return parent
    raise ValueError(f"{script_path} is not inside a Workspaces/<name>/ tree")


def _phase_folder(script_path: Path, root: Path) -> str:
    folder = script_path.relative_to(root).parts[0]
    if folder not in _PHASES:
        raise ValueError(f"{script_path} is not under a known phase folder {sorted(_PHASES)}")
    return folder


def _made(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest Tests/workspace/test_phase.py -q`
Expected: PASS — 5 passed

- [ ] **Step 5: Commit**

```bash
git add askslm/workspace.py Tests/workspace/test_phase.py
git commit -m "feat(workspace): phase path resolution from numbered-folder convention

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: `upstream()` and the `shared` module

**Files:**
- Modify: `askslm/workspace.py`
- Test: `Tests/workspace/test_upstream.py`

- [ ] **Step 1: Write the failing tests**

```python
# Tests/workspace/test_upstream.py
import numpy as np
import pytest
from biom import Table

from askslm import workspace


def _write_community(path):
    table = Table(np.array([[1.0, 2.0], [3.0, 4.0]]),
                  observation_ids=["a", "b"], sample_ids=["s1", "s2"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(table.to_json("test"))


def test_transform_upstream_is_build_community(tmp_path):
    root = tmp_path / "Workspaces" / "ABX"
    _write_community(root / "1_build" / "community.biom")
    script = root / "2_transform" / "no-control_bacteria" / "explore.py"
    script.parent.mkdir(parents=True)

    loaded = workspace.phase(script).upstream()

    assert loaded.shape == (2, 2)


def test_analyze_upstream_is_exploration_result(tmp_path):
    root = tmp_path / "Workspaces" / "ABX"
    _write_community(root / "2_transform" / "no-control_bacteria" / "result" / "community.biom")
    script = root / "3_analyze" / "no-control_bacteria" / "braycurtis" / "analysis.py"
    script.parent.mkdir(parents=True)

    loaded = workspace.phase(script).upstream()

    assert loaded.shape == (2, 2)


def test_build_upstream_raises(tmp_path):
    root = tmp_path / "Workspaces" / "ABX"
    script = root / "1_build" / "build.py"
    script.parent.mkdir(parents=True)

    with pytest.raises(ValueError):
        workspace.phase(script).upstream()


def test_shared_module_loads_phase_helpers(tmp_path):
    root = tmp_path / "Workspaces" / "ABX"
    (root / "2_transform").mkdir(parents=True)
    (root / "2_transform" / "shared.py").write_text("def cohort(table):\n    return table\n")
    script = root / "2_transform" / "no-control_bacteria" / "explore.py"
    script.parent.mkdir(parents=True)

    shared = workspace.phase(script).shared

    assert shared.cohort("x") == "x"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest Tests/workspace/test_upstream.py -q`
Expected: FAIL — `AttributeError: '_Phase' object has no attribute 'upstream'`

- [ ] **Step 3: Add `upstream()`, `shared`, and helpers**

Add these imports at the top of `askslm/workspace.py` (below the existing `from pathlib import Path`):

```python
import importlib.util

from biom import load_table
```

Add these two members inside `_Phase` (e.g. after the `plots` property):

```python
    @property
    def shared(self):
        return _load_module(self.root / self._folder / "shared.py")

    def upstream(self):
        return load_table(str(self._upstream_path()))

    def _upstream_path(self) -> Path:
        if self.name == "transform":
            return self.root / "1_build" / "community.biom"
        if self.name == "analyze":
            exploration = self._script.parent.parent.name
            return self.root / "2_transform" / exploration / "result" / "community.biom"
        raise ValueError("build reads from ws.inputs; it has no upstream")
```

Add this module-level helper at the bottom of the file:

```python
def _load_module(path: Path):
    spec = importlib.util.spec_from_file_location("shared", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest Tests/workspace/ -q`
Expected: PASS — 9 passed (5 from Task 1 + 4 here)

- [ ] **Step 5: Commit**

```bash
git add askslm/workspace.py Tests/workspace/test_upstream.py
git commit -m "feat(workspace): upstream() loader and phase shared module

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: The scaffold CLI

**Files:**
- Create: `Clients/cli.py`
- Modify: `pyproject.toml`
- Test: `Tests/cli/test_scaffold.py`

- [ ] **Step 1: Write the failing tests**

```python
# Tests/cli/test_scaffold.py
from Clients.cli import main


def test_workspace_new_stamps_phase_tree(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    main(["workspace", "new", "ABX"])

    root = tmp_path / "Workspaces" / "ABX"
    assert (root / "0_inputs").is_dir()
    assert (root / "1_build" / "build.py").exists()
    assert (root / "2_transform" / "shared.py").exists()
    assert (root / "3_analyze" / "shared.py").exists()


def test_build_template_uses_workspace_import(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    main(["workspace", "new", "ABX"])

    build = (tmp_path / "Workspaces" / "ABX" / "1_build" / "build.py").read_text()
    assert "from askslm import workspace" in build
    assert "workspace.phase(__file__)" in build


def test_transform_add_creates_exploration(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    main(["workspace", "new", "ABX"])

    main(["transform", "add", "ABX", "no-control_bacteria"])

    explore = tmp_path / "Workspaces" / "ABX" / "2_transform" / "no-control_bacteria" / "explore.py"
    assert "ws.upstream()" in explore.read_text()


def test_analysis_add_creates_grouped_analysis(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    main(["workspace", "new", "ABX"])
    main(["transform", "add", "ABX", "no-control_bacteria"])

    main(["analysis", "add", "ABX", "no-control_bacteria", "braycurtis"])

    analysis = (tmp_path / "Workspaces" / "ABX" / "3_analyze"
                / "no-control_bacteria" / "braycurtis" / "analysis.py")
    assert "ws.upstream()" in analysis.read_text()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest Tests/cli/test_scaffold.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'Clients.cli'`

- [ ] **Step 3: Write the CLI with its templates**

```python
# Clients/cli.py
"""askslm scaffold CLI: stamp the locked workspace phase tree. Entry point: main().

Conventions it encodes are the law in AGENTS.md; rationale is in
Docs/superpowers/specs/2026-06-03-workspace-tooling-design.html.
"""
import argparse
from pathlib import Path

WORKSPACES = Path("Workspaces")

SHARED_STUB = '''"""(workspace, {phase}) helpers — study-specific. Promote a step here only when a 2nd script needs it."""
'''

BUILD_PY = '''"""build (ingest + assemble): the atomic community -> community.biom. Run once."""
from askslm import workspace

ws = workspace.phase(__file__)

# read raw sources from ws.inputs (one Accessor each) and assemble ONE biom.Table:
#   counts (atomic self_count) + feature metadata (lineage) + sample metadata.
# then write biom JSON (HDF5 can't round-trip nested lineage metadata):
# (ws.result / "community.biom").write_text(table.to_json("askslm-build"))
'''

BUILD_MD = '''---
kind: build
intent: assemble the atomic community for this study
input: 0_inputs/
outputs: [community.biom]
---
The one run-once building block: counts + lineage feature metadata + sample metadata.
'''

EXPLORE_PY = '''"""transform · {exploration}: shape the community, write result/community.biom."""
from askslm import workspace

ws = workspace.phase(__file__)
community = ws.upstream()                       # 1_build/community.biom

# shape it with biom calls + ws.shared helpers: restrict clade / roll up rank / cohort / norm.
# community = ws.shared.<helper>(community)

(ws.result / "community.biom").write_text(      # biom JSON — HDF5 can't round-trip lineage
    community.to_json("askslm-{exploration}"))
'''

EXPLORE_MD = '''---
kind: transform
intent: one line — what this exploration shapes
input: ../../1_build/community.biom
outputs: [result/community.biom]
---
What this exploration keeps/rolls-up, and why.
'''

ANALYSIS_PY = '''"""analyze · {exploration} / {name}: measure the exploration's community."""
from askslm import workspace

ws = workspace.phase(__file__)
community = ws.upstream()                        # the exploration's result/community.biom

# measure with skbio / scipy + ws.shared, then write:
# result.to_csv(ws.data / "{name}.csv", index=False)
# ws.shared.<plot>(result, ws.plots / "{name}.png")
'''

ANALYSIS_MD = '''---
kind: analysis
intent: one line — what this measures
input: ../../../2_transform/{exploration}/result/community.biom
outputs: [data/{name}.csv, plots/{name}.png]
---
What this analysis measures and the headline finding.
'''


def workspace_new(name: str) -> None:
    root = WORKSPACES / name
    _write(root / "0_inputs" / ".keep", "")
    _write(root / "1_build" / "build.py", BUILD_PY)
    _write(root / "1_build" / "build.md", BUILD_MD)
    _write(root / "2_transform" / "shared.py", SHARED_STUB.format(phase="transform"))
    _write(root / "3_analyze" / "shared.py", SHARED_STUB.format(phase="analyze"))


def transform_add(name: str, exploration: str) -> None:
    folder = WORKSPACES / name / "2_transform" / exploration
    _write(folder / "explore.py", EXPLORE_PY.format(exploration=exploration))
    _write(folder / "explore.md", EXPLORE_MD.format(exploration=exploration))


def analysis_add(name: str, exploration: str, analysis: str) -> None:
    folder = WORKSPACES / name / "3_analyze" / exploration / analysis
    _write(folder / "analysis.py", ANALYSIS_PY.format(exploration=exploration, name=analysis))
    _write(folder / "analysis.md", ANALYSIS_MD.format(exploration=exploration, name=analysis))


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def main(argv=None) -> None:
    args = _build_parser().parse_args(argv)
    _dispatch(args)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="askslm")
    groups = parser.add_subparsers(dest="group", required=True)
    _add_workspace(groups)
    _add_transform(groups)
    _add_analysis(groups)
    return parser


def _add_workspace(groups) -> None:
    actions = groups.add_parser("workspace").add_subparsers(dest="action", required=True)
    new = actions.add_parser("new")
    new.add_argument("name")


def _add_transform(groups) -> None:
    actions = groups.add_parser("transform").add_subparsers(dest="action", required=True)
    add = actions.add_parser("add")
    add.add_argument("name")
    add.add_argument("exploration")


def _add_analysis(groups) -> None:
    actions = groups.add_parser("analysis").add_subparsers(dest="action", required=True)
    add = actions.add_parser("add")
    add.add_argument("name")
    add.add_argument("exploration")
    add.add_argument("analysis")


def _dispatch(args) -> None:
    if args.group == "workspace":
        return workspace_new(args.name)
    if args.group == "transform":
        return transform_add(args.name, args.exploration)
    return analysis_add(args.name, args.exploration, args.analysis)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest Tests/cli/test_scaffold.py -q`
Expected: PASS — 4 passed

- [ ] **Step 5: Wire the console script and reinstall**

Add to `pyproject.toml` after the `[project]` block:

```toml
[project.scripts]
askslm = "Clients.cli:main"
```

Then reinstall so the `askslm` command registers:

Run: `.venv/bin/pip install -e . -q && .venv/bin/askslm workspace new _smoke && ls Workspaces/_smoke && rm -rf Workspaces/_smoke`
Expected: lists `0_inputs 1_build 2_transform 3_analyze`, then removes the smoke workspace.

- [ ] **Step 6: Commit**

```bash
git add Clients/cli.py Tests/cli/test_scaffold.py pyproject.toml
git commit -m "feat(cli): askslm scaffold for workspace/transform/analysis

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 4: Agent-agnostic conventions in `AGENTS.md`

**Files:**
- Modify: `AGENTS.md`

- [ ] **Step 1: Insert the phase-workflow section**

Insert this section immediately after the `## What this repo is` block (before `## Architecture to respect`). Do **not** delete the legacy `## Workspace conventions` section — its contradiction with the numbered-phase layout is surfaced to the user separately.

```markdown
## Workspace phase workflow (numbered phases)
A study lives in `Workspaces/<name>/` as phases handed off through files on disk:
`0_inputs/ -> 1_build/community.biom -> 2_transform/<exploration>/result/community.biom -> 3_analyze/<exploration>/<analysis>/{data,plots}`.

- **Scaffold with the CLI, never by hand:** `askslm workspace new <name>`, `askslm transform add <ws> <exploration>`, `askslm analysis add <ws> <exploration> <name>`.
- **Every phase script starts** `from askslm import workspace` then `ws = workspace.phase(__file__)`. No `sys.path` / `parents[N]`. Use `ws.inputs`, `ws.upstream()`, `ws.result`, `ws.data`, `ws.plots`, `ws.shared`.
- **Promotion rule:** write a step inline first; lift it into that phase's `shared.py` only when a 2nd script in the same phase needs it.
- **Two libraries:** general reusable logic lives in the `askslm` package; study-specific helpers live in `<phase>/shared.py`.
- **Naming:** explorations are intent-named (`no-control_bacteria`); analyses are grouped under their exploration by method (`braycurtis`).
- **Serialization:** communities are biom **JSON** (`to_json` / `load_table`) — HDF5 cannot round-trip the nested lineage metadata.
- Rationale and full model: `Docs/abundancetable.html` and `Docs/superpowers/specs/2026-06-03-workspace-tooling-design.html`.
```

- [ ] **Step 2: Verify the section reads correctly**

Run: `grep -n "Workspace phase workflow" AGENTS.md`
Expected: one match, before the `## Architecture to respect` line (confirm with `grep -n "^## " AGENTS.md`).

- [ ] **Step 3: Commit**

```bash
git add AGENTS.md
git commit -m "docs(agents): codify the numbered-phase workspace workflow

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 5: Migrate `ABX_new` (acceptance test — gitignored, no commit)

**Files (all under gitignored `Workspaces/`, so no git commit):**
- Modify: `Workspaces/ABX_new/1_build/build.py`
- Modify: `Workspaces/ABX_new/2_transform/no-control_bacteria/explore.py`
- Modify: `Workspaces/ABX_new/3_analyze/no-control_bacteria/braycurtis/analysis.py`
- Modify: `Workspaces/ABX_new/3_analyze/no-control_bacteria/mann-whitney/analysis.py`

- [ ] **Step 1: Rewrite `1_build/build.py`**

```python
"""build (ingest + assemble): the atomic ABX_new community -> community.biom. Run once."""
import pandas as pd
from biom import Table

from askslm import metadata, taxonomy, workspace

ws = workspace.phase(__file__)

# counts: features (tax_id) x samples (acc) -- atomic self_count
tax = taxonomy.load(str(ws.inputs / "taxonomy.csv"))
counts = tax.pivot_table(index="tax_id", columns="acc", values="self_count",
                         aggfunc="sum", fill_value=0)

# feature metadata: lineage per tax_id (the only real build logic)
features = taxonomy.lineage_table(counts.index)

# sample metadata: assay + subject + cluster (Master Map) + day (canon), one row per acc
samples = metadata.extract(str(ws.inputs / "metadata.csv"))
clusters = pd.read_excel(ws.inputs / "Viral_Ecological_Clusters_Master_Map-v2.xlsx")
days = pd.read_excel(ws.inputs / "canon.xlsx")[["library", "day"]]
sample_meta = (samples
               .merge(clusters, left_on="host_subject_id_sam", right_on="Subject", how="left")
               .merge(days, left_on="sample_name", right_on="library", how="left")
               .set_index("acc"))

# assemble ONE biom.Table = counts + feature metadata + sample metadata
table = Table(counts.values,
              observation_ids=counts.index.astype(str),
              sample_ids=counts.columns.astype(str))
table.add_metadata({str(t): row for t, row in features.to_dict("index").items()}, axis="observation")
table.add_metadata(sample_meta.to_dict("index"), axis="sample")

(ws.result / "community.biom").write_text(table.to_json("askslm-abx_new-build"))
print(f"community.biom: {table.shape[0]} features x {table.shape[1]} samples")
```

- [ ] **Step 2: Run build, verify the atomic community**

Run: `.venv/bin/python Workspaces/ABX_new/1_build/build.py`
Expected: `community.biom: 23283 features x 1284 samples`

- [ ] **Step 3: Rewrite `2_transform/no-control_bacteria/explore.py`**

```python
"""transform · no-control_bacteria: Bacteria -> species, cohort only, relative abundance."""
from askslm import workspace

ws = workspace.phase(__file__)

BACTERIA = 2
RANK = "species"


def in_bacteria_clade(values, feature_id, md):
    return BACTERIA in md["lineage"]


def has_species(values, feature_id, md):
    return md["ranks"].get(RANK) is not None


def species_of(feature_id, md):
    return str(md["ranks"][RANK])


def roll_up_to_species(community):
    with_species = community.filter(has_species, axis="observation", inplace=False)   # removes genus-and-above
    return with_species.collapse(species_of, norm=False, axis="observation",          # merges sub-species into their species
                                 include_collapsed_metadata=False)


community = ws.upstream()
community = community.filter(in_bacteria_clade, axis="observation", inplace=False)  # keep the Bacteria clade
community = roll_up_to_species(community)                                            # sum counts to species
community = ws.shared.cohort(community)                                              # WGS, clustered, has-day, no controls
community = community.norm(axis="sample", inplace=False)                             # relative abundance

(ws.result / "community.biom").write_text(community.to_json("askslm-no-control_bacteria"))
print(f"result: {community.shape[0]} species x {community.shape[1]} cohort samples")
```

- [ ] **Step 4: Run transform, verify the cohort community**

Run: `.venv/bin/python Workspaces/ABX_new/2_transform/no-control_bacteria/explore.py`
Expected: `result: 12933 species x 960 cohort samples`

- [ ] **Step 5: Rewrite `3_analyze/no-control_bacteria/braycurtis/analysis.py`**

```python
"""analyze · no-control_bacteria / braycurtis: within-subject day-0 -> last-day community shift."""
from askslm import workspace

ws = workspace.phase(__file__)
BASELINE_TOLERANCE_DAYS = 2

community = ws.upstream()
braycurtis = ws.shared.per_subject_braycurtis(community, BASELINE_TOLERANCE_DAYS)

braycurtis.to_csv(ws.data / "braycurtis.csv", index=False)
ws.shared.boxplot_by_cluster(braycurtis, ws.plots / "braycurtis_box.png")
print(f"{len(braycurtis)} subjects")
print(braycurtis.groupby("Cluster_Name")["braycurtis"].agg(["size", "mean"]))
```

- [ ] **Step 6: Run braycurtis, verify the cluster means**

Run: `.venv/bin/python Workspaces/ABX_new/3_analyze/no-control_bacteria/braycurtis/analysis.py`
Expected: `59 subjects`, and per-cluster means ≈ 0.41 / 0.38 / 0.33 / 0.33 (matching the locked numbers).

- [ ] **Step 7: Rewrite `3_analyze/no-control_bacteria/mann-whitney/analysis.py`**

```python
"""analyze · no-control_bacteria / mann-whitney: pairwise cluster test of the day-0 -> last shift."""
from itertools import combinations

import pandas as pd
from scipy.stats import mannwhitneyu

from askslm import workspace

ws = workspace.phase(__file__)
BASELINE_TOLERANCE_DAYS = 2

community = ws.upstream()
shifts = ws.shared.per_subject_braycurtis(community, BASELINE_TOLERANCE_DAYS)


def compare_clusters(cluster_a, cluster_b):
    a = shifts[shifts["Cluster_ID"] == cluster_a]["braycurtis"]
    b = shifts[shifts["Cluster_ID"] == cluster_b]["braycurtis"]
    u, p = mannwhitneyu(a, b, alternative="two-sided")
    return {"cluster_a": cluster_a, "cluster_b": cluster_b, "n_a": len(a), "n_b": len(b),
            "U": float(u), "p": float(p)}


clusters = sorted(shifts["Cluster_ID"].unique())
pairwise = (pd.DataFrame([compare_clusters(a, b) for a, b in combinations(clusters, 2)])
            .sort_values("p").reset_index(drop=True))

pairwise.to_csv(ws.data / "mann_whitney.csv", index=False)
ws.shared.pvalue_heatmap(pairwise, ws.plots / "mann_whitney_pvalues.png")
print(pairwise.to_string(index=False))
```

- [ ] **Step 8: Run mann-whitney, verify the pairwise result**

Run: `.venv/bin/python Workspaces/ABX_new/3_analyze/no-control_bacteria/mann-whitney/analysis.py`
Expected: pairwise table where cluster 0 vs 2 is significant (p ≈ 0.028) and is the smallest p.

- [ ] **Step 9: No commit**

These four files live under the gitignored `Workspaces/`. There is nothing to commit — passing Steps 2/4/6/8 with the locked numbers **is** the acceptance test. Confirm with `git status` that no tracked files changed.

---

## Self-Review

**Spec coverage:**
- §2 `workspace.phase` import + handle members + self-location + per-phase resolution → Tasks 1–2 ✓
- §3 scaffold CLI (3 commands, templates, no `run`), pyproject console script → Task 3 ✓
- §4 `AGENTS.md` agent-agnostic conventions + template comments → Task 4 (AGENTS.md) + Task 3 (template comments carry biom-JSON / clade-rank-cohort cues) ✓
- §5 migrate the four `ABX_new` scripts as acceptance, numbers must match → Task 5 ✓
- §6 decisions (no `ws.save`, no `run`, `ws.result` writes) → reflected: templates write via `ws.result`, no `save`/`run` anywhere ✓

**Placeholder scan:** No `TBD`/`TODO` in plan steps. (The generated stub `.md` files use neutral one-line prompts the scientist fills — that is intended stub content, not a plan placeholder.)

**Type/name consistency:** `phase()` returns `_Phase`; members `inputs`, `result`, `data`, `plots`, `shared`, `upstream()`, `name`, `root` used identically across Tasks 1, 2, 5. CLI funcs `workspace_new(name)`, `transform_add(name, exploration)`, `analysis_add(name, exploration, analysis)` match `_dispatch`. Template placeholders `{exploration}`/`{name}` match the `.format(...)` calls. ✓
