# Deletions & Integration — Implementation Plan (Plan 3 of 3)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the superseded layers (fat CLI, Manager orchestration, MappingEngine, old MetadataOverviewEngine, ENVO/ontology branch, DownstreamAnalysis, DatasetAssemblyEngine, old lineage-DB code, SraAccessor, RunnerContext/Logger/pipeline_contracts) and finish the lean-core integration with a proper top-level README and a CLAUDE.md aligned to the new layering. Plans 1 + 2 already added the new lean core (`from askslm import metadata, taxonomy`); nothing in it depends on what this plan deletes (verified by grep before drafting).

**Architecture invariant:** the lean core is self-contained — `Engines/{TaxonomyEngine,MetadataEngine}`, `Accessors/{TaxonomyAccessor/taxonomy_file_accessor.py, MergedDumpAccessor, MetadataAccessor, matrix_writers}`, `Common/contracts/{sra_schema, selectors, taxonomy_results, metadata_results}`, and `askslm/`. Every task here either removes legacy code that nothing in the core touches, or improves the surviving public-facing docs.

**Tech Stack:** git, pytest, grep. No new runtime code.

**Pre-flight (REQUIRED before starting):**
- Working tree must be CLEAN of WIP that touches the to-be-deleted files. The user has substantial in-flight changes in `cli.py`, `managers/`, `Engines/{DatasetAssemblyEngine,MetadataOverviewEngine}`, `Accessors/SraAccessor`, etc. Commit or stash that WIP first — every `git rm` below uses plain (non-`-f`) form and will REFUSE to clobber unstaged changes (which is the safe behaviour).
- Notebooks (`Notebooks/*.ipynb`) and large `Docs/` reorganisations are OUT OF SCOPE for this plan — the user owns those. We touch only `README.md` and `CLAUDE.md`.

**Per-task rhythm:**
1. **Pre-check** with grep that nothing outside the to-be-deleted set still imports from it. The grep command lists exactly what to expect; anything else means stop and investigate.
2. **`git rm`** the named files (plain form; no `-f`).
3. **Full suite** `python -m pytest Tests -q` from the repo root. The lean-core baseline is **63 passed, 0 failed** — every task must leave that intact.
4. **Commit** with a focused message (no `Co-Authored-By` line).

Note on case: git tracks `common/` and `tests/` lowercase even though the on-disk dirs read `Common/`, `Tests/` on macOS. The bash below uses the lowercase paths git actually stores.

---

## File Structure

This plan only DELETES (and writes two docs). No new code.

**Surviving structure (target):**
```
askslm/                        # public facade
Engines/
  TaxonomyEngine/              # load, resolve, build_abundance_matrix, get_profile_subset
  MetadataEngine/              # extract, overview
Accessors/
  TaxonomyAccessor/            # ONLY taxonomy_file_accessor.py + merged.dmp
  MergedDumpAccessor/          # NCBI merged.dmp reader
  MetadataAccessor/            # metadata.csv reader
  matrix_writers/              # counts/relative/maaslin/biom strategy
Common/contracts/              # sra_schema, selectors, taxonomy_results, metadata_results
Tests/                         # only the lean-core suite (taxonomy + metadata + e2e)
README.md                      # canonical lean-core usage
CLAUDE.md                      # reflects Engine → Accessor (no Manager)
```

---

## Task 1: Delete the fat CLI + the top-level shell + their tests

**Files to delete:** `cli.py`, `askslm.py`, `tests/unit/test_cli_top_values_formatting.py`, `tests/e2e/test_cli_end_to_end.py`.

- [ ] **Pre-check** — confirm nothing else imports from `cli` or `askslm` (the file, not the package):
  ```bash
  grep -rE "^(from|import) cli($|[. ])|^from askslm import build_parser|^import askslm($|[. ])" --include='*.py' . | grep -v -E '^(cli\.py|askslm\.py|tests/(unit/test_cli_top_values_formatting|e2e/test_cli_end_to_end)\.py):'
  ```
  Expected: NO output. Anything that prints means a consumer survives the deletion — STOP.

