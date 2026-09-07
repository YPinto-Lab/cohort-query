"""The interactive session: `$ askslm`.

Line-oriented on purpose. A full-screen TUI owns the terminal and needs a layout
engine; this needs to show a table, arrow between options, confirm, and repeat.
Every screen here maps to exactly one call the public API already has.

Not unit-tested: verified by running it. The parts worth testing (plan folders, job
templating/status, on_step, GPU wrapping) are extracted into rundir.py/jobs.py/
build.py/adapters.py, which do have tests.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
import shlex
import shutil
import sys
from pathlib import Path

import questionary
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.table import Table

import askslm
from askslm.cli import jobs, progress, rundir, watch
from askslm.cli.render import narrow_warning, overlap_rows, preview_line
from askslm.plan import Plan, load_plan
from askslm.settings_file import CONFIG_PATH, stored_settings, write_settings
from askslm.sources import ProfilerFamily, Source, SourceKind

console = Console()
logger = logging.getLogger("askslm.session")


def main() -> None:
    """`askslm` starts a session; `askslm load` picks a saved plan from a list;
    `askslm load plans/x[/plan.json]` reattaches to one directly."""
    if len(sys.argv) > 1 and sys.argv[1] == "load":
        path = _pick_plan() if len(sys.argv) == 2 else _plan_json(Path(sys.argv[2]))
        if path is not None:
            _load(path)
        return
    _configure()
    _session()


def _plan_json(path: Path) -> Path:
    """`askslm load plans/x` and `askslm load plans/x/plan.json` both work."""
    return path / "plan.json" if path.is_dir() else path


def _pick_plan(root: Path = rundir.PLANS_ROOT) -> Path | None:
    """List saved plans newest first, named by question + interpretation."""
    plan_paths = sorted(root.glob("*/plan.json"), reverse=True)
    if not plan_paths:
        console.print(f"[yellow]no saved plans under {root}[/yellow]")
        return None
    choices = [questionary.Choice(title=_plan_label(path), value=path) for path in plan_paths]
    return questionary.select("Which plan?", choices=choices).ask()


def _plan_label(path: Path) -> str:
    payload = json.loads(path.read_text())
    ts = path.parent.name[:15]                        # YYYYMMDD_HHMMSS, slug may follow
    when = datetime.strptime(ts, "%Y%m%d_%H%M%S").strftime("%b %d, %Y %H:%M")
    return f"{when}  {payload['question']!r} -- {payload['interpretation']}"


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
    plan_dir = None
    while True:
        if plan is None:
            question = questionary.text("What cohort do you need?", default=question).ask()
            if not question:
                return
            plan_dir = rundir.new_plan_dir(question)
            handler = rundir.attach_log_handler(plan_dir)
            logger.info("question -> %r", question)
            plan = _ask(question, plan_dir)
            rundir.detach_log_handler(handler)
            if plan is None:
                continue
        choice = questionary.select("What now?", choices=[
            "Run it", "Refine the question", "Ask new question", "Discard", "Quit"]).ask()
        if choice == "Run it":
            _run(plan, plan_dir)
        elif choice == "Refine the question":
            plan = None
        elif choice == "Ask new question":
            plan = None
            question = ""
        elif choice == "Discard":
            _discard(plan_dir)
            plan = None
            question = ""
        else:
            return


def _ask(question: str, plan_dir: Path) -> Plan | None:
    """A question the model cannot translate is a screen, not a stack trace."""
    with Progress(SpinnerColumn(), TextColumn("thinking"), TimeElapsedColumn(),
                  console=console, transient=True) as progress:
        progress.add_task("")
        plan = askslm.ask(question)
    if plan.error is not None:
        console.print(f"[red]Could not translate that into a query.[/red]\n{plan.error}")
        return None
    plan.save(plan_dir / "plan.json")
    console.print(f"[bold]{plan.translation.interpretation}[/bold]")
    console.print(preview_line(plan.preview))
    warning = narrow_warning(plan.preview)
    if warning:
        console.print(f"[yellow]{warning}[/yellow]")
    _show_overlap(plan)
    return plan


def _run(plan: Plan, plan_dir: Path) -> None:
    families = _families(plan)
    if len(families) == 1:
        family_name = families[0]
        console.print(f"  feature space: {family_name} (only option)")
    else:
        family_name = questionary.select("Which feature space?", choices=families).ask()
        if family_name is None:
            return
    sources = _sources_of(ProfilerFamily[family_name])
    if len(sources) == 1:
        chosen = sources
        console.print(f"  sources: {sources[0].name} (only option)")
    else:
        picked = questionary.checkbox("Which sources? (order = precedence)",
                                      choices=[source.name for source in sources]).ask()
        if not picked:
            return
        chosen = [Source[name] for name in picked]
    out = questionary.text("Write to", default=str(plan_dir / "cohort.biom")).ask()
    if not out:
        return
    gpu = questionary.confirm("Use GPU acceleration for this build?", default=False).ask()
    _submit(plan_dir, chosen, Path(out), gpu)


def _submit(plan_dir: Path, sources: list[Source], out: Path, gpu: bool) -> None:
    _clear_previous_run(plan_dir)
    settings = stored_settings()
    args = [sys.executable, "-m", "askslm.cli.worker",
           "--plan-dir", str(plan_dir), "--plan", str(plan_dir / "plan.json"),
           "--sources", ",".join(source.name for source in sources),
           "--out", str(out), "--db", str(settings["db"])]
    if gpu:
        args.append("--gpu")
    worker_cmd = shlex.join(args)
    script = jobs.write_sbatch(plan_dir, worker_cmd, gpu)
    job_id = jobs.submit(script)
    jobs.write_job_id(plan_dir, job_id)
    progress.write_submitted(plan_dir)
    console.print(f"[green]Submitted SLURM job {job_id}[/green]")
    console.print(f"  squeue:  squeue -j {job_id}")
    console.print(f"  log:     tail -f {plan_dir / 'log.txt'}")
    choice = questionary.select("Watch progress now, or back to menu?",
                                choices=["Watch progress", "Back to menu"]).ask()
    if choice == "Watch progress":
        watch.watch(plan_dir, console)


def _clear_previous_run(plan_dir: Path) -> None:
    """Rerunning a plan reuses its folder, so a prior status.txt/progress.txt
    still on disk would read as this run's -- watch() would see DONE/FAILED
    before the new job even starts and bail out instantly."""
    stale = ["status.txt", "progress.txt", "report.txt", "submitted.txt", "job.id"]
    for name in stale:
        (plan_dir / name).unlink(missing_ok=True)
    for pattern in ("slurm-*.out", "slurm-*.err"):
        for path in plan_dir.glob(pattern):
            path.unlink()


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


def _discard(plan_dir: Path) -> None:
    """The session created plan.json here itself (autosave), so the whole folder is
    disposable -- cancel a live job first, never delete files out from under it."""
    _cancel_if_running(plan_dir)
    shutil.rmtree(plan_dir)


def _discard_loaded(plan_dir: Path, keep: Path) -> None:
    """`keep` is the plan.json path the caller passed to `askslm load` -- a
    caller-owned input, not something this run created, so it survives; only this
    run's own artifacts (log, job files, biom) are removed."""
    _cancel_if_running(plan_dir)
    for entry in plan_dir.iterdir():
        if entry.samefile(keep):
            continue
        if entry.is_dir():
            shutil.rmtree(entry)
        else:
            entry.unlink()


