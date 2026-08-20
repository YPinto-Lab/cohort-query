# Session Run-Directory, Logging & SLURM Run UX Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every question gets a `plans/<ts>/` folder with an auto-saved plan and a full log; `Run it` submits a real SLURM job (CPU or GPU) instead of running on the login node, and progress can be watched from any terminal, surviving the submitting shell dying.

**Architecture:** Extract the testable mechanics into small new modules (`cli/rundir.py` for plan folders + logging, `cli/jobs.py` for sbatch templating/submission/status, `cli/worker.py` as the LLM-free SLURM entrypoint, `cli/watch.py` for the shared live-progress view) so `build.py`/`adapters.py`/`runtime.py` gain a few narrow, unit-testable hooks (`on_step` callback, a `gpu` mode, structured logging). `cli/session.py` wires all of it together but stays untested glue, exactly as it is today (its own module docstring already says so) — verified by running it.

**Tech Stack:** Python stdlib `logging`, `subprocess` (for `sbatch`/`squeue`/`scancel`), `argparse`; existing `questionary`/`rich` for the terminal; DuckDB + Anna Shafir's pre-built Sirius GPU extension for the optional GPU path.

**Design:** `Docs/superpowers/specs/2026-08-20-session-logging-and-run-ux-design.html`. Read it — it has the "why" behind every decision below, including the real sbatch numbers pulled from Anna's own working job scripts on the cluster.

**One correction made while translating the spec to code:** the spec's §5.2 says `askslm load` "creates its own timestamped folder" *and* separately "checks that folder for `job.id`" to reattach — those two statements don't fit together (a brand-new folder can never already have a `job.id` in it). This plan resolves it the simpler way: `askslm load <path>` uses `<path>.parent` directly as its plan folder (which is exactly the folder that already holds `log.txt`/`job.id`/etc. if a job was submitted from it), and its `Discard` deletes everything in that folder *except* the `plan.json` path the caller passed in — see Task 9.

---

## Prerequisites

```bash
git fetch origin && git switch -c feature/session-slurm-ux origin/main
```

Never delete branches. Finish with push + `gh pr create --base main`, then stop.

## Context

- **Run tests:** `python3 -m pytest Tests/ -q` from the repo root. Baseline **84 passing**.
- House style: no `lambda` — always a named `def`; readability first; trust input and fail fast (the sanctioned validation points are `config()` and the LLM boundary); no backward-compat aliases/shims; compose over duplicate; no comments that explain *what*, only non-obvious *why*.
- `session.py`'s own docstring already states it is glue, verified by running it, not by a test suite — this plan keeps that convention. Everything genuinely testable is pulled out of it into the new modules below, which *do* get tests.
- `runtime.cohort_builder()` never touches `runtime.backend()` — only `runtime.database()`. This is why the SLURM worker never needs an LLM key (verified by reading `runtime.py`).
- Anna Shafir's real, working job scripts (read 2026-08-20 at `/private/pinto-lab/anna/`): `run_duckdb.sh` (CPU: `cpu192G-48h`, 18 cpus, 64G, 4h) and `run_sirius.sh` (GPU: `H200-12h`, 48 cpus, `--gres=gpu:1`, 1T, 4h) — this plan's sbatch templates use scaled-down numbers agreed with the user (8 cpus/48G/2h CPU; 16 cpus/128G/2h GPU), same partitions.
- The Sirius GPU extension already exists on the cluster at `/private/pinto-lab/anna/sirius/build/sirius.duckdb_extension` — her own home-directory build, not a tools-owned path. This plan wires askslm to load it by that path; it is not rebuilt or vendored here.
- `askslm run <path>` is being renamed `askslm load <path>` at the `main()` dispatch — this is a shell-level rename only, `Plan.run(...)` the Python method is untouched.

## File Structure

| File | Responsibility |
|---|---|
| `src/askslm/cli/rundir.py` | **new.** `plans/<ts>/` folder creation; attach/detach a per-folder log file handler. |
| `src/askslm/build.py` | **modify.** `CohortBuilder.build` gains an `on_step` callback fired before each of its 3 phases. |
| `src/askslm/plan.py` | **modify.** `Plan.run` threads `on_step` through to `build`. |
| `src/askslm/adapters.py` | **modify.** `DuckDbConnection` gains a `gpu` mode (Sirius extension) and logs every query; `GeminiBackend` logs its three LLM calls. |
| `src/askslm/runtime.py` | **modify.** `Settings.gpu` field; `database()` passes it to `DuckDbConnection`. |
| `src/askslm/__init__.py` | **modify.** `config(..., gpu: bool = False)`. |
| `src/askslm/cli/jobs.py` | **new.** sbatch templates (CPU/GPU), `submit`/`squeue_state`/`cancel` (all via an injectable `run=subprocess.run`), and `job.id`/`status.txt` read/write. |
| `src/askslm/cli/worker.py` | **new.** The SLURM entrypoint: loads a saved plan, builds with no LLM, writes status/report. |
| `src/askslm/cli/watch.py` | **new.** The live progress view shared by "Run it → Watch progress" and `askslm load` reattach. |
| `src/askslm/cli/session.py` | **modify.** Plan folders, autosave, new menu (SQL/overlap inlined, Discard/Ask-new-question, no more Save-and-quit), single-option auto-decide, SLURM submission, `run`→`load` rename + reattach. |
| `Tests/test_rundir.py` | **new.** |
| `Tests/test_build_progress.py` | **new.** |
| `Tests/test_attached_mirror.py` | **modify.** GPU-wrap + query-logging tests added. |
| `Tests/test_gemini_backend.py` | **modify.** Logging tests added. |
| `Tests/test_runtime_gpu.py` | **new.** |
| `Tests/test_jobs.py` | **new.** |
| `Tests/test_worker.py` | **new.** |
| `Tests/test_watch.py` | **new.** |

---

### Task 1: Plan folders + per-folder logging

**Files:**
- Create: `src/askslm/cli/rundir.py`
- Test: `Tests/test_rundir.py`

- [ ] **Step 1: Write the failing test**

```python
"""One plan folder per question, created immediately -- and the log handler that
makes every SQL/LLM call inside it land in that folder's log.txt."""
import logging

from askslm.cli import rundir


def test_new_plan_dir_is_timestamped_and_already_created(tmp_path):
    plan_dir = rundir.new_plan_dir(root=tmp_path)

    assert plan_dir.parent == tmp_path
    assert plan_dir.exists()
    assert len(plan_dir.name) == 15                # YYYYMMDD_HHMMSS


def test_attached_handler_captures_askslm_logger_records(tmp_path):
    plan_dir = rundir.new_plan_dir(root=tmp_path)
    handler = rundir.attach_log_handler(plan_dir)

    logging.getLogger("askslm.adapters").info("hello from a query")
    rundir.detach_log_handler(handler)

    assert "hello from a query" in (plan_dir / "log.txt").read_text()


def test_detached_handler_no_longer_receives_records(tmp_path):
    plan_dir = rundir.new_plan_dir(root=tmp_path)
    handler = rundir.attach_log_handler(plan_dir)
    rundir.detach_log_handler(handler)

    logging.getLogger("askslm.adapters").info("should not appear")

    assert (plan_dir / "log.txt").read_text() == ""
```

