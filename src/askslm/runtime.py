"""The composition root -- the one place concretes are constructed and wired to ports.

A module, not a class: two factories and no state worth wrapping in an object.
`load_plan(path).run(...)` has to work from a bare file, so the one Settings set
at config() time is module state.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from askslm.adapters import DuckDbConnection, verify_mirror
from askslm.build import BiomFactory, CohortBuilder
from askslm.catalog import SchemaCatalog
from askslm.cohort import CriterionResolver
from askslm.concept_search import ConceptIndex, Embedder
from askslm.jattr_concepts import JattrConceptIndex
from askslm.metadata import MetadataReader, MetadataReconciler
from askslm.ports import Database, LlmBackend
from askslm.profiles import ProfileReader, ProfileReconciler
from askslm.translation import Translator


@dataclass(frozen=True)
class Settings:
    """Constructed from explicit arguments; knows nothing about config files or the
    environment. Whoever calls config() sources the values -- which is what lets this
    validation stay a plain fail-fast __post_init__."""
    db_path: Path
    llm: str = "canned"
    llm_key: str = ""
    llm_model: str = "gemini-2.5-flash"
    gpu: bool = False

    def __post_init__(self):
        if not Path(self.db_path).exists():
            raise ValueError(f"database file not found: {self.db_path}")
        if self.llm not in ("canned", "gemini"):
            raise ValueError(f"unknown llm {self.llm!r}: expected 'canned' or 'gemini'")
        if self.llm == "gemini" and not self.llm_key:
            raise ValueError("no API key: gemini needs one (HLD H.1)")


_settings: Settings | None = None
_database: Database | None = None
_backend: LlmBackend | None = None
_embedder: Embedder | None = None


def configure(settings: Settings, database: Database | None = None,
              backend: LlmBackend | None = None, embedder: Embedder | None = None) -> None:
    """Called by config(). The overrides are how tests inject fakes without a
    conditional anywhere in the services."""
    global _settings, _database, _backend, _embedder
    _settings = settings
    _database = database
    _backend = backend
    _embedder = embedder


def database() -> Database:
    """Built once, and only published once it has been verified.

    The connection is held in a local until `verify_mirror` passes: assigning the
    global first would leave an unusable mirror cached behind it, so the second call
    would sail past the `is None` guard and hand back the very connection the first
    call rejected -- with its DuckDB handle still open.
    """
    global _database
    if _database is None:
        settings = _require_settings()
        connection = DuckDbConnection(settings.db_path, gpu=settings.gpu)
        try:
            verify_mirror(connection, settings.db_path)
        except BaseException:
            connection.close()
            raise
        _database = connection
    return _database


def backend() -> LlmBackend:
    """An explicitly injected backend always wins -- that is how the tests pass a fake.
    Otherwise the one named in Settings is constructed here, at the composition root."""
    global _backend
    if _backend is None:
        _backend = _named_backend(_require_settings())
    return _backend


def _named_backend(settings: Settings) -> LlmBackend:
    if settings.llm == "gemini":
        from askslm.adapters import open_gemini

        return open_gemini(settings.llm_key, settings.llm_model)
    raise RuntimeError(
        "no LlmBackend configured: pass backend=... or config(llm='gemini', llm_key=...)")


def embedder() -> Embedder:
    """An explicitly injected embedder always wins (tests). Otherwise: gemini mode
    gets a local model -- a hosted embeddings API's free tier proved too rate-limited
    to finish the concept-embedding build even right after a fresh daily quota
    reset (see step6_embed_concepts.py's docstring), so query-time embedding
    must match the same local model the build used. Canned mode has no model to
    call, so it keeps using the canned backend's own no-op embed() (retrieval
    degrades to substring matching), unchanged from before."""
    global _embedder
    if _embedder is None:
        settings = _require_settings()
        if settings.llm == "gemini":
            from askslm.adapters import open_local_embedder

            _embedder = open_local_embedder()
        else:
            _embedder = backend()
    return _embedder


def translator() -> Translator:
    db = database()
    concepts = ConceptIndex(db, embedder=embedder())
    return Translator(backend(), SchemaCatalog(db), concepts)


class _LazyEmbedder:
    """Defers resolving the real embedder until embed() is actually called.

    run() must stay LLM-free when a query has no jattr_criteria (JattrConceptIndex
    never calls embed() in that case) -- "one LLM hop lives on the ask edge, every
    run() after it is free" (module docstring). Resolving embedder() eagerly here
    would force a worker replaying a saved plan, with no backend injected, to fail
    even when nothing it does needs embedding."""

    def embed(self, texts: list[str]) -> list[list[float]]:
        return embedder().embed(texts)


def criterion_resolver() -> CriterionResolver:
    connection = database()
    return CriterionResolver(connection, JattrConceptIndex(connection, embedder=_LazyEmbedder()))


def cohort_builder() -> CohortBuilder:
    connection = database()
    return CohortBuilder(criterion_resolver(),
                         ProfileReconciler(ProfileReader(connection)),
                         MetadataReconciler(MetadataReader(connection)),
                         BiomFactory())


def _require_settings() -> Settings:
    if _settings is None:
        raise RuntimeError("askslm.config(...) has not been called")
    return _settings