- [ ] **Delete:**
  ```bash
  git rm cli.py askslm.py tests/unit/test_cli_top_values_formatting.py tests/e2e/test_cli_end_to_end.py
  ```
  Confirm `from askslm import metadata, taxonomy` still works (the `askslm/` package wins now that `askslm.py` is gone):
  ```bash
  python -c "from askslm import metadata, taxonomy; print('ok')"
  ```

- [ ] **Verify:** `python -m pytest Tests -q` → expect 61 passed (was 63; minus 2 deleted CLI tests).

- [ ] **Commit:** `chore(cleanup): remove fat CLI shell and its tests`

> **Note for the user, not the implementer:** `Notebooks/Cli_Runner.ipynb` and any other notebook referencing `cli.py` will break at runtime. Updating notebooks is outside Plan 3's scope.

---

## Task 2: Delete the Manager layer

**Files to delete:** `managers/__init__.py`, `managers/analysis_pipeline_manager.py`, `managers/mapping_config_manager.py`, `tests/unit/test_mapping_config_manager_headless.py`.

- [ ] **Pre-check:**
  ```bash
  grep -rE "^(from|import) managers($|[. ])" --include='*.py' . | grep -v -E '^(managers/|tests/unit/test_mapping_config_manager_headless\.py):'
  ```
  Expected: NO output.

- [ ] **Delete:**
  ```bash
  git rm -r managers tests/unit/test_mapping_config_manager_headless.py
  ```

- [ ] **Verify:** `python -m pytest Tests -q` → expect 60 passed.

- [ ] **Commit:** `chore(cleanup): remove Manager orchestration layer`

---

## Task 3: Delete MappingEngine

**Files to delete:** `Engines/MappingEngine/__init__.py`, `Engines/MappingEngine/mapping_engine.py`, `tests/unit/test_metadata_passthrough_columns.py`.

- [ ] **Pre-check:**
  ```bash
  grep -rE "from Engines\.MappingEngine|from Engines import MappingEngine" --include='*.py' . | grep -v -E '^(Engines/MappingEngine/|tests/unit/test_metadata_passthrough_columns\.py):'
  ```
  Expected: NO output.

- [ ] **Delete:**
  ```bash
  git rm -r Engines/MappingEngine tests/unit/test_metadata_passthrough_columns.py
  ```

- [ ] **Verify:** `python -m pytest Tests -q` → expect 59 passed.

- [ ] **Commit:** `chore(cleanup): remove MappingEngine (AI handles metadata mapping)`

---

## Task 4: Delete the ENVO / ontology / metalog branch

**Files to delete:** `Engines/EnvoResolutionEngine/`, `Accessors/OntologyAccessor/`, `Accessors/MetalogAccessor/`, `Scripts/scrape_metalog.py`.

- [ ] **Pre-check:**
  ```bash
  grep -rE "EnvoResolutionEngine|OntologyAccessor|MetalogAccessor|scrape_metalog" --include='*.py' . | grep -v -E '^(Engines/EnvoResolutionEngine/|Accessors/(Ontology|Metalog)Accessor/|Scripts/scrape_metalog\.py):'
  ```
  Expected: NO output.

- [ ] **Delete:**
  ```bash
  git rm -r Engines/EnvoResolutionEngine Accessors/OntologyAccessor Accessors/MetalogAccessor Scripts/scrape_metalog.py
  ```
  If `Scripts/` becomes empty after this, remove it too: `[ -z "$(git ls-files Scripts)" ] && rmdir Scripts 2>/dev/null; true`.

- [ ] **Verify:** `python -m pytest Tests -q` → expect 59 passed (no test deletions in this task).

- [ ] **Commit:** `chore(cleanup): remove ENVO ontology / metalog branch`

