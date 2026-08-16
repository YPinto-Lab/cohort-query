# Agent Operating Model Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the runtime agent competent by installing a three-layer operating model (identity preamble + thin operating manual + per-turn workspace snapshot), plus on-demand read tools and three chat UI fixes.

**Architecture:** The agent's `system` string is assembled fresh on every LLM call from three layers: a static identity preamble and operating manual (`src/agent/operating_manual.md`, which delegates to canonical repo docs via a pointer map), and a workspace snapshot rendered from disk each turn. Two read-only tools (`read_file`, `list_dir`, repo-scoped, size-capped) make the pointer map actionable. A vendored `Docs/agent-code-standards.md` gives the agent a reachable code-quality reference.

**Tech Stack:** Python 3.14, pytest, FastAPI + Jinja2 + htmx (web), `biom`/`pandas` (domain). Tests live under `Tests/`, run with `.venv/bin/pytest` (config in `pyproject.toml`: `testpaths = Tests`, `addopts = -m "not llm"`).

**Branch:** `feature-agent-operating-model` (already created off `origin/main`).

**Spec:** `Docs/superpowers/specs/2026-06-05-agent-operating-model-design.html`

---

## File Structure

| File | Responsibility | Task |
|------|----------------|------|
| `Docs/agent-code-standards.md` | Repo-resident code-quality reference the read tool can reach | 1 |
| `src/agent/operating_manual.md` | Layer 2: durable model + pointer map (static) | 2 |
| `src/agent/workspace_snapshot.py` | Layer 3: render live on-disk workspace state | 3 |
| `Tests/agent/test_workspace_snapshot.py` | Snapshot renderer tests | 3 |
| `src/agent/loop.py` | Assemble the three layers in `build_system_prompt`; wire into `run` | 4 |
| `Tests/agent/test_system_prompt.py` | Assembly tests | 4 |
| `src/agent/tools/session_tools.py` | `read_file` / `list_dir` read-only tools | 5 |
| `Tests/agent/test_session_tools.py` | Read-tool tests (append) | 5 |
| `src/web/app.py` | Bug #2: stop streaming `user` events to the log | 6 |
| `Tests/web/test_app.py` | `_streams_to_log` predicate test (append) | 6 |
| `src/web/templates/chat.html` | Bug #1 (wrap CSS) + bug #3 (thinking indicator JS) | 7 |

---

### Task 1: Vendored code standards doc

**Files:**
- Create: `Docs/agent-code-standards.md`

This is a static reference document (no test — pure content). It is the in-repo home the operating manual's pointer map delegates to for the code-quality bar.

- [ ] **Step 1: Create the standards doc**

Create `Docs/agent-code-standards.md` with exactly this content:

```markdown
---
kind: reference
audience: ask-slm runtime agent
intent: the code-quality bar for any code the agent writes or edits
---

# Ask-SLM code standards

Readability is the highest priority — above brevity, cleverness, and convenience.
Code is read far more than written. When any rule trades against readability, readability wins.

## Shape
- No `else`. Use early returns (guard clauses) or polymorphism.
- Functions do one thing; keep them to ~10 lines. Extract helpers past that. (Tests are exempt.)
- 1–3 parameters, never more. Group related params into a dataclass/DTO. Pass only what is used.
- Write classes, not loose collections of functions. One class per file, ~90% of the time. Keep files small.
- Never use `lambda` — always a named `def`.
- KISS: prefer the clearest expression of the design over cleverness.

## Comments
- Sparse, English, explain *why* not *what*. No redundant comments, no commented-out code.
- Exception — opaque library calls: a short inline comment naming the *domain effect* is encouraged
  (e.g. `# removes genus-and-above`, `# merges sub-species into their species`).