- [ ] **Step 2: Run it, confirm it fails on the missing module**

Run: `python3 -m pytest Tests/test_rundir.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'askslm.cli.rundir'`

- [ ] **Step 3: Implement `rundir.py`**

```python
"""Per-question plan folders: plans/<ts>/ created the instant a question is
submitted, so a run leaves a trail even if ask() throws before anything else."""
from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

PLANS_ROOT = Path("plans")
LOGGER_NAME = "askslm"


def new_plan_dir(root: Path = PLANS_ROOT) -> Path:
    plan_dir = root / datetime.now().strftime("%Y%m%d_%H%M%S")
    plan_dir.mkdir(parents=True)
    return plan_dir


def attach_log_handler(plan_dir: Path) -> logging.Handler:
    handler = logging.FileHandler(plan_dir / "log.txt")
    handler.setFormatter(logging.Formatter("%(asctime)s %(name)s %(message)s"))
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    return handler


def detach_log_handler(handler: logging.Handler) -> None:
    logging.getLogger(LOGGER_NAME).removeHandler(handler)
    handler.close()
```

- [ ] **Step 4: Run it, confirm it passes**

Run: `python3 -m pytest Tests/test_rundir.py -q`
Expected: `3 passed`

- [ ] **Step 5: Commit**

```bash
git add src/askslm/cli/rundir.py Tests/test_rundir.py
git commit -m "feat(cli): per-question plan folders with attachable file logging"
```

---

### Task 2: `on_step` progress callback on `CohortBuilder.build`

**Files:**
- Modify: `src/askslm/build.py`
- Modify: `src/askslm/plan.py`
- Test: `Tests/test_build_progress.py`

- [ ] **Step 1: Write the failing test**

```python
"""on_step lets a caller (the SLURM worker) log which phase is running, without
CohortBuilder knowing anything about logging or SLURM."""
import askslm
from askslm.adapters import CannedLlmBackend, DuckDbConnection
from askslm.translation import SourceQuery, Translation

from fixtures.mirror import build_fixture_mirror

TRANSLATION = Translation(
    interpretation="gut metagenomes",
    queries=(SourceQuery(askslm.Source.METALOG_METADATA,
                         "SELECT * FROM metalog_metadata"),))


def test_on_step_is_called_for_each_phase_in_order(tmp_path):
    path = build_fixture_mirror(tmp_path / "fixture.duckdb")
    connection = DuckDbConnection(path)
    askslm.config(db=path, database=connection, backend=CannedLlmBackend(TRANSLATION))
    plan = askslm.ask("gut metagenomes")
    seen = []

    plan.run(profile_sources=askslm.Source.METALOG_MOTUS3, on_step=seen.append)

    assert seen == ["discovering cohort", "reading profile matrix",
                    "assembling and writing biom"]
    connection.close()


def test_on_step_defaults_to_doing_nothing(tmp_path):
    """Every existing caller of Plan.run passes no on_step -- this must not break."""
    path = build_fixture_mirror(tmp_path / "fixture.duckdb")
    connection = DuckDbConnection(path)
    askslm.config(db=path, database=connection, backend=CannedLlmBackend(TRANSLATION))
    plan = askslm.ask("gut metagenomes")

    table, report = plan.run(profile_sources=askslm.Source.METALOG_MOTUS3)

    assert report.biosamples > 0
    connection.close()
```

- [ ] **Step 2: Run it, confirm it fails**

Run: `python3 -m pytest Tests/test_build_progress.py -q`
Expected: FAIL with `TypeError: run() got an unexpected keyword argument 'on_step'`

- [ ] **Step 3: Add `on_step` to `CohortBuilder.build`**

In `src/askslm/build.py`, add the import and a module-level no-op, then extend `CohortBuilder.build`:

```python
from typing import Callable
```

(add this import near the top, alongside the existing `dataclasses`/`pathlib` imports)

```python
def _noop_step(label: str) -> None:
    pass
```

(add this function above `class CohortBuilder`)

Replace the existing `CohortBuilder.build` method with:

```python
    def build(self, queries, request: Materialization, out: Path | None,
             on_step: Callable[[str], None] | None = None) -> tuple[biom.Table, BuildReport]:
        step = on_step or _noop_step
        step("discovering cohort")
        cohort = self._discovery.discover(queries)
        step("reading profile matrix")
        matrix = self._profiles.read(request.profile_sources, cohort.union())
        step("assembling and writing biom")
        metadata = self._metadata.reconciled(cohort, request.metadata_winning_source)
        table = self._factory.build(matrix, metadata.restricted_to(matrix.biosamples()))
        return self._written(table, out), self._report(request, cohort, matrix)
```

- [ ] **Step 4: Thread `on_step` through `Plan.run`**

In `src/askslm/plan.py`, change the `Sequence` import line to also bring in `Callable`:

```python
from typing import Callable, Sequence
```

Replace the existing `Plan.run` method with:

```python
    def run(self, profile_sources: Source | Sequence[Source],
            out: Path | None = None,
            metadata_winning_source: Source = Source.METALOG_METADATA,
            on_step: Callable[[str], None] | None = None
            ) -> tuple[biom.Table, BuildReport]:
        self._guard_runnable()
        request = Materialization(profile_sources=_as_tuple(profile_sources),
                                  metadata_winning_source=metadata_winning_source)
        return runtime.cohort_builder().build(self.translation.queries, request, out,
                                              on_step=on_step)
```

- [ ] **Step 5: Run it, confirm it passes, then run the full suite**

Run: `python3 -m pytest Tests/test_build_progress.py -q`
Expected: `2 passed`

Run: `python3 -m pytest Tests/ -q`
Expected: `86 passed` (84 baseline + 2 new)

- [ ] **Step 6: Commit**

```bash
git add src/askslm/build.py src/askslm/plan.py Tests/test_build_progress.py
git commit -m "feat(build): on_step progress callback through Plan.run"
```

---

### Task 3: GPU mode on `DuckDbConnection` (Anna's Sirius extension)

**Files:**
- Modify: `src/askslm/adapters.py`
- Modify: `Tests/test_attached_mirror.py`

- [ ] **Step 1: Write the failing test**

Add to `Tests/test_attached_mirror.py` (keep the existing tests and fixtures in that
file unchanged; this only adds new tests and a new import):

