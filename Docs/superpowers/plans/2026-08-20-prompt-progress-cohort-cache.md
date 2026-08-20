# Prompt Fix, Structured Progress View, and Cohort Caching Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix three problems surfaced by the first real cluster run of the SLURM-submission feature: a prompt bug that silently drops a named criterion, a "watch" view that dumps raw debug logs instead of showing clean progress, and an expensive discovery query that re-runs twice (once in the terminal, again inside the SLURM job) with no caching.

**Architecture:** A prompt-text-only fix (no code). A new small `progress.py` module gives the worker a structured, dedicated phase trail separate from the full-debug `log.txt`, and `watch()` is rewritten to render from that plus `squeue`'s state+reason, with a redraw-in-place status line (via `rich`'s `console.status()`, already used elsewhere) instead of one line per poll. `Plan` gains a `discovered: Cohort | None` field that `ask()` populates and `run()`/`CohortBuilder.build()` reuse instead of re-querying, surviving save/load and the SLURM process boundary.

**Tech Stack:** Existing stack only — stdlib, `rich`, `pytest`. No new dependencies.

**Design:** `/Users/yarintamam/.claude/plans/you-suggested-fix-will-crystalline-moon.md` — read it for the full "why," including the two design decisions already resolved with the user (disclose-in-interpretation over omit-entirely for Fix 1; redraw-in-place over append-per-poll for Fix 2).

---

## Prerequisites

```bash
git fetch origin && git switch -c feature/prompt-progress-and-cohort-cache origin/main
```

(Already done for this session — branch exists and is checked out.) Never delete branches. Finish with push + `gh pr create --base main`, then stop.

## Context