## Domain rules (Ask-SLM specific)
- Reuse libraries — skbio / biom / ete3 / pandas. Write new custom code only on explicit authorization.
- Compose over duplicate: before writing a transformation, find the canonical equivalent and route through it.
- Keep taxonomy and metadata as TWO separate DataFrames — never merge them into one.
- Each Accessor reads and validates exactly ONE source. Joins belong in Processors, not Accessors.
- Trust input, fail fast: do the work or let the library raise. Validation only at the Accessor boundary.
- Prefer typed domain objects over raw DataFrames at API boundaries.
- No backward-compatibility aliases or deprecated re-exports. Rename everywhere and commit clean.
```

- [ ] **Step 2: Commit**

```bash
git add Docs/agent-code-standards.md
git commit -m "docs: vendor agent code-standards reference into the repo"
```

---

### Task 2: Operating manual (layer 2)

**Files:**
- Create: `src/agent/operating_manual.md`

Static content (no test — the loader that reads it is tested in Task 4 via `build_system_prompt`).

- [ ] **Step 1: Create the operating manual**

Create `src/agent/operating_manual.md` with exactly this content:

```markdown
---
kind: reference
audience: ask-slm runtime agent
intent: the durable operating model + a pointer map to authoritative sources
---

# How to work in Ask-SLM

You build and analyze metagenomic studies by authoring and running Python against the `askslm`
package and established libraries (biom, ete3, scikit-bio, scipy, pandas). The disk is the source
of truth. Reuse what `askslm` provides — never hand-roll what the package already does.

## Vocabulary & model
- A **feature table** is ONE `biom.Table`: counts (features × samples) + sample metadata + feature
  metadata (lineage). One feature table per community study.
- A **community** is one sample's microbes (biological).
- Five operation kinds: ingest, build, transform, split, analyze.

## Count semantics (non-negotiable — getting this wrong silently corrupts results)
- `self_count` is the ATOMIC, direct count at a taxon.
- `total_count` is CUMULATIVE over the taxon's whole clade.
- NEVER sum `total_count` across the tree. Build the counts matrix from `self_count`.

## Phase flow
Work is organized into numbered phases on disk:
`0_inputs → 1_build → 2_transform/<exploration> → 3_analyze/<exploration>/<analysis>`.

- **Build** (run once): read each raw source with one Accessor, assemble ONE `biom.Table`
  (counts from `self_count` + lineage feature metadata + sample metadata), then write it as biom
  **JSON** to `1_build/feature_table.biom`. Use JSON, not HDF5 — HDF5 cannot round-trip nested
  lineage metadata.
- **Transform**: shape the upstream feature table, write `result/feature_table.biom`.
- **Analyze**: measure a feature table, write CSVs/plots.

Inside a phase script, `from askslm import workspace; ws = workspace.phase(__file__)` gives you
`ws.inputs`, `ws.result`, `ws.shared`, and `ws.upstream()`. Every phase writes into its own
`result/`.

## When you need more, read the source (use the read_file / list_dir tools)
| Need | Read |
|------|------|
| the feature-table model / library palette (the bible) | `Docs/feature-table-and-library-palette.html` |
| phase-tree organization rationale | `Docs/superpowers/specs/2026-06-03-workspace-phase-organization-design.html` |
| workspace tooling rationale | `Docs/superpowers/specs/2026-06-03-workspace-tooling-design.html` |
| a worked example done right | `Workspaces/ABX_new` (read its `1_build/build.py`) |
| real `askslm` signatures & behavior | `src/askslm/` (e.g. `accessors/`, `workspace.py`, `sra_schema.py`) |
| the code-quality bar for any code you write | `Docs/agent-code-standards.md` |

Do NOT read large data files (e.g. `taxonomy.csv` can be hundreds of MB) into context — inspect
their shape with `run_python` instead.
```

- [ ] **Step 2: Commit**

```bash
git add src/agent/operating_manual.md
git commit -m "feat(agent): add thin operating manual (layer 2)"
```

---

### Task 3: Workspace snapshot renderer (layer 3)

**Files:**
- Create: `src/agent/workspace_snapshot.py`
- Test: `Tests/agent/test_workspace_snapshot.py`

- [ ] **Step 1: Write the failing tests**

Create `Tests/agent/test_workspace_snapshot.py`:

```python
from agent.workspace import Workspace
from agent.workspace_snapshot import WorkspaceSnapshot


