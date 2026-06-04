# Project Reconciliation & Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the repository tell one story — the agent-driven, biom-feature-table model — by deleting the old toolkit code, rewiring the survivors, consolidating source under `src/`, sweeping junk, and reframing the docs.

**Architecture:** This is a refactor, not new features. The safety net is the existing pytest suite plus the `Workspaces/ABX_new` phase chain, which must keep running unchanged. Deletions are **gated**: before removing any module, grep for surviving importers and remove only when the count is zero. Order is chosen so the tree is never broken between commits: rewire callers first, trim re-exports, then delete the now-orphaned code, then move, then sweep, then reframe docs.

**Tech Stack:** Python 3.12, biom-format, ete3, scikit-bio, pandas, scipy; FastAPI (web); Anthropic SDK (agent); pytest.

**Spec:** `Docs/superpowers/specs/2026-06-04-project-reconciliation-and-cleanup-design.html`

**Branch:** `refactor-reconciliation-cleanup` (already created).

**Pre-flight (run once, do not commit):** confirm the baseline is green so later failures are attributable.
```bash
python -m pytest Tests -q
python Workspaces/ABX_new/1_build/build.py   # must print "feature_table.biom: N features x M samples"
```

---

### Task 1: Reconcile the agent's recognized-domain-object surface

The agent recognizes a fixed set of domain types (for handle creation + summaries). Swap the retired types (`Metadata`, `AbundanceMatrix`, `Cohort`, `ResolvedTaxonomy`) for the new model: `biom.Table` (feature table), the surviving `MetadataOverview`, and `DataFrame`. Imports here still use pre-move paths; Task 8 rewrites them.

**Files:**
- Modify: `Agents/summaries.py` (full rewrite)
- Modify: `Agents/tools/_sandbox_worker.py:11-18`
- Modify: `Agents/tools/run_python.py` (docstring, ~line 36-37)
- Test: `Tests/agent/test_summaries.py`

- [ ] **Step 1: Rewrite `Agents/summaries.py`**

```python
from __future__ import annotations
from typing import Any, Callable
import pandas as pd
from biom import Table

from Common.contracts.metadata_results import MetadataOverview


def _feature_table(t: Table) -> dict:
    return {
        "type": "FeatureTable",
        "shape": [t.shape[0], t.shape[1]],          # features x samples
        "features_preview": list(t.ids("observation"))[:5],
        "samples_preview": list(t.ids("sample"))[:5],
    }


def _metadata_overview(o: MetadataOverview) -> dict:
    return {"type": "MetadataOverview", "summary_available": True}


def _dataframe(df: pd.DataFrame) -> dict:
    return {
        "type": "DataFrame",
        "shape": list(df.shape),
        "columns": list(df.columns)[:30],
    }


_SUMMARIZERS: list[tuple[type, Callable[[Any], dict]]] = [
    (Table, _feature_table),
    (MetadataOverview, _metadata_overview),
    (pd.DataFrame, _dataframe),
]


def summarize_object(obj: Any) -> dict:
    for typ, fn in _SUMMARIZERS:
        if isinstance(obj, typ):
            return fn(obj)
    return {"type": "object", "repr": repr(obj)[:200]}
```

- [ ] **Step 2: Update the recognized-type list in `Agents/tools/_sandbox_worker.py`** (replace lines 11-18)

```python
RECOGNIZED_TYPE_PATHS = (
    "biom.table.Table",
    "Common.contracts.metadata_results.MetadataOverview",
    "pandas.core.frame.DataFrame",
)
```

- [ ] **Step 3: Update the `run_python` docstring** in `Agents/tools/run_python.py` — replace the parenthetical listing the old types:

Find: `(Metadata, AbundanceMatrix, Cohort, ResolvedTaxonomy, DataFrame)`
Replace with: `(biom.Table feature tables, MetadataOverview, DataFrame)`

- [ ] **Step 4: Replace `Tests/agent/test_summaries.py`** with assertions for the new types

```python
import pandas as pd
from biom import Table

from Agents.summaries import summarize_object


def test_feature_table_summary():
    t = Table([[1, 2], [3, 4]], observation_ids=["10", "20"], sample_ids=["sA", "sB"])
    out = summarize_object(t)
    assert out["type"] == "FeatureTable"
    assert out["shape"] == [2, 2]


def test_dataframe_summary():
    out = summarize_object(pd.DataFrame({"a": [1, 2], "b": [3, 4]}))
    assert out["type"] == "DataFrame"
    assert out["shape"] == [2, 2]


def test_unknown_object_falls_back():
    assert summarize_object(object())["type"] == "object"
```