---

## Task 5: Delete DownstreamAnalysis engines

**Files to delete:** entire `Engines/DownstreamAnalysis/` subtree (AlphaDiversity, TaxonomicAbundance, LongitudinalAnalysisEngine, plus `__init__.py`).

- [ ] **Pre-check:**
  ```bash
  grep -rE "from Engines\.DownstreamAnalysis|from Engines import DownstreamAnalysis" --include='*.py' . | grep -v '^Engines/DownstreamAnalysis/'
  ```
  Expected: NO output.

- [ ] **Delete:**
  ```bash
  git rm -r Engines/DownstreamAnalysis
  ```

- [ ] **Verify:** `python -m pytest Tests -q` → expect 59 passed.

- [ ] **Commit:** `chore(cleanup): remove DownstreamAnalysis engines (handled by 3rd-party libs)`

---

## Task 6: Delete the OLD MetadataOverviewEngine

**Files to delete:** entire `Engines/MetadataOverviewEngine/` subtree.

- [ ] **Pre-check:**
  ```bash
  grep -rE "from Engines\.MetadataOverviewEngine|from Engines import MetadataOverviewEngine" --include='*.py' . | grep -v '^Engines/MetadataOverviewEngine/'
  ```
  Expected: NO output.

- [ ] **Delete:**
  ```bash
  git rm -r Engines/MetadataOverviewEngine
  ```

- [ ] **Verify:** `python -m pytest Tests -q` → expect 59 passed.

- [ ] **Commit:** `chore(cleanup): remove superseded MetadataOverviewEngine`

---

## Task 7: Delete the DatasetAssemblyEngine + its test

**Files to delete:** entire `Engines/DatasetAssemblyEngine/` subtree (incl. the duplicate `TaxonomyResolver.py`, `runtime_assembly/`, `runtime_assembly_*.py`, `dataset_assembly_engine.py`, `__init__.py`), plus `tests/unit/test_taxonomy_merge_resolution.py` (it imports from the old subtree).

- [ ] **Pre-check:**
  ```bash
  grep -rE "from Engines\.DatasetAssemblyEngine|from Engines import DatasetAssemblyEngine" --include='*.py' . | grep -v -E '^(Engines/DatasetAssemblyEngine/|tests/unit/test_taxonomy_merge_resolution\.py):'
  ```
  Expected: NO output.

- [ ] **Delete:**
  ```bash
  git rm -r Engines/DatasetAssemblyEngine tests/unit/test_taxonomy_merge_resolution.py
  ```

- [ ] **Verify:** `python -m pytest Tests -q` → expect 58 passed (one more test removed).

- [ ] **Commit:** `chore(cleanup): remove DatasetAssemblyEngine (superseded by TaxonomyEngine)`

---

## Task 8: Delete the old lineage-DB + dump accessor; slim TaxonomyAccessor/__init__.py

**Files to delete:** `Accessors/TaxonomyAccessor/taxonomy_accessor.py` (the old persisted lineage-DB class), `Accessors/TaxonomyAccessor/taxonomy_dump_accessor.py` (the old `TaxonomyDumpAccessor`).

**File to rewrite:** `Accessors/TaxonomyAccessor/__init__.py` (currently exports both deleted classes — must drop those exports).

**Keep:** `Accessors/TaxonomyAccessor/taxonomy_file_accessor.py` and `Accessors/TaxonomyAccessor/merged.dmp` (consumed by `MergedDumpAccessor`).

- [ ] **Pre-check** — at this point Tasks 1, 2, 5, 7 have all run, so the only remaining consumers of these classes should be the files themselves and the to-be-rewritten `__init__.py`:
  ```bash
  grep -rE "TaxonomyDumpAccessor|from Accessors\.TaxonomyAccessor\.(taxonomy_accessor|taxonomy_dump_accessor)|from Accessors\.TaxonomyAccessor import TaxonomyAccessor" --include='*.py' .
  ```
  Expected output: ONLY references inside `Accessors/TaxonomyAccessor/` (the two files being deleted + the `__init__.py` re-exports). No outside consumers.

