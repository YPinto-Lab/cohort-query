"""Concrete implementations of the two ports. The only place third-party libs are touched."""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path

import duckdb
import pandas as pd

from askslm.expansion import MAX_TERMS
from askslm.expansion import SYSTEM_INSTRUCTION as EXPANSION_INSTRUCTION
from askslm.prompt import SYSTEM_INSTRUCTION
from askslm.sources import Source, SourceKind
from askslm.translation import SourceQuery, Translation, TranslationPrompt


SIRIUS_EXTENSION_PATH = "/private/pinto-lab/anna/sirius/build/sirius.duckdb_extension"

# mirror_config key -> ATTACH alias, for the big tables kept OUTSIDE the mirror file.
# Sorting these by their read key is what makes a cohort filter prune row groups instead
# of scanning the whole table, so they are built once and attached read-only rather than
# copied into the mirror. step3_assemble_mirror.py writes the views against these same aliases.
#
# `sra_db_path` is the historical name for the sorted TAXONOMY file and is kept so that
# mirrors built before the metadata sort keep resolving.
SIDECAR_ALIASES = {"sra_db_path": "sorted_src",          # sra_taxonomy  -> tax_fact
                   "sra_metadata_path": "sorted_meta"}   # sra_metadata  -> metadata_fact


# What a usable mirror must contain. `step3_assemble_mirror.py` produces only the first seven;
# the last four come from step4_index_attributes.py, step5_catalog_schema.py and
# step6_embed_concepts.py, which for a long time were run by hand -- so a mirror
# built by the documented command was silently missing the LLM's entire vocabulary and
# failed much later, deep in discovery, with a bare DuckDB "table does not exist".
#
# `mirror_config` is deliberately NOT required: a single-file mirror (the generated test
# fixture) has no sidecars to record and is perfectly usable without it.
REQUIRED_TABLES = frozenset({
    "sra_metadata", "sra_taxonomy", "stat_coverage",
    "metalog_metadata", "metalog_metaphlan4", "metalog_motus3", "metalog_spire_motus",
    "attribute_keys",            # every jattr key, so a question can name a phenotype
    "schema_catalog",            # columns + real value vocabularies for the prompt
    "attribute_key_embeddings",  # concept search over those keys
    "column_value_embeddings",   # concept search over those values
})


class IncompleteMirror(RuntimeError):
    """Raised when a mirror is missing tables the package needs to answer anything."""


_PRESENT_SQL = ("SELECT table_name AS name FROM duckdb_tables() "
                "UNION ALL SELECT view_name FROM duckdb_views() WHERE NOT internal")


def missing_tables(connection) -> list[str]:
    """Which REQUIRED_TABLES a raw DuckDB connection lacks. For the build scripts,
    which hold a connection rather than a Database."""
    present = {row[0] for row in connection.execute(_PRESENT_SQL).fetchall()}
    return sorted(REQUIRED_TABLES - present)


def verify_mirror(database, db_path=None) -> None:
    """Fail at open time, naming the missing tables and the command that adds them.

    Checked here rather than in DuckDbConnection so that tests may still construct
    deliberately partial fixtures directly; this guards the real path, where a
    researcher has typed a question and would otherwise wait through discovery only to
    hit a CatalogException that says nothing about which build step was skipped.

    Goes through the Database port's own `query`, never a private attribute, so any
    implementation of the port -- including a test double -- can be verified.
    """
    absent = sorted(REQUIRED_TABLES - set(database.query(_PRESENT_SQL)["name"]))
    if not absent:
        return
    where = f" at {db_path}" if db_path else ""
    raise IncompleteMirror(
        f"The mirror{where} is incomplete -- missing: {', '.join(absent)}.\n"
        f"Finish it with:  Scripts/build_mirror/build_all.sh --stage enrich "
        f"--out-dir <the directory holding the mirror>")

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


def sidecars_of(connection) -> list[tuple[str, str]]:
    """(alias, path) for every sidecar this mirror records, in SIDECAR_ALIASES order.

    A mirror with no `mirror_config` (the generated single-file test fixture) records
    none, and one predating a given sidecar simply omits that key.
    """
    tables = connection.execute("SHOW TABLES").fetchall()
    if ("mirror_config",) not in tables:
        return []
    configured = dict(connection.execute("SELECT key, value FROM mirror_config").fetchall())
    return [(alias, configured[key])
            for key, alias in SIDECAR_ALIASES.items() if key in configured]


def attach_sidecars(connection) -> list[tuple[str, str]]:
    """ATTACH every recorded sidecar read-only, so the mirror's `sra_*` views resolve.

    Shared by the runtime connection and by the build scripts that open a mirror
    directly -- since the big tables became views, a plain `duckdb.connect(mirror)`
    cannot read `sra_metadata` at all without this, and fails with
    'schema sorted_meta does not exist'.
    """
    attached = sidecars_of(connection)
    for alias, path in attached:
        connection.execute(f"ATTACH '{path}' AS {alias} (READ_ONLY)")
    return attached


