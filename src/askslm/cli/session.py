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
    """Ask until it works. A mistyped path must produce a sentence and another prompt,
    never a traceback -- HLD C.0.1 makes this the one place the app catches its own
    fail-fast validation instead of letting it reach the user.

    Nothing is written until config() accepts, so a typo or a Ctrl-C cannot leave a
    broken file behind that poisons every later run.
    """
    settings = stored_settings()
    prompted = False
    while True:
        missing = [name for name in ("db", "llm_key") if not settings.get(name)]
        if missing:
            settings.update(_ask_for(missing))
            prompted = True
        try:
            askslm.config(db=settings["db"], llm="gemini", llm_key=settings["llm_key"])
        except ValueError as error:
            console.print(f"[red]{error}[/red]")
            settings.pop(_culprit(error), None)
            prompted = True
            continue
        if prompted:
            write_settings(CONFIG_PATH, **settings)
            console.print(f"[green]saved to {CONFIG_PATH}[/green]")
        return


def _culprit(error: ValueError) -> str:
    """Which answer to ask for again. Re-asking for a path the user already got right
    because their key was wrong is the sort of thing that makes people stop using a tool."""
    return "db" if "database file" in str(error) else "llm_key"


def _ask_for(missing: list[str]) -> dict:
    """Only what is actually missing.

    A site that pins the database path -- a launcher on the lab server, say -- should
    leave the user answering one question, not two. Re-asking for a path the machine
    already knows is how a "two questions, once" flow becomes two questions, always.
    """
    ask = {"db": _ask_db, "llm_key": _ask_key}
    answers = {}
    for name in missing:
        value = ask[name]()
        if value is None:              # Ctrl-C or EOF: leave no config behind
            raise SystemExit(0)
        answers[name] = value.strip()  # a tab-completed path arrives with a trailing space
    return answers


def _ask_db() -> str:
    return questionary.path("Path to the SRA x Metalog database").ask()


def _ask_key() -> str:
    return questionary.password("Gemini API key").ask()


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
