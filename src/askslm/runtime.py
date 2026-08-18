"""The composition root -- the one place concretes are constructed and wired to ports.

A module, not a class: two factories and no state worth wrapping in an object.
`load_plan(path).run(...)` has to work from a bare file, so the one Settings set
at config() time is module state.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from askslm.adapters import DuckDbConnection
from askslm.build import BiomFactory, CohortBuilder
from askslm.catalog import SchemaCatalog
from askslm.cohort import CohortDiscovery
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

    def __post_init__(self):
        if not Path(self.db_path).exists():
            raise ValueError(f"database file not found: {self.db_path}")


_settings: Settings | None = None
_database: Database | None = None
_backend: LlmBackend | None = None


def configure(settings: Settings, database: Database | None = None,
              backend: LlmBackend | None = None) -> None:
    """Called by config(). The two overrides are how tests inject fakes without a
    conditional anywhere in the services."""
    global _settings, _database, _backend
    _settings = settings
    _database = database
    _backend = backend


def database() -> Database:
    global _database
    if _database is None:
        _database = DuckDbConnection(_require_settings().db_path)
    return _database


def backend() -> LlmBackend:
    if _backend is None:
        raise RuntimeError("no LlmBackend configured")
    return _backend


def translator() -> Translator:
    return Translator(backend(), SchemaCatalog(database()))


def cohort_builder() -> CohortBuilder:
    connection = database()
    return CohortBuilder(CohortDiscovery(connection),
                         ProfileReconciler(ProfileReader(connection)),
                         MetadataReconciler(MetadataReader(connection)),
                         BiomFactory())


def _require_settings() -> Settings:
    if _settings is None:
        raise RuntimeError("askslm.config(...) has not been called")
    return _settings
