"""The live progress view: shared by 'Run it' -> Watch progress and by reattaching
via `askslm load` to a plan folder whose job is still running.

Reads only the worker's own structured progress trail (progress.py) and squeue --
never log.txt, which carries full SQL/LLM debug logging from the interactive ask()
phase and would otherwise be replayed as if it were live job activity."""
from __future__ import annotations

import time
from pathlib import Path

from rich.console import Console
from rich.status import Status

from askslm.cli import jobs, progress

POLL_SECONDS = 3
TOTAL_PHASES = 3          # CohortBuilder.build's fixed phase count


def watch(plan_dir: Path, console: Console) -> None:
    """`console.status()`'s redraw-in-place only renders on a real terminal --
    `rich.status.Status` is a transient Live display that writes nothing at all
    when `console.is_terminal` is False (piped output, a logged session). On
    those, the status line is also printed as an ordinary line each poll, so a
    non-interactive watcher still sees periodic progress instead of silence."""
    job_id = jobs.read_job_id(plan_dir)
    submitted_at = progress.read_submitted(plan_dir)
    printed: set[str] = set()
    interactive = console.is_terminal
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
                    _show(live, console, interactive,
                         f"[yellow]squeue check failed, retrying: {error}[/yellow]")
                    time.sleep(POLL_SECONDS)
                    continue
                if result is None:
                    status = jobs.read_status(plan_dir)
                    if status in ("DONE", "FAILED"):
                        report_path = plan_dir / "report.txt"
                        if report_path.exists():
                            console.print(report_path.read_text())
                        return
                    if status is None:
                        console.print(
                            "[red]job left the queue and never reported a status[/red]")
                    else:
                        console.print(
                            f"[yellow]job left the queue while status.txt still said "
                            f"{status!r} -- likely killed outside askslm (scancel, OOM)[/yellow]")
                    return
                state, reason = result
                _show(live, console, interactive,
                     _status_line(job_id, state, reason, submitted_at, events, printed))
                time.sleep(POLL_SECONDS)
    except KeyboardInterrupt:
        console.print("\n[dim]stopped watching -- job keeps running[/dim]")


def _show(live: Status, console: Console, interactive: bool, line: str) -> None:
    live.update(line)
    if not interactive:
        console.print(line)


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
