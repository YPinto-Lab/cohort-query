# Terminal App + Plan Persistence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `$ askslm` — a biologist who writes no Python types a question, reads the cohort, picks sources, and gets a `.biom`. Plus the plan file that replays it without the LLM.

**Architecture:** A line-oriented prompt flow (`questionary` + `rich`), NOT a full-screen TUI. The session is ~200 lines of glue over the existing `ask()` / `run()` verbs — every screen maps to exactly one API call that already exists. Plan persistence is JSON round-trip on the existing frozen dataclasses.

**Tech Stack:** Python 3.12+, `questionary`, `rich`, stdlib `tomllib`/`json`.

**Explicitly NOT textual.** HLD C.0.3: full-screen TUIs own the terminal, redraw, and maintain a layout engine — weeks of work and a permanent maintenance surface. Show a table, arrow between options, confirm, repeat. It scrolls like normal terminal output.

**This is the 80% pass.** The user has explicitly accepted bugs and rough edges in exchange for a working tool. Prefer shipping the whole loop over polishing any one screen. Do not gold-plate.

---

## Prerequisites

```bash
git fetch origin && git switch -c feature/terminal-app origin/main
```

Announce the branch. Never delete branches. When done: push, `gh pr create --draft --base main`, then stop.

## Context an implementer needs

- **Run tests:** `python3 -m pytest Tests/ -q` from the repo root. `Tests/conftest.py` puts `src/` on the path. Baseline at branch point: **59 passing**.
- **The two verbs already exist and work.** `askslm.ask(question) -> Plan`; `plan.run(profile_sources=..., metadata_winning_source=..., out=...) -> (biom.Table, BuildReport)`. Read `src/askslm/plan.py` and `src/askslm/__init__.py` first. Do not change their signatures.
- **`Plan` is a frozen dataclass** holding `question: ResearchQuestion`, `translation: Translation`, `preview: CohortPreview`, `error: str | None`. `Translation` holds `interpretation: str`, `queries: tuple[SourceQuery, ...]`, `failure: str | None`. `SourceQuery` holds `source: Source` (an Enum) and `sql: str`.
- **`Plan.error` already exists and is already rendered by `_guard_runnable`.** A question the LLM cannot translate must never dump a stack trace at a biologist — the app catches it and re-prompts.
- **House style:** no `lambda` — always a named `def`; readability first; trust input and fail fast (the sanctioned validation points are `config()` and the LLM boundary in `adapters.py`); no backward-compat aliases; compose rather than duplicate.

## File Structure

| File | Responsibility |
|---|---|
| `src/askslm/plan.py` | **modify.** `Plan.save(path)`; module-level `load_plan(path)`. |
| `src/askslm/settings_file.py` | **new.** Where config comes from: env → `~/.askslm/config.toml` → first-run prompt. |
| `src/askslm/cli/__init__.py` | **new.** Empty package marker. |
| `src/askslm/cli/render.py` | **new.** `rich` rendering: the preview line, the overlap/SQL screen, the build summary. Pure formatting, no prompting. |
| `src/askslm/cli/session.py` | **new.** The loop: `main()`, the five screens. `questionary` lives here and nowhere else. |
| `pyproject.toml` | **modify.** `questionary`/`rich` deps; `[project.scripts] askslm = "askslm.cli.session:main"`. |
| `Tests/test_plan_persistence.py` | **new.** |
| `Tests/test_settings_file.py` | **new.** |
| `Tests/test_render.py` | **new.** |

**Testing the terminal.** Do NOT try to drive `questionary` in tests — that way lies mocking `prompt_toolkit` and testing nothing. Keep every decision in pure functions in `render.py` and `settings_file.py` and test those. `session.py` is thin glue; it is verified by running it, and the user has accepted that.

---

### Task 1: Plan persistence

The plan is the reproducible artifact — the same file the non-interactive path replays. `load_plan(path).run(...)` must never touch `LlmBackend`.

**Files:** Modify `src/askslm/plan.py`; test `Tests/test_plan_persistence.py`.

- [ ] **Step 1: Write the failing test**

