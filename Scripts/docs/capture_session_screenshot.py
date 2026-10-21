"""Regenerate Docs/img/cohortquery-session.svg from a REAL run against the test
fixture mirror -- same render functions session.py uses, same
CriterionResolver/JattrConceptIndex code path CLI users hit. Only the LLM is
canned (Tests/test_walking_skeleton.py's pattern) and the embedder is the
fixture's deterministic one (Tests/test_jattr_concepts_integration.py's), so
this needs no API key and no real mirror.

Run whenever the CLI's screen-by-screen output changes (new menu choice, new
table column, etc.) so the README screenshot does not go stale again:

    python Scripts/docs/capture_session_screenshot.py
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "Tests"))

from rich.console import Console
from rich.table import Table

import cohortquery
from cohortquery.adapters import CannedLlmBackend, DuckDbConnection
from cohortquery.bioproject_rollup import BioProjectRollup
from cohortquery.cli.render import (bioproject_columns, bioproject_table_rows,
                                     narrow_warning, overlap_rows, preview_line)
from cohortquery.concept_search import EMBED_DIM
from cohortquery.translation import JattrCriterion, SourceQuery, Translation
from fixtures.mirror import build_fixture_mirror

OUT_PATH = REPO_ROOT / "Docs" / "img" / "cohortquery-session.svg"

QUESTION = "fecal metagenomes from adults with IBD, Western countries"

# The LLM states "IBD" as an English concept rather than SQL (translation.py's
# jattr-touching-criteria design) -- CriterionResolver then finds it semantically,
# through the real nearest-neighbor search, landing on a biosample whose only
# recorded field is the free-text key `ibd_sam`. That is the actual differentiator
# this screenshot exists to show, not an illustrative stand-in for it.
TRANSLATION = Translation(
    interpretation="body_site = fecal · disease = IBD · host = adult · geography = Western",
    queries=(
        SourceQuery(cohortquery.Source.SRA_METADATA,
                    sql=None,
                    jattr_criteria=(JattrCriterion("IBD"),)),
        SourceQuery(cohortquery.Source.METALOG_METADATA,
                    sql="SELECT biosample FROM metalog_metadata "
                        "WHERE subject_disease_status IN ('Crohn''s disease', 'ulcerative colitis') "
                        "AND age_years >= 18 "
                        "AND geographic_location IN ('Germany', 'United States', 'Israel')"),
    ),
)


class _FixtureEmbedder:
    """Identical mapping to Tests/fixtures/mirror.py's -- "IBD" and the real
    disease values are deliberate semantic neighbors of each other."""
    _KNOWN_TERMS = frozenset({"IBD", "Crohn's disease", "ulcerative colitis", "ibd_sam"})

    def embed(self, texts):
        return [self._vector_for(text) for text in texts]

    def _vector_for(self, text):
        vector = [0.0] * EMBED_DIM
        index = 0 if text in self._KNOWN_TERMS else 1 + (len(text) % (EMBED_DIM - 1))
        vector[index] = 1.0
        return vector


def main() -> None:
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        mirror_path = Path(tmp) / "fixture.duckdb"
        build_fixture_mirror(mirror_path)
        connection = DuckDbConnection(mirror_path)
        cohortquery.config(db=mirror_path, database=connection,
                            backend=CannedLlmBackend(TRANSLATION),
                            embedder=_FixtureEmbedder())
        _record(connection)
        connection.close()


def _record(connection) -> None:
    console = Console(record=True, width=118)
    console.print(f"[bold cyan]?[/bold cyan] [bold]What cohort do you need?[/bold] "
                  f"[yellow]{QUESTION}[/yellow]")

    plan = cohortquery.ask(QUESTION)
    assert plan.error is None, plan.error

    console.print(f"[bold]{plan.translation.interpretation}[/bold]")
    console.print(preview_line(plan.preview))
    warning = narrow_warning(plan.preview)
    if warning:
        console.print(f"[yellow]{warning}[/yellow]")

    overlap_table = Table("source", "samples", "")
    for row in overlap_rows(plan.preview, winner=cohortquery.Source.METALOG_METADATA):
        overlap_table.add_row(*row)
    console.print(overlap_table)
    for query in plan.translation.queries:
        if query.sql:
            console.print(f"[dim]{query.source.name}[/dim] {query.sql}")
        if query.jattr_criteria:
            concepts = ", ".join(f'"{c.concept}"' for c in query.jattr_criteria)
            console.print(f"[dim]{query.source.name}[/dim] "
                           f"[magenta]semantic match[/magenta] -- concept: {concepts}")

    rows = BioProjectRollup(cohortquery.runtime.database()).rows(plan.discovered)
    if rows:
        columns = bioproject_columns(rows)
        bp_table = Table("project", "biosamples", *columns)
        for row in bioproject_table_rows(rows, columns):
            bp_table.add_row(*row)
        console.print(bp_table)

    console.print("[bold]?[/bold] [bold]What now?[/bold] "
                   "[green]» Run it[/green]   Refine the question   Ask new question   Discard   Quit")

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    console.save_svg(str(OUT_PATH), title="yarintamam — cohortquery — 118x44")
    print(f"wrote {OUT_PATH}")


if __name__ == "__main__":
    main()