class DuckDbConnection:
    """The mirror is opened READ-ONLY. Any write -- including a stray LLM INSERT -- is
    refused by DuckDB itself rather than by validation we would have to write.

    If the mirror records a `sra_db_path` in `mirror_config`, that database is attached
    read-only too: `sra_taxonomy` is a view over its 13.6B-row table rather than a copy.
    config(db=...) therefore still takes ONE path -- the second is read out of the
    mirror, not asked of the caller. A fixture with no mirror_config just skips this.
    """

    def __init__(self, db_path: Path, gpu: bool = False):
        start = time.monotonic()
        self._connection = duckdb.connect(str(db_path), read_only=True)
        self._connection.execute("INSTALL vss")
        self._connection.execute("LOAD vss")
        self._attach_sources()
        self._gpu = gpu
        if gpu:
            self._connection.execute(f"LOAD '{SIRIUS_EXTENSION_PATH}'")
            self._connection.execute("SELECT gpu_buffer_init()")
        _logger.info("connect %s (%.2fs)", db_path, time.monotonic() - start)

    def _attach_sources(self) -> None:
        attach_sidecars(self._connection)

    def _attachments(self) -> list[tuple[str, str]]:
        """Which sidecar databases to attach, and under which alias.

        The mirror stores each big table as a VIEW, and a view definition BAKES IN the
        alias it was written against -- so the aliases here and the ones step3_assemble_mirror.py
        writes its views against are one contract, not two independent choices. That is
        why they live in SIDECAR_ALIASES, imported by both.

        A mirror predating the sorted metadata carries only `sra_db_path`; it attaches
        that one and works exactly as before, so this is safe to deploy ahead of a
        rebuild.
        """
        return sidecars_of(self._connection)

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


class LocalEmbedder:
    """Runs entirely on-node: no API key, no quota, no cost. A hosted embeddings API's
    free-tier quota (both per-minute and per-day caps) proved too restrictive to finish
    a ~99k-item build even right after a fresh daily reset -- see
    step6_embed_concepts.py's docstring. Query-time embedding (ConceptIndex) MUST use
    this same model, not just the same output width: vectors from two different models
    aren't comparable even at matching width.

    A general-purpose model (all-MiniLM-L6-v2) was tried first and failed the
    feature's own flagship case: it ranked "IBS" closer to "IBD" than "Crohn's
    disease" or "ulcerative colitis" (0.73 vs 0.29-0.38 cosine) -- pure spelling
    resemblance, no clinical knowledge. SapBERT is trained specifically on UMLS
    synonym pairs (biomedical abbreviation <-> full name, exactly this task) and
    correctly ranks "inflammatory bowel disease" (0.80) and "Crohn's disease"
    (0.76) above "IBS" (0.73) for the same query -- verified 2026-08-27."""

    MODEL_NAME = "cambridgeltl/SapBERT-from-PubMedBERT-fulltext"
    MAX_TOKENS = 25    # SapBERT's own recommended max_length -- these are entity
                       # names/abbreviations, not sentences.
    BATCH_SIZE = 64    # unlike sentence-transformers' .encode(), raw transformers does
                       # NOT batch internally -- a bare call would tokenize and forward
                       # all ~99k build-time texts as one batch and exhaust memory.

    def __init__(self, tokenizer, model):
        self._tokenizer = tokenizer
        self._model = model

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        start = time.monotonic()
        import torch

        vectors = []
        for batch_start in range(0, len(texts), self.BATCH_SIZE):
            batch = texts[batch_start:batch_start + self.BATCH_SIZE]
            inputs = self._tokenizer(batch, padding=True, truncation=True,
                                     return_tensors="pt", max_length=self.MAX_TOKENS)
            with torch.no_grad():
                output = self._model(**inputs)
            vectors.extend(output.last_hidden_state[:, 0, :].tolist())   # [CLS] token
        _logger.info("embed (%.2fs) for %d texts (local)", time.monotonic() - start, len(texts))
        return vectors


def open_local_embedder() -> LocalEmbedder:
    """Imported lazily so `import askslm` does not require transformers/torch for
    anyone using Gemini-only. Downloads MODEL_NAME to the HuggingFace cache on first
    use -- unlogged otherwise, this one-time download/load showed up as an
    unexplained multi-minute gap between SQL log lines (2026-09-06 run)."""
    start = time.monotonic()
    from transformers import AutoModel, AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(LocalEmbedder.MODEL_NAME)
    model = AutoModel.from_pretrained(LocalEmbedder.MODEL_NAME)
    model.eval()
    _logger.info("load local embedder %s (%.2fs)", LocalEmbedder.MODEL_NAME,
                time.monotonic() - start)
    return LocalEmbedder(tokenizer, model)


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
