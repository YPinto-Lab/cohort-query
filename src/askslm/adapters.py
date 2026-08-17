"""Concrete implementations of the two ports. The only place third-party libs are touched."""
from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd

from askslm.translation import Translation, TranslationPrompt


class DuckDbConnection:
    """The mirror is opened READ-ONLY. Any write -- including a stray LLM INSERT -- is
    refused by DuckDB itself rather than by validation we would have to write."""

    def __init__(self, db_path: Path):
        self._connection = duckdb.connect(str(db_path), read_only=True)

    def query(self, sql: str) -> pd.DataFrame:
        return self._connection.execute(sql).fetch_df()

    def close(self) -> None:
        self._connection.close()


class CannedLlmBackend:
    """A backend that returns a Translation it was handed.

    ponytail: this is the walking skeleton's LLM. It exists so the whole
    discover -> reconcile -> assemble path is exercised end to end before a real
    provider is wired in; GeminiBackend implements the same port and replaces it
    at the composition root with nothing else changing.
    """

    def __init__(self, translation: Translation):
        self._translation = translation

    def translate(self, prompt: TranslationPrompt) -> Translation:
        return self._translation