- [ ] **Step 5: Run the affected tests**

Run: `python -m pytest Tests/agent/test_summaries.py Tests/agent/test_run_python.py -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add Agents/summaries.py Agents/tools/_sandbox_worker.py Agents/tools/run_python.py Tests/agent/test_summaries.py
git commit -m "refactor(agent): recognize biom.Table feature tables, drop retired domain types"
```

---

### Task 2: Delete the narrow agent tools and rewire the registry

The `taxonomy_tools` / `metadata_tools` files are the old narrow-tool model and the last agent importers of `AbundanceMatrix`. The agent now works via `run_python` + `askslm` + the scaffold CLI.

**Files:**
- Delete: `Agents/tools/taxonomy_tools.py`, `Agents/tools/metadata_tools.py`
- Modify: `Agents/tools/__init__.py`
- Delete: `Tests/agent/test_taxonomy_tools.py`, `Tests/agent/test_metadata_tools.py`

- [ ] **Step 1: Delete the two tool files and their tests**

```bash
git rm Agents/tools/taxonomy_tools.py Agents/tools/metadata_tools.py \
       Tests/agent/test_taxonomy_tools.py Tests/agent/test_metadata_tools.py
```

- [ ] **Step 2: Rewrite `Agents/tools/__init__.py`** to drop the two registries

```python
from __future__ import annotations
from Agents.tools.registry import Registry
from Agents.tools.session_tools import session_registry
from Agents.tools.run_python import run_python_registry


def _merge(*regs: Registry) -> Registry:
    merged = Registry()
    for r in regs:
        for name, tool in r._tools.items():  # noqa: SLF001
            merged._tools[name] = tool        # noqa: SLF001
    return merged


default_registry: Registry = _merge(session_registry, run_python_registry)

__all__ = ["default_registry"]
```

- [ ] **Step 3: Confirm no remaining agent reference to the deleted tools or to AbundanceMatrix**

Run: `grep -rn "metadata_tools\|taxonomy_tools\|AbundanceMatrix" Agents --include='*.py' | grep -v __pycache__`
Expected: no output

- [ ] **Step 4: Run the agent suite**

Run: `python -m pytest Tests/agent -q`
Expected: PASS (the registry/loop tests pick up the smaller default_registry)

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "refactor(agent): delete narrow metadata/taxonomy tools; agent works via run_python"
```

---

### Task 3: Trim the TaxonomyEngine surface to `load` + `lineage_table`

Remove `resolve`, `build_abundance_matrix`, `build_cohort` and their imports. `load` and `lineage_table` (the only things `ABX_new/1_build/build.py` calls) stay.

**Files:**
- Modify: `Engines/TaxonomyEngine/__init__.py` (rewrite)

- [ ] **Step 1: Rewrite `Engines/TaxonomyEngine/__init__.py`**

```python
from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

import pandas as pd
from ete3 import NCBITaxa

from Accessors.TaxonomyAccessor.taxonomy_file_accessor import TaxonomyFileAccessor


def load(source: str | Path) -> pd.DataFrame:
    return TaxonomyFileAccessor().read(Path(source))


def lineage_table(tax_ids: Iterable[int]) -> pd.DataFrame:
    """One row per tax_id: name, rank, full lineage, and the ancestor taxid at each rank."""
    ids = [int(t) for t in tax_ids]
    ncbi = NCBITaxa()
    lineages = ncbi.get_lineage_translator(ids)
    ranks = ncbi.get_rank([anc for lineage in lineages.values() for anc in lineage])
    names = ncbi.get_taxid_translator(ids)
    rows = {t: _feature_row(t, lineages.get(t, []), ranks, names) for t in ids}
    return pd.DataFrame.from_dict(rows, orient="index")


def _feature_row(tax_id: int, lineage: list[int], ranks: dict, names: dict) -> dict:
    return {
        "name": names.get(tax_id),
        "rank": ranks.get(tax_id),
        "lineage": tuple(lineage),
        "ranks": {ranks[anc]: anc for anc in lineage if anc in ranks},
    }