def test_snapshot_lists_files_and_inlines_md(tmp_path):
    root = tmp_path / "study"
    (root / "1_build").mkdir(parents=True)
    (root / "1_build" / "build.py").write_text("x = 1\n")
    (root / "1_build" / "build.md").write_text("the intent")
    (root / "0_inputs").mkdir()
    (root / "0_inputs" / "taxonomy.csv").write_text("a,b\n1,2\n")

    out = WorkspaceSnapshot(Workspace.open(root)).render()

    assert "study" in out
    assert "1_build/build.py" in out
    assert "0_inputs/taxonomy.csv" in out
    assert "the intent" in out      # .md inlined
    assert "a,b" not in out         # csv contents NOT read


def test_snapshot_skips_results_and_pycache(tmp_path):
    root = tmp_path / "study"
    ws = Workspace.open(root)        # creates results/agent_log
    (root / "__pycache__").mkdir()
    (root / "__pycache__" / "x.pyc").write_text("junk")

    out = WorkspaceSnapshot(ws).render()

    assert "agent_log" not in out
    assert "x.pyc" not in out
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest Tests/agent/test_workspace_snapshot.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'agent.workspace_snapshot'`

- [ ] **Step 3: Write the implementation**

Create `src/agent/workspace_snapshot.py`:

```python
from __future__ import annotations
from pathlib import Path

from agent.workspace import Workspace

_SKIP_DIRS = {"results", "__pycache__", ".git"}


class WorkspaceSnapshot:
    """Renders the live on-disk state of a workspace for the agent's system prompt."""

    def __init__(self, workspace: Workspace) -> None:
        self._root = workspace.root

    def render(self) -> str:
        lines = [f"# Workspace: {self._root.name}", "", "## Files"]
        lines.extend(self._tree_lines())
        lines.extend(self._intent_blocks())
        return "\n".join(lines)

    def _files(self) -> list[Path]:
        return [p for p in sorted(self._root.rglob("*")) if self._included(p)]

    def _included(self, path: Path) -> bool:
        if not path.is_file() or path.name.startswith("."):
            return False
        return not (set(path.relative_to(self._root).parts) & _SKIP_DIRS)

    def _tree_lines(self) -> list[str]:
        return [f"- {p.relative_to(self._root).as_posix()}" for p in self._files()]

    def _intent_blocks(self) -> list[str]:
        return [self._intent_block(p) for p in self._files() if p.suffix == ".md"]

    def _intent_block(self, path: Path) -> str:
        return f"\n## {path.relative_to(self._root).as_posix()}\n{path.read_text()}"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest Tests/agent/test_workspace_snapshot.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add src/agent/workspace_snapshot.py Tests/agent/test_workspace_snapshot.py
git commit -m "feat(agent): render live workspace snapshot (layer 3)"
```

---

### Task 4: Assemble the system prompt and wire it in

**Files:**
- Modify: `src/agent/loop.py:12-19` (replace `SYSTEM_PROMPT` constant) and `src/agent/loop.py:38` (the `system=` argument)
- Test: `Tests/agent/test_system_prompt.py`

- [ ] **Step 1: Write the failing test**

Create `Tests/agent/test_system_prompt.py`:

```python
from agent.workspace import Workspace
from agent.session import Session
from agent.loop import build_system_prompt


def test_build_system_prompt_has_all_three_layers(tmp_path):
    root = tmp_path / "ABC_study"
    (root / "1_build").mkdir(parents=True)
    (root / "1_build" / "build.md").write_text("assemble the table")
    sess = Session.start(Workspace.open(root))

    prompt = build_system_prompt(sess)

    assert "reuse" in prompt.lower()        # identity preamble
    assert "self_count" in prompt           # operating manual
    assert "ABC_study" in prompt            # workspace snapshot
    assert "assemble the table" in prompt   # intent .md inlined by the snapshot
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest Tests/agent/test_system_prompt.py -v`
Expected: FAIL with `ImportError: cannot import name 'build_system_prompt'`

- [ ] **Step 3: Replace the constant with the assembly function**

In `src/agent/loop.py`, replace the import block and the `SYSTEM_PROMPT` constant (current lines 1-19). Change the top of the file from:

```python
from __future__ import annotations
import json
from typing import Iterator

from agent.events import Event
from agent.session import Session
from agent.llm_client import LLMClient
from agent.tools.registry import Registry

MAX_STEPS = 20

