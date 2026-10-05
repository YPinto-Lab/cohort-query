"""Per-question plan folders: plans/<ts>_<slug>/ created the instant a question is
submitted, so a run leaves a trail even if ask() throws before anything else."""
from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path

PLANS_ROOT = Path("plans")
LOGGER_NAME = "cohortquery"


def new_plan_dir(question: str = "", root: Path = PLANS_ROOT) -> Path:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    slug = _slugify(question)
    plan_dir = root / (f"{ts}_{slug}" if slug else ts)
    plan_dir.mkdir(parents=True)
    return plan_dir


def _slugify(text: str, max_len: int = 40) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:max_len].rstrip("-")


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