- **Run tests:** `python3 -m pytest Tests/ -q` from the repo root. Baseline **114 passing**.
- House style: no `lambda` — always a named `def`, including nested closures; trust input and fail fast; minimal comments (WHY only); readability first; small single-responsibility modules (see `jobs.py`/`rundir.py`/`watch.py` for the existing pattern this plan follows).
- `progress.py` and `log.txt` are deliberately separate: `log.txt` keeps carrying full SQL/LLM debug logging (via `logging.getLogger(__name__)` in `adapters.py`) for manual `tail -f` postmortem; `progress.py`'s files are a small, dedicated, structured trail `watch()` reads instead.
- `squeue_state(job_id) -> str | None` (existing, used by `session.py`'s `_cancel_if_running`/`_load` as a plain "is it still queued" check) is left untouched. A new, separate `squeue_state_and_reason` is added for `watch()`'s richer display, so the two existing call sites never need to unpack a tuple they don't use.
- `Plan.discovered` is additive with a `None` default — every existing `Plan(...)` construction across the test suite keeps working unchanged; an old saved `plan.json` (no `"discovered"` key) loads fine via `payload.get("discovered")` and falls back to fresh discovery, which is the *only* fallback behavior (no legacy-mode branching).
- Import graph confirmed by reading the actual files: `cohort.py` has zero dependency on `plan.py` or `__init__.py`, so `plan.py` importing `Cohort`/`Accession` from `askslm.cohort` at module level is safe.

## File Structure

| File | Responsibility |
|---|---|
| `src/askslm/prompt.py` | **modify.** New paragraph closing the partial-criterion-omission gap. |
| `src/askslm/cli/progress.py` | **new.** The worker's structured phase trail + submission timestamp. |
| `src/askslm/cli/jobs.py` | **modify.** New `squeue_state_and_reason`. |
| `src/askslm/cli/worker.py` | **modify.** `on_step` also writes to `progress.py`. |
| `src/askslm/cli/session.py` | **modify.** `_submit()` records the submission timestamp. |
| `src/askslm/cli/watch.py` | **modify.** Full rewrite: reads `progress.py`+`squeue`, not `log.txt`; redraw-in-place status line. |
| `src/askslm/plan.py` | **modify.** `Plan.discovered` field + save/load serialization + `run()` passthrough. |
| `src/askslm/build.py` | **modify.** `CohortBuilder.build()` accepts `discovered`, skips re-discovery when given. |
| `src/askslm/__init__.py` | **modify.** `_preview()` → `_discover()` returning cohort+preview; `ask()`/`_repaired()` attach it. |
| `Tests/test_progress.py` | **new.** |
| `Tests/test_jobs.py` | **modify.** |
| `Tests/test_worker.py` | **modify.** |
| `Tests/test_watch.py` | **modify.** |
| `Tests/test_plan_persistence.py` | **modify.** |
| `Tests/test_build_progress.py` | **modify.** |
| `Tests/test_walking_skeleton.py` | **modify.** |

---

### Task 1: Prompt fix (`src/askslm/prompt.py`)

**Files:**
- Modify: `src/askslm/prompt.py`

No automated test — this is prompt text, verified against the real LLM/mirror, matching the convention already used for the earlier synonym-OR prompt fix in this same file's history.

- [ ] **Step 1: Insert the new paragraph**

In `src/askslm/prompt.py`, find this existing block (currently lines 55–62):

```
WHEN A SOURCE CANNOT EXPRESS PART OF THE QUESTION
The caller unions every source's results, so a query against a source with nothing
relevant to the question does not narrow the cohort -- it WIDENS it, silently adding
unrelated samples. If a source's columns cannot express the question (or the part of
it that source would cover), omit that source's query entirely rather than writing an
approximate or unrelated one. For example, "human tumour RNA-seq" is expressible in
SRA_METADATA; Metalog has no comparable field, so a Metalog query returning anything
at all would corrupt the result -- omit METALOG_METADATA's query for that question.
```

Replace it with the same text plus this new paragraph immediately after (before the
blank line that precedes `PREFER RECALL OVER PRECISION`):

```
WHEN A SOURCE CANNOT EXPRESS PART OF THE QUESTION
The caller unions every source's results, so a query against a source with nothing
relevant to the question does not narrow the cohort -- it WIDENS it, silently adding
unrelated samples. If a source's columns cannot express the question (or the part of
it that source would cover), omit that source's query entirely rather than writing an
approximate or unrelated one. For example, "human tumour RNA-seq" is expressible in
SRA_METADATA; Metalog has no comparable field, so a Metalog query returning anything
at all would corrupt the result -- omit METALOG_METADATA's query for that question.

A CRITERION CAN BE MISSING EVEN WHEN THE SOURCE IS NOT
The rule above is about a source with nothing relevant to the WHOLE question. The
same harm happens one level down: a source can express most of the question's
criteria and still have no field for one of them. Writing a query that filters
only on what the source CAN express, and dropping the rest, does not narrow that
source's contribution to the question -- it widens it, exactly as when a whole
source is irrelevant, because every row that source returns is then treated as if
it satisfied a criterion it never checked.

Do not write a query that silently drops an expressible criterion. If the source
has NO field for the missing criterion, and no synonym of it, that criterion is
not a partial-coverage judgment call to make silently -- name the gap in
`interpretation` (e.g. "Metalog has no calprotectin field, so its query only
enforces IBD/fecal/metagenomic and the calprotectin criterion is unverified in
that source's rows"), so a human reviewing the cohort sees it was widened on
that source, not narrowed.

This is a different situation from choosing among SYNONYMS for one measurement
(see the ibd_sam/calprotectin rule below) -- that rule is about several listed
attributes naming the SAME concept. This rule is about a criterion that is a
wholly separate, missing axis of filtering, with no field or synonym anywhere in
the source's schema.

Example: "IBD fecal metagenomic samples with a calprotectin measurement." SRA has
a calprotectin jattr key -- use it. Metalog CAN express IBD, fecal, and
metagenomic, but has no calprotectin field and no synonym of one. Do not write a
Metalog query filtered only on IBD/fecal/metagenomic as if that covered the whole
question for that source -- state in `interpretation` that Metalog's contribution
does not verify calprotectin, so the researcher knows those rows are not
guaranteed to have it.
```

- [ ] **Step 2: Run the full suite (text-only change, nothing should break)**

Run: `python3 -m pytest Tests/ -q`
Expected: `114 passed`

- [ ] **Step 3: Commit**

```bash
git add src/askslm/prompt.py
git commit -m "fix(prompt): disclose a criterion a source can't verify instead of silently dropping it"
```

---

### Task 2: `progress.py` — the worker's structured phase trail

**Files:**
- Create: `src/askslm/cli/progress.py`
- Test: `Tests/test_progress.py`

- [ ] **Step 1: Write the failing test**

```python
"""progress.txt/submitted.txt are the worker's structured phase trail -- separate
from log.txt's full SQL/LLM debug logging, so watch() can render clean progress
without replaying that backlog."""
import time

from askslm.cli import progress


def test_write_start_appends_a_timestamped_event(tmp_path):
    progress.write_start(tmp_path, "discovering cohort")
    progress.write_start(tmp_path, "reading profile matrix")

    events = progress.read_events(tmp_path)

    assert [label for _, _, label in events] == [
        "discovering cohort", "reading profile matrix"]
    assert all(event == "start" for _, event, _ in events)
    assert events[0][0] <= events[1][0]           # timestamps in order


def test_read_events_with_no_file_yet_is_empty(tmp_path):
    assert progress.read_events(tmp_path) == []


def test_submitted_time_round_trips(tmp_path):
    progress.write_submitted(tmp_path)

    submitted = progress.read_submitted(tmp_path)

    assert submitted is not None
    assert submitted <= time.time()


def test_read_submitted_with_no_file_yet_is_none(tmp_path):
    assert progress.read_submitted(tmp_path) is None
```

- [ ] **Step 2: Run it, confirm it fails**

Run: `python3 -m pytest Tests/test_progress.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'askslm.cli.progress'`

- [ ] **Step 3: Implement `progress.py`**

```python
"""The build's phase-by-phase progress trail: separate from log.txt (which
carries full ask()-phase SQL/LLM debug logging) so watch() can render
structured phase timing without replaying that backlog."""
from __future__ import annotations

import time
from pathlib import Path

PROGRESS_FILENAME = "progress.txt"
SUBMITTED_FILENAME = "submitted.txt"


def write_start(plan_dir: Path, label: str) -> None:
    path = plan_dir / PROGRESS_FILENAME
    with path.open("a") as handle:
        handle.write(f"{time.time()} start {label}\n")


def read_events(plan_dir: Path) -> list[tuple[float, str, str]]:
    path = plan_dir / PROGRESS_FILENAME
    if not path.exists():
        return []
    events = []
    for line in path.read_text().splitlines():
        timestamp_text, event, label = line.split(" ", 2)
        events.append((float(timestamp_text), event, label))
    return events


def write_submitted(plan_dir: Path) -> None:
    (plan_dir / SUBMITTED_FILENAME).write_text(str(time.time()))


def read_submitted(plan_dir: Path) -> float | None:
    path = plan_dir / SUBMITTED_FILENAME
    return float(path.read_text()) if path.exists() else None
```

- [ ] **Step 4: Run it, confirm it passes, then run the full suite**

Run: `python3 -m pytest Tests/test_progress.py -q`
Expected: `4 passed`

Run: `python3 -m pytest Tests/ -q`
Expected: `118 passed`

- [ ] **Step 5: Commit**

```bash
git add src/askslm/cli/progress.py Tests/test_progress.py
git commit -m "feat(cli): progress.py, the worker's structured phase trail"
```

---

### Task 3: `jobs.py` — `squeue_state_and_reason`

**Files:**
- Modify: `src/askslm/cli/jobs.py`
- Modify: `Tests/test_jobs.py`

- [ ] **Step 1: Write the failing test**

Add to `Tests/test_jobs.py` (keep everything else in that file unchanged):

```python
def test_squeue_state_and_reason_reports_state_and_reason_while_pending():
    def fake_run(args, **kwargs):
        return subprocess.CompletedProcess(args, 0, stdout="PENDING Resources\n", stderr="")

    assert jobs.squeue_state_and_reason("4213765", run=fake_run) == ("PENDING", "Resources")


def test_squeue_state_and_reason_reports_none_once_the_job_has_left_the_queue():
    def fake_run(args, **kwargs):
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    assert jobs.squeue_state_and_reason("4213765", run=fake_run) is None


def test_squeue_state_and_reason_raises_if_squeue_itself_fails():
    def fake_run(args, **kwargs):
        return subprocess.CompletedProcess(args, 1, stdout="",
                                           stderr="squeue: error: bad job id")

    with pytest.raises(RuntimeError, match="bad job id"):
        jobs.squeue_state_and_reason("4213765", run=fake_run)
```

- [ ] **Step 2: Run it, confirm it fails**

Run: `python3 -m pytest Tests/test_jobs.py -q`
Expected: FAIL with `AttributeError: module 'askslm.cli.jobs' has no attribute 'squeue_state_and_reason'`

- [ ] **Step 3: Implement `squeue_state_and_reason`**

In `src/askslm/cli/jobs.py`, add this function right after the existing `squeue_state`:

```python
def squeue_state_and_reason(job_id: str,
        run: Callable[..., subprocess.CompletedProcess] = subprocess.run
        ) -> tuple[str, str] | None:
    """Like squeue_state, but also returns the REASON code (e.g. 'Resources',
    'Priority') a PENDING job reports -- one extra %R column, no second call.
    None means the job is no longer in the queue, same convention as squeue_state."""
    result = run(["squeue", "-j", job_id, "-h", "-o", "%T %R"], capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"squeue failed for job {job_id}: {result.stderr!r}")
    output = result.stdout.strip()
    if not output:
        return None
    state, reason = output.split(" ", 1)
    return state, reason
```

- [ ] **Step 4: Run it, confirm it passes, then run the full suite**

Run: `python3 -m pytest Tests/test_jobs.py -q`
Expected: `13 passed` (10 existing + 3 new)

Run: `python3 -m pytest Tests/ -q`
Expected: `121 passed`

- [ ] **Step 5: Commit**

```bash
git add src/askslm/cli/jobs.py Tests/test_jobs.py
git commit -m "feat(cli): squeue_state_and_reason for the watch view's reason-code display"
```

---

### Task 4: `worker.py` — write progress events alongside the log

**Files:**
- Modify: `src/askslm/cli/worker.py`
- Modify: `Tests/test_worker.py`

- [ ] **Step 1: Write the failing test**

Add to `Tests/test_worker.py`: change the import line
`from askslm.cli import worker` to `from askslm.cli import progress, worker`, then add
this assertion to the end of `test_main_builds_the_biom_and_reports_success` (keep
everything already in that test, just append):

```python
    progress_labels = [label for _, _, label in progress.read_events(plan_dir)]
    assert progress_labels == ["discovering cohort", "reading profile matrix",
                               "assembling and writing biom"]
```

- [ ] **Step 2: Run it, confirm it fails**

Run: `python3 -m pytest Tests/test_worker.py -q`
Expected: FAIL — `progress_labels == []`, the assertion finds no events

- [ ] **Step 3: Wire `on_step` to also write progress events**

In `src/askslm/cli/worker.py`, add `progress` to the existing import and add
`Callable` to the `typing` import:

```python
from typing import Callable
```

```python
from askslm.cli import jobs, progress, rundir
```

Replace the `on_step=_log_step` argument in `main()` with `on_step=_on_step(args.plan_dir)`,
and replace the module-level `_log_step` function with:

```python
def _on_step(plan_dir: Path) -> Callable[[str], None]:
    def step(label: str) -> None:
        _logger.info(label)
        progress.write_start(plan_dir, label)
    return step
```

(The existing `_logger.info(label)` call stays — `log.txt` keeps carrying this for
manual postmortem, unchanged.)

- [ ] **Step 4: Run it, confirm it passes, then run the full suite**

Run: `python3 -m pytest Tests/test_worker.py -q`
Expected: `2 passed`

Run: `python3 -m pytest Tests/ -q`
Expected: `121 passed`

- [ ] **Step 5: Commit**

```bash
git add src/askslm/cli/worker.py Tests/test_worker.py
git commit -m "feat(cli): worker writes structured progress events alongside log.txt"
```

---

### Task 5: `session.py` — record the submission timestamp

**Files:**
- Modify: `src/askslm/cli/session.py`

No automated test — `session.py` is glue, per its own module docstring and the
existing convention for this file.

- [ ] **Step 1: Add `progress` to the import and record the timestamp**

In `src/askslm/cli/session.py`, change:

```python
from askslm.cli import jobs, rundir, watch
```

to:

```python
from askslm.cli import jobs, progress, rundir, watch
```

In `_submit()`, right after `jobs.write_job_id(plan_dir, job_id)`, add:

```python
    progress.write_submitted(plan_dir)
```

- [ ] **Step 2: Run the full suite (nothing exercises this directly, confirm nothing broke)**

Run: `python3 -m pytest Tests/ -q`
Expected: `121 passed`

- [ ] **Step 3: Commit**

```bash
git add src/askslm/cli/session.py
git commit -m "feat(cli): record the SLURM submission timestamp for the watch view's queued timer"
```

---

### Task 6: `watch.py` — structured, redraw-in-place progress display

**Files:**
- Modify: `src/askslm/cli/watch.py`
- Modify: `Tests/test_watch.py`

- [ ] **Step 1: Write the failing tests**

Replace `Tests/test_watch.py` in full with:

```python
"""_new_phase_lines/_status_line/_elapsed are pure enough to unit test -- watch()
itself is a live terminal loop (polling squeue, sleeping, catching Ctrl-C),
verified by running it, the same convention session.py already uses. One
exception: the "job left the queue" exit condition is a real correctness
property (a job killed outside askslm never gets to write status.txt, so status
alone would hang the loop forever) worth locking down end to end."""
import time

from askslm.cli import jobs, watch


def test_no_phases_yet_prints_nothing():
    assert watch._new_phase_lines([], printed=set(), job_finished=False) == []


def test_a_completed_phase_prints_once_with_its_duration():
    events = [(100.0, "start", "discovering cohort"),
             (112.4, "start", "reading profile matrix")]

    lines = watch._new_phase_lines(events, printed=set(), job_finished=False)

    assert lines == ["[1/3] discovering cohort... 12.4s"]


def test_the_open_final_phase_is_not_printed_while_still_running():
    events = [(100.0, "start", "discovering cohort")]

    assert watch._new_phase_lines(events, printed=set(), job_finished=False) == []


def test_the_open_final_phase_is_printed_once_the_job_is_finished():
    events = [(100.0, "start", "discovering cohort")]

    lines = watch._new_phase_lines(events, printed=set(), job_finished=True)

    assert len(lines) == 1
    assert lines[0].startswith("[1/3] discovering cohort...")


def test_an_already_printed_phase_is_never_printed_again():
    events = [(100.0, "start", "discovering cohort"),
             (112.4, "start", "reading profile matrix")]

    lines = watch._new_phase_lines(events, printed={"discovering cohort"}, job_finished=False)

    assert lines == []


def test_status_line_shows_the_pending_reason_and_queued_time():
    line = watch._status_line("123", "PENDING", "Resources", submitted_at=0.0,
                              events=[], printed=set())

    assert "PENDING" in line
    assert "Resources" in line
    assert "queued" in line


def test_status_line_shows_the_running_phase_when_one_is_open():
    events = [(0.0, "start", "discovering cohort")]

    line = watch._status_line("123", "RUNNING", "None", submitted_at=0.0,
                              events=events, printed=set())

    assert "discovering cohort" in line
    assert "running" in line


def test_status_line_falls_back_to_bare_state_when_no_phase_is_open_yet():
    line = watch._status_line("123", "RUNNING", "None", submitted_at=0.0,
                              events=[], printed=set())

    assert line == "job 123 · RUNNING"


def test_elapsed_with_no_start_time_is_a_question_mark():
    assert watch._elapsed(None) == "?"


def test_elapsed_formats_minutes_and_seconds():
    assert watch._elapsed(time.time() - 125) == "2:05"


def test_watch_stops_once_squeue_says_the_job_is_gone_even_if_status_still_says_running(
        tmp_path, monkeypatch, capsys):
    """A job killed by `scancel` from outside askslm, or OOM-killed, dies before its
    finally block can write DONE/FAILED -- status.txt is stuck at RUNNING forever.
    squeue leaving the queue is the only signal guaranteed to update, so it alone
    must end the loop."""
    def _job_already_gone(job_id, run=None):
        return None

    def _no_sleep(seconds):
        pass

    jobs.write_job_id(tmp_path, "4213765")
    jobs.write_status(tmp_path, "RUNNING")
    monkeypatch.setattr(jobs, "squeue_state_and_reason", _job_already_gone)
    monkeypatch.setattr(watch.time, "sleep", _no_sleep)

    watch.watch(tmp_path, watch.Console(width=200))

    assert "killed outside askslm" in capsys.readouterr().out
```

- [ ] **Step 2: Run it, confirm it fails**

Run: `python3 -m pytest Tests/test_watch.py -q`
Expected: FAIL — `AttributeError: module 'askslm.cli.watch' has no attribute '_new_phase_lines'`
(and similar for `_status_line`/`_elapsed`)

- [ ] **Step 3: Rewrite `watch.py`**

Replace the whole file with:

```python
"""The live progress view: shared by 'Run it' -> Watch progress and by reattaching
via `askslm load` to a plan folder whose job is still running.

Reads only the worker's own structured progress trail (progress.py) and squeue --
never log.txt, which carries full SQL/LLM debug logging from the interactive ask()
phase and would otherwise be replayed as if it were live job activity."""
from __future__ import annotations

import time
from pathlib import Path

from rich.console import Console

from askslm.cli import jobs, progress

POLL_SECONDS = 3
TOTAL_PHASES = 3          # CohortBuilder.build's fixed phase count


def watch(plan_dir: Path, console: Console) -> None:
    job_id = jobs.read_job_id(plan_dir)
    submitted_at = progress.read_submitted(plan_dir)
    printed: set[str] = set()
    try:
        with console.status("") as live:
            while True:
                status = jobs.read_status(plan_dir)
                done = status in ("DONE", "FAILED")
                events = progress.read_events(plan_dir)
                for line in _new_phase_lines(events, printed, done):
                    console.print(f"  {line}")
                if done:
                    report_path = plan_dir / "report.txt"
                    if report_path.exists():
                        console.print(report_path.read_text())
                    return
                try:
                    result = jobs.squeue_state_and_reason(job_id)
                except RuntimeError as error:
                    live.update(f"[yellow]squeue check failed, retrying: {error}[/yellow]")
                    time.sleep(POLL_SECONDS)
                    continue
                if result is None:
                    if status is None:
                        console.print(
                            "[red]job left the queue and never reported a status[/red]")
                    else:
                        console.print(
                            f"[yellow]job left the queue while status.txt still said "
                            f"{status!r} -- likely killed outside askslm (scancel, OOM)[/yellow]")
                    return
                state, reason = result
                live.update(_status_line(job_id, state, reason, submitted_at, events, printed))
                time.sleep(POLL_SECONDS)
    except KeyboardInterrupt:
        console.print("\n[dim]stopped watching -- job keeps running[/dim]")


def _new_phase_lines(events: list[tuple[float, str, str]], printed: set[str],
                     job_finished: bool) -> list[str]:
    """Phases that are DONE (a later phase started, or the job itself finished) and
    have not been shown yet -- each prints exactly once, never re-printed on a
    later poll. The still-open final phase is left out here; it lives in the
    transient status line instead, via _status_line."""
    lines = []
    for index, (start, _, label) in enumerate(events):
        if label in printed:
            continue
        has_next = index + 1 < len(events)
        if not has_next and not job_finished:
            continue
        end = events[index + 1][0] if has_next else time.time()
        lines.append(f"[{index + 1}/{TOTAL_PHASES}] {label}... {end - start:.1f}s")
        printed.add(label)
    return lines


def _status_line(job_id: str, state: str, reason: str, submitted_at: float | None,
                 events: list[tuple[float, str, str]], printed: set[str]) -> str:
    if state == "PENDING":
        return f"job {job_id} · PENDING (reason: {reason}) - queued {_elapsed(submitted_at)}"
    running = next(((index, start, label) for index, (start, _, label) in enumerate(events)
                   if label not in printed), None)
    if running is None:
        return f"job {job_id} · {state}"
    index, start, label = running
    return f"[{index + 1}/{TOTAL_PHASES}] {label}... running ({_elapsed(start)})"


def _elapsed(since: float | None) -> str:
    if since is None:
        return "?"
    seconds = int(time.time() - since)
    return f"{seconds // 60}:{seconds % 60:02d}"
```

- [ ] **Step 4: Run it, confirm it passes, then run the full suite**

Run: `python3 -m pytest Tests/test_watch.py -q`
Expected: `11 passed`

Run: `python3 -m pytest Tests/ -q`
Expected: `129 passed`

- [ ] **Step 5: Commit**

```bash
git add src/askslm/cli/watch.py Tests/test_watch.py
git commit -m "feat(cli): structured, redraw-in-place progress display for watch()"
```

- [ ] **Step 6: Manual verification checklist** (this file's live loop is not
      unit-tested beyond the pure helpers above — verify by running it)

1. Submit a real SLURM job, choose "Watch progress" — confirm the transient
   status line updates in place (no repeated near-duplicate scrollback lines)
   while PENDING, showing the `squeue` reason code and a growing queued timer.
2. Once the job starts running, confirm each phase prints exactly once,
   permanently, with a real elapsed duration, and the still-open phase shows
   as part of the transient status line (`running (0:00:42)` style) until the
   next phase starts.
3. Confirm `log.txt` is untouched and `tail -f plans/<ts>/log.txt` still shows
   full SQL/LLM debug detail exactly as before.
4. Reattach via `askslm load plans/<ts>/plan.json` to a folder whose job is
   still running from another terminal — confirm it drops into the same
   clean display, not a raw log dump.

---

### Task 7: `plan.py` — cache the discovered `Cohort` on `Plan`

**Files:**
- Modify: `src/askslm/plan.py`
- Modify: `Tests/test_plan_persistence.py`

- [ ] **Step 1: Write the failing tests**

Add to `Tests/test_plan_persistence.py` (add `import json` alongside the existing
`import pytest`; keep everything else in the file unchanged):

```python
def test_discovered_cohort_round_trips(tmp_path):
    from askslm.cohort import Cohort

    plan = Plan(
        question=ResearchQuestion("adults with IBD"),
        translation=Translation(
            interpretation="x",
            queries=(SourceQuery(askslm.Source.METALOG_METADATA,
                                 "SELECT biosample FROM metalog_metadata"),)),
        preview=CohortPreview(union=2),
        discovered=Cohort({askslm.Source.METALOG_METADATA:
                           frozenset({"SAMN001", "SAMN002"})}))
    path = tmp_path / "cached.json"

    plan.save(path)
    loaded = load_plan(path)

    assert (loaded.discovered.by_source[askslm.Source.METALOG_METADATA]
           == frozenset({"SAMN001", "SAMN002"}))


def test_an_old_plan_json_with_no_discovered_key_still_loads(tmp_path):
    """An old plan.json, saved before this field existed, has no "discovered" key
    at all -- it must still load, with discovered=None, and fall back to fresh
    discovery rather than crashing on a missing key."""
    path = tmp_path / "old.json"
    _plan().save(path)
    payload = json.loads(path.read_text())
    del payload["discovered"]
    path.write_text(json.dumps(payload))

    loaded = load_plan(path)

    assert loaded.discovered is None
```

- [ ] **Step 2: Run it, confirm it fails**

Run: `python3 -m pytest Tests/test_plan_persistence.py -q`
Expected: FAIL — `TypeError: Plan.__init__() got an unexpected keyword argument 'discovered'`

- [ ] **Step 3: Add the `discovered` field and serialization**

In `src/askslm/plan.py`, change the import line:

```python
from askslm.cohort import Accession, Cohort
```

(add this alongside the existing imports, after `from askslm.build import ...`)

Replace the `Plan` dataclass with:

```python
@dataclass(frozen=True)
class Plan:
    question: ResearchQuestion
    translation: Translation
    preview: CohortPreview
    error: str | None = None
    discovered: Cohort | None = None   # ask()'s own Cohort, cached so run() need not re-query it

    def run(self, profile_sources: Source | Sequence[Source],
            out: Path | None = None,
            metadata_winning_source: Source = Source.METALOG_METADATA,
            on_step: Callable[[str], None] | None = None
            ) -> tuple[biom.Table, BuildReport]:
        self._guard_runnable()
        request = Materialization(profile_sources=_as_tuple(profile_sources),
                                  metadata_winning_source=metadata_winning_source)
        return runtime.cohort_builder().build(self.translation.queries, request, out,
                                              on_step=on_step, discovered=self.discovered)

    def _guard_runnable(self) -> None:
        if self.error is not None:
            raise TranslationError(self.error)

    def __str__(self) -> str:
        return f'Plan · "{self.question.text}"\n{self.translation.interpretation}\n{self.preview}'

    def save(self, path: Path) -> Path:
        """Write the plan as JSON. Source enums become their names -- JSON keys are
        strings, and a Source that came back as the string "METALOG_METADATA" would
        silently match nothing."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(_as_json(self), indent=2))
        return path
```

Replace `_as_json` with:

```python
def _as_json(plan: Plan) -> dict:
    return {
        "question": plan.question.text,
        "interpretation": plan.translation.interpretation,
        "queries": [{"source": query.source.name, "sql": query.sql}
                    for query in plan.translation.queries],
        "failure": plan.translation.failure,
        "preview": {
            "by_metadata_source": _named(plan.preview.by_metadata_source),
            "by_profile_source": _named(plan.preview.by_profile_source),
            "shared": plan.preview.shared,
            "union": plan.preview.union,
        },
        "error": plan.error,
        "discovered": _cohort_json(plan.discovered) if plan.discovered is not None else None,
    }


def _cohort_json(cohort: Cohort) -> dict:
    return {source.name: sorted(keys) for source, keys in cohort.by_source.items()}
```

Add `_cohort_of` next to the existing `_sourced` helper:

```python
def _cohort_of(payload: dict) -> Cohort:
    return Cohort({Source[name]: frozenset(Accession(key) for key in keys)
                   for name, keys in payload.items()})
```

Replace `_from_json` with:

```python
def _from_json(payload: dict) -> Plan:
    preview = payload["preview"]
    discovered_payload = payload.get("discovered")
    return Plan(
        question=ResearchQuestion(payload["question"]),
        translation=Translation(
            interpretation=payload["interpretation"],
            queries=tuple(SourceQuery(Source[entry["source"]], entry["sql"])
                          for entry in payload["queries"]),
            failure=payload["failure"]),
        preview=CohortPreview(
            by_metadata_source=_sourced(preview["by_metadata_source"]),
            by_profile_source=_sourced(preview["by_profile_source"]),
            shared=preview["shared"], union=preview["union"]),
        error=payload["error"],
        discovered=_cohort_of(discovered_payload) if discovered_payload else None)
```

- [ ] **Step 4: Run it, confirm it passes, then run the full suite**

Run: `python3 -m pytest Tests/test_plan_persistence.py -q`
Expected: `5 passed` (3 existing + 2 new)

Run: `python3 -m pytest Tests/ -q`
Expected: `131 passed`

- [ ] **Step 5: Commit**

```bash
git add src/askslm/plan.py Tests/test_plan_persistence.py
git commit -m "feat(plan): Plan.discovered caches the Cohort so run() need not re-query it"
```

---

### Task 8: `build.py` — `CohortBuilder.build()` accepts a cached cohort

**Files:**
- Modify: `src/askslm/build.py`
- Modify: `Tests/test_build_progress.py`

- [ ] **Step 1: Write the failing test**

Add to `Tests/test_build_progress.py` (keep the existing tests/fixture untouched):

```python
def test_a_cached_cohort_skips_rediscovery_and_gets_a_distinct_label(tmp_path):
    path = build_fixture_mirror(tmp_path / "fixture.duckdb")
    connection = DuckDbConnection(path)
    askslm.config(db=path, database=connection, backend=CannedLlmBackend(TRANSLATION))
    plan = askslm.ask("gut metagenomes")
    seen = []

    plan.run(profile_sources=askslm.Source.METALOG_MOTUS3, on_step=seen.append)

    assert seen[0] == "discovering cohort (cached)"
    connection.close()
```

- [ ] **Step 2: Run it, confirm it fails**

Run: `python3 -m pytest Tests/test_build_progress.py -q`
Expected: FAIL — `seen[0] == "discovering cohort"`, not `"discovering cohort (cached)"`
(this fails today because `ask()` doesn't attach a cached cohort yet — that's Task 9;
for now it fails simply because the label is never `"(cached)"` since `build()`
doesn't accept `discovered` at all yet, so this test is really checking `build.py`'s
new parameter in isolation first)

- [ ] **Step 3: Add the `discovered` parameter to `CohortBuilder.build()`**

In `src/askslm/build.py`, replace the `build` method with:

```python
    def build(self, queries, request: Materialization, out: Path | None,
              on_step: Callable[[str], None] | None = None,
              discovered: Cohort | None = None) -> tuple[biom.Table, BuildReport]:
        step = on_step or _noop_step
        if discovered is not None:
            step("discovering cohort (cached)")
            cohort = discovered
        else:
            step("discovering cohort")
            cohort = self._discovery.discover(queries)
        step("reading profile matrix")
        matrix = self._profiles.read(request.profile_sources, cohort.union())
        step("assembling and writing biom")
        metadata = self._metadata.reconciled(cohort, request.metadata_winning_source)
        table = self._factory.build(matrix, metadata.restricted_to(matrix.biosamples()))
        return self._written(table, out), self._report(request, cohort, matrix)
```

- [ ] **Step 4: Run it — it will still fail, because nothing passes `discovered`
      yet (that's Task 9). Confirm the failure mode changed:**

Run: `python3 -m pytest Tests/test_build_progress.py -q`
Expected: FAIL — `seen[0] == "discovering cohort"` (build.py now supports the
parameter, but `Plan.run()`/`ask()` don't populate it yet)

This is expected and correct at this point in the plan — Task 9 makes the test
pass. Do not skip ahead or improvise a fix here; the two tasks are deliberately
split (build.py's mechanism, then `__init__.py`'s wiring) so each commit is a
single, reviewable, working step. Run the rest of the suite to confirm nothing
else broke:

Run: `python3 -m pytest Tests/ -q`
Expected: `131 passed, 1 failed` (the new test above, expected to fail until Task 9)

- [ ] **Step 5: Commit**

```bash
git add src/askslm/build.py Tests/test_build_progress.py
git commit -m "feat(build): CohortBuilder.build() accepts a cached cohort, skipping rediscovery"
```

---

### Task 9: `__init__.py` — `ask()`/`_repaired()` attach the discovered cohort

**Files:**
- Modify: `src/askslm/__init__.py`
- Modify: `Tests/test_walking_skeleton.py`

- [ ] **Step 1: Write the failing tests**

Add to `Tests/test_walking_skeleton.py` (keep everything else in that file
unchanged):

```python
def test_ask_caches_the_discovered_cohort_on_the_plan(configured):
    plan = askslm.ask("fecal metagenomes from adults with IBD, Western countries")

    assert plan.discovered is not None
    assert plan.preview.union == len(plan.discovered.union())
```

Also add this single assertion at the end of the existing
`test_bad_sql_is_repaired_once_and_the_cohort_survives` test (keep everything
already there, just add the line before `connection.close()`):

```python
    assert plan.discovered is not None      # the repaired SQL's cohort, cached too
```

- [ ] **Step 2: Run it, confirm it fails**

Run: `python3 -m pytest Tests/test_walking_skeleton.py -q`
Expected: FAIL — `plan.discovered is not None` (currently `None`, since `ask()`
never attaches it)

- [ ] **Step 3: Wire `_discover()` and attach the cohort in `ask()`/`_repaired()`**

In `src/askslm/__init__.py`, add `dataclass` to the imports:

```python
from dataclasses import dataclass
```

Add `CohortDiscovery` to the existing `askslm.cohort` import line:

```python
from askslm.cohort import Accession, Cohort, CohortDiscovery, InvalidCohortQuery
```

Replace `ask()` with:

```python
def ask(question: str, save: str | Path | None = None) -> Plan:
    """One LLM hop plus cheap COUNTs. Pass save= to also persist the plan as JSON."""
    research_question = ResearchQuestion(question)
    translation = runtime.translator().translate(research_question)
    if translation.failure is not None:
        plan = Plan(research_question, translation, CohortPreview(), error=translation.failure)
    else:
        try:
            discovery = _discover(translation)
            plan = Plan(research_question, translation, discovery.preview,
                       discovered=discovery.cohort)
        except InvalidCohortQuery as error:
            plan = _repaired(research_question, translation, error)
    if save is not None:
        plan.save(save)
    return plan
```

Replace `_repaired()` with (docstring unchanged, only the body's success branch
changes):

```python
def _repaired(question: ResearchQuestion, translation: Translation,
              error: InvalidCohortQuery) -> Plan:
    """One retry, using the database's own error text.

    Four rounds of prompt tuning each fixed one class of bad SQL and revealed the next.
    Handing the model the rejection instead is the standard text-to-SQL answer and it
    generalises: DuckDB names the offending column and even suggests candidates, which
    is better information than any rule we could write in advance.

    A second failure is reported as-is. There is no third attempt -- if the model cannot
    fix its own SQL with the error in front of it, looping will not help.
    """
    fixed = runtime.backend().repair(
        sql=_sql_for(translation, error.source),
        error=error.message,
        columns=_columns_of(error.source))
    retried = _with_sql(translation, error.source, fixed)
    try:
        discovery = _discover(retried)
        return Plan(question, retried, discovery.preview, discovered=discovery.cohort)
    except InvalidCohortQuery as second:
        return Plan(question, retried, CohortPreview(), error=str(second))
```

Replace `_preview()` (renaming it, and its return shape) with:

```python
@dataclass(frozen=True)
class _Discovery:
    cohort: Cohort
    preview: CohortPreview


def _discover(translation: Translation) -> _Discovery:
    cohort = CohortDiscovery(runtime.database()).discover(translation.queries)
    reader = ProfileReader(runtime.database())
    preview = CohortPreview(
        by_metadata_source={source: len(keys) for source, keys in cohort.by_source.items()},
        shared=len(cohort.shared()),
        union=len(cohort.union()),
        by_profile_source={source: len(reader.coverage(source, cohort.union()))
                           for source in Source if source.kind() is SourceKind.PROFILE},
    )
    return _Discovery(cohort, preview)
```

(`_sql_for`, `_with_sql`, `_columns_of` are unchanged — only `_preview` is renamed
and reshaped, and only `ask()`/`_repaired()`, its two callers, change.)

- [ ] **Step 4: Run it, confirm it passes, then run the full suite (this also
      finishes Task 8's pending test)**

Run: `python3 -m pytest Tests/test_walking_skeleton.py -q`
Expected: all pass (report the real count)

Run: `python3 -m pytest Tests/test_build_progress.py -q`
Expected: `2 passed` (the Task 8 test now passes too, since `ask()` populates
`plan.discovered`)

Run: `python3 -m pytest Tests/ -q`
Expected: `133 passed`

- [ ] **Step 5: Commit**

```bash
git add src/askslm/__init__.py Tests/test_walking_skeleton.py
git commit -m "feat: ask() attaches its discovered cohort to Plan, so run() reuses it"
```

---

### Task 10: Wrap-up

- [ ] **Step 1: Run the full suite one more time**

Run: `python3 -m pytest Tests/ -q`
Expected: `133 passed`

- [ ] **Step 2: Manual verification against the real mirror** (per the design
      doc's verification section)

1. Re-ask the real question ("IBD fecal metagenomic with calprotectin") and
   confirm `interpretation` now discloses the Metalog calprotectin gap; spot
   check an unrelated whole-source-omission question (e.g. "human tumour
   RNA-seq") is unaffected.
2. Run `ask()` then `Plan.run()` and confirm (via `log.txt`) the expensive
   discovery SQL executes exactly once, not twice; confirm the saved
   `plan.json` has a `"discovered"` key with real biosample keys; confirm an
   old plan.json (from before this change) still loads and runs.
3. Submit a real SLURM job and watch it — confirm the Task 6 manual checklist
   items all hold together end to end.

- [ ] **Step 3: Push and open the PR**

```bash
git push -u origin feature/prompt-progress-and-cohort-cache
gh pr create --base main --title "fix: disclose unverifiable criteria, structured progress view, cache discovered cohorts" --body "$(cat <<'EOF'
## Summary
- prompt.py: a source that can express most of a compound question but is missing one named criterion (e.g. Metalog has no calprotectin field) must now disclose that gap in `interpretation` instead of silently returning samples that don't meet it.
- The live "watch" view no longer dumps raw log.txt (which mixes in full SQL/LLM debug logging from ask()); it renders a clean, redraw-in-place status line plus permanent phase lines from a new dedicated progress.py trail, including squeue's reason code and a queued-time counter.
- Plan now caches the Cohort ask() discovers, so an expensive discovery query that hasn't changed no longer re-runs a second time inside Plan.run() -- including across the SLURM job boundary and through saved/reloaded plans.

Design: /Users/yarintamam/.claude/plans/you-suggested-fix-will-crystalline-moon.md
Plan: Docs/superpowers/plans/2026-08-20-prompt-progress-cohort-cache.md

## Test plan
- [ ] python3 -m pytest Tests/ -q -- 133 passed
- [ ] Manual checklist in Task 10 of the plan, run against the real mirror on the cluster
EOF
)"
```

- [ ] **Step 4: Stop.** The user squash-merges through GitHub.
