"""SLURM job templating, submission, and status -- the mechanics 'Run it' needs to
submit a real sbatch job instead of running the build on the login node.

Resource numbers are scaled down from Anna Shafir's own proven-working jobs on this
cluster (run_duckdb.sh: cpu192G-48h/18cpu/64G/4h; run_sirius.sh: H200-12h/48cpu/
gres:gpu:1/1T/4h) -- hers ran a full 39M-row unfiltered join; a cohort build reads an
already-discovered, cohort-scoped set of biosamples off stat_coverage.

CPU memory revised 2026-08-20 from the first real build (job 23680753, a 4503-biosample
IBD cohort over SRA_TAXONOMY): DuckDB alone reached MaxRSS 41.3G against the old 48G
cap, and that was before `fetch_df` materialized the result. The result frame, the
`_with_biosample` merge, the pivot, and `to_json` all live OUTSIDE DuckDB's buffer pool,
so they are not spillable and not counted by `memory_limit` -- the cap has to cover the
buffer pool AND everything pandas builds on top of it. 160G still fits the 192G nodes,
which are usually idle, so the headroom costs no queue time.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Callable

CPU_TEMPLATE = """#!/bin/bash
#SBATCH --job-name=cohortquery-cohort
#SBATCH --partition=cpu192G-48h
#SBATCH --cpus-per-task=8
#SBATCH --mem=160G
#SBATCH --time=08:00:00
#SBATCH --output={plan_dir}/slurm-%j.out
#SBATCH --error={plan_dir}/slurm-%j.err

{worker_cmd}
"""

GPU_TEMPLATE = """#!/bin/bash
#SBATCH --job-name=cohortquery-cohort-gpu
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


def submit(script_path: Path,
          run: Callable[..., subprocess.CompletedProcess] = subprocess.run) -> str:
    result = run(["sbatch", str(script_path)], capture_output=True, text=True, check=True)
    match = re.search(r"Submitted batch job (\d+)", result.stdout)
    if not match:
        raise RuntimeError(
            f"could not parse a job id from sbatch output: "
            f"stdout={result.stdout!r} stderr={result.stderr!r}")
    return match.group(1)


def squeue_state(job_id: str,
                run: Callable[..., subprocess.CompletedProcess] = subprocess.run) -> str | None:
    """None means the job is no longer in the queue -- finished, one way or another.
    A nonzero exit is squeue itself failing (not on PATH, scheduler hiccup) and must
    not be confused with that: a job that's actually gone still exits 0 with empty
    stdout."""
    result = run(["squeue", "-j", job_id, "-h", "-o", "%T"], capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"squeue failed for job {job_id}: {result.stderr!r}")
    state = result.stdout.strip()
    return state or None


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


def cancel(job_id: str,
          run: Callable[..., subprocess.CompletedProcess] = subprocess.run) -> None:
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