```

- [ ] **Step 2: Verify the surviving surface imports and ABX_new build still works**

Run: `python -c "from askslm import taxonomy; print(taxonomy.load, taxonomy.lineage_table)"`
Run: `python Workspaces/ABX_new/1_build/build.py`
Expected: build prints `feature_table.biom: N features x M samples`

- [ ] **Step 3: Commit**

```bash
git add Engines/TaxonomyEngine/__init__.py
git commit -m "refactor(taxonomy): trim engine to load + lineage_table"
```

---

### Task 4: Trim `askslm/contracts.py` to the surviving surface

Keep `MetadataOverview`; drop the selector and resolved-taxonomy re-exports.

**Files:**
- Modify: `askslm/contracts.py`

- [ ] **Step 1: Rewrite `askslm/contracts.py`**

```python
from Common.contracts.metadata_results import MetadataOverview

__all__ = ["MetadataOverview"]
```

- [ ] **Step 2: Verify the public package still imports**

Run: `python -c "from askslm import metadata, taxonomy, workspace; from askslm.contracts import MetadataOverview; print('ok')"`
Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add askslm/contracts.py
git commit -m "refactor(askslm): contracts expose MetadataOverview only"
```

---

### Task 5: Delete the `Metadata` value object (now orphaned) and its test

After Tasks 1-2, the only importers of `Engines/MetadataEngine/metadata.py` were the deleted tools, `summaries.py` (rewritten), and the dying `cohort.py`. `metadata.extract` returns a plain `DataFrame`, so the value object is unused.

**Files:**
- Delete: `Engines/MetadataEngine/metadata.py`
- Delete: `Tests/unit/metadata/test_metadata.py`

- [ ] **Step 1: Gate — confirm no surviving importer**

Run: `grep -rn "MetadataEngine.metadata import Metadata\|MetadataEngine\.metadata\b" Engines Accessors Agents Web askslm --include='*.py' | grep -v __pycache__`
Expected: no output. **If output appears, stop and resolve that importer before deleting.**

- [ ] **Step 2: Delete the file and its test**

```bash
git rm Engines/MetadataEngine/metadata.py Tests/unit/metadata/test_metadata.py
```

- [ ] **Step 3: Verify metadata surface intact**

Run: `python -c "from askslm import metadata; print(metadata.extract, metadata.overview)"`
Run: `python -m pytest Tests/unit/metadata -q`
Expected: PASS (extract/overview/builder tests still pass; `test_metadata.py` gone)

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "refactor(metadata): delete unused Metadata value object"
```

---

### Task 6: Delete the dead taxonomy domain code + tests (gated)

These have no surviving importer after Tasks 1-5: `abundance_matrix`, `abundance_matrix_builder`, `cohort`, `taxonomy_resolver`, `nested_set_lineage_resolver`, and the `MergedDumpAccessor` (+ `merged.dmp`) that only `resolve` used.

**Files:**
- Delete: `Engines/TaxonomyEngine/{abundance_matrix.py,abundance_matrix_builder.py,cohort.py,taxonomy_resolver.py,nested_set_lineage_resolver.py}`
- Delete: `Accessors/MergedDumpAccessor/` (whole dir, incl. `merged.dmp`)
- Delete tests: `Tests/unit/taxonomy/{test_abundance_matrix.py,test_abundance_matrix_builder.py,test_cohort.py,test_taxonomy_resolver.py,test_nested_set_lineage_resolver.py,test_merged_dump_accessor.py}`

- [ ] **Step 1: Gate — confirm each module is importer-free across surviving code**

Run:
```bash
grep -rn "abundance_matrix\|AbundanceMatrix\|TaxonomyEngine.cohort\|import Cohort\|taxonomy_resolver\|TaxonomyResolver\|nested_set_lineage_resolver\|MergedDumpAccessor" \
  Engines Accessors Agents Web askslm --include='*.py' | grep -v __pycache__
```
Expected: no output. **If any line appears, resolve that importer first.**

- [ ] **Step 2: Delete the modules, the accessor, and their tests**

```bash
git rm Engines/TaxonomyEngine/abundance_matrix.py \
       Engines/TaxonomyEngine/abundance_matrix_builder.py \
       Engines/TaxonomyEngine/cohort.py \
       Engines/TaxonomyEngine/taxonomy_resolver.py \
       Engines/TaxonomyEngine/nested_set_lineage_resolver.py \
       Tests/unit/taxonomy/test_abundance_matrix.py \
       Tests/unit/taxonomy/test_abundance_matrix_builder.py \
       Tests/unit/taxonomy/test_cohort.py \
       Tests/unit/taxonomy/test_taxonomy_resolver.py \
       Tests/unit/taxonomy/test_nested_set_lineage_resolver.py \
       Tests/unit/taxonomy/test_merged_dump_accessor.py