SYSTEM_PROMPT = (
    "You are Ask-SLM, an agent that helps researchers analyze SRA microbiome data.\n"
    "Workspace: {workspace}.\n"
    "You drive a fixed set of Python tools that wrap the askslm API. Prefer named "
    "tools; use run_python for novel analyses (third-party libs, ad-hoc dataframe "
    "work). When a tool returns a handle, pass that handle to subsequent tools. "
    "Be concise."
)
```

to:

```python
from __future__ import annotations
import json
from pathlib import Path
from typing import Iterator

from agent.events import Event
from agent.session import Session
from agent.llm_client import LLMClient
from agent.tools.registry import Registry
from agent.workspace_snapshot import WorkspaceSnapshot

MAX_STEPS = 20

IDENTITY_PREAMBLE = (
    "You are Ask-SLM, an agent that builds and analyzes metagenomic studies with the user.\n"
    "The disk is the source of truth. Reuse the askslm package and established libraries; "
    "never hand-roll what the package already provides. Author your work as phase scripts and "
    "run them. When a tool returns a handle, pass that handle to subsequent tools. Be concise."
)

_MANUAL_PATH = Path(__file__).parent / "operating_manual.md"


def _operating_manual() -> str:
    return _MANUAL_PATH.read_text()


def build_system_prompt(session: Session) -> str:
    return "\n\n".join([
        IDENTITY_PREAMBLE,
        _operating_manual(),
        WorkspaceSnapshot(session.workspace).render(),
    ])
```

- [ ] **Step 4: Use it in the run loop**

In `src/agent/loop.py`, inside `run(...)`, change the `llm.complete` call. Replace:

```python
            response = llm.complete(
                messages=session.messages,
                tools=registry.schemas(),
                system=SYSTEM_PROMPT.format(workspace=session.workspace.name),
            )
```

with:

```python
            response = llm.complete(
                messages=session.messages,
                tools=registry.schemas(),
                system=build_system_prompt(session),
            )
```

- [ ] **Step 5: Run the new test plus the existing loop tests**

Run: `.venv/bin/pytest Tests/agent/test_system_prompt.py Tests/agent/test_loop.py -v`
Expected: PASS (all tests; the loop tests still pass because `build_system_prompt` works on their tmp workspaces)

- [ ] **Step 6: Commit**

```bash
git add src/agent/loop.py Tests/agent/test_system_prompt.py
git commit -m "feat(agent): assemble three-layer system prompt per turn"
```

---

### Task 5: On-demand read tools

**Files:**
- Modify: `src/agent/tools/session_tools.py` (append tools + helpers)
- Test: `Tests/agent/test_session_tools.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `Tests/agent/test_session_tools.py`:

```python
def _session(tmp_path):
    root = tmp_path / "ws"; root.mkdir()
    return Session.start(Workspace.open(root))


def test_read_file_reads_repo_file(tmp_path):
    sess = _session(tmp_path)
    r = session_registry.execute(sess, "read_file", {"path": "CLAUDE.md"})
    assert not r.is_error
    assert "Ask-SLM" in r.summary["value"]
    assert r.summary["truncated"] is False


def test_read_file_caps_size(tmp_path, monkeypatch):
    monkeypatch.setattr("agent.tools.session_tools._READ_CAP_BYTES", 10)
    sess = _session(tmp_path)
    r = session_registry.execute(sess, "read_file", {"path": "CLAUDE.md"})
    assert not r.is_error
    assert len(r.summary["value"]) <= 10
    assert r.summary["truncated"] is True


def test_read_file_rejects_path_escape(tmp_path):
    sess = _session(tmp_path)
    r = session_registry.execute(sess, "read_file", {"path": "../../../../etc/passwd"})
    assert r.is_error
    assert "escapes" in r.error


def test_list_dir_lists_entries(tmp_path):
    sess = _session(tmp_path)
    r = session_registry.execute(sess, "list_dir", {"path": "Docs"})
    assert not r.is_error
    names = {e["name"] for e in r.summary["value"]}
    assert "feature-table-and-library-palette.html" in names
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest Tests/agent/test_session_tools.py -v`
Expected: FAIL with `unknown tool: read_file` / `unknown tool: list_dir` (registry returns an error result)

- [ ] **Step 3: Write the implementation**

Append to `src/agent/tools/session_tools.py` (also add `from pathlib import Path` at the top of the file if not present):

