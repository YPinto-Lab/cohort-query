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
            try:
                state = jobs.squeue_state(job_id)
            except RuntimeError as error:
                # A transient squeue failure isn't the job's fault -- retry rather
                # than crash the view or mistake it for the job having finished.
                console.print(f"[yellow]squeue check failed, retrying: {error}[/yellow]")
                time.sleep(POLL_SECONDS)
                continue
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
