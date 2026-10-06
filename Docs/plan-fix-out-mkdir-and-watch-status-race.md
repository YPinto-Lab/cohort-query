# Plan: fix two bugs found investigating SLURM job 29510021

Investigated on the lab server (`ssh biu`) via `sacct -j 29510021` and reading
`~/plans/20260915_125826_ibd-calprotectin/{status.txt,slurm-29510021.err}`.
Two independent bugs, both worth fixing:

## Bug 1 — `CohortBuilder._written()` never creates `out`'s parent directory

`src/askslm/build.py:239-242`:

```python
def _written(self, table: biom.Table, out: Path | None) -> biom.Table:
    if out is not None:
        Path(out).write_text(table.to_json("askslm"))
    return table
```

This is the only file-writer in the codebase that skips the
`mkdir(parents=True, exist_ok=True)` convention every other writer already
follows:

- `src/askslm/plan.py:85` (`Plan.save`)
- `src/askslm/settings_file.py:38`
- `src/askslm/checkpoint.py:121-123` (`_mkdir`)

Because of the gap, job 29510021 discovered its full cohort, read the profile
matrix, and assembled the biom table (~56s of real work, all successful) and
only then crashed at the last line with `FileNotFoundError` because `out`'s
directory didn't exist — discarding the entire build.

### Fix
Mirror `plan.py:85`'s pattern exactly:

```python
def _written(self, table: biom.Table, out: Path | None) -> biom.Table:
    if out is not None:
        out = Path(out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(table.to_json("askslm"))
    return table
```

No new dependency, no new abstraction — same one-liner already used three
other places in this codebase (see [[feedback_compose_over_duplicate]]-style
reuse: match the existing pattern instead of inventing a new one).

### Test
`Tests/` smoke test: call `_written` (or `CohortBuilder.build` with a minimal
fake table) with an `out` path whose parent doesn't exist yet; assert the file
exists after the call. This is exactly the scenario that crashed job
29510021 — reproduce it, then confirm the fix closes it.

## Bug 2 — `watch.py` misreports a real FAILED job as "never reported a status"

`src/askslm/cli/watch.py:51-60`. When `squeue` reports the job gone, the
watcher does exactly **one** re-read of `status.txt`:

```python
if result is None:
    status = jobs.read_status(plan_dir)
    if status in ("DONE", "FAILED"):
        ...
    if status is None:
        console.print("[red]job left the queue and never reported a status[/red]")
```

`worker.py:39-41` writes `status.txt = "FAILED"` **before** re-raising and
exiting, so the file is written before the SLURM job disappears from
`squeue`. But job 29510021's `status.txt` did say `FAILED` — confirmed by
reading it directly, well after the fact — so the write happened; the
watcher's single read next to the squeue-gone check just raced it (NFS
propagation lag between the compute node's write and the watcher's read,
consistent with [[project_lab_cluster_and_io_wall]]). Net effect: a real,
correctly-recorded failure gets reported to the user as an unexplained
disappearance, hiding the actual traceback.

### Fix
Retry the `status.txt` read a few times with a short backoff before
concluding it's genuinely absent, instead of a single read:

```python
if result is None:
    status = _read_status_with_retry(plan_dir)
    if status in ("DONE", "FAILED"):
        report_path = plan_dir / "report.txt"
        if report_path.exists():
            console.print(report_path.read_text())
        return
    if status is None:
        console.print("[red]job left the queue and never reported a status[/red]")
    else:
        console.print(
            f"[yellow]job left the queue while status.txt still said "
            f"{status!r} -- likely killed outside askslm (scancel, OOM)[/yellow]")
    return
```

```python
def _read_status_with_retry(plan_dir: Path, attempts: int = 3, delay: float = 2.0) -> str | None:
    for i in range(attempts):
        status = jobs.read_status(plan_dir)
        if status is not None:
            return status
        if i < attempts - 1:
            time.sleep(delay)
    return None
```

`time` is already imported in `watch.py`. Numbers (3 attempts, 2s) are a
starting guess, not tuned against measured NFS lag — fine as a first pass
since the failure mode (false negative on a real status) is what's being
closed, not exact timing.

### Test
`Tests/` smoke test: fake `jobs.read_status` to return `None` on the first
two calls and `"FAILED"` on the third; assert `_read_status_with_retry`
returns `"FAILED"` (proves the retry, not just the first read, matters) and
that a `None`-only fake still returns `None` after `attempts` tries (proves it
doesn't retry forever).

## Branching
Per `CLAUDE.md`: one branch off `main` covers both (they were found together
investigating the same job): `git fetch origin && git switch -c
bug/out-mkdir-and-watch-status-race origin/main`. Don't work on `main` or the
current `feature/prjna400072-viral-ecology` branch.

## Out of scope
- Not touching the `_ask_db`/"Write to" prompt UX (e.g. validating the path
  up front) — the fix belongs at the writer, not by restricting what path the
  user can type.
- Not tuning the exact retry count/delay against measured NFS latency —
  revisit only if the race still reproduces with 3x2s.