def _job_running(job_id: str) -> bool:
    """squeue on this cluster errors outright, not just empty stdout, once a job has
    aged fully out of the queue -- so a squeue failure here means gone, not unknown."""
    try:
        return jobs.squeue_state(job_id) is not None
    except RuntimeError:
        return False


def _print_last_report(plan_dir: Path) -> None:
    status = jobs.read_status(plan_dir)
    if status not in ("DONE", "FAILED"):
        return
    report_path = plan_dir / "report.txt"
    if report_path.exists():
        console.print(report_path.read_text())
    else:
        console.print(f"[yellow]job finished ({status}) -- no report.txt[/yellow]")


def _cancel_if_running(plan_dir: Path) -> None:
    job_id = jobs.read_job_id(plan_dir)
    if job_id is None:
        return
    try:
        still_running = jobs.squeue_state(job_id) is not None
    except RuntimeError as error:
        console.print(f"[yellow]couldn't confirm job status ({error}); cancelling anyway[/yellow]")
        still_running = True
    if still_running:
        jobs.cancel(job_id)


def _load(path: Path) -> None:
    """No LLM hop -- the reproducible half of the loop. Reattaches straight to the
    live progress view if a job submitted from this same folder is still running,
    or prints its report if it already finished."""
    settings = stored_settings()
    askslm.config(db=settings["db"], llm="gemini", llm_key=settings.get("llm_key", ""))
    plan_dir = path.parent
    job_id = jobs.read_job_id(plan_dir)
    if job_id is not None:
        if _job_running(job_id):
            watch.watch(plan_dir, console)
        else:
            _print_last_report(plan_dir)
    plan = load_plan(path)
    console.print(preview_line(plan.preview))
    while True:
        choice = questionary.select("What now?", choices=["Run it", "Discard", "Quit"]).ask()
        if choice == "Run it":
            _run(plan, plan_dir)
        elif choice == "Discard":
            _discard_loaded(plan_dir, keep=path)
            return
        else:
            return
