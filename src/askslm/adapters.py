"""Concrete implementations of the two ports. The only place third-party libs are touched."""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path

import duckdb
import pandas as pd

from askslm.concept_search import EMBED_DIM
from askslm.expansion import MAX_TERMS
from askslm.expansion import SYSTEM_INSTRUCTION as EXPANSION_INSTRUCTION
from askslm.prompt import SYSTEM_INSTRUCTION
from askslm.sources import Source, SourceKind
from askslm.translation import SourceQuery, Translation, TranslationPrompt


SIRIUS_EXTENSION_PATH = "/private/pinto-lab/anna/sirius/build/sirius.duckdb_extension"

_logger = logging.getLogger(__name__)


def _log_safely(message: str, *args) -> None:
    """expand()/repair() are documented as never raising -- a broken log handler
    (full disk, bad formatter) must not turn that into a lie."""
    try:
        _logger.info(message, *args)
    except Exception:
        pass


def _sql_literal(value) -> str:
    if isinstance(value, list):
        return "[" + ", ".join(_sql_literal(item) for item in value) + "]"
    return "'" + str(value).replace("'", "''") + "'"


def _inlined(sql: str, params: list) -> str:
    for value in params:
        sql = sql.replace("?", _sql_literal(value), 1)
    return sql


def _gpu_wrapped(sql: str, params: list, gpu: bool) -> tuple[str, list]:
    """gpu_processing() takes SQL as a dollar-quoted string literal, so a `?` inside
    it is just text to DuckDB's outer parser, not a bind parameter -- params have to
    be inlined as literals before wrapping, or every parameterized query (which is
    most of the profile/cohort reads GPU mode targets) throws a parameter mismatch."""
    if not gpu:
        return sql, params
    if params:
        sql = _inlined(sql, params)
        params = []
    return f"SELECT * FROM gpu_processing($$ {sql} $$)", params


class DuckDbConnection:
    """The mirror is opened READ-ONLY. Any write -- including a stray LLM INSERT -- is
    refused by DuckDB itself rather than by validation we would have to write.

    If the mirror records a `sra_db_path` in `mirror_config`, that database is attached
    read-only too: `sra_taxonomy` is a view over its 13.6B-row table rather than a copy.
    config(db=...) therefore still takes ONE path -- the second is read out of the
    mirror, not asked of the caller. A fixture with no mirror_config just skips this.
    """

    def __init__(self, db_path: Path, gpu: bool = False):
        self._connection = duckdb.connect(str(db_path), read_only=True)
        self._connection.execute("INSTALL vss")
        self._connection.execute("LOAD vss")
        self._attach_sources()
        self._gpu = gpu
        if gpu:
            self._connection.execute(f"LOAD '{SIRIUS_EXTENSION_PATH}'")
            self._connection.execute("SELECT gpu_buffer_init()")

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
        wrapped_sql, wrapped_params = _gpu_wrapped(sql, params or [], self._gpu)
        start = time.monotonic()
        frame = self._connection.execute(wrapped_sql, wrapped_params).fetch_df()
        _logger.info("SQL (%.2fs, %d rows): %s", time.monotonic() - start, len(frame), sql)
        return frame

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

    def expand(self, question: str) -> list[str]:
        """No model behind this backend, so no synonyms -- retrieval falls back to the
        words of the question, which is what the tests exercise."""
        return []

    def repair(self, sql: str, error: str, columns: str) -> str:
        """No model, nothing to repair with."""
        return sql

    def embed(self, texts: list[str]) -> list[list[float]]:
        """No model behind this backend, so no vectors -- retrieval falls back to
        substring matching, which is what the tests exercise."""
        return []

    def translate(self, prompt: TranslationPrompt) -> Translation:
        return self._translation


