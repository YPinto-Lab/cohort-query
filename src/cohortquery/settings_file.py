"""Where config() gets its arguments when nobody is writing Python.

Precedence is env -> file -> nothing (which means the app prompts). The
environment winning is what lets the lab server and CI run with no interactive
step and no file on disk. HLD C.0.1.
"""
from __future__ import annotations

import os
import tomllib
from pathlib import Path

CONFIG_PATH = Path.home() / ".cohortquery" / "config.toml"


def stored_settings(path: Path = CONFIG_PATH) -> dict:
    """Everything we could find, or {} if the app must ask. Partial is possible:
    a db path in the file and a key in the environment is a normal setup."""
    settings = _from_file(path)
    settings.update(_from_environment())
    return settings


def _from_environment() -> dict:
    found = {"db": os.environ.get("COHORTQUERY_DB"),
             "llm_key": os.environ.get("COHORTQUERY_LLM_KEY")}
    return {key: value for key, value in found.items() if value}


def _from_file(path: Path) -> dict:
    if not path.exists():
        return {}
    return dict(tomllib.loads(path.read_text()))


def write_settings(path: Path, db: str, llm_key: str) -> Path:
    """Written once on first run. Mode 0600 -- it holds an API key."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f'db = "{db}"\nllm_key = "{llm_key}"\n')
    path.chmod(0o600)
    return path
