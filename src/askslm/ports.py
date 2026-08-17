"""The two interfaces the core defines for things it needs from outside.

The core depends on these, never on DuckDB or a specific LLM. They earn their
keep twice over: the tests swap in fakes so every service runs with no network
and no disk, and the product commits to a provider swap.
"""
from __future__ import annotations

from typing import Protocol

import pandas as pd


class Database(Protocol):
    def query(self, sql: str, params: list | None = None) -> pd.DataFrame:
        """Run read-only SQL and return the rows.

        `params` exists so a cohort's key set travels as ONE bound list rather than
        as inlined literals -- a 200k-sample cohort is a 3 MB SQL string otherwise,
        and SRA has 32M biosamples.
        """


class LlmBackend(Protocol):
    def translate(self, prompt: "TranslationPrompt") -> "Translation":
        """Turn a research question plus schemas into one SQL per metadata source."""
