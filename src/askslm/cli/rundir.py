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
