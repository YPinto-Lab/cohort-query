"""cohortquery — turn a research question into a cross-study metagenomic feature table.

    cohortquery.config(db="mirror.duckdb")
    plan = cohortquery.ask("fecal metagenomes from adults with IBD, Western countries")
    print(plan)
    table, report = plan.run(profile_sources=cohortquery.Source.METALOG_MOTUS3, out="cohort.biom")

Two verbs. ask() understands the question and previews the cohort cheaply -- one LLM
hop, no source choices, no biom presupposed. run() materializes and is the only place
sources are named.

STATUS: the question -> .biom path is real end to end, with a real LLM. Configure it
with config(db=..., llm="gemini", llm_key=...); llm="canned" plus an injected backend
is what the tests use. The terminal app (`$ cohortquery`, src/cohortquery/cli/session.py) and
plan persistence (Plan.save / load_plan) now exist too, hand-verified by scripting
questionary end to end against the fixture mirror. Still rough: session.py is glue,
not unit-tested -- it is verified by running it, not by a test suite; Translation
accuracy against the eval set in Scripts/eval/ has not yet been measured.

Design: Docs/superpowers/specs/2026-06-17-cohortquery-architecture-hld-lld.html
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from cohortquery import runtime
from cohortquery.build import BuildReport, Materialization
from cohortquery.cohort import Accession, Cohort, InvalidCohortQuery
from cohortquery.plan import CohortPreview, Plan, TranslationError, load_plan
from cohortquery.ports import Database, LlmBackend
from cohortquery.profiles import ProfileReader
from cohortquery.sources import ProfilerFamily, Source, SourceKind, Unit
from cohortquery.translation import ResearchQuestion, SourceQuery, Translation, TranslationPrompt

__all__ = [
    "config", "ask",
    "Source", "SourceKind", "ProfilerFamily", "Unit",
    "Plan", "CohortPreview", "BuildReport", "Materialization",
    "Translation", "SourceQuery", "ResearchQuestion", "TranslationPrompt",
    "Cohort", "Accession", "Database", "LlmBackend", "TranslationError",
    "load_plan",
]


def config(db: str | Path, llm: str = "canned", llm_key: str = "",
           llm_model: str = "gemini-2.5-flash", gpu: bool = False, **wiring) -> None:
    """Configure once. Fails fast if the database is missing or the llm name is unknown."""
    runtime.configure(
        runtime.Settings(db_path=Path(db), llm=llm, llm_key=llm_key,
                        llm_model=llm_model, gpu=gpu),
        **wiring)


def ask(question: str, save: str | Path | None = None) -> Plan:
    """One LLM hop plus cheap COUNTs. Pass save= to also persist the plan as JSON."""
    research_question = ResearchQuestion(question)
    translation = runtime.translator().translate(research_question)
    if translation.failure is not None:
        plan = Plan(research_question, translation, CohortPreview(), error=translation.failure)
    else:
        try:
            discovery = _discover(translation)
            plan = Plan(research_question, translation, discovery.preview,
                       discovered=discovery.cohort)
        except InvalidCohortQuery as error:
            plan = _repaired(research_question, translation, error)
    if save is not None:
        plan.save(save)
    return plan


def _repaired(question: ResearchQuestion, translation: Translation,
              error: InvalidCohortQuery) -> Plan:
    """One retry, using the database's own error text.

    Four rounds of prompt tuning each fixed one class of bad SQL and revealed the next.
    Handing the model the rejection instead is the standard text-to-SQL answer and it
    generalises: DuckDB names the offending column and even suggests candidates, which
    is better information than any rule we could write in advance.

    A second failure is reported as-is. There is no third attempt -- if the model cannot
    fix its own SQL with the error in front of it, looping will not help.
    """
    fixed = runtime.backend().repair(
        sql=_sql_for(translation, error.source),
        error=error.message,
        columns=_columns_of(error.source))
    retried = _with_sql(translation, error.source, fixed)
    try:
        discovery = _discover(retried)
        return Plan(question, retried, discovery.preview, discovered=discovery.cohort)
    except InvalidCohortQuery as second:
        return Plan(question, retried, CohortPreview(), error=str(second))


def _sql_for(translation: Translation, source: Source) -> str:
    return next(query.sql for query in translation.queries if query.source is source)


def _with_sql(translation: Translation, source: Source, sql: str) -> Translation:
    queries = tuple(_replace_sql(query, sql) if query.source is source else query
                    for query in translation.queries)
    return Translation(interpretation=translation.interpretation, queries=queries,
                       failure=translation.failure)


def _replace_sql(query: SourceQuery, sql: str) -> SourceQuery:
    """Repair only ever rewrites `sql` -- the jattr_criteria/jattr_combinator/
    sql_jattr_combinator half of the query was never rejected by DuckDB and
    must survive unchanged."""
    return SourceQuery(query.source, sql, jattr_criteria=query.jattr_criteria,
                       jattr_combinator=query.jattr_combinator,
                       sql_jattr_combinator=query.sql_jattr_combinator)


def _columns_of(source: Source) -> str:
    frame = runtime.database().query(f"DESCRIBE {source.spec().table}")
    return ", ".join(f"{name} {kind}" for name, kind
                     in zip(frame["column_name"], frame["column_type"]))


@dataclass(frozen=True)
class _Discovery:
    cohort: Cohort
    preview: CohortPreview


def _discover(translation: Translation) -> _Discovery:
    cohort = runtime.criterion_resolver().discover(translation.queries)
    reader = ProfileReader(runtime.database())
    preview = CohortPreview(
        by_metadata_source={source: len(keys) for source, keys in cohort.by_source.items()},
        shared=len(cohort.shared()),
        union=len(cohort.union()),
        by_profile_source={source: len(reader.coverage(source, cohort.union()))
                           for source in Source if source.kind() is SourceKind.PROFILE},
    )
    return _Discovery(cohort, preview)