git rm -r Accessors/MergedDumpAccessor
```

- [ ] **Step 3: Verify**

Run: `python -m pytest Tests/unit/taxonomy -q && python Workspaces/ABX_new/1_build/build.py`
Expected: PASS + build prints its summary

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "refactor(taxonomy): delete AbundanceMatrix, cohort, resolvers, MergedDumpAccessor"
```

---

### Task 7: Delete `Managers/`, `matrix_writers/`, dead contracts, and the old taxonomy e2e

`Managers/` and `Accessors/matrix_writers/` have no importer outside tests (verified). `Common/contracts/selectors.py` (used only by the now-deleted `cohort`/`metadata` value object) and `taxonomy_results.py` (used only by deleted `resolve` + rewritten agent files) are now orphaned. The taxonomy e2e tests `resolve`/`build_abundance_matrix` and must be replaced.

**Files:**
- Delete: `Managers/`, `Accessors/matrix_writers/`, `Common/contracts/selectors.py`, `Common/contracts/taxonomy_results.py`
- Delete tests: `Tests/unit/taxonomy/{test_matrix_writers.py,test_selectors.py,test_taxonomy_results.py}`
- Replace: `Tests/e2e/test_taxonomy_flow.py`

- [ ] **Step 1: Gate — confirm orphaned**

Run:
```bash
grep -rn "import Managers\|from Managers\|matrix_writers\|contracts.selectors\|SampleSelector\|TaxaSelector\|FilterCriteria\|taxonomy_results\|ResolvedTaxonomy\|ResolutionSummary" \
  Engines Accessors Agents Web askslm --include='*.py' | grep -v __pycache__
```
Expected: no output. **Resolve any hit before deleting.**

- [ ] **Step 2: Delete dead code + tests**

```bash
git rm -r Managers Accessors/matrix_writers
git rm Common/contracts/selectors.py Common/contracts/taxonomy_results.py \
       Tests/unit/taxonomy/test_matrix_writers.py \
       Tests/unit/taxonomy/test_selectors.py \
       Tests/unit/taxonomy/test_taxonomy_results.py
```

- [ ] **Step 3: Replace `Tests/e2e/test_taxonomy_flow.py`** with the new build-flow e2e (mirrors `ABX_new/1_build/build.py`)

```python
"""e2e: load a taxonomy report, build feature metadata, assemble a biom feature table."""
from pathlib import Path

from biom import Table

from askslm import taxonomy

TAX = Path(__file__).parent.parent / "fixtures" / "taxonomy_tiny.csv"


def test_load_lineage_and_assemble():
    tax = taxonomy.load(str(TAX))
    counts = tax.pivot_table(index="tax_id", columns="acc", values="self_count",
                             aggfunc="sum", fill_value=0)
    features = taxonomy.lineage_table(counts.index)

    table = Table(counts.values,
                  observation_ids=counts.index.astype(str),
                  sample_ids=counts.columns.astype(str))
    table.add_metadata({str(t): row for t, row in features.to_dict("index").items()},
                       axis="observation")

    assert table.shape[0] == len(counts.index)
    assert table.shape[1] == len(counts.columns)
    fm = table.metadata_to_dataframe("observation")
    assert {"name", "rank", "lineage", "ranks"}.issubset(fm.columns)
```

- [ ] **Step 4: Verify**

Run: `python -m pytest Tests/e2e/test_taxonomy_flow.py Tests/e2e/test_metadata_flow.py -q`
Expected: PASS (the new e2e needs the ete3 DB at `~/.etetoolkit/taxa.sqlite`; the metadata flow is unchanged)

- [ ] **Step 5: Full suite regression**

Run: `python -m pytest Tests -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "refactor: delete Managers, matrix_writers, dead contracts; new biom build e2e"
```

---

### Task 8: Consolidate source under `src/` (atomic move + import rewrite)

Move the surviving source into three peer packages under `src/`. The package name `askslm` is unchanged, so `Workspaces/ABX_new` scripts (`from askslm import ...`) need no edits. This task commits as one logical unit; verify with the full suite at the end.

