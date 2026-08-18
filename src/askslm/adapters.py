"""Concrete implementations of the two ports. The only place third-party libs are touched."""
from __future__ import annotations

import json
from pathlib import Path

import duckdb
import pandas as pd

from askslm.prompt import SYSTEM_INSTRUCTION
from askslm.sources import Source, SourceKind
from askslm.translation import SourceQuery, Translation, TranslationPrompt


class DuckDbConnection:
    """The mirror is opened READ-ONLY. Any write -- including a stray LLM INSERT -- is
    refused by DuckDB itself rather than by validation we would have to write.

    If the mirror records a `sra_db_path` in `mirror_config`, that database is attached
    read-only too: `sra_taxonomy` is a view over its 13.6B-row table rather than a copy.
    config(db=...) therefore still takes ONE path -- the second is read out of the
    mirror, not asked of the caller. A fixture with no mirror_config just skips this.
    """

    def __init__(self, db_path: Path):
        self._connection = duckdb.connect(str(db_path), read_only=True)
        self._attach_sources()

    def _attach_sources(self) -> None:
        for alias, path in self._attachments():
            self._connection.execute(f"ATTACH '{path}' AS {alias} (READ_ONLY)")

    def _attachments(self) -> list[tuple[str, str]]:
        tables = self._connection.execute("SHOW TABLES").fetchall()
        if ("mirror_config",) not in tables:
            return []
        rows = self._connection.execute(
            "SELECT value FROM mirror_config WHERE key = 'sra_db_path'").fetchall()
        return [("sra", row[0]) for row in rows]

    def query(self, sql: str, params: list | None = None) -> pd.DataFrame:
        return self._connection.execute(sql, params or []).fetch_df()

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


class GeminiBackend:
    """The real LlmBackend. Same port as CannedLlmBackend, so nothing below it changes.

    The client is injected rather than constructed here: that is what lets the tests
    exercise every branch of the parsing with no API key and no network.
    """

    def __init__(self, client, model: str):
        self._client = client
        self._model = model

    def translate(self, prompt: TranslationPrompt) -> Translation:
        response = self._client.models.generate_content(
            model=self._model,
            contents=_prompt_text(prompt),
            config={"system_instruction": SYSTEM_INSTRUCTION,
                    "response_mime_type": "application/json"})
        return _translation_of(json.loads(_unfenced(response.text)))


def open_gemini(api_key: str, model: str) -> GeminiBackend:
    """Constructed at the composition root; imported lazily so `import askslm` does not
    require google-genai for anyone using the canned backend."""
    from google import genai

    return GeminiBackend(genai.Client(api_key=api_key), model)


def _prompt_text(prompt: TranslationPrompt) -> str:
    return (f"SCHEMA\n{prompt.schemas}\n\n"
            f"QUESTION\n{prompt.question.text}\n")


def _unfenced(text: str) -> str:
    """Models fence their JSON even when told to return JSON only."""
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    body = stripped.split("\n", 1)[1]
    return body.rsplit("```", 1)[0].strip()


def _translation_of(payload: dict) -> Translation:
    """This is the boundary where an external model's output enters the system, so it is
    the one place a wrong-kind source name is checked: `by_source` is trusted to be
    metadata-keyed everywhere downstream (HLD E.2), and a PROFILE source slipped in here
    would have MetadataReconciler read a multi-billion-row taxonomy table as metadata --
    silently, and without the check ever failing loudly again."""
    queries = tuple(_source_query_of(entry) for entry in payload.get("queries", []))
    return Translation(interpretation=payload.get("interpretation") or "",
                       queries=queries,
                       failure=payload.get("failure"))


def _source_query_of(entry: dict) -> SourceQuery:
    source = Source[entry["source"]]
    if source.kind() is not SourceKind.METADATA:
        raise ValueError(f"model returned a non-metadata source: {source.name}")
    return SourceQuery(source, entry["sql"])