- [ ] **Rewrite `Accessors/TaxonomyAccessor/__init__.py` to EXACTLY:**
  ```python
  ```
  (empty file — the facade and tests import via the full submodule path `from Accessors.TaxonomyAccessor.taxonomy_file_accessor import TaxonomyFileAccessor`, mirroring how the package has been used throughout Plans 1 + 2)

- [ ] **Delete:**
  ```bash
  git rm Accessors/TaxonomyAccessor/taxonomy_accessor.py Accessors/TaxonomyAccessor/taxonomy_dump_accessor.py
  git add Accessors/TaxonomyAccessor/__init__.py
  ```

- [ ] **Verify:** `python -m pytest Tests -q` → expect 58 passed.

- [ ] **Commit:** `chore(cleanup): remove persisted lineage DB and old dump accessor`

---

## Task 9: Delete SraAccessor

**Files to delete:** entire `Accessors/SraAccessor/` subtree.

- [ ] **Pre-check:**
  ```bash
  grep -rE "from Accessors\.SraAccessor|from Accessors import SraAccessor|SRA(Metadata|Taxonomy|Workspace)Accessor|SRAAccessor" --include='*.py' . | grep -v '^Accessors/SraAccessor/'
  ```
  Expected: NO output. (The new `MetadataFileAccessor` and `TaxonomyFileAccessor` replaced these readers in Plans 1 + 2.)

- [ ] **Delete:**
  ```bash
  git rm -r Accessors/SraAccessor
  ```

- [ ] **Verify:** `python -m pytest Tests -q` → expect 58 passed.

- [ ] **Commit:** `chore(cleanup): remove SraAccessor (superseded by domain file accessors)`

---

## Task 10: Delete RunnerContext / Logger / pipeline_contracts

**Files to delete:** `common/RunnerContext.py`, `common/Logger.py`, `common/contracts/pipeline_contracts.py`.

- [ ] **Pre-check:**
  ```bash
  grep -rE "from Common\.(RunnerContext|Logger)|from Common\.contracts\.pipeline_contracts|from common\.(RunnerContext|Logger)|from common\.contracts\.pipeline_contracts" --include='*.py' . | grep -v -E '^common/(RunnerContext\.py|Logger\.py|contracts/pipeline_contracts\.py):'
  ```
  Expected: NO output. (The lean core uses standard `logging`, no `RunnerContext`, no stage DTOs.)

- [ ] **Delete:**
  ```bash
  git rm common/RunnerContext.py common/Logger.py common/contracts/pipeline_contracts.py
  ```

- [ ] **Verify:** `python -m pytest Tests -q` → expect 58 passed.

- [ ] **Commit:** `chore(cleanup): remove RunnerContext, Logger, and pipeline_contracts`

---

## Task 11: README + CLAUDE.md aligned with the lean core

**Files to modify:** `README.md` (currently a 2-line stub), `CLAUDE.md` (currently describes `Client → Manager → Engine → Accessor`; the Manager layer is gone).

### Step A — Replace `README.md` with EXACTLY:

```markdown
# Ask-SLM

A small, well-tested Python toolkit for metagenomic analysis of SRA datasets. Public API exposes two domains — `metadata` and `taxonomy` — and is designed to hand its output to third-party libraries (scikit-bio, scipy, MaAsLin2, …) for downstream statistics.

## Install

```bash
pip install -r Docs/requirements.txt
```

Python 3.11+ recommended.

## Canonical usage

```python
from askslm import metadata, taxonomy
from askslm.contracts import SubsetCriteria, TaxaSelector, SampleSelector

# Metadata: expand jattr/attributes blobs into real columns, then summarize.
metadata_df = metadata.extract("metadata.csv")
overview = metadata.overview(metadata_df)
overview.write("out/metadata_overview")

