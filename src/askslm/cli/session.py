"""The interactive session: `$ askslm`.

Line-oriented on purpose. A full-screen TUI owns the terminal and needs a layout
engine; this needs to show a table, arrow between options, confirm, and repeat.
Every screen here maps to exactly one call the public API already has.
"""
from __future__ import annotations

import sys
from pathlib import Path

import questionary
from rich.console import Console
from rich.table import Table

import askslm
from askslm.cli.render import narrow_warning, overlap_rows, preview_line
from askslm.plan import Plan, load_plan
from askslm.settings_file import CONFIG_PATH, stored_settings, write_settings
from askslm.sources import ProfilerFamily, Source, SourceKind

console = Console()


def main() -> None:
    """`askslm` starts a session; `askslm run plans/x.json` replays one, no LLM."""
    if len(sys.argv) > 2 and sys.argv[1] == "run":
        _replay(Path(sys.argv[2]))
        return
    _configure()
    _session()


def _configure() -> None:
    settings = stored_settings()
    if not settings.get("db") or not settings.get("llm_key"):
        console.print("No configuration found. Two questions, once.")
        settings = _ask_for_settings()
        write_settings(CONFIG_PATH, **settings)
        console.print(f"[green]saved to {CONFIG_PATH}[/green]")
    askslm.config(db=settings["db"], llm="gemini", llm_key=settings["llm_key"])


def _ask_for_settings() -> dict:
    db = questionary.path("Path to the SRA x Metalog database").ask()
    llm_key = questionary.password("Gemini API key").ask()
    return {"db": db, "llm_key": llm_key}


def _session() -> None:
    question = ""
    plan = None
    while True:
        if plan is None:
            question = questionary.text("What cohort do you need?", default=question).ask()
            if not question:
                return
            plan = _ask(question)
            if plan is None:
                continue
        choice = questionary.select("What now?", choices=[
            "Run it", "Refine the question", "Show the SQL and overlap",
            "Save plan and quit", "Quit"]).ask()
        if choice == "Run it":
            _run(plan)
        elif choice == "Refine the question":
            plan = None
        elif choice == "Show the SQL and overlap":
            _show_overlap(plan)
        elif choice == "Save plan and quit":
            _save(plan)
            return
        else:
            return


def _ask(question: str) -> Plan | None:
    """A question the model cannot translate is a screen, not a stack trace."""
    with console.status("thinking"):
        plan = askslm.ask(question)
    if plan.error is not None:
        console.print(f"[red]Could not translate that into a query.[/red]\n{plan.error}")
        return None
    console.print(f"[bold]{plan.translation.interpretation}[/bold]")
    console.print(preview_line(plan.preview))
    warning = narrow_warning(plan.preview)
    if warning:
        console.print(f"[yellow]{warning}[/yellow]")
    return plan


def _run(plan: Plan) -> None:
    family = questionary.select("Which feature space?", choices=_families(plan)).ask()
    if family is None:
        return
    sources = _sources_of(ProfilerFamily[family])
    chosen = questionary.checkbox("Which sources? (order = precedence)",
                                  choices=[source.name for source in sources]).ask()
    if not chosen:
        return
    out = questionary.text("Write to", default="feature_table.biom").ask()
    with console.status("building"):
        table, report = plan.run(profile_sources=[Source[name] for name in chosen],
                                 out=Path(out))
    console.print(f"[green]{out}[/green]")
    console.print(str(report))


def _families(plan: Plan) -> list[str]:
    """Only families that actually cover this cohort. Picking the family first is what
    makes the cross-family guard unreachable by construction (HLD C.0.2)."""
    covered = {source.family().name for source, count in plan.preview.by_profile_source.items()
               if count}
    return sorted(covered) or sorted(family.name for family in ProfilerFamily)


def _sources_of(family: ProfilerFamily) -> list[Source]:
    return [source for source in Source
            if source.kind() is SourceKind.PROFILE and source.family() is family]


def _show_overlap(plan: Plan) -> None:
    table = Table("source", "samples", "")
    for row in overlap_rows(plan.preview, winner=Source.METALOG_METADATA):
        table.add_row(*row)
    console.print(table)
    for query in plan.translation.queries:
        console.print(f"[dim]{query.source.name}[/dim] {query.sql}")


def _save(plan: Plan) -> None:
    out = questionary.text("Save plan to", default="plans/cohort.json").ask()
    path = plan.save(Path(out))
    console.print(f"[green]{path}[/green] -- replay with: askslm run {path}")


def _replay(path: Path) -> None:
    """No LLM hop -- the reproducible half of the loop. Still asks which family,
    sources, and output path to materialize: the persisted Plan only carries the
    translation and the preview, not a Materialization choice, so `_run` has to
    ask every time regardless of how the plan was produced."""
    settings = stored_settings()
    askslm.config(db=settings["db"], llm="gemini", llm_key=settings.get("llm_key", ""))
    plan = load_plan(path)
    console.print(preview_line(plan.preview))
    _run(plan)