```python
_REPO_ROOT = Path(__file__).resolve().parents[3]
_READ_CAP_BYTES = 65536


@session_registry.tool
def list_dir(session: Session, path: str) -> dict:
    """List the entries of a directory inside the repository (read-only)."""
    target = _safe_repo_path(path)
    return {"value": [_entry(child) for child in sorted(target.iterdir())]}


@session_registry.tool
def read_file(session: Session, path: str) -> dict:
    """Read a text file inside the repository, capped at 64 KB (read-only)."""
    target = _safe_repo_path(path)
    raw = target.read_bytes()
    return {
        "value": raw[:_READ_CAP_BYTES].decode("utf-8", errors="replace"),
        "truncated": len(raw) > _READ_CAP_BYTES,
    }


def _safe_repo_path(path: str) -> Path:
    candidate = (_REPO_ROOT / path).resolve()
    if not candidate.is_relative_to(_REPO_ROOT):
        raise ValueError(f"path escapes repository root: {path}")
    if not candidate.exists():
        raise FileNotFoundError(f"path not found: {path}")
    return candidate


def _entry(child: Path) -> dict:
    return {
        "name": child.name,
        "kind": "dir" if child.is_dir() else "file",
        "size_bytes": child.stat().st_size if child.is_file() else None,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest Tests/agent/test_session_tools.py -v`
Expected: PASS (all tests, including the two pre-existing ones)

- [ ] **Step 5: Commit**

```bash
git add src/agent/tools/session_tools.py Tests/agent/test_session_tools.py
git commit -m "feat(agent): add read-only read_file/list_dir tools (repo-scoped, size-capped)"
```

---

### Task 6: UI bug #2 — stop echoing the user's message

**Files:**
- Modify: `src/web/app.py:131-144` (the `event_stream` generator) + add `_streams_to_log` helper
- Test: `Tests/web/test_app.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `Tests/web/test_app.py`:

```python
from web.app import _streams_to_log
from agent.events import Event


def test_user_events_do_not_stream_to_log():
    assert _streams_to_log(Event.user("hi")) is False
    assert _streams_to_log(Event.assistant_final("yo")) is True
    assert _streams_to_log(Event.tool_call("t", {})) is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest Tests/web/test_app.py::test_user_events_do_not_stream_to_log -v`
Expected: FAIL with `ImportError: cannot import name '_streams_to_log'`

- [ ] **Step 3: Add the predicate and use it**

In `src/web/app.py`, add this helper just above the `messages` route (before `@app.post("/w/{workspace}/messages")`):

```python
def _streams_to_log(ev: Event) -> bool:
    # The browser appends the user's own message locally; re-rendering the server's
    # user event would duplicate it in the chat log.
    return ev.type != "user"
```

Then, inside `event_stream`, guard the html block. Replace:

```python
        for ev in agent.chat(message):
            data = json.dumps({"type": ev.type, **ev.payload})
            yield f"event: {ev.type}\ndata: {data}\n\n".encode()
            html = templates.get_template("_event.html").render(event=ev)
            yield f"event: html\ndata: {json.dumps(html)}\n\n".encode()
```

with:

```python
        for ev in agent.chat(message):
            data = json.dumps({"type": ev.type, **ev.payload})
            yield f"event: {ev.type}\ndata: {data}\n\n".encode()
            if _streams_to_log(ev):
                html = templates.get_template("_event.html").render(event=ev)
                yield f"event: html\ndata: {json.dumps(html)}\n\n".encode()