```python
"""A plan is the reproducible artifact: save it, replay it, never re-ask the LLM."""
import pytest

import askslm
from askslm.plan import Plan, load_plan
from askslm.translation import ResearchQuestion, SourceQuery, Translation
from askslm.plan import CohortPreview


def _plan() -> Plan:
    return Plan(
        question=ResearchQuestion("adults with IBD"),
        translation=Translation(
            interpretation="subject_disease_status in (Crohn's disease, ulcerative colitis)",
            queries=(SourceQuery(askslm.Source.METALOG_METADATA,
                                 "SELECT biosample FROM metalog_metadata"),)),
        preview=CohortPreview(by_metadata_source={askslm.Source.METALOG_METADATA: 12},
                              shared=3, union=12,
                              by_profile_source={askslm.Source.METALOG_MOTUS3: 8}))


def test_a_saved_plan_round_trips_to_an_equal_plan(tmp_path):
    """Equality is the whole contract: replay must reproduce the same cohort, so
    anything lost in the round trip is a silently different result later."""
    path = tmp_path / "ibd.json"

    _plan().save(path)

    assert load_plan(path) == _plan()


def test_enum_keys_survive_the_round_trip(tmp_path):
    """JSON object keys are strings. Source enum members used as dict keys are the
    thing most likely to come back wrong, and would silently empty the preview."""
    path = tmp_path / "ibd.json"

    _plan().save(path)
    loaded = load_plan(path)

    assert loaded.preview.by_profile_source[askslm.Source.METALOG_MOTUS3] == 8
    assert loaded.translation.queries[0].source is askslm.Source.METALOG_METADATA


def test_a_failed_plan_still_saves_and_still_refuses_to_run(tmp_path):
    """A plan that could not be translated is still worth saving -- the user may want
    to send it to someone. It must keep refusing to run after a round trip."""
    path = tmp_path / "bad.json"
    failed = Plan(ResearchQuestion("people who felt unwell"),
                  Translation(interpretation="", queries=(), failure="no such field"),
                  CohortPreview(), error="no such field")

    failed.save(path)

    with pytest.raises(askslm.TranslationError):
        load_plan(path).run(profile_sources=askslm.Source.METALOG_MOTUS3)
```

- [ ] **Step 2: Run it, confirm it fails** — `ImportError: cannot import name 'load_plan'`.

- [ ] **Step 3: Implement.** Append to `src/askslm/plan.py`, and add `import json` at the top:

```python
    def save(self, path: Path) -> Path:
        """Write the plan as JSON. Source enums become their names -- JSON keys are
        strings, and a Source that came back as the string "METALOG_METADATA" would
        silently match nothing."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(_as_json(self), indent=2))
        return path


def load_plan(path: Path) -> Plan:
    """Rebuild a Plan from disk. Never touches LlmBackend -- that is the point: one
    LLM hop lives on the ask edge, and every replay after it is free."""
    return _from_json(json.loads(Path(path).read_text()))


def _as_json(plan: Plan) -> dict:
    return {
        "question": plan.question.text,
        "interpretation": plan.translation.interpretation,
        "queries": [{"source": query.source.name, "sql": query.sql}
                    for query in plan.translation.queries],
        "failure": plan.translation.failure,
        "preview": {
            "by_metadata_source": _named(plan.preview.by_metadata_source),
            "by_profile_source": _named(plan.preview.by_profile_source),
            "shared": plan.preview.shared,
            "union": plan.preview.union,
        },
        "error": plan.error,
    }


def _named(counts: dict) -> dict:
    return {source.name: count for source, count in counts.items()}


def _sourced(counts: dict) -> dict:
    return {Source[name]: count for name, count in counts.items()}


def _from_json(payload: dict) -> Plan:
    preview = payload["preview"]
    return Plan(
        question=ResearchQuestion(payload["question"]),
        translation=Translation(
            interpretation=payload["interpretation"],
            queries=tuple(SourceQuery(Source[entry["source"]], entry["sql"])
                          for entry in payload["queries"]),
            failure=payload["failure"]),
        preview=CohortPreview(
            by_metadata_source=_sourced(preview["by_metadata_source"]),
            by_profile_source=_sourced(preview["by_profile_source"]),
            shared=preview["shared"], union=preview["union"]),
        error=payload["error"])
```

Import `SourceQuery` alongside the existing translation imports.

- [ ] **Step 4: `ask()` gains `save=`.** In `src/askslm/__init__.py`, `ask(question, save=None)`; when `save` is given, call `plan.save(save)` before returning. Export `load_plan` in `__all__`.

- [ ] **Step 5: Full suite** — `python3 -m pytest Tests/ -q`, expect 62.

- [ ] **Step 6: Commit**

```bash
git commit -am "feat(plan): save and load a plan as JSON

The plan is the reproducible artifact -- load_plan(path).run(...) replays a
cohort with no LLM hop at all. Source enums are persisted by name because JSON
keys are strings, and a Source that came back as a bare string would match
nothing and silently empty the preview."
```

---

### Task 2: Where configuration comes from

`config(db, llm, llm_key)` takes explicit arguments. A user who writes no Python cannot supply them, so the app sources them itself. HLD C.0.1 precedence: **env wins → `~/.askslm/config.toml` → first-run prompt.**

Env winning matters for the lab server and CI: no interactive step, no file on disk.

**Files:** Create `src/askslm/settings_file.py`; test `Tests/test_settings_file.py`.

- [ ] **Step 1: Write the failing test**