# Taxonomy: load → resolve deprecated NCBI tax_ids → build a single-rank,
# non-overlapping abundance matrix (default rank='genus', value = each rank-node's
# total_count, plus one Unclassified_<rank> bucket per sample).
taxonomy_df = taxonomy.load("taxonomy.csv")
resolved    = taxonomy.resolve(taxonomy_df)
matrix      = taxonomy.build_abundance_matrix(resolved.df)
matrix.write("out/abundance_maaslin.tsv", fmt="maaslin")

# Slice the matrix by clade + sample for downstream analysis. The subset returns
# two aligned DataFrames; they are never merged (two-DataFrame rule).
subset = taxonomy.get_profile_subset(
    matrix,
    metadata_df,
    SubsetCriteria(
        taxa=TaxaSelector(rank="superkingdom", names=("Bacteria",)),
        samples=SampleSelector(column="Group", values=("treatment",)),
    ),
)
subset.profile_df    # samples × bacterial taxa
subset.metadata_df   # aligned metadata, lazy
```

## Design

- Architecture and API contract: `Docs/superpowers/specs/2026-05-25-askslm-lean-core-api-design.md`
- Why abundance is single-rank `total_count` + `Unclassified_<rank>` (avoids double-counting cumulative clade counts): `Docs/superpowers/decisions/2026-05-25-abundance-count-semantics.md`

## Tests

```bash
python -m pytest Tests -q
```
```

### Step B — Update `CLAUDE.md` so the layering table reflects the lean core (Manager removed).

Read `CLAUDE.md` first. Find the layer table (the rows are: Client | Clients/ | …, Manager | Managers/ | …, Engine | Engines/ | …, Accessor | Accessors/ | …, Utilities | Common/ | …). Make these changes:

1. **Delete the `Manager` row entirely.**
2. **Change the calling-rules line** from `Client → Manager → Engine → Accessor` to `Client → Engine → Accessor`.
3. **In the `Client` row**, replace the role description with: `Public Python API (askslm.metadata, askslm.taxonomy). A user-facing CLI/UI is deferred to a separate layer.`
4. **Leave the rest of the file unchanged** (project overview, workspace structure, API design decisions, two-DataFrame rule, accessor rule). Do NOT touch unrelated sections.

### Verify and commit

- [ ] `python -m pytest Tests -q` → expect 58 passed (no test changes).
- [ ] `git add README.md CLAUDE.md`
- [ ] **Commit:** `docs: rewrite README for lean core and drop Manager layer from CLAUDE.md`

---

## Self-Review (completed by plan author)

**Spec coverage:** removes every module flagged for deletion in the spec (§2.2) — Managers (T2), MappingEngine (T3), ENVO/Ontology/MetalogAccessor + scrape script (T4), DownstreamAnalysis (T5), old MetadataOverviewEngine (T6), DatasetAssemblyEngine incl. stage machinery + duplicate TaxonomyResolver (T7), persisted lineage DB code (T8), SraAccessor (T9), pipeline_contracts/RunnerContext/Logger (T10), fat CLI + top-level shell (T1). Reconciles `askslm.py` vs `askslm/` (T1) and refreshes README + CLAUDE.md (T11).

**Placeholder scan:** none — every step is an exact command or exact file content.

**Idempotency / safety:** every `git rm` is the plain non-`-f` form, so any unstaged WIP on the target file aborts the task instead of silently destroying work. Each task ends with the full suite — the green-bar count is stated explicitly per task so any regression is obvious.

**Out-of-scope (deferred):** `Notebooks/` (user's WIP); broader `Docs/` reorganisation; the optional `resolve()` double-traversal perf cleanup and the verbatim-relocated `TaxonomyResolver` style polish noted in the Plan-1 final review (both non-blocking, low value, can be done later as a small targeted PR).