class GeminiBackend:
    """The real LlmBackend. Same port as CannedLlmBackend, so nothing below it changes.

    The client is injected rather than constructed here: that is what lets the tests
    exercise every branch of the parsing with no API key and no network.
    """

    # Free-tier quota is counted PER MODEL (GenerateRequestsPerDayPerProjectPerModel),
    # and gemini-2.5-flash allows 20 requests a DAY. Translation is the hard task and
    # keeps that budget to itself; expansion and repair are trivial and run on a
    # different model, which is both cheaper and a SEPARATE quota pool -- so one
    # question costs one request from each, not two from the same one.
    HELPER_MODEL = "gemini-2.5-flash-lite"

    # gemini-embedding-001 is the current recommended text embedding model
    # (text-embedding-004 was deprecated January 2026) -- free tier, separate
    # quota pool from both the translation and helper models. Confirm this is
    # still current before relying on it; Google deprecates on ~annual cadence.
    EMBEDDING_MODEL = "gemini-embedding-001"

    def __init__(self, client, model: str):
        self._client = client
        self._model = model

    def expand(self, question: str) -> list[str]:
        """Never raises: a failed expansion must degrade to plain lexical matching,
        not take down ask()."""
        start = time.monotonic()
        try:
            response = self._client.models.generate_content(
                model=self.HELPER_MODEL, contents=question,
                config={"system_instruction": EXPANSION_INSTRUCTION,
                        "response_mime_type": "application/json",
                        "automatic_function_calling": {"disable": True}})
            terms = json.loads(_unfenced(response.text)).get("terms", [])
        except Exception:
            _log_safely("expand (%.2fs) failed for question=%r",
                       time.monotonic() - start, question)
            return []
        _log_safely("expand (%.2fs)\nQUESTION: %s\nRESPONSE: %s",
                   time.monotonic() - start, question, response.text)
        return [str(term).lower() for term in terms][:MAX_TERMS]

    def repair(self, sql: str, error: str, columns: str) -> str:
        """One targeted retry. Never raises -- a failed repair leaves the original SQL
        and the original error, which is what the user would have seen anyway."""
        instruction = (
            "You are given SQL that a DuckDB database REJECTED, the exact error, and "
            "the real columns of the table. Return corrected SQL only -- no prose, no "
            "markdown fence. Use ONLY the listed columns. Keep the query's intent and "
            "its SELECT list unchanged. If a column the query wants does not exist, "
            "drop that condition rather than inventing a replacement.")
        start = time.monotonic()
        try:
            response = self._client.models.generate_content(
                model=self.HELPER_MODEL,
                contents=f"ERROR\n{error}\n\nCOLUMNS\n{columns}\n\nSQL\n{sql}",
                config={"system_instruction": instruction,
                        "automatic_function_calling": {"disable": True}})
            fixed = _unfenced(response.text) or sql
        except Exception:
            _log_safely("repair (%.2fs) failed for sql=%r", time.monotonic() - start, sql)
            return sql
        _log_safely("repair (%.2fs)\nSQL: %s\nERROR: %s\nFIXED: %s",
                   time.monotonic() - start, sql, error, fixed)
        return fixed

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Never raises: a failed embedding call must degrade to substring-only
        retrieval, not take down ask(). Batched into ONE call -- embed_content
        accepts a list of contents and returns one vector per input, same order."""
        if not texts:
            return []
        start = time.monotonic()
        try:
            response = self._client.models.embed_content(
                model=self.EMBEDDING_MODEL, contents=texts,
                config={"output_dimensionality": EMBED_DIM})
        except Exception:
            _log_safely("embed (%.2fs) failed for texts=%r",
                       time.monotonic() - start, texts)
            return []
        _log_safely("embed (%.2fs) for %d texts", time.monotonic() - start, len(texts))
        return [list(embedding.values) for embedding in response.embeddings]

    def translate(self, prompt: TranslationPrompt) -> Translation:
        start = time.monotonic()
        response = self._client.models.generate_content(
            model=self._model,
            contents=_prompt_text(prompt),
            config={"system_instruction": SYSTEM_INSTRUCTION,
                    "response_mime_type": "application/json",
                    # We pass no tools, so automatic function calling has nothing to do
                    # -- but it is ON by default, and the SDK then warns on every call
                    # that AFC belongs in Chat.send_message. Saying "off" states the
                    # intent and removes the warning at its cause.
                    "automatic_function_calling": {"disable": True}})
        _logger.info("translate (%.2fs)\nPROMPT: %s\nRESPONSE: %s",
                    time.monotonic() - start, prompt.question.text, response.text)
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