```python
"""Where config comes from, and in what order. The lab server must never be asked
a question -- that is what the environment override is for."""
from askslm.settings_file import stored_settings, write_settings


def test_the_environment_wins_over_the_file(tmp_path, monkeypatch):
    """CI and the lab server set env vars and must never hit a prompt or a file."""
    config = tmp_path / "config.toml"
    write_settings(config, db="/from/file.duckdb", llm_key="file-key")
    monkeypatch.setenv("ASKSLM_DB", "/from/env.duckdb")
    monkeypatch.setenv("ASKSLM_LLM_KEY", "env-key")

    settings = stored_settings(config)

    assert settings == {"db": "/from/env.duckdb", "llm_key": "env-key"}


def test_the_file_is_used_when_the_environment_is_empty(tmp_path, monkeypatch):
    config = tmp_path / "config.toml"
    write_settings(config, db="/from/file.duckdb", llm_key="file-key")
    monkeypatch.delenv("ASKSLM_DB", raising=False)
    monkeypatch.delenv("ASKSLM_LLM_KEY", raising=False)

    settings = stored_settings(config)

    assert settings == {"db": "/from/file.duckdb", "llm_key": "file-key"}


def test_nothing_stored_anywhere_returns_empty_so_the_app_can_prompt(tmp_path, monkeypatch):
    monkeypatch.delenv("ASKSLM_DB", raising=False)
    monkeypatch.delenv("ASKSLM_LLM_KEY", raising=False)

    assert stored_settings(tmp_path / "absent.toml") == {}


def test_a_written_file_is_not_world_readable(tmp_path):
    """It holds an API key."""
    config = tmp_path / "config.toml"

    write_settings(config, db="/x.duckdb", llm_key="secret")

    assert (config.stat().st_mode & 0o077) == 0
```

- [ ] **Step 2: Run it, confirm it fails** — no module `askslm.settings_file`.

- [ ] **Step 3: Implement** `src/askslm/settings_file.py`:

```python
"""Where config() gets its arguments when nobody is writing Python.

Precedence is env -> file -> nothing (which means the app prompts). The
environment winning is what lets the lab server and CI run with no interactive
step and no file on disk. HLD C.0.1.
"""
from __future__ import annotations

import os
import tomllib
from pathlib import Path

CONFIG_PATH = Path.home() / ".askslm" / "config.toml"


def stored_settings(path: Path = CONFIG_PATH) -> dict:
    """Everything we could find, or {} if the app must ask. Partial is possible:
    a db path in the file and a key in the environment is a normal setup."""
    settings = _from_file(path)
    settings.update(_from_environment())
    return settings


def _from_environment() -> dict:
    found = {"db": os.environ.get("ASKSLM_DB"),
             "llm_key": os.environ.get("ASKSLM_LLM_KEY")}
    return {key: value for key, value in found.items() if value}


def _from_file(path: Path) -> dict:
    if not path.exists():
        return {}
    return dict(tomllib.loads(path.read_text()))


def write_settings(path: Path, db: str, llm_key: str) -> Path:
    """Written once on first run. Mode 0600 -- it holds an API key."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f'db = "{db}"\nllm_key = "{llm_key}"\n')
    path.chmod(0o600)
    return path
```

- [ ] **Step 4: Full suite** — expect 66.

- [ ] **Step 5: Commit**

```bash
git commit -am "feat(settings): env -> ~/.askslm/config.toml -> prompt

config() takes explicit arguments and a biologist cannot supply them, so the
app sources them. The environment winning is what keeps the lab server and CI
non-interactive with no file on disk. The file is 0600 -- it holds an API key."
```

---

### Task 3: Rendering

Pure formatting, no prompting, so the interesting parts are testable without driving a terminal.

**Files:** Create `src/askslm/cli/__init__.py` (empty) and `src/askslm/cli/render.py`; test `Tests/test_render.py`.

- [ ] **Step 1: Write the failing test**

```python
"""Rendering is pure so it can be tested without driving a terminal."""
import askslm
from askslm.cli.render import narrow_warning, preview_line, overlap_rows
from askslm.plan import CohortPreview


def _preview() -> CohortPreview:
    return CohortPreview(
        by_metadata_source={askslm.Source.SRA_METADATA: 380,
                            askslm.Source.METALOG_METADATA: 207},
        shared=175, union=412,
        by_profile_source={askslm.Source.SRA_TAXONOMY: 380,
                           askslm.Source.METALOG_METAPHLAN4_ALL: 228})


def test_the_preview_line_leads_with_the_cohort_size(_=None):
    """HLD C.0: one line, cohort size first, then per-family coverage."""
    line = preview_line(_preview())

    assert line.startswith("412 biosamples")
    assert "228" in line


def test_a_narrow_cohort_is_warned_about():
    """A plain threshold, not a model judgement -- 12 samples is usually a mistake
    the user wants to see before spending the expensive run()."""
    assert narrow_warning(CohortPreview(union=12)) is not None
    assert narrow_warning(_preview()) is None


def test_overlap_rows_name_the_winner_of_the_shared_partition():
    """The trust screen: the user must be able to see WHICH source won the samples
    that appear in both databases."""
    rows = overlap_rows(_preview(), winner=askslm.Source.METALOG_METADATA)

    labels = [row[0] for row in rows]
    assert "shared" in labels
    assert any("METALOG_METADATA" in str(row) for row in rows)
```

