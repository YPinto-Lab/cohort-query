"""askslm — turn a research question into a cross-study metagenomic feature table.

    askslm.config(db="mirror.duckdb")
    plan = askslm.ask("fecal metagenomes from adults with IBD, Western countries")
    print(plan)
    table, report = plan.run(profile_sources=askslm.Source.METALOG_MOTUS3, out="cohort.biom")

Two verbs. ask() understands the question and previews the cohort cheaply -- one LLM
hop, no source choices, no biom presupposed. run() materializes and is the only place
sources are named.

STATUS: walking skeleton. The path below is real end to end (real DuckDB, real biom),
but the LLM is a canned backend and there is no terminal app or plan persistence yet.

Design: Docs/superpowers/specs/2026-06-17-askslm-architecture-hld-lld.html
"""
from __future__ import annotations

from pathlib import Path

from askslm import runtime
from askslm.build import BuildReport, Materialization
from askslm.cohort import Accession, Cohort
from askslm.plan import CohortPreview, Plan, TranslationError
from askslm.ports import Database, LlmBackend
from askslm.profiles import ProfileReader
from askslm.sources import ProfilerFamily, Source, SourceKind, Unit
from askslm.translation import ResearchQuestion, SourceQuery, Translation, TranslationPrompt

__all__ = [
    "config", "ask",
    "Source", "SourceKind", "ProfilerFamily", "Unit",
    "Plan", "CohortPreview", "BuildReport", "Materialization",
    "Translation", "SourceQuery", "ResearchQuestion", "TranslationPrompt",
    "Cohort", "Accession", "Database", "LlmBackend", "TranslationError",
]


def config(db: str | Path, llm: str = "canned", llm_key: str = "",
           llm_model: str = "gemini-2.5-pro", **wiring) -> None:
    """Configure once. Fails fast if the database is missing or the llm name is unknown."""
    runtime.configure(
        runtime.Settings(db_path=Path(db), llm=llm, llm_key=llm_key, llm_model=llm_model),
        **wiring)


def ask(question: str) -> Plan:
    """One LLM hop plus cheap COUNTs. Persists nothing yet -- see the status note above."""
    research_question = ResearchQuestion(question)
    translation = runtime.translator().translate(research_question)
    if translation.failure is not None:
        return Plan(research_question, translation, CohortPreview(), error=translation.failure)
    return Plan(research_question, translation, _preview(translation))


def _preview(translation: Translation) -> CohortPreview:
    from askslm.cohort import CohortDiscovery

    cohort = CohortDiscovery(runtime.database()).discover(translation.queries)
    reader = ProfileReader(runtime.database())
    return CohortPreview(
        by_metadata_source={source: len(keys) for source, keys in cohort.by_source.items()},
        shared=len(cohort.shared()),
        union=len(cohort.union()),
        by_profile_source={source: len(reader.coverage(source, cohort.union()))
                           for source in Source if source.kind() is SourceKind.PROFILE},
    )