**Target mapping:**
| From | To |
|---|---|
| `askslm/` (`__init__.py`, `workspace.py`, `contracts.py`) | `src/askslm/` |
| `Engines/MetadataEngine/` | `src/askslm/metadata/` (subpackage; `__init__` keeps `extract`, `overview`) |
| `Engines/TaxonomyEngine/` | `src/askslm/taxonomy/` (subpackage; `__init__` keeps `load`, `lineage_table`) |
| `Accessors/MetadataAccessor/`, `Accessors/TaxonomyAccessor/` | `src/askslm/accessors/` |
| `Common/contracts/metadata_results.py` | `src/askslm/contracts.py` (move the `MetadataOverview` class in directly) |
| `Common/contracts/sra_schema.py` | `src/askslm/metadata/sra_schema.py` |
| `Clients/cli.py` | `src/askslm/cli.py` |
| `Agents/` | `src/agent/` |
| `Web/` | `src/web/` |

- [ ] **Step 1: Create `src/` and move the toolbox package**

```bash
mkdir -p src
git mv askslm src/askslm
git mv Engines/MetadataEngine src/askslm/metadata
git mv Engines/TaxonomyEngine src/askslm/taxonomy
mkdir -p src/askslm/accessors
git mv Accessors/MetadataAccessor/metadata_file_accessor.py src/askslm/accessors/metadata_file_accessor.py
git mv Accessors/TaxonomyAccessor/taxonomy_file_accessor.py src/askslm/accessors/taxonomy_file_accessor.py
git mv Accessors/TaxonomyAccessor/merged.dmp src/askslm/accessors/merged.dmp
git mv Common/contracts/sra_schema.py src/askslm/metadata/sra_schema.py
git mv Clients/cli.py src/askslm/cli.py
touch src/askslm/accessors/__init__.py
```

- [ ] **Step 2: Move `MetadataOverview` into `src/askslm/contracts.py`**

Open `Common/contracts/metadata_results.py`, copy the full `MetadataOverview` class body, and write it as the entire content of `src/askslm/contracts.py` (replacing the re-export). Then:
```bash
git rm Common/contracts/metadata_results.py
git rm -r Common Accessors Engines Clients   # now-empty old layer dirs
```

- [ ] **Step 3: Move the two app packages and rename their internal imports**

```bash
git mv Agents src/agent
git mv Web src/web
```

- [ ] **Step 4: Rewrite every import across `src/` and `Tests/`**