```

- [ ] **Step 4: Run the test (and the existing app tests) to verify they pass**

Run: `.venv/bin/pytest Tests/web/test_app.py -v`
Expected: PASS (all tests)

- [ ] **Step 5: Commit**

```bash
git add src/web/app.py Tests/web/test_app.py
git commit -m "fix(web): don't re-render the user's own message into the chat log"
```

---

### Task 7: UI bugs #1 and #3 — text wrapping and a thinking indicator

**Files:**
- Modify: `src/web/templates/chat.html` (CSS in `<style>`, and the `send()` function in `<script>`)

Front-end only; verified manually (no unit test for CSS/streaming JS).

- [ ] **Step 1: Add wrapping CSS and an indicator style**

In `src/web/templates/chat.html`, inside the `<style>` block, add these two rules just after the `.you{...}` rule (around line 42):

```css
  .event pre,.event code{white-space:pre-wrap;overflow-wrap:anywhere;word-break:break-word}
  .pending{color:#7d8590;font-style:italic;margin-bottom:8px}
```

- [ ] **Step 2: Replace the `send()` function to add the thinking indicator**

In `src/web/templates/chat.html`, replace the entire `send` function (currently lines 78-95) with:

```javascript
  async function send(e){
    e.preventDefault();
    const input=document.getElementById('msg'); const message=input.value.trim();
    if(!message) return;
    const you=document.createElement('div'); you.className='you';
    const lab=document.createElement('b'); lab.textContent='You: ';
    you.appendChild(lab); you.appendChild(document.createTextNode(message));
    log.appendChild(you); log.scrollTop=log.scrollHeight; input.value='';
    const pending=document.createElement('div'); pending.className='pending';
    pending.textContent='⋯ agent is working…';
    log.appendChild(pending); log.scrollTop=log.scrollHeight;
    const clearPending=()=>{ if(pending.parentNode) pending.remove(); };
    try{
      const res=await fetch('/w/{{ workspace }}/messages',{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},body:'message='+encodeURIComponent(message)});
      const reader=res.body.getReader(); const dec=new TextDecoder(); let buf='';
      while(true){ const {value,done}=await reader.read(); if(done) break; buf+=dec.decode(value,{stream:true});
        let i; while((i=buf.indexOf('\n\n'))>=0){ const block=buf.slice(0,i); buf=buf.slice(i+2);
          const lines=block.split('\n'); let ev='',data='';
          for(const ln of lines){ if(ln.startsWith('event:')) ev=ln.slice(6).trim(); else if(ln.startsWith('data:')) data += ln.slice(5); }
          if(ev==='html' && data){ clearPending(); append(JSON.parse(data)); }
        }
      }
    } finally {
      clearPending();
    }
  }
```

The indicator appears immediately after the user's message, is removed when the first rendered event arrives (`clearPending()` before the first `append`), and the `finally` guarantees removal when the stream ends or errors.

- [ ] **Step 3: Manual verification**

Start the app:

```bash
PYTHONPATH=src .venv/bin/uvicorn web.app:app --reload
```

Open a workspace at `http://127.0.0.1:8000`, send a message, and confirm:
1. Long tool-result lines **wrap** instead of producing a horizontal scrollbar.
2. Your message appears **once** (no echo).
3. An "⋯ agent is working…" row shows after sending and disappears once results stream in.

- [ ] **Step 4: Commit**

```bash
git add src/web/templates/chat.html
git commit -m "fix(web): wrap chat text and show a thinking indicator while the agent works"
```

---

### Task 8: Full regression and finish

- [ ] **Step 1: Run the whole suite**

Run: `.venv/bin/pytest`
Expected: PASS (the entire suite green; `llm`-marked tests are skipped by default)

- [ ] **Step 2: Push the branch and open a PR**

```bash
git push -u origin feature-agent-operating-model
gh pr create --base main --title "Agent operating model: competence, read tools, chat UI fixes" --body "Implements Docs/superpowers/specs/2026-06-05-agent-operating-model-design.html"
```

Then stop — the user squash-merges through GitHub.

---

## Self-Review Notes

- **Spec coverage:** §2 three layers → Tasks 2/3/4; §3 operating manual + pointer map → Task 2; §4 workspace snapshot (per-turn, skips CSVs/results) → Task 3; §5 read tools (scope guard + size cap) → Task 5; §6 vendored standards → Task 1; §7 wiring → Task 4; §8 UI fixes #1/#2/#3 → Tasks 7/6/7; §9 testing → Tasks 3/4/5/6 + Task 8 regression. All sections covered.
- **Type consistency:** `build_system_prompt(session)`, `WorkspaceSnapshot(workspace).render()`, `_safe_repo_path`, `_entry`, `_streams_to_log`, `_READ_CAP_BYTES` are referenced identically across tasks.
- **Out of scope** (no tasks, by design): token-streaming of final text, biom-viewer rework, new high-level `askslm` build tools.