```python
from askslm.adapters import _gpu_wrapped


def test_gpu_mode_wraps_the_sql_in_gpu_processing():
    assert (_gpu_wrapped("SELECT 1", gpu=True)
           == "SELECT * FROM gpu_processing($$ SELECT 1 $$)")


def test_cpu_mode_leaves_the_sql_unchanged():
    assert _gpu_wrapped("SELECT 1", gpu=False) == "SELECT 1"
```

- [ ] **Step 2: Run it, confirm it fails**

Run: `python3 -m pytest Tests/test_attached_mirror.py -q`
Expected: FAIL with `ImportError: cannot import name '_gpu_wrapped'`

- [ ] **Step 3: Add the GPU mode to `DuckDbConnection`**

In `src/askslm/adapters.py`, add a module-level constant near the top (below the
existing imports):

```python
SIRIUS_EXTENSION_PATH = "/private/pinto-lab/anna/sirius/build/sirius.duckdb_extension"
```

Add this function above `class DuckDbConnection`:

```python
def _gpu_wrapped(sql: str, gpu: bool) -> str:
    if not gpu:
        return sql
    return f"SELECT * FROM gpu_processing($$ {sql} $$)"
```

Replace `DuckDbConnection.__init__` and `query` with:

```python
    def __init__(self, db_path: Path, gpu: bool = False):
        self._connection = duckdb.connect(str(db_path), read_only=True)
        self._attach_sources()
        self._gpu = gpu
        if gpu:
            self._connection.execute(f"LOAD '{SIRIUS_EXTENSION_PATH}'")
            self._connection.execute("SELECT gpu_buffer_init()")

    def query(self, sql: str, params: list | None = None) -> pd.DataFrame:
        return self._connection.execute(_gpu_wrapped(sql, self._gpu),
                                        params or []).fetch_df()
```

(The logging added to `query` in Task 4 replaces this version of the method again —
this step only adds the `gpu` wrapping so it can be tested and committed on its own.)

- [ ] **Step 4: Run it, confirm it passes, then run the full suite**

Run: `python3 -m pytest Tests/test_attached_mirror.py -q`
Expected: `5 passed` (3 existing + 2 new)

Run: `python3 -m pytest Tests/ -q`
Expected: `88 passed`

- [ ] **Step 5: Commit**

```bash
git add src/askslm/adapters.py Tests/test_attached_mirror.py
git commit -m "feat(adapters): opt-in GPU mode wrapping queries in gpu_processing()"
```

