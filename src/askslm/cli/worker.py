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
from typing import Callable

import askslm
from askslm.cli import jobs, progress, rundir
from askslm.plan import load_plan
from askslm.sources import Source

_logger = logging.getLogger("askslm.worker")


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)
    handler = rundir.attach_log_handler(args.plan_dir)
    try:
        jobs.write_status(args.plan_dir, "RUNNING")
        plan = load_plan(args.plan)
        askslm.config(db=args.db, gpu=args.gpu)
        _, report = plan.run(
            profile_sources=[Source[name.strip()] for name in args.sources.split(",")],
            out=args.out,
            on_step=_on_step(args.plan_dir))
        (args.plan_dir / "report.txt").write_text(str(report))
        jobs.write_status(args.plan_dir, "DONE")
    except Exception:
        jobs.write_status(args.plan_dir, "FAILED")
        raise
    finally:
        rundir.detach_log_handler(handler)


def _on_step(plan_dir: Path) -> Callable[[str], None]:
    def step(label: str) -> None:
        _logger.info(label)
        progress.write_start(plan_dir, label)
    return step


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