Apply these replacements (use your editor's project-wide replace, scoped to `src/` and `Tests/`):
```
from Engines.MetadataEngine            ->  from askslm.metadata
from Engines.TaxonomyEngine            ->  from askslm.taxonomy
import Engines.TaxonomyEngine as        ->  import askslm.taxonomy as
from Engines import MetadataEngine as   ->  from askslm import metadata as     # (in src/askslm/__init__.py)
from Engines import TaxonomyEngine as   ->  from askslm import taxonomy as
from Accessors.MetadataAccessor.metadata_file_accessor  ->  from askslm.accessors.metadata_file_accessor
from Accessors.TaxonomyAccessor.taxonomy_file_accessor  ->  from askslm.accessors.taxonomy_file_accessor
from Common.contracts.metadata_results ->  from askslm.contracts
from Common.contracts.sra_schema       ->  from askslm.metadata.sra_schema
from Agents                            ->  from agent
import Agents                          ->  import agent
from Web                               ->  from web
```
Then fix the two internal package `__init__`/path references:
- `src/askslm/__init__.py` becomes:
  ```python
  from askslm import metadata, taxonomy, workspace
  __all__ = ["metadata", "taxonomy", "workspace"]
  ```
- In `src/askslm/taxonomy/__init__.py`, the accessor import becomes `from askslm.accessors.taxonomy_file_accessor import TaxonomyFileAccessor`.
- In `src/askslm/metadata/__init__.py`, `from askslm.accessors.metadata_file_accessor import MetadataFileAccessor` and `from askslm.contracts import MetadataOverview` and `from askslm.metadata.sra_schema import ...` as needed.
- `src/askslm/cli.py`: its `WORKSPACES` constant resolves the repo root by walking parents — confirm it still points at `<repo>/Workspaces` after the move (it locates relative to the file); adjust the parent count if the depth changed.
- `src/askslm/taxonomy/__init__.py` `DEFAULT_MERGED_DMP` is gone (resolve deleted) — no path fix needed there.
- `Agents/tools/_sandbox_worker.py` recognized path `Common.contracts.metadata_results.MetadataOverview` -> `askslm.contracts.MetadataOverview`; `Agents/summaries.py` import -> `from askslm.contracts import MetadataOverview`.

- [ ] **Step 5: Update `pyproject.toml`**

Replace the packaging section:
```toml
[project.scripts]
askslm = "askslm.cli:main"

[tool.setuptools.packages.find]
where = ["src"]
include = ["askslm*", "agent*", "web*"]
namespaces = true
```

- [ ] **Step 6: Update `Tests/conftest.py`** if it manipulates `sys.path` to the old layer roots — point it at `src/` (or rely on the editable install in Step 7).

- [ ] **Step 7: Reinstall editable and run the full suite + ABX_new chain**

```bash
pip install -e .
grep -rn "from Engines\|from Accessors\|from Common\|from Managers\|import Agents\|from Web\b" src Tests --include='*.py' | grep -v __pycache__   # expect: no output
python -m pytest Tests -q
python Workspaces/ABX_new/1_build/build.py
python Workspaces/ABX_new/2_transform/no-control_bacteria/explore.py
python Workspaces/ABX_new/3_analyze/no-control_bacteria/braycurtis/analysis.py
python Workspaces/ABX_new/3_analyze/no-control_bacteria/mann-whitney/analysis.py
```
Expected: no stale-import hits; suite PASS; all four ABX_new scripts run and write their outputs.

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "refactor: consolidate source under src/ (askslm, agent, web); rewrite imports"
```

---

### Task 9: Junk sweep + `.gitignore`

**Files:**
- Delete: stale notebooks, `taxdump.tar.gz`, `out/` scratch, both `*.egg-info/`, caches
- Modify: `.gitignore`

- [ ] **Step 1: Delete tracked junk**

```bash
git rm -r --cached --ignore-unmatch ask_slm.egg-info askslm.egg-info 2>/dev/null; rm -rf ask_slm.egg-info askslm.egg-info
git rm -r Notebooks/out 2>/dev/null
git rm Notebooks/Cli_Runner.ipynb Notebooks/Demo.ipynb Notebooks/cluster_braycurtis.ipynb \
       Notebooks/new.ipynb Notebooks/pivot.ipynb Notebooks/runner.ipynb \
       Notebooks/taxdump.tar.gz "Notebooks/Viral_Ecological_Clusters_Master_Map-v2.xlsx" 2>/dev/null
find . -name __pycache__ -type d -prune -exec rm -rf {} + ; find . -name '.DS_Store' -delete
```
(`Notebooks/biom_explore.ipynb` is kept.)

- [ ] **Step 2: Update `.gitignore`** — append if absent:

```gitignore
__pycache__/
*.py[cod]
*.egg-info/
.DS_Store
.idea/
.pytest_cache/
```

- [ ] **Step 3: Verify the tree is clean and biom_explore survives**

Run: `ls Notebooks && git status --porcelain | head`
Expected: `Notebooks/` contains only `biom_explore.ipynb`

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "chore: sweep notebooks, build artifacts, caches; tighten .gitignore"
```

---

### Task 10: Delete superseded docs (no archive — git history is the archive)

**Files:**
- Delete: `Docs/product-documentation/`, `Docs/engineering-playbook.md`, all `Docs/superpowers/plans/`, the old `Docs/superpowers/specs/`, the abundance decision
- Keep: feature-table HTML, the two `2026-06-03-workspace-*` specs, this reconciliation spec, `requirements.txt`, `research_capabilities.md`

- [ ] **Step 1: Delete the old docs**

```bash
git rm -r Docs/product-documentation
git rm Docs/engineering-playbook.md
git rm -r Docs/superpowers/plans
git rm Docs/superpowers/decisions/2026-05-25-abundance-count-semantics.md
git rm Docs/superpowers/specs/2026-05-25-askslm-lean-core-api-design.md \
       Docs/superpowers/specs/2026-05-26-agent-orchestrator-design.md \
       Docs/superpowers/specs/2026-05-26-cohort-replaces-profile-subset-design.md \
       Docs/superpowers/specs/2026-05-27-cohort-enrichment-and-splitting-design.md \
       Docs/superpowers/specs/2026-05-28-web-ui-readability-spec-b-design.md
```
> Note: this plan file (`Docs/superpowers/plans/2026-06-04-...`) is being deleted by the `git rm -r Docs/superpowers/plans` above. Before running it, the executor should copy this plan out (or run this task last and accept that the executed plan lives only in git history). Recommended: keep this plan until the work is merged, then delete in a follow-up — **skip the `plans/` line if executing live.**

- [ ] **Step 2: Trim stale deps from `requirements.txt`** — remove `pandera` (schema-validation contradicts the trust-input contract) and any of `plotly`/`ipywidgets`/`nbformat` not used by surviving code (grep first):

Run: `grep -rn "import plotly\|import ipywidgets\|import nbformat\|pandera" src Tests Notebooks --include='*.py' --include='*.ipynb'`
Remove from `requirements.txt` only the ones with no hits.

- [ ] **Step 3: Verify the kept docs remain**

Run: `ls Docs Docs/superpowers/specs`
Expected: `feature-table-and-library-palette.html`, `requirements.txt`, `research_capabilities.md`; specs dir has the two `2026-06-03-workspace-*` files + the reconciliation spec.

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "docs: delete superseded product-documentation, old plans/specs"
```

---

### Task 11: Reframe `CLAUDE.md`, `README.md`, `AGENTS.md`

**Files:**
- Modify: `CLAUDE.md`, `README.md`, `AGENTS.md`

- [ ] **Step 1: Rewrite `CLAUDE.md`** — replace the SRA overview + Layer Architecture + API Design + Two-DataFrame sections with the new model; keep the Branching Policy verbatim.

```markdown
# CLAUDE.md

## Project Overview

Ask-SLM is a workbench that makes metagenomic analysis easy and reproducible. The user works
entirely through a **web UI**, chatting with an **LLM agent** that builds and analyzes the study
with them — from raw inputs to results — and answers questions about the data.

The agent works by authoring and running Python against the `askslm` package and established
libraries (biom, ete3, scikit-bio, scipy, pandas), standardizing everything into one structure:
a **biom feature table** (counts + sample metadata + feature lineage).

Each study is a reproducible **workspace**: a plain folder of files on disk (Python scripts,
`.biom` tables, CSVs, plots), organized into phases (build → transform → analyze). The disk is
the source of truth; the web UI is the driver, not a walled garden. `Workspaces/ABX_new` is the
canonical example. The domain today is metagenomics; the structure is general enough to extend.

Design source of truth: `Docs/feature-table-and-library-palette.html`.

## Layout

```
src/askslm/   the toolbox the agent calls (workspace phase tooling, metadata, taxonomy, accessors, cli)
src/agent/    the LLM agent (run_python + session + registry)
src/web/      the web UI — the only thing the user touches
Workspaces/   runtime studies (git-ignored); ABX_new is canonical
Docs/ Tests/ Scripts/git-guard/
```

## The feature table

One `biom.Table` per community study: counts (features × samples) + sample metadata + feature
metadata (lineage). Five operation kinds — ingest, build, transform, split, analyze — delegate to
the library palette; Ask-SLM adds only the small logic libraries lack (chiefly `lineage_table`).
We trust input and fail fast: no defensive validation outside the accessor boundary.

## Branching Policy (enforced)

[... keep the existing Branching Policy section verbatim ...]
```

- [ ] **Step 2: Rewrite `README.md`** — product framing + the ABX_new phase-script style (not the retired `build_abundance_matrix` flow):

```markdown
# Ask-SLM

A workbench for reproducible metagenomic analysis. The user works through a web UI, chatting with
an LLM agent that builds and analyzes a study as a workspace of phase scripts — exactly like
`Workspaces/ABX_new`. The toolbox is the `askslm` package plus established libraries
(biom, ete3, scikit-bio, scipy, pandas).

## Install
```bash
pip install -r Docs/requirements.txt
pip install -e .
```
Python 3.12+. The ete3 NCBI database (`~/.etetoolkit/taxa.sqlite`) must be built locally.

## A workspace
A study is a folder of phases handed off through files on disk:
`0_inputs/ → 1_build/feature_table.biom → 2_transform/<exploration>/result/ → 3_analyze/<exploration>/<analysis>/`.
Scaffold with the CLI, never by hand:
```bash
askslm workspace new my_study
askslm transform add my_study no-control_bacteria
askslm analysis add my_study no-control_bacteria braycurtis
```
Every phase script starts `from askslm import workspace` then `ws = workspace.phase(__file__)`.
See `Workspaces/ABX_new` for a complete example and `Docs/feature-table-and-library-palette.html`
for the model.

## Tests
```bash
python -m pytest Tests -q
```
```

- [ ] **Step 3: Rewrite `AGENTS.md`** — delete the entire legacy section (Managers, DatasetAssemblyEngine, stage_01-05, old CLI command list, validation-against-old-CLI). Keep: the numbered-phase workflow, scaffold-CLI rules, the `from askslm import workspace` convention, biom-JSON serialization, the promotion rule. Update the architecture section to the `src/` layout and point to the feature-table bible + the two `2026-06-03-workspace-*` specs. Remove the `## Workspace conventions`, `## Mapping and taxonomy rules`, `## DatasetAssemblyEngine artifact flow`, and `## CLI entrypoints and aliases` sections entirely.

- [ ] **Step 4: Verify no stale model references survive in the three docs**

Run: `grep -ni "AbundanceMatrix\|DatasetAssembly\|metadata-overview\|two-DataFrame\|Layer Architecture\|Managers\|Client → Engine" CLAUDE.md README.md AGENTS.md`
Expected: no output

- [ ] **Step 5: Commit**

```bash
git add CLAUDE.md README.md AGENTS.md
git commit -m "docs: reframe CLAUDE/README/AGENTS to the agent-driven feature-table model"
```

---

### Task 12: Final verification

- [ ] **Step 1: No stale model code or imports anywhere in `src/`**

Run:
```bash
grep -rn "AbundanceMatrix\|matrix_writers\|Managers\|from Engines\|from Accessors\|from Common\|contracts.selectors\|ResolvedTaxonomy" src Tests --include='*.py' | grep -v __pycache__
```
Expected: no output

- [ ] **Step 2: Suite green**

Run: `python -m pytest Tests -q`
Expected: PASS

- [ ] **Step 3: ABX_new chain runs unedited**

Run the four scripts (build → explore → braycurtis → mann-whitney) as in Task 8 Step 7.
Expected: each prints its summary and writes its outputs; `git status` shows only regenerated workspace artifacts (which are git-ignored).

- [ ] **Step 4: Clean install**

Run: `pip install -e . && askslm workspace new _verify_tmp && rm -rf Workspaces/_verify_tmp`
Expected: install succeeds; the scaffold CLI stamps a workspace; one egg-info named `ask_slm`.

- [ ] **Step 5: Open a PR (do not merge)**

```bash
git push -u origin refactor-reconciliation-cleanup
gh pr create --base main --title "Project reconciliation & cleanup" \
  --body "Reconciles the codebase to the agent-driven feature-table model per Docs/superpowers/specs/2026-06-04-project-reconciliation-and-cleanup-design.html. Deletes the old AbundanceMatrix/Managers/matrix_writers stack, rewires the agent, consolidates source under src/, sweeps docs. ABX_new chain + suite green."
```
Then stop; the user squash-merges.

---

## Self-Review

**Spec coverage:**
- §2 definition → Task 11 (CLAUDE/README). ✓
- §3 survives/dies → Tasks 3-7 (trims + deletions), gated. ✓
- §4 agent surface → Tasks 1-2. ✓
- §5 src/ layout → Task 8. ✓
- §6 junk sweep + Docs disposition → Tasks 9-10. ✓
- §7 reframed docs → Task 11. ✓
- §8 order → tasks ordered rewire→trim→delete→move→sweep→docs. ✓
- §9 out of scope → respected (no Web UI re-spec, no new analyses). ✓
- §10 verification → Task 12. ✓

**Placeholder scan:** concrete code/commands given for every edit; deletions gated by exact greps with decision rules; the one genuinely investigative spot (requirements.txt trim) carries its grep + rule. No "TBD"/"handle edge cases".

**Type consistency:** `summarize_object`, `_feature_table`, `lineage_table`, `extract`, `overview`, `load`, `default_registry`, `MetadataOverview` used consistently across tasks. The recognized-type set (biom.Table / MetadataOverview / DataFrame) matches between `summaries.py` (Task 1), `_sandbox_worker.py` (Task 1), and the move rewrite (Task 8).

**Known caveat:** Task 10 deletes `Docs/superpowers/plans/`, which contains this plan — flagged inline to skip that line when executing live and delete the plan only post-merge.