- [ ] **Step 2: Run it, confirm it fails.**

- [ ] **Step 3: Implement** `src/askslm/cli/render.py`:

```python
"""Formatting only -- no prompting, no state. Kept separate from session.py so the
parts worth testing do not require driving a terminal."""
from __future__ import annotations

from askslm.plan import CohortPreview
from askslm.sources import Source

NARROW = 50            # a plain threshold, not a model judgement (HLD C.0.2)


def preview_line(preview: CohortPreview) -> str:
    """`412 biosamples · STAT 380 · METAPHLAN 228 · MOTUS 222`"""
    parts = [f"{preview.union} biosamples"]
    parts += [f"{source.name} {count}"
              for source, count in preview.by_profile_source.items()]
    return " · ".join(parts)


def narrow_warning(preview: CohortPreview) -> str | None:
    if preview.union >= NARROW:
        return None
    return f"{preview.union} samples -- narrow. Try widening the question."


def overlap_rows(preview: CohortPreview, winner: Source) -> list[tuple[str, str, str]]:
    """The trust screen (HLD C.1.3): who has which samples, and who wins the overlap."""
    counts = preview.by_metadata_source
    rows = [(source.name, str(count), "") for source, count in counts.items()]
    rows.append(("shared", str(preview.shared), f"<- {winner.name} wins these"))
    return rows
```

- [ ] **Step 4: Full suite** — expect 69.

- [ ] **Step 5: Commit** — `feat(cli): pure rendering helpers for the preview and trust screens`

---

### Task 4: The session

The loop. This is glue and is NOT unit-tested — it is verified by running it. Keep it short.

**Files:** Create `src/askslm/cli/session.py`; modify `pyproject.toml`.

- [ ] **Step 1: Add the dependencies and entry point** to `pyproject.toml`: add `"questionary>=2.0"` and `"rich>=13.0"` to `dependencies`, then:

```toml
[project.scripts]
askslm = "askslm.cli.session:main"
```

(The file currently carries a comment saying the entry point is deferred — delete that comment, it is now wrong.)

- [ ] **Step 2: Implement** `src/askslm/cli/session.py`. Write the loop below. It is deliberately line-oriented — it scrolls like normal terminal output, no redraw, no layout engine (HLD C.0.3).

```python
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
    console.print(report)


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
    """No LLM, no questions -- the reproducible path."""
    settings = stored_settings()
    askslm.config(db=settings["db"], llm="gemini", llm_key=settings.get("llm_key", ""))
    plan = load_plan(path)
    console.print(preview_line(plan.preview))
    _run(plan)
```

- [ ] **Step 3: Verify it imports and the entry point resolves**

```bash
python3 -c "import sys; sys.path.insert(0,'src'); import askslm.cli.session as s; print(s.main)"
python3 -m pytest Tests/ -q
```

Expect 69 still passing (this task adds no tests).

- [ ] **Step 4: Smoke-run it by hand** against the fixture mirror. Build a fixture, set `ASKSLM_DB` to it, and run the session with a real key if one is available; otherwise confirm it reaches the first prompt and exits cleanly on Ctrl-C. **Report exactly what you observed** — this is the only verification this task gets.

- [ ] **Step 5: Commit** — `feat(cli): the interactive session`

---

### Task 5: Docs

- [ ] **Step 1** — `README.md`: `$ askslm` as the primary usage, the Python API second, `askslm run plans/x.json` for replay.
- [ ] **Step 2** — `CLAUDE.md` Layout: add `cli/`, `settings_file.py`.
- [ ] **Step 3** — `src/askslm/__init__.py` STATUS: the terminal app and plan persistence now exist; say plainly what is still rough.
- [ ] **Step 4** — Full suite, then commit `docs: the terminal app exists`.

---

## Finishing

```bash
git push -u origin feature/terminal-app
gh pr create --draft --base main --title "feat(cli): the interactive terminal app and plan persistence"
```

Then stop. The human squash-merges.

## Out of scope

- The `dropped` CSV side-file (HLD C.0.2 screen 4) — `BuildReport` already carries the list.
- "Build another family from this cohort" as a post-run menu — the loop already allows re-running.
- Reordering sources by drag; `questionary.checkbox` order is selection order, which is close enough.
- The catalog exclusion policy, `jattr` flattening, the `tax_raw` sort, eval gold SQL — all tracked separately.