**Not covered by this test (deliberately):** actually loading
`SIRIUS_EXTENSION_PATH` requires the real compiled extension on the cluster and is not
something CI can exercise — no automated test constructs `DuckDbConnection(path,
gpu=True)`. This is verified by running a real GPU job (Task 9's manual checklist),
the same way `GeminiBackend`'s real network call is never automated-tested either
(`StubClient` stands in for it).

---

### Task 4: Structured logging in `adapters.py`

**Files:**
- Modify: `src/askslm/adapters.py`
- Modify: `Tests/test_attached_mirror.py`
- Modify: `Tests/test_gemini_backend.py`

- [ ] **Step 1: Write the failing tests**

Add to `Tests/test_attached_mirror.py`:

```python
import logging


def test_query_logs_the_sql_and_row_count(caplog, tmp_path):
    import duckdb

    db_path = tmp_path / "t.duckdb"
    raw = duckdb.connect(str(db_path))
    raw.execute("CREATE TABLE t (x INTEGER)")
    raw.execute("INSERT INTO t VALUES (1), (2)")
    raw.close()
    caplog.set_level(logging.INFO, logger="askslm.adapters")

    connection = DuckDbConnection(db_path)
    connection.query("SELECT * FROM t")
    connection.close()

    assert any("SELECT * FROM t" in record.message for record in caplog.records)
```

Add to `Tests/test_gemini_backend.py` (add `import logging` alongside the existing
`import json`):

```python
def test_translate_logs_the_prompt_and_the_response(caplog):
    payload = json.dumps({"interpretation": "x", "queries": [], "failure": None})
    caplog.set_level(logging.INFO, logger="askslm.adapters")

    GeminiBackend(StubClient(payload), model="test-model").translate(_prompt())

    assert any("adults with IBD" in record.message for record in caplog.records)
    assert any(payload in record.message for record in caplog.records)
```

- [ ] **Step 2: Run them, confirm they fail**

Run: `python3 -m pytest Tests/test_attached_mirror.py Tests/test_gemini_backend.py -q`
Expected: FAIL — the new assertions find no matching log record (nothing logs yet)

- [ ] **Step 3: Add logging to `adapters.py`**

Add these imports near the top of `src/askslm/adapters.py` (alongside the existing
`json`/`Path` imports):

```python
import logging
import time
```

Add a module-level logger right after the imports, above `class DuckDbConnection`:

```python
_logger = logging.getLogger(__name__)
```

Replace `DuckDbConnection.query` (from Task 3) with:

```python
    def query(self, sql: str, params: list | None = None) -> pd.DataFrame:
        start = time.monotonic()
        frame = self._connection.execute(_gpu_wrapped(sql, self._gpu),
                                         params or []).fetch_df()
        _logger.info("SQL (%.2fs, %d rows): %s", time.monotonic() - start, len(frame), sql)
        return frame
```

Replace `GeminiBackend.translate` with:

```python
    def translate(self, prompt: TranslationPrompt) -> Translation:
        start = time.monotonic()
        response = self._client.models.generate_content(
            model=self._model,
            contents=_prompt_text(prompt),
            config={"system_instruction": SYSTEM_INSTRUCTION,
                    "response_mime_type": "application/json",
                    # We pass no tools, so automatic function calling has nothing to do
                    # -- but it is ON by default, and the SDK then warns on every call
                    # that AFC belongs in Chat.send_message. Saying "off" states the
                    # intent and removes the warning at its cause.
                    "automatic_function_calling": {"disable": True}})
        _logger.info("translate (%.2fs)\nPROMPT: %s\nRESPONSE: %s",
                    time.monotonic() - start, prompt.question.text, response.text)
        return _translation_of(json.loads(_unfenced(response.text)))
```

Replace `GeminiBackend.expand` with:

```python
    def expand(self, question: str) -> list[str]:
        """Never raises: a failed expansion must degrade to plain lexical matching,
        not take down ask()."""
        start = time.monotonic()
        try:
            response = self._client.models.generate_content(
                model=self.HELPER_MODEL, contents=question,
                config={"system_instruction": EXPANSION_INSTRUCTION,
                        "response_mime_type": "application/json",
                        "automatic_function_calling": {"disable": True}})
            terms = json.loads(_unfenced(response.text)).get("terms", [])
        except Exception:
            _logger.info("expand (%.2fs) failed for question=%r",
                         time.monotonic() - start, question)
            return []
        _logger.info("expand (%.2fs)\nQUESTION: %s\nRESPONSE: %s",
                    time.monotonic() - start, question, response.text)
        return [str(term).lower() for term in terms][:MAX_TERMS]
```

Replace `GeminiBackend.repair` with:

```python
    def repair(self, sql: str, error: str, columns: str) -> str:
        """One targeted retry. Never raises -- a failed repair leaves the original SQL
        and the original error, which is what the user would have seen anyway."""
        instruction = (
            "You are given SQL that a DuckDB database REJECTED, the exact error, and "
            "the real columns of the table. Return corrected SQL only -- no prose, no "
            "markdown fence. Use ONLY the listed columns. Keep the query's intent and "
            "its SELECT list unchanged. If a column the query wants does not exist, "
            "drop that condition rather than inventing a replacement.")
        start = time.monotonic()
        try:
            response = self._client.models.generate_content(
                model=self.HELPER_MODEL,
                contents=f"ERROR\n{error}\n\nCOLUMNS\n{columns}\n\nSQL\n{sql}",
                config={"system_instruction": instruction,
                        "automatic_function_calling": {"disable": True}})
            fixed = _unfenced(response.text) or sql
        except Exception:
            _logger.info("repair (%.2fs) failed for sql=%r", time.monotonic() - start, sql)
            return sql
        _logger.info("repair (%.2fs)\nSQL: %s\nERROR: %s\nFIXED: %s",
                    time.monotonic() - start, sql, error, fixed)
        return fixed
```

- [ ] **Step 4: Run them, confirm they pass, then run the full suite**

Run: `python3 -m pytest Tests/test_attached_mirror.py Tests/test_gemini_backend.py -q`
Expected: `6 passed`, `9 passed` respectively

Run: `python3 -m pytest Tests/ -q`
Expected: `90 passed`

- [ ] **Step 5: Commit**

```bash
git add src/askslm/adapters.py Tests/test_attached_mirror.py Tests/test_gemini_backend.py
git commit -m "feat(adapters): log every SQL query and every LLM call with timing"
```

---

### Task 5: `gpu` threaded through `runtime.py` and `config()`

**Files:**
- Modify: `src/askslm/runtime.py`
- Modify: `src/askslm/__init__.py`
- Test: `Tests/test_runtime_gpu.py`

- [ ] **Step 1: Write the failing test**

```python
"""config(gpu=...) has to actually reach DuckDbConnection's constructor -- an
interactive session's own connection must never be gpu mode; only a worker's
explicit config() call is."""
import askslm
from askslm import runtime


class _RecordingConnection:
    def __init__(self, db_path, gpu=False):
        self.db_path = db_path
        self.gpu = gpu


def test_database_passes_gpu_through_to_the_connection(tmp_path, monkeypatch):
    monkeypatch.setattr("askslm.runtime.DuckDbConnection", _RecordingConnection)
    db_path = tmp_path / "fixture.duckdb"
    db_path.touch()

    askslm.config(db=db_path, gpu=True)
    connection = runtime.database()

    assert connection.gpu is True


def test_gpu_defaults_to_false(tmp_path, monkeypatch):
    monkeypatch.setattr("askslm.runtime.DuckDbConnection", _RecordingConnection)
    db_path = tmp_path / "fixture.duckdb"
    db_path.touch()

    askslm.config(db=db_path)
    connection = runtime.database()

    assert connection.gpu is False
```

- [ ] **Step 2: Run it, confirm it fails**

Run: `python3 -m pytest Tests/test_runtime_gpu.py -q`
Expected: FAIL with `TypeError: config() got an unexpected keyword argument 'gpu'`

- [ ] **Step 3: Add the `gpu` field and thread it through**

In `src/askslm/runtime.py`, add a field to `Settings`:

```python
@dataclass(frozen=True)
class Settings:
    """Constructed from explicit arguments; knows nothing about config files or the
    environment. Whoever calls config() sources the values -- which is what lets this
    validation stay a plain fail-fast __post_init__."""
    db_path: Path
    llm: str = "canned"
    llm_key: str = ""
    llm_model: str = "gemini-2.5-flash"
    gpu: bool = False

    def __post_init__(self):
        if not Path(self.db_path).exists():
            raise ValueError(f"database file not found: {self.db_path}")
        if self.llm not in ("canned", "gemini"):
            raise ValueError(f"unknown llm {self.llm!r}: expected 'canned' or 'gemini'")
        if self.llm == "gemini" and not self.llm_key:
            raise ValueError("no API key: gemini needs one (HLD H.1)")
```

Replace `database()`:

```python
def database() -> Database:
    global _database
    if _database is None:
        settings = _require_settings()
        _database = DuckDbConnection(settings.db_path, gpu=settings.gpu)
    return _database
```

In `src/askslm/__init__.py`, replace `config`:

```python
def config(db: str | Path, llm: str = "canned", llm_key: str = "",
           llm_model: str = "gemini-2.5-flash", gpu: bool = False, **wiring) -> None:
    """Configure once. Fails fast if the database is missing or the llm name is unknown."""
    runtime.configure(
        runtime.Settings(db_path=Path(db), llm=llm, llm_key=llm_key,
                        llm_model=llm_model, gpu=gpu),
        **wiring)
```

- [ ] **Step 4: Run it, confirm it passes, then run the full suite**

Run: `python3 -m pytest Tests/test_runtime_gpu.py -q`
Expected: `2 passed`

Run: `python3 -m pytest Tests/ -q`
Expected: `92 passed`

- [ ] **Step 5: Commit**

```bash
git add src/askslm/runtime.py src/askslm/__init__.py Tests/test_runtime_gpu.py
git commit -m "feat: config(gpu=...) threaded through to DuckDbConnection"
```

---

### Task 6: `jobs.py` — sbatch templates, submission, status

**Files:**
- Create: `src/askslm/cli/jobs.py`
- Test: `Tests/test_jobs.py`

- [ ] **Step 1: Write the failing test**

```python
"""SLURM mechanics: templating, submission, status -- all through an injectable
`run` so no test needs a real cluster."""
import subprocess

import pytest

from askslm.cli import jobs


def test_cpu_template_names_the_partition_and_the_worker_command(tmp_path):
    script = jobs.render_sbatch(tmp_path, worker_cmd="python -m askslm.cli.worker",
                                gpu=False)

    assert "#SBATCH --partition=cpu192G-48h" in script
    assert "#SBATCH --cpus-per-task=8" in script
    assert "#SBATCH --mem=48G" in script
    assert "python -m askslm.cli.worker" in script
    assert "--gres=gpu" not in script


def test_gpu_template_requests_the_h200_partition_and_a_gpu(tmp_path):
    script = jobs.render_sbatch(tmp_path, worker_cmd="python -m askslm.cli.worker --gpu",
                                gpu=True)

    assert "#SBATCH --partition=H200-12h" in script
    assert "#SBATCH --cpus-per-task=16" in script
    assert "#SBATCH --mem=128G" in script
    assert "#SBATCH --gres=gpu:1" in script


def test_write_sbatch_writes_the_script_into_the_plan_folder(tmp_path):
    path = jobs.write_sbatch(tmp_path, worker_cmd="echo hi", gpu=False)

    assert path == tmp_path / "job.sbatch"
    assert "echo hi" in path.read_text()


def test_submit_parses_the_job_id_from_sbatch_stdout(tmp_path):
    def fake_run(args, **kwargs):
        return subprocess.CompletedProcess(args, 0,
                                           stdout="Submitted batch job 4213765\n", stderr="")

    job_id = jobs.submit(tmp_path / "job.sbatch", run=fake_run)

    assert job_id == "4213765"


def test_submit_raises_if_sbatch_output_is_unparseable(tmp_path):
    def fake_run(args, **kwargs):
        return subprocess.CompletedProcess(args, 0,
                                           stdout="sbatch: error: something broke\n", stderr="")

    with pytest.raises(RuntimeError, match="something broke"):
        jobs.submit(tmp_path / "job.sbatch", run=fake_run)


def test_squeue_state_reports_none_once_the_job_has_left_the_queue():
    def fake_run(args, **kwargs):
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    assert jobs.squeue_state("4213765", run=fake_run) is None


def test_squeue_state_reports_the_job_state_while_queued():
    def fake_run(args, **kwargs):
        return subprocess.CompletedProcess(args, 0, stdout="RUNNING\n", stderr="")

    assert jobs.squeue_state("4213765", run=fake_run) == "RUNNING"


def test_job_id_and_status_round_trip_through_the_plan_folder(tmp_path):
    jobs.write_job_id(tmp_path, "4213765")
    jobs.write_status(tmp_path, "RUNNING")

    assert jobs.read_job_id(tmp_path) == "4213765"
    assert jobs.read_status(tmp_path) == "RUNNING"


def test_missing_job_id_and_status_read_as_none(tmp_path):
    assert jobs.read_job_id(tmp_path) is None
    assert jobs.read_status(tmp_path) is None
```

- [ ] **Step 2: Run it, confirm it fails**

Run: `python3 -m pytest Tests/test_jobs.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'askslm.cli.jobs'`

- [ ] **Step 3: Implement `jobs.py`**

```python
"""SLURM job templating, submission, and status -- the mechanics 'Run it' needs to
submit a real sbatch job instead of running the build on the login node.

Resource numbers are scaled down from Anna Shafir's own proven-working jobs on this
cluster (run_duckdb.sh: cpu192G-48h/18cpu/64G/4h; run_sirius.sh: H200-12h/48cpu/
gres:gpu:1/1T/4h) -- hers ran a full 39M-row unfiltered join; a cohort build reads an
already-discovered, cohort-scoped set of biosamples off stat_coverage. Revisit with
real timing once a few builds have run.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

CPU_TEMPLATE = """#!/bin/bash
#SBATCH --job-name=askslm-cohort
#SBATCH --partition=cpu192G-48h
#SBATCH --cpus-per-task=8
#SBATCH --mem=48G
#SBATCH --time=02:00:00
#SBATCH --output={plan_dir}/slurm-%j.out
#SBATCH --error={plan_dir}/slurm-%j.err

{worker_cmd}
"""

GPU_TEMPLATE = """#!/bin/bash
#SBATCH --job-name=askslm-cohort-gpu
#SBATCH --partition=H200-12h
#SBATCH --cpus-per-task=16
#SBATCH --mem=128G
#SBATCH --gres=gpu:1
#SBATCH --time=02:00:00
#SBATCH --output={plan_dir}/slurm-%j.out
#SBATCH --error={plan_dir}/slurm-%j.err

{worker_cmd}
"""


def render_sbatch(plan_dir: Path, worker_cmd: str, gpu: bool) -> str:
    template = GPU_TEMPLATE if gpu else CPU_TEMPLATE
    return template.format(plan_dir=plan_dir, worker_cmd=worker_cmd)


def write_sbatch(plan_dir: Path, worker_cmd: str, gpu: bool) -> Path:
    path = plan_dir / "job.sbatch"
    path.write_text(render_sbatch(plan_dir, worker_cmd, gpu))
    return path


def submit(script_path: Path, run=subprocess.run) -> str:
    result = run(["sbatch", str(script_path)], capture_output=True, text=True, check=True)
    match = re.search(r"Submitted batch job (\d+)", result.stdout)
    if not match:
        raise RuntimeError(f"could not parse a job id from sbatch output: {result.stdout!r}")
    return match.group(1)


def squeue_state(job_id: str, run=subprocess.run) -> str | None:
    """None means the job is no longer in the queue -- finished, one way or another."""
    result = run(["squeue", "-j", job_id, "-h", "-o", "%T"], capture_output=True, text=True)
    state = result.stdout.strip()
    return state or None


def cancel(job_id: str, run=subprocess.run) -> None:
    run(["scancel", job_id], check=True)


def write_job_id(plan_dir: Path, job_id: str) -> None:
    (plan_dir / "job.id").write_text(job_id)


def read_job_id(plan_dir: Path) -> str | None:
    path = plan_dir / "job.id"
    return path.read_text().strip() if path.exists() else None


def write_status(plan_dir: Path, status: str) -> None:
    (plan_dir / "status.txt").write_text(status)


def read_status(plan_dir: Path) -> str | None:
    path = plan_dir / "status.txt"
    return path.read_text().strip() if path.exists() else None
```

- [ ] **Step 4: Run it, confirm it passes, then run the full suite**

Run: `python3 -m pytest Tests/test_jobs.py -q`
Expected: `9 passed`

Run: `python3 -m pytest Tests/ -q`
Expected: `101 passed`

- [ ] **Step 5: Commit**

```bash
git add src/askslm/cli/jobs.py Tests/test_jobs.py
git commit -m "feat(cli): sbatch templating, submission, and job status tracking"
```

---

### Task 7: `worker.py` — the LLM-free SLURM entrypoint

**Files:**
- Create: `src/askslm/cli/worker.py`
- Test: `Tests/test_worker.py`

- [ ] **Step 1: Write the failing test**

```python
"""The SLURM job runs this. No LLM, no session -- just plan.json + a mirror in,
biom and status files out."""
import pytest

import askslm
from askslm.adapters import CannedLlmBackend, DuckDbConnection
from askslm.cli import worker
from askslm.translation import SourceQuery, Translation

from fixtures.mirror import build_fixture_mirror

TRANSLATION = Translation(
    interpretation="gut metagenomes",
    queries=(SourceQuery(askslm.Source.METALOG_METADATA,
                         "SELECT * FROM metalog_metadata"),))


def test_main_builds_the_biom_and_reports_success(tmp_path):
    db_path = build_fixture_mirror(tmp_path / "fixture.duckdb")
    connection = DuckDbConnection(db_path)
    askslm.config(db=db_path, database=connection, backend=CannedLlmBackend(TRANSLATION))
    plan = askslm.ask("gut metagenomes")
    plan_dir = tmp_path / "plans" / "20260820_000000"
    plan_dir.mkdir(parents=True)
    plan.save(plan_dir / "plan.json")
    connection.close()

    worker.main([
        "--plan-dir", str(plan_dir), "--plan", str(plan_dir / "plan.json"),
        "--sources", "METALOG_MOTUS3", "--out", str(plan_dir / "cohort.biom"),
        "--db", str(db_path)])

    assert (plan_dir / "cohort.biom").exists()
    assert (plan_dir / "status.txt").read_text() == "DONE"
    assert "family" in (plan_dir / "report.txt").read_text()
    log_text = (plan_dir / "log.txt").read_text()
    assert "discovering cohort" in log_text
    assert "reading profile matrix" in log_text


def test_main_reports_failed_status_on_error(tmp_path):
    db_path = build_fixture_mirror(tmp_path / "fixture.duckdb")
    connection = DuckDbConnection(db_path)
    askslm.config(db=db_path, database=connection, backend=CannedLlmBackend(TRANSLATION))
    plan = askslm.ask("gut metagenomes")
    plan_dir = tmp_path / "plans" / "20260820_000001"
    plan_dir.mkdir(parents=True)
    plan.save(plan_dir / "plan.json")
    connection.close()

    with pytest.raises(ValueError):
        worker.main([
            "--plan-dir", str(plan_dir), "--plan", str(plan_dir / "plan.json"),
            "--sources", "METALOG_MOTUS3", "--out", str(plan_dir / "cohort.biom"),
            "--db", str(tmp_path / "does_not_exist.duckdb")])

    assert (plan_dir / "status.txt").read_text() == "FAILED"
```

- [ ] **Step 2: Run it, confirm it fails**

Run: `python3 -m pytest Tests/test_worker.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'askslm.cli.worker'`

- [ ] **Step 3: Implement `worker.py`**

```python
"""The SLURM entrypoint: builds one cohort with no LLM hop, invoked as

    python -m askslm.cli.worker --plan-dir <dir> --plan <plan.json> \\
        --sources SOURCE_A,SOURCE_B --out <biom path> --db <mirror path> [--gpu]

Plan.run needs no backend -- CohortBuilder only ever touches runtime.database(),
never runtime.backend() (verified by reading runtime.py) -- so this never asks for
an LLM key.
"""
from __future__ import annotations

import argparse
import logging
from pathlib import Path

import askslm
from askslm.cli import jobs, rundir
from askslm.plan import load_plan
from askslm.sources import Source

_logger = logging.getLogger("askslm.worker")


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)
    handler = rundir.attach_log_handler(args.plan_dir)
    jobs.write_status(args.plan_dir, "RUNNING")
    try:
        plan = load_plan(args.plan)
        askslm.config(db=args.db, gpu=args.gpu)
        _, report = plan.run(
            profile_sources=[Source[name] for name in args.sources.split(",")],
            out=args.out,
            on_step=_log_step)
        (args.plan_dir / "report.txt").write_text(str(report))
        jobs.write_status(args.plan_dir, "DONE")
    except Exception:
        jobs.write_status(args.plan_dir, "FAILED")
        raise
    finally:
        rundir.detach_log_handler(handler)


def _log_step(label: str) -> None:
    _logger.info(label)


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan-dir", type=Path, required=True, dest="plan_dir")
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--sources", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--gpu", action="store_true")
    return parser.parse_args(argv)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run it, confirm it passes, then run the full suite**

Run: `python3 -m pytest Tests/test_worker.py -q`
Expected: `2 passed`

Run: `python3 -m pytest Tests/ -q`
Expected: `103 passed`

- [ ] **Step 5: Commit**

```bash
git add src/askslm/cli/worker.py Tests/test_worker.py
git commit -m "feat(cli): worker.py, the LLM-free SLURM entrypoint"
```

---

### Task 8: `watch.py` — the shared live-progress view

**Files:**
- Create: `src/askslm/cli/watch.py`
- Test: `Tests/test_watch.py`

- [ ] **Step 1: Write the failing test**

```python
"""Only _new_lines is pure enough to unit test -- watch() itself is a live terminal
loop (polling squeue, sleeping, catching Ctrl-C), verified by running it, the same
convention session.py already uses."""
from askslm.cli.watch import _new_lines


def test_no_log_file_yet_returns_no_lines(tmp_path):
    assert _new_lines(tmp_path / "log.txt", seen=0) == []


def test_returns_only_lines_not_seen_before(tmp_path):
    log_path = tmp_path / "log.txt"
    log_path.write_text("one\ntwo\nthree\n")

    assert _new_lines(log_path, seen=1) == ["two", "three"]
```

- [ ] **Step 2: Run it, confirm it fails**

Run: `python3 -m pytest Tests/test_watch.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'askslm.cli.watch'`

- [ ] **Step 3: Implement `watch.py`**

```python
"""The live progress view: shared by 'Run it' -> Watch progress and by reattaching
via `askslm load` to a plan folder whose job is still running."""
from __future__ import annotations

import time
from pathlib import Path

from rich.console import Console

from askslm.cli import jobs

POLL_SECONDS = 3


def watch(plan_dir: Path, console: Console) -> None:
    job_id = jobs.read_job_id(plan_dir)
    log_path = plan_dir / "log.txt"
    seen = 0
    try:
        while True:
            lines = _new_lines(log_path, seen)
            seen += len(lines)
            for line in lines:
                console.print(f"  {line}")
            status = jobs.read_status(plan_dir)
            if status in ("DONE", "FAILED"):
                report_path = plan_dir / "report.txt"
                if report_path.exists():
                    console.print(report_path.read_text())
                return
            state = jobs.squeue_state(job_id)
            if state is None and status is None:
                console.print("[red]job left the queue and never reported a status[/red]")
                return
            console.print(f"job {job_id} · {state or status}")
            time.sleep(POLL_SECONDS)
    except KeyboardInterrupt:
        console.print("\n[dim]stopped watching -- job keeps running[/dim]")


def _new_lines(log_path: Path, seen: int) -> list[str]:
    if not log_path.exists():
        return []
    return log_path.read_text().splitlines()[seen:]
```

- [ ] **Step 4: Run it, confirm it passes, then run the full suite**

Run: `python3 -m pytest Tests/test_watch.py -q`
Expected: `2 passed`

Run: `python3 -m pytest Tests/ -q`
Expected: `105 passed`

- [ ] **Step 5: Commit**

```bash
git add src/askslm/cli/watch.py Tests/test_watch.py
git commit -m "feat(cli): shared live-progress watch view"
```

---

### Task 9: Rewire `session.py`

**Files:**
- Modify: `src/askslm/cli/session.py`

No automated test — this file's own docstring already documents the convention
("verified by running it, not by a test suite"), and every piece of logic worth
testing in isolation was already pulled out and tested in Tasks 1–8. This task wires
those pieces together.

- [ ] **Step 1: Replace the whole file**

```python
"""The interactive session: `$ askslm`.

Line-oriented on purpose. A full-screen TUI owns the terminal and needs a layout
engine; this needs to show a table, arrow between options, confirm, and repeat.
Every screen here maps to exactly one call the public API already has.

Not unit-tested: verified by running it. The parts worth testing (plan folders, job
templating/status, on_step, GPU wrapping) are extracted into rundir.py/jobs.py/
build.py/adapters.py, which do have tests.
"""
from __future__ import annotations

import logging
import shutil
import sys
from pathlib import Path

import questionary
from rich.console import Console
from rich.table import Table

import askslm
from askslm.cli import jobs, rundir, watch
from askslm.cli.render import narrow_warning, overlap_rows, preview_line
from askslm.plan import Plan, load_plan
from askslm.settings_file import CONFIG_PATH, stored_settings, write_settings
from askslm.sources import ProfilerFamily, Source, SourceKind

console = Console()
logger = logging.getLogger("askslm.session")


def main() -> None:
    """`askslm` starts a session; `askslm load plans/x/plan.json` reattaches to one."""
    if len(sys.argv) > 2 and sys.argv[1] == "load":
        _load(Path(sys.argv[2]))
        return
    _configure()
    _session()


def _configure() -> None:
    """Ask until it works. A mistyped path must produce a sentence and another prompt,
    never a traceback -- HLD C.0.1 makes this the one place the app catches its own
    fail-fast validation instead of letting it reach the user.

    Nothing is written until config() accepts, so a typo or a Ctrl-C cannot leave a
    broken file behind that poisons every later run.
    """
    settings = stored_settings()
    prompted = False
    while True:
        missing = [name for name in ("db", "llm_key") if not settings.get(name)]
        if missing:
            settings.update(_ask_for(missing))
            prompted = True
        try:
            askslm.config(db=settings["db"], llm="gemini", llm_key=settings["llm_key"])
        except ValueError as error:
            console.print(f"[red]{error}[/red]")
            settings.pop(_culprit(error), None)
            prompted = True
            continue
        if prompted:
            write_settings(CONFIG_PATH, **settings)
            console.print(f"[green]saved to {CONFIG_PATH}[/green]")
        return


def _culprit(error: ValueError) -> str:
    """Which answer to ask for again. Re-asking for a path the user already got right
    because their key was wrong is the sort of thing that makes people stop using a tool."""
    return "db" if "database file" in str(error) else "llm_key"


def _ask_for(missing: list[str]) -> dict:
    """Only what is actually missing.

    A site that pins the database path -- a launcher on the lab server, say -- should
    leave the user answering one question, not two. Re-asking for a path the machine
    already knows is how a "two questions, once" flow becomes two questions, always.
    """
    ask = {"db": _ask_db, "llm_key": _ask_key}
    answers = {}
    for name in missing:
        value = ask[name]()
        if value is None:              # Ctrl-C or EOF: leave no config behind
            raise SystemExit(0)
        answers[name] = value.strip()  # a tab-completed path arrives with a trailing space
    return answers


def _ask_db() -> str:
    return questionary.path("Path to the SRA x Metalog database").ask()


def _ask_key() -> str:
    return questionary.password("Gemini API key").ask()


def _session() -> None:
    question = ""
    plan = None
    plan_dir = None
    while True:
        if plan is None:
            question = questionary.text("What cohort do you need?", default=question).ask()
            if not question:
                return
            plan_dir = rundir.new_plan_dir()
            handler = rundir.attach_log_handler(plan_dir)
            logger.info("question -> %r", question)
            plan = _ask(question, plan_dir)
            rundir.detach_log_handler(handler)
            if plan is None:
                continue
        choice = questionary.select("What now?", choices=[
            "Run it", "Refine the question", "Ask new question", "Discard", "Quit"]).ask()
        if choice == "Run it":
            _run(plan, plan_dir)
        elif choice == "Refine the question":
            plan = None
        elif choice == "Ask new question":
            plan = None
            question = ""
        elif choice == "Discard":
            _discard(plan_dir)
            plan = None
            question = ""
        else:
            return


def _ask(question: str, plan_dir: Path) -> Plan | None:
    """A question the model cannot translate is a screen, not a stack trace."""
    with console.status("thinking"):
        plan = askslm.ask(question)
    if plan.error is not None:
        console.print(f"[red]Could not translate that into a query.[/red]\n{plan.error}")
        return None
    plan.save(plan_dir / "plan.json")
    console.print(f"[bold]{plan.translation.interpretation}[/bold]")
    console.print(preview_line(plan.preview))
    warning = narrow_warning(plan.preview)
    if warning:
        console.print(f"[yellow]{warning}[/yellow]")
    _show_overlap(plan)
    return plan


def _run(plan: Plan, plan_dir: Path) -> None:
    families = _families(plan)
    if len(families) == 1:
        family_name = families[0]
        console.print(f"  feature space: {family_name} (only option)")
    else:
        family_name = questionary.select("Which feature space?", choices=families).ask()
        if family_name is None:
            return
    sources = _sources_of(ProfilerFamily[family_name])
    if len(sources) == 1:
        chosen = sources
        console.print(f"  sources: {sources[0].name} (only option)")
    else:
        picked = questionary.checkbox("Which sources? (order = precedence)",
                                      choices=[source.name for source in sources]).ask()
        if not picked:
            return
        chosen = [Source[name] for name in picked]
    out = questionary.text("Write to", default=str(plan_dir / "cohort.biom")).ask()
    if not out:
        return
    gpu = questionary.confirm("Use GPU acceleration for this build?", default=False).ask()
    _submit(plan_dir, chosen, Path(out), gpu)


def _submit(plan_dir: Path, sources: list[Source], out: Path, gpu: bool) -> None:
    settings = stored_settings()
    worker_cmd = (f'"{sys.executable}" -m askslm.cli.worker '
                 f'--plan-dir "{plan_dir}" --plan "{plan_dir / "plan.json"}" '
                 f'--sources "{",".join(source.name for source in sources)}" '
                 f'--out "{out}" --db "{settings["db"]}"' + (" --gpu" if gpu else ""))
    script = jobs.write_sbatch(plan_dir, worker_cmd, gpu)
    job_id = jobs.submit(script)
    jobs.write_job_id(plan_dir, job_id)
    console.print(f"[green]Submitted SLURM job {job_id}[/green]")
    console.print(f"  squeue:  squeue -j {job_id}")
    console.print(f"  log:     tail -f {plan_dir / 'log.txt'}")
    choice = questionary.select("Watch progress now, or back to menu?",
                                choices=["Watch progress", "Back to menu"]).ask()
    if choice == "Watch progress":
        watch.watch(plan_dir, console)


def _families(plan: Plan) -> list[str]:
    """Only families that actually cover this cohort. Picking the family first is what
    makes the cross-family guard unreachable by construction (HLD C.0.2)."""
    covered = {source.family().name for source, count in plan.preview.by_profile_source.items()
              if count}
    return sorted(covered) or sorted(family.name for family in ProfilerFamily)


def _sources_of(family: ProfilerFamily) -> list[Source]:
    return [source for source in Source
            if source.kind() is SourceKind.PROFILE and source.family() is family]


def _show_overlap(plan: Plan) -> None:
    table = Table("source", "samples", "")
    for row in overlap_rows(plan.preview, winner=Source.METALOG_METADATA):
        table.add_row(*row)
    console.print(table)
    for query in plan.translation.queries:
        console.print(f"[dim]{query.source.name}[/dim] {query.sql}")


def _discard(plan_dir: Path) -> None:
    """The session created plan.json here itself (autosave), so the whole folder is
    disposable -- cancel a live job first, never delete files out from under it."""
    _cancel_if_running(plan_dir)
    shutil.rmtree(plan_dir)


def _discard_loaded(plan_dir: Path, keep: Path) -> None:
    """`keep` is the plan.json path the caller passed to `askslm load` -- a
    caller-owned input, not something this run created, so it survives; only this
    run's own artifacts (log, job files, biom) are removed."""
    _cancel_if_running(plan_dir)
    for entry in plan_dir.iterdir():
        if entry == keep:
            continue
        if entry.is_dir():
            shutil.rmtree(entry)
        else:
            entry.unlink()


def _cancel_if_running(plan_dir: Path) -> None:
    job_id = jobs.read_job_id(plan_dir)
    if job_id is not None and jobs.squeue_state(job_id) is not None:
        jobs.cancel(job_id)


def _load(path: Path) -> None:
    """No LLM hop -- the reproducible half of the loop. Reattaches straight to the
    live progress view if a job submitted from this same folder is still running."""
    settings = stored_settings()
    askslm.config(db=settings["db"], llm="gemini", llm_key=settings.get("llm_key", ""))
    plan_dir = path.parent
    job_id = jobs.read_job_id(plan_dir)
    if job_id is not None and jobs.squeue_state(job_id) is not None:
        watch.watch(plan_dir, console)
    plan = load_plan(path)
    console.print(preview_line(plan.preview))
    while True:
        choice = questionary.select("What now?", choices=["Run it", "Discard", "Quit"]).ask()
        if choice == "Run it":
            _run(plan, plan_dir)
        elif choice == "Discard":
            _discard_loaded(plan_dir, keep=path)
            return
        else:
            return
```

- [ ] **Step 2: Run the full suite (nothing here is exercised by it, but nothing
      should be broken by the rewrite)**

Run: `python3 -m pytest Tests/ -q`
Expected: `105 passed`

- [ ] **Step 3: Manual verification checklist**

Since `session.py` is glue with no automated coverage, verify by actually running it
against the fixture mirror (or the real one, if you have it configured):

1. `askslm` → type a question → confirm a `plans/<ts>/` folder now exists with
   `log.txt` and (on success) `plan.json`.
2. At the menu, confirm the choices are exactly `Run it / Refine the question / Ask
   new question / Discard / Quit` (no `Show the SQL and overlap`, no `Save plan and
   quit`) and that the SQL + overlap table already printed right after the question.
3. `Discard` → confirm the folder is gone and you land on a blank question prompt.
4. `Run it` on a cohort that covers only one `ProfilerFamily`/one `Source` → confirm
   the `(only option)` lines print and no select/checkbox prompt appears.
5. `Run it` → answer `n` to GPU → confirm a job is submitted (`squeue -u $USER` shows
   it), `job.sbatch` in the plan folder has `#SBATCH --partition=cpu192G-48h`, and
   `job.id` holds the numeric id `sbatch` printed.
6. Choose `Watch progress` → confirm phase lines appear as `log.txt` grows and the
   view returns to the menu on its own once `status.txt` becomes `DONE`.
7. From a **second terminal**, run `askslm load plans/<ts>/plan.json` on a folder
   whose job is still running → confirm it drops straight into the same live view
   with no menu shown first.
8. `askslm load` on a folder whose job has already finished → confirm you see the
   `Run it / Discard / Quit` menu, and that `Discard` there deletes everything in the
   folder except `plan.json` itself.

- [ ] **Step 4: Commit**

```bash
git add src/askslm/cli/session.py
git commit -m "feat(cli): rewire session.py for plan folders, SLURM submission, and the new menu"
```

---

### Task 10: Wrap-up

- [ ] **Step 1: Run the full suite one more time**

Run: `python3 -m pytest Tests/ -q`
Expected: `105 passed`

- [ ] **Step 2: Push and open the PR**

```bash
git push -u origin feature/session-slurm-ux
gh pr create --base main --title "feat: SLURM-submitted Run it, per-question logging, and a leaner menu" --body "$(cat <<'EOF'
## Summary
- Every question now gets a plans/<ts>/ folder with an auto-saved plan.json and a full log.txt (every SQL query and every LLM call, with timing).
- "Run it" submits a real sbatch job instead of running the build on the SLURM login node, with an optional GPU mode (Anna Shafir's Sirius extension) and a live progress view watchable from any terminal, including after the submitting shell is gone.
- Menu: SQL/overlap now print automatically, Show the SQL and overlap and Save plan and quit are removed, Discard and Ask new question are added, and a prompt with only one real choice is auto-picked and reported instead of asked.
- askslm run <path> is renamed askslm load <path>.

Design: Docs/superpowers/specs/2026-08-20-session-logging-and-run-ux-design.html
Plan: Docs/superpowers/plans/2026-08-20-session-slurm-ux.md

## Test plan
- [ ] python3 -m pytest Tests/ -q -- 105 passed
- [ ] Manual checklist in Task 9 of the plan, run against the real mirror on the cluster
EOF
)"
```

- [ ] **Step 3: Stop.** The user squash-merges through GitHub.
