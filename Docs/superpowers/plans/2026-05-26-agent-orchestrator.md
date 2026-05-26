# Agent Orchestrator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build v1 of a natural-language agent that drives Ask-SLM's existing Python API via a hybrid of named tools + a sandboxed `run_python` escape hatch, served as a local FastAPI/HTMX chat UI.

**Architecture:** New top-of-stack `Agents/` package. A `Session` owns the per-chat state (workspace, message history, variable store of domain-object handles, JSONL transcript). A `@tool` decorator registers Python functions and auto-generates Anthropic tool schemas from type hints. The ReAct loop is a single ~150-line generator yielding `Event` objects that simultaneously drive the web stream, the transcript, and tests. A thin `Web/` FastAPI app wraps the agent as an SSE chat surface.

**Tech Stack:** Python 3.11+, Anthropic SDK, Pydantic v2, FastAPI, Uvicorn, HTMX (no build pipeline), pytest. Domain objects come from the existing `askslm.metadata` / `askslm.taxonomy` API and the contracts in `Common/contracts/`.

**Spec:** `Docs/superpowers/specs/2026-05-26-agent-orchestrator-design.md`

---

## File map

**New files (Agents core):**
- `Agents/__init__.py` — public surface: `Agent`, `Session`
- `Agents/handle.py` — `Handle[T]` phantom-type alias for `str`
- `Agents/variable_store.py` — `VariableStore`: put/get handles, summary dispatch
- `Agents/summaries.py` — per-type summary functions (`Metadata`, `AbundanceMatrix`, `Cohort`, `ResolvedTaxonomy`, `DataFrame`, `MetadataOverview`)
- `Agents/transcript.py` — `TranscriptWriter`: JSONL append per event type
- `Agents/workspace.py` — `Workspace` dataclass with `inputs_dir`, `results_dir`, `agent_log_dir`
- `Agents/session.py` — `Session`: composes everything; lock to one workspace
- `Agents/events.py` — `Event` dataclass + factory methods (user, assistant_final, tool_call, tool_result, error)
- `Agents/llm_client.py` — `LLMClient` ABC, `FakeLLMClient` (for tests), `AnthropicClient`
- `Agents/loop.py` — the `run()` generator
- `Agents/agent.py` — `Agent` facade composing Session + loop + LLM
- `Agents/cli.py` — `python -m Agents.cli review|show` entrypoint
- `Agents/review.py` — `agent-review` logic: whitelist + tool-promotion mining
- `Agents/show.py` — `agent-show` logic: pretty-print one transcript
- `Agents/tools/__init__.py` — exports the registered tool registry
- `Agents/tools/registry.py` — `@tool` decorator, schema generation, execution wrapper
- `Agents/tools/metadata_tools.py` — `extract_metadata`, `metadata_overview`
- `Agents/tools/taxonomy_tools.py` — `load_taxonomy`, `resolve_taxonomy`, `build_abundance_matrix`, `build_cohort`
- `Agents/tools/session_tools.py` — `summarize`, `list_workspace_inputs`
- `Agents/tools/run_python.py` — the `run_python` `@tool` and AST import extractor
- `Agents/tools/_sandbox_worker.py` — subprocess entrypoint (pickled-IO worker)

**New files (Web shell):**
- `Web/__init__.py`
- `Web/app.py` — FastAPI app, routes, SSE generator wrapper
- `Web/sessions_index.py` — discover transcripts, build sidebar listing
- `Web/templates/chat.html` — main chat page (HTMX)
- `Web/templates/_event.html` — partial for one event
- `Web/static/app.css`

**New files (tests):**
- `Tests/agent/__init__.py`
- `Tests/agent/conftest.py` — shared fixtures (tmp workspace, fake LLM)
- `Tests/agent/test_handle.py`
- `Tests/agent/test_variable_store.py`
- `Tests/agent/test_summaries.py`
- `Tests/agent/test_transcript.py`
- `Tests/agent/test_session.py`
- `Tests/agent/test_events.py`
- `Tests/agent/test_registry.py`
- `Tests/agent/test_metadata_tools.py`
- `Tests/agent/test_taxonomy_tools.py`
- `Tests/agent/test_session_tools.py`
- `Tests/agent/test_run_python.py`
- `Tests/agent/test_fake_llm.py`
- `Tests/agent/test_anthropic_client.py`
- `Tests/agent/test_loop.py`
- `Tests/agent/integration/test_full_flow.py`
- `Tests/agent/test_review.py`
- `Tests/agent/test_show.py`
- `Tests/agent/llm_smoke/test_trajectories.py` (opt-in via `@pytest.mark.llm`)
- `Tests/web/__init__.py`
- `Tests/web/test_app.py`

**Modified files:**
- `Docs/requirements.txt` — add `anthropic`, `pydantic>=2`, `fastapi`, `uvicorn`, `jinja2`, `httpx` (for tests)
- `pytest.ini` or `pyproject.toml` — register the `llm` marker
- `.gitignore` — ignore `Workspaces/*/results/agent_log/`

---

## Task 1: Package skeleton, dependencies, marker registration

**Files:**
- Create: `Agents/__init__.py`
- Create: `Agents/tools/__init__.py`
- Create: `Tests/agent/__init__.py`
- Create: `Tests/web/__init__.py`
- Modify: `Docs/requirements.txt`
- Create: `pytest.ini`

- [ ] **Step 1: Create empty package files**

Create the four `__init__.py` files above as empty files.

- [ ] **Step 2: Add dependencies**

Append to `Docs/requirements.txt`:

```
anthropic>=0.40
pydantic>=2.5
fastapi>=0.110
uvicorn[standard]>=0.27
jinja2>=3.1
httpx>=0.27
```

- [ ] **Step 3: Create pytest.ini with marker registration**

```ini
[pytest]
testpaths = Tests
markers =
    llm: hits a real LLM API (costs money); skipped by default
addopts = -m "not llm"
```

- [ ] **Step 4: Install and verify**

```bash
pip install -r Docs/requirements.txt
python -c "import Agents, anthropic, pydantic, fastapi"
pytest Tests -q
```

Expected: imports succeed; existing tests still pass.

- [ ] **Step 5: Commit**

```bash
git add Agents Tests/agent Tests/web Docs/requirements.txt pytest.ini
git commit -m "feat(agent): scaffold Agents package and add deps"
```

---

## Task 2: Handle type alias

**Files:**
- Create: `Agents/handle.py`
- Test: `Tests/agent/test_handle.py`

The `Handle[T]` type is a phantom-typed alias for `str`. At runtime it's just a string; at type-check time it carries the wrapped type for documentation and tool-schema generation.

- [ ] **Step 1: Write the failing test**

`Tests/agent/test_handle.py`:

```python
from typing import get_type_hints
from Agents.handle import Handle


def test_handle_is_str_at_runtime():
    h: Handle[int] = "matrix_1"
    assert isinstance(h, str)
    assert h == "matrix_1"


def test_handle_unwrap_arg_returns_underlying_type():
    from Agents.handle import unwrap_handle_arg
    def fn(x: Handle[int]) -> None: ...
    hint = get_type_hints(fn, include_extras=True)["x"]
    assert unwrap_handle_arg(hint) is int


def test_unwrap_returns_none_for_non_handle():
    from Agents.handle import unwrap_handle_arg
    assert unwrap_handle_arg(str) is None
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest Tests/agent/test_handle.py -v
```

Expected: ImportError on `Agents.handle`.

- [ ] **Step 3: Implement**

`Agents/handle.py`:

```python
from __future__ import annotations
from typing import Annotated, TypeVar, get_args, get_origin

T = TypeVar("T")

class _HandleMarker:
    """Marker so unwrap_handle_arg can recognize Handle[T] forms."""

Handle = Annotated[str, _HandleMarker]
# Usage: Handle[Metadata] — but Annotated requires the metadata not the param.
# We expose Handle as a callable: Handle[X] returns Annotated[str, _HandleMarker, X].

class _HandleFactory:
    def __getitem__(self, item):
        return Annotated[str, _HandleMarker, item]

Handle = _HandleFactory()  # type: ignore[assignment]


def unwrap_handle_arg(annotation) -> type | None:
    """Return T if annotation is Handle[T], else None."""
    if get_origin(annotation) is None:
        return None
    args = get_args(annotation)
    if len(args) >= 3 and args[0] is str and args[1] is _HandleMarker:
        return args[2]
    return None
```

- [ ] **Step 4: Run tests**

```bash
pytest Tests/agent/test_handle.py -v
```

Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add Agents/handle.py Tests/agent/test_handle.py
git commit -m "feat(agent): add Handle[T] phantom type and unwrap helper"
```

---

## Task 3: Summaries dispatch

**Files:**
- Create: `Agents/summaries.py`
- Test: `Tests/agent/test_summaries.py`

A dispatch table mapping domain types to a small `dict` summary that is safe to send to the LLM.

- [ ] **Step 1: Write the failing test**

`Tests/agent/test_summaries.py`:

```python
import pandas as pd
from Engines.MetadataEngine.metadata import Metadata
from Agents.summaries import summarize_object


def test_summarize_metadata():
    df = pd.DataFrame({"acc": ["S1", "S2"], "group": ["a", "b"]})
    md = Metadata(df=df)
    s = summarize_object(md)
    assert s["type"] == "Metadata"
    assert s["n_samples"] == 2
    assert "group" in s["columns"]


def test_summarize_dataframe():
    df = pd.DataFrame({"x": [1, 2, 3]})
    s = summarize_object(df)
    assert s["type"] == "DataFrame"
    assert s["shape"] == [3, 1]


def test_summarize_unknown_falls_back_to_repr():
    s = summarize_object(object())
    assert s["type"] == "object"
    assert "repr" in s
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest Tests/agent/test_summaries.py -v
```

Expected: ImportError.

- [ ] **Step 3: Implement**

`Agents/summaries.py`:

```python
from __future__ import annotations
from typing import Any, Callable
import pandas as pd

from Engines.MetadataEngine.metadata import Metadata
from Engines.TaxonomyEngine.abundance_matrix import AbundanceMatrix
from Engines.TaxonomyEngine.cohort import Cohort
from Common.contracts.taxonomy_results import ResolvedTaxonomy
from Common.contracts.metadata_results import MetadataOverview


def _metadata(md: Metadata) -> dict:
    return {
        "type": "Metadata",
        "n_samples": int(len(md.df)),
        "columns": list(md.df.columns)[:30],
    }

def _abundance_matrix(m: AbundanceMatrix) -> dict:
    return {
        "type": "AbundanceMatrix",
        "shape": list(m.counts.shape),
        "samples_preview": list(m.counts.index[:5]),
        "taxa_preview": list(m.counts.columns[:5]),
    }

def _cohort(c: Cohort) -> dict:
    return {
        "type": "Cohort",
        "n_samples": int(len(c.matrix.counts)),
        "n_taxa": int(c.matrix.counts.shape[1]),
        "metadata_columns": list(c.metadata.df.columns)[:30],
    }

def _resolved_taxonomy(r: ResolvedTaxonomy) -> dict:
    return {
        "type": "ResolvedTaxonomy",
        "input_rows": r.summary.input_rows,
        "rows_updated": r.summary.rows_updated,
    }

def _metadata_overview(o: MetadataOverview) -> dict:
    return {"type": "MetadataOverview", "summary_available": True}

def _dataframe(df: pd.DataFrame) -> dict:
    return {
        "type": "DataFrame",
        "shape": list(df.shape),
        "columns": list(df.columns)[:30],
    }


_SUMMARIZERS: list[tuple[type, Callable[[Any], dict]]] = [
    (Metadata, _metadata),
    (AbundanceMatrix, _abundance_matrix),
    (Cohort, _cohort),
    (ResolvedTaxonomy, _resolved_taxonomy),
    (MetadataOverview, _metadata_overview),
    (pd.DataFrame, _dataframe),
]


def summarize_object(obj: Any) -> dict:
    for typ, fn in _SUMMARIZERS:
        if isinstance(obj, typ):
            return fn(obj)
    return {"type": "object", "repr": repr(obj)[:200]}
```

- [ ] **Step 4: Run tests**

```bash
pytest Tests/agent/test_summaries.py -v
```

Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add Agents/summaries.py Tests/agent/test_summaries.py
git commit -m "feat(agent): summarize_object dispatch for domain types"
```

---

## Task 4: VariableStore

**Files:**
- Create: `Agents/variable_store.py`
- Test: `Tests/agent/test_variable_store.py`

Holds named objects (`matrix_1`, `cohort_a`, …) and serves their summaries.

- [ ] **Step 1: Write the failing test**

`Tests/agent/test_variable_store.py`:

```python
import pandas as pd
import pytest
from Agents.variable_store import VariableStore


def test_put_returns_handle_and_get_returns_object():
    store = VariableStore()
    df = pd.DataFrame({"x": [1]})
    h = store.put(df, hint="df")
    assert h == "df_1"
    assert store.get(h) is df


def test_handles_increment_per_hint():
    store = VariableStore()
    store.put(pd.DataFrame(), hint="df")
    h2 = store.put(pd.DataFrame(), hint="df")
    assert h2 == "df_2"


def test_missing_handle_raises_with_available_list():
    store = VariableStore()
    store.put(pd.DataFrame(), hint="df")
    with pytest.raises(KeyError) as exc:
        store.get("missing_99")
    assert "df_1" in str(exc.value)


def test_summary_uses_summarize_object():
    store = VariableStore()
    h = store.put(pd.DataFrame({"a": [1, 2]}), hint="df")
    s = store.summary(h)
    assert s["handle"] == h
    assert s["type"] == "DataFrame"


def test_list_handles_returns_handle_to_summary_map():
    store = VariableStore()
    store.put(pd.DataFrame(), hint="df")
    listing = store.list_handles()
    assert "df_1" in listing
    assert listing["df_1"]["type"] == "DataFrame"
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest Tests/agent/test_variable_store.py -v
```

Expected: ImportError.

- [ ] **Step 3: Implement**

`Agents/variable_store.py`:

```python
from __future__ import annotations
from typing import Any
from Agents.summaries import summarize_object


class VariableStore:
    def __init__(self) -> None:
        self._objects: dict[str, Any] = {}
        self._counters: dict[str, int] = {}

    def put(self, obj: Any, *, hint: str) -> str:
        self._counters[hint] = self._counters.get(hint, 0) + 1
        handle = f"{hint}_{self._counters[hint]}"
        self._objects[handle] = obj
        return handle

    def get(self, handle: str) -> Any:
        if handle not in self._objects:
            raise KeyError(
                f"Handle {handle!r} not found. Available: {sorted(self._objects)}"
            )
        return self._objects[handle]

    def summary(self, handle: str) -> dict:
        return {"handle": handle, **summarize_object(self.get(handle))}

    def list_handles(self) -> dict[str, dict]:
        return {h: summarize_object(o) for h, o in self._objects.items()}

    def __contains__(self, handle: str) -> bool:
        return handle in self._objects
```

- [ ] **Step 4: Run tests**

```bash
pytest Tests/agent/test_variable_store.py -v
```

Expected: 5 PASS.

- [ ] **Step 5: Commit**

```bash
git add Agents/variable_store.py Tests/agent/test_variable_store.py
git commit -m "feat(agent): VariableStore with handle naming and summaries"
```

---

## Task 5: TranscriptWriter

**Files:**
- Create: `Agents/transcript.py`
- Test: `Tests/agent/test_transcript.py`

Append-only JSONL writer with one method per event shape from spec §8.

- [ ] **Step 1: Write the failing test**

`Tests/agent/test_transcript.py`:

```python
import json
from Agents.transcript import TranscriptWriter


def test_writes_user_message(tmp_path):
    w = TranscriptWriter(tmp_path / "t.jsonl")
    w.user("hi")
    lines = [json.loads(l) for l in (tmp_path / "t.jsonl").read_text().splitlines()]
    assert lines[0]["type"] == "user"
    assert lines[0]["content"] == "hi"
    assert "ts" in lines[0]


def test_writes_tool_call_and_result_pair(tmp_path):
    w = TranscriptWriter(tmp_path / "t.jsonl")
    w.tool_call("build_abundance_matrix", {"taxonomy": "tax_1", "rank": "genus"}, tool_use_id="u1")
    w.tool_result_ok("u1", {"type": "AbundanceMatrix"}, latency_ms=12)
    lines = [json.loads(l) for l in (tmp_path / "t.jsonl").read_text().splitlines()]
    assert lines[0]["type"] == "tool_call"
    assert lines[0]["tool"] == "build_abundance_matrix"
    assert lines[1]["type"] == "tool_result"
    assert lines[1]["is_error"] is False
    assert lines[1]["latency_ms"] == 12


def test_writes_tool_error(tmp_path):
    w = TranscriptWriter(tmp_path / "t.jsonl")
    w.tool_result_err("u1", "boom", "Traceback...", latency_ms=3)
    line = json.loads((tmp_path / "t.jsonl").read_text().splitlines()[0])
    assert line["is_error"] is True
    assert line["error"] == "boom"


def test_run_python_call_includes_code_and_imports(tmp_path):
    w = TranscriptWriter(tmp_path / "t.jsonl")
    w.tool_call(
        "run_python",
        {"code": "import skbio\nx = 1"},
        tool_use_id="u1",
        code="import skbio\nx = 1",
        imports_used=["skbio"],
    )
    line = json.loads((tmp_path / "t.jsonl").read_text().splitlines()[0])
    assert line["code"] == "import skbio\nx = 1"
    assert line["imports_used"] == ["skbio"]
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest Tests/agent/test_transcript.py -v
```

Expected: ImportError.

- [ ] **Step 3: Implement**

`Agents/transcript.py`:

```python
from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class TranscriptWriter:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.touch(exist_ok=True)

    def _append(self, record: dict) -> None:
        with self.path.open("a") as f:
            f.write(json.dumps(record) + "\n")

    def user(self, content: str) -> None:
        self._append({"ts": _now(), "type": "user", "content": content})

    def assistant(self, content: str) -> None:
        self._append({"ts": _now(), "type": "assistant", "content": content})

    def tool_call(
        self,
        tool: str,
        args: dict,
        *,
        tool_use_id: str,
        code: str | None = None,
        imports_used: list[str] | None = None,
    ) -> None:
        rec: dict[str, Any] = {
            "ts": _now(),
            "type": "tool_call",
            "tool": tool,
            "args": args,
            "tool_use_id": tool_use_id,
        }
        if code is not None:
            rec["code"] = code
        if imports_used is not None:
            rec["imports_used"] = imports_used
        self._append(rec)

    def tool_result_ok(
        self,
        tool_use_id: str,
        result_summary: dict,
        *,
        latency_ms: int,
        new_handles: list[str] | None = None,
    ) -> None:
        rec: dict[str, Any] = {
            "ts": _now(),
            "type": "tool_result",
            "tool_use_id": tool_use_id,
            "result_summary": result_summary,
            "is_error": False,
            "latency_ms": latency_ms,
        }
        if new_handles is not None:
            rec["new_handles"] = new_handles
        self._append(rec)

    def tool_result_err(
        self, tool_use_id: str, error: str, traceback: str, *, latency_ms: int
    ) -> None:
        self._append({
            "ts": _now(),
            "type": "tool_result",
            "tool_use_id": tool_use_id,
            "error": error,
            "traceback": traceback,
            "is_error": True,
            "latency_ms": latency_ms,
        })

    def error(self, message: str) -> None:
        self._append({"ts": _now(), "type": "error", "message": message})
```

- [ ] **Step 4: Run tests**

```bash
pytest Tests/agent/test_transcript.py -v
```

Expected: 4 PASS.

- [ ] **Step 5: Commit**

```bash
git add Agents/transcript.py Tests/agent/test_transcript.py
git commit -m "feat(agent): TranscriptWriter with JSONL schema per event"
```

---

## Task 6: Workspace dataclass

**Files:**
- Create: `Agents/workspace.py`
- Test: `Tests/agent/test_workspace.py`

A typed view over a `Workspaces/<name>/` directory.

- [ ] **Step 1: Write the failing test**

`Tests/agent/test_workspace.py`:

```python
import pytest
from Agents.workspace import Workspace


def test_paths_resolve_relative_to_root(tmp_path):
    root = tmp_path / "ABX"
    (root / "inputs").mkdir(parents=True)
    ws = Workspace.open(root)
    assert ws.name == "ABX"
    assert ws.inputs_dir == root / "inputs"
    assert ws.results_dir == root / "results"
    assert ws.agent_log_dir == root / "results" / "agent_log"


def test_open_creates_agent_log_dir(tmp_path):
    root = tmp_path / "ABX"
    root.mkdir()
    ws = Workspace.open(root)
    assert ws.agent_log_dir.is_dir()


def test_missing_root_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        Workspace.open(tmp_path / "nope")
```

- [ ] **Step 2: Verify failure**

```bash
pytest Tests/agent/test_workspace.py -v
```

- [ ] **Step 3: Implement**

`Agents/workspace.py`:

```python
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Workspace:
    root: Path

    @classmethod
    def open(cls, root: Path | str) -> "Workspace":
        root = Path(root)
        if not root.is_dir():
            raise FileNotFoundError(f"Workspace not found: {root}")
        ws = cls(root=root)
        ws.agent_log_dir.mkdir(parents=True, exist_ok=True)
        return ws

    @property
    def name(self) -> str:
        return self.root.name

    @property
    def inputs_dir(self) -> Path:
        return self.root / "inputs"

    @property
    def results_dir(self) -> Path:
        return self.root / "results"

    @property
    def agent_log_dir(self) -> Path:
        return self.results_dir / "agent_log"
```

- [ ] **Step 4: Run tests**

```bash
pytest Tests/agent/test_workspace.py -v
```

Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add Agents/workspace.py Tests/agent/test_workspace.py
git commit -m "feat(agent): Workspace dataclass with canonical paths"
```

---

## Task 7: Session

**Files:**
- Create: `Agents/session.py`
- Test: `Tests/agent/test_session.py`

Composes workspace, variable store, message list, and transcript.

- [ ] **Step 1: Write the failing test**

`Tests/agent/test_session.py`:

```python
import json
import pandas as pd
from Agents.workspace import Workspace
from Agents.session import Session


def test_session_creates_transcript_in_workspace(tmp_path):
    root = tmp_path / "ABX"
    root.mkdir()
    ws = Workspace.open(root)
    sess = Session.start(ws)
    assert sess.workspace is ws
    assert sess.transcript.path.parent == ws.agent_log_dir
    assert sess.transcript.path.suffix == ".jsonl"
    assert sess.messages == []


def test_session_put_and_get_handle(tmp_path):
    root = tmp_path / "ABX"; root.mkdir()
    ws = Workspace.open(root)
    sess = Session.start(ws)
    h = sess.variables.put(pd.DataFrame({"x": [1]}), hint="df")
    assert h == "df_1"
    assert sess.variables.get(h) is not None


def test_session_id_is_transcript_stem(tmp_path):
    root = tmp_path / "ABX"; root.mkdir()
    ws = Workspace.open(root)
    sess = Session.start(ws)
    assert sess.id == sess.transcript.path.stem
```

- [ ] **Step 2: Verify failure**

```bash
pytest Tests/agent/test_session.py -v
```

- [ ] **Step 3: Implement**

`Agents/session.py`:

```python
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
import uuid

from Agents.workspace import Workspace
from Agents.variable_store import VariableStore
from Agents.transcript import TranscriptWriter


@dataclass
class Session:
    workspace: Workspace
    variables: VariableStore
    transcript: TranscriptWriter
    messages: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def start(cls, workspace: Workspace) -> "Session":
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        sid = f"{stamp}-{uuid.uuid4().hex[:6]}"
        path = workspace.agent_log_dir / f"{sid}.jsonl"
        return cls(
            workspace=workspace,
            variables=VariableStore(),
            transcript=TranscriptWriter(path),
        )

    @property
    def id(self) -> str:
        return self.transcript.path.stem
```

- [ ] **Step 4: Run tests**

```bash
pytest Tests/agent/test_session.py -v
```

Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add Agents/session.py Tests/agent/test_session.py
git commit -m "feat(agent): Session composing workspace + store + transcript"
```

---

## Task 8: Event types

**Files:**
- Create: `Agents/events.py`
- Test: `Tests/agent/test_events.py`

- [ ] **Step 1: Write the failing test**

`Tests/agent/test_events.py`:

```python
from Agents.events import Event


def test_event_factories():
    assert Event.user("hi").type == "user"
    assert Event.assistant_final("done").type == "assistant_final"
    tc = Event.tool_call("foo", {"a": 1})
    assert tc.type == "tool_call" and tc.payload["tool"] == "foo"
    tr = Event.tool_result("foo", {"type": "DataFrame"})
    assert tr.type == "tool_result"
    assert Event.error("nope").type == "error"
```

- [ ] **Step 2: Verify failure**

```bash
pytest Tests/agent/test_events.py -v
```

- [ ] **Step 3: Implement**

`Agents/events.py`:

```python
from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Literal

EventType = Literal["user", "assistant_final", "tool_call", "tool_result", "error"]


@dataclass(frozen=True)
class Event:
    type: EventType
    payload: dict[str, Any]

    @classmethod
    def user(cls, content: str) -> "Event":
        return cls("user", {"content": content})

    @classmethod
    def assistant_final(cls, content: str) -> "Event":
        return cls("assistant_final", {"content": content})

    @classmethod
    def tool_call(cls, tool: str, args: dict) -> "Event":
        return cls("tool_call", {"tool": tool, "args": args})

    @classmethod
    def tool_result(cls, tool: str, summary: dict, is_error: bool = False) -> "Event":
        return cls("tool_result", {"tool": tool, "summary": summary, "is_error": is_error})

    @classmethod
    def error(cls, message: str) -> "Event":
        return cls("error", {"message": message})
```

- [ ] **Step 4: Run tests**

```bash
pytest Tests/agent/test_events.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add Agents/events.py Tests/agent/test_events.py
git commit -m "feat(agent): Event dataclass and factories"
```

---

## Task 9: `@tool` decorator and registry

**Files:**
- Create: `Agents/tools/registry.py`
- Test: `Tests/agent/test_registry.py`

The decorator inspects type hints, builds a Pydantic v2 model for argument validation, and stores the tool with its Anthropic-shaped JSON schema. Tools that need session declare `session: Session` as the first parameter; the registry strips it from the schema and injects it at execution time.

- [ ] **Step 1: Write the failing test**

`Tests/agent/test_registry.py`:

```python
import pytest
from typing import Literal
from Agents.tools.registry import tool, Registry
from Agents.handle import Handle
from Agents.session import Session
from Agents.workspace import Workspace


@pytest.fixture
def session(tmp_path):
    root = tmp_path / "ws"; root.mkdir()
    return Session.start(Workspace.open(root))


def test_tool_schema_omits_session_param(session):
    reg = Registry()

    @reg.tool
    def adder(session: Session, x: int, y: int = 1) -> int:
        """Add two integers."""
        return x + y

    schema = reg.schemas()[0]
    assert schema["name"] == "adder"
    assert schema["description"].startswith("Add two integers")
    assert set(schema["input_schema"]["properties"]) == {"x", "y"}
    assert schema["input_schema"]["required"] == ["x"]


def test_tool_schema_for_handle_param(session):
    reg = Registry()

    @reg.tool
    def use_df(session: Session, df: Handle[int]) -> int:
        """Use it."""
        return 0

    prop = reg.schemas()[0]["input_schema"]["properties"]["df"]
    assert prop["type"] == "string"
    assert "handle" in prop["description"].lower()


def test_execute_validates_args(session):
    reg = Registry()

    @reg.tool
    def adder(session: Session, x: int) -> int:
        """Add."""
        return x + 1

    res = reg.execute(session, "adder", {"x": "not an int"})
    assert res.is_error
    assert "x" in res.error


def test_execute_resolves_handle(session):
    reg = Registry()

    @reg.tool
    def double(session: Session, h: Handle[int]) -> int:
        """Double."""
        return session.variables.get(h) * 2

    h = session.variables.put(21, hint="n")
    res = reg.execute(session, "double", {"h": h})
    assert not res.is_error
    assert res.value == 42


def test_execute_missing_handle_errors(session):
    reg = Registry()

    @reg.tool
    def passer(session: Session, h: Handle[int]) -> int:
        """Pass."""
        return 0

    res = reg.execute(session, "passer", {"h": "n_99"})
    assert res.is_error
    assert "n_99" in res.error


def test_execute_captures_exception(session):
    reg = Registry()

    @reg.tool
    def boom(session: Session) -> int:
        """Boom."""
        raise RuntimeError("kaboom")

    res = reg.execute(session, "boom", {})
    assert res.is_error
    assert "kaboom" in res.error
    assert "Traceback" in res.traceback


def test_unknown_tool_errors(session):
    reg = Registry()
    res = reg.execute(session, "nope", {})
    assert res.is_error
    assert "unknown tool" in res.error.lower()
```

- [ ] **Step 2: Verify failure**

```bash
pytest Tests/agent/test_registry.py -v
```

- [ ] **Step 3: Implement**

`Agents/tools/registry.py`:

```python
from __future__ import annotations
import inspect
import time
import traceback
from dataclasses import dataclass
from typing import Any, Callable, get_type_hints
from pydantic import ValidationError, create_model

from Agents.handle import unwrap_handle_arg
from Agents.session import Session


@dataclass
class ToolResult:
    is_error: bool
    value: Any = None
    summary: dict | None = None
    error: str | None = None
    traceback: str | None = None
    latency_ms: int = 0


@dataclass
class _Tool:
    name: str
    fn: Callable
    schema: dict
    arg_model: type  # Pydantic model
    handle_params: dict[str, type]  # param name -> wrapped type


class Registry:
    def __init__(self) -> None:
        self._tools: dict[str, _Tool] = {}

    def tool(self, fn: Callable) -> Callable:
        spec = inspect.signature(fn)
        hints = get_type_hints(fn, include_extras=True)
        fields: dict[str, tuple] = {}
        properties: dict[str, dict] = {}
        required: list[str] = []
        handle_params: dict[str, type] = {}

        for pname, param in spec.parameters.items():
            if pname == "session":
                continue
            ann = hints.get(pname, Any)
            wrapped = unwrap_handle_arg(ann)
            if wrapped is not None:
                handle_params[pname] = wrapped
                properties[pname] = {
                    "type": "string",
                    "description": f"handle to a {wrapped.__name__}",
                }
                fields[pname] = (str, ... if param.default is inspect.Parameter.empty else param.default)
            else:
                properties[pname] = _json_schema_for(ann)
                if param.default is inspect.Parameter.empty:
                    fields[pname] = (ann, ...)
                else:
                    fields[pname] = (ann, param.default)
            if param.default is inspect.Parameter.empty:
                required.append(pname)

        arg_model = create_model(f"{fn.__name__}_Args", **fields)  # type: ignore[arg-type]
        doc = (fn.__doc__ or "").strip()
        schema = {
            "name": fn.__name__,
            "description": doc,
            "input_schema": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        }
        self._tools[fn.__name__] = _Tool(
            name=fn.__name__, fn=fn, schema=schema, arg_model=arg_model,
            handle_params=handle_params,
        )
        return fn

    def schemas(self) -> list[dict]:
        return [t.schema for t in self._tools.values()]

    def execute(self, session: Session, name: str, raw_input: dict) -> ToolResult:
        t0 = time.perf_counter()
        if name not in self._tools:
            return ToolResult(
                is_error=True,
                error=f"unknown tool: {name}",
                latency_ms=int((time.perf_counter() - t0) * 1000),
            )
        t = self._tools[name]
        try:
            validated = t.arg_model(**raw_input)
        except ValidationError as e:
            return ToolResult(
                is_error=True,
                error=str(e),
                latency_ms=int((time.perf_counter() - t0) * 1000),
            )

        kwargs = validated.model_dump()
        for pname in t.handle_params:
            handle = kwargs[pname]
            if handle not in session.variables:
                return ToolResult(
                    is_error=True,
                    error=(
                        f"Handle {handle!r} not found for arg {pname!r}. "
                        f"Available: {sorted(session.variables.list_handles())}"
                    ),
                    latency_ms=int((time.perf_counter() - t0) * 1000),
                )

        try:
            value = t.fn(session, **kwargs)
        except Exception as e:
            return ToolResult(
                is_error=True,
                error=str(e),
                traceback=traceback.format_exc(),
                latency_ms=int((time.perf_counter() - t0) * 1000),
            )

        summary = value if isinstance(value, dict) else {"value": _to_jsonable(value)}
        return ToolResult(
            is_error=False, value=value, summary=summary,
            latency_ms=int((time.perf_counter() - t0) * 1000),
        )


_PRIMITIVE_SCHEMA = {
    int: {"type": "integer"},
    float: {"type": "number"},
    str: {"type": "string"},
    bool: {"type": "boolean"},
}


def _json_schema_for(annotation) -> dict:
    from typing import get_origin, get_args, Literal
    if annotation in _PRIMITIVE_SCHEMA:
        return _PRIMITIVE_SCHEMA[annotation]
    if get_origin(annotation) is Literal:
        return {"type": "string", "enum": list(get_args(annotation))}
    return {"type": "string"}


def _to_jsonable(v: Any) -> Any:
    if isinstance(v, (str, int, float, bool, type(None))):
        return v
    if isinstance(v, (list, tuple)):
        return [_to_jsonable(x) for x in v]
    if isinstance(v, dict):
        return {str(k): _to_jsonable(x) for k, x in v.items()}
    return repr(v)[:200]
```

- [ ] **Step 4: Run tests**

```bash
pytest Tests/agent/test_registry.py -v
```

Expected: 7 PASS.

- [ ] **Step 5: Commit**

```bash
git add Agents/tools/registry.py Tests/agent/test_registry.py
git commit -m "feat(agent): @tool decorator with schema gen and execution wrapper"
```

---

## Task 10: Metadata tools

**Files:**
- Create: `Agents/tools/metadata_tools.py`
- Test: `Tests/agent/test_metadata_tools.py`

Wraps `askslm.metadata` 1:1. Functions register on a module-level `metadata_registry: Registry`; later we merge registries into a single one.

- [ ] **Step 1: Write the failing test**

`Tests/agent/test_metadata_tools.py`:

```python
import pandas as pd
from Agents.workspace import Workspace
from Agents.session import Session
from Agents.tools.metadata_tools import metadata_registry


def _write_csv(path, df):
    df.to_csv(path, index=False)


def test_extract_metadata_returns_handle(tmp_path):
    root = tmp_path / "ws"; (root / "inputs").mkdir(parents=True)
    csv = root / "inputs" / "metadata.csv"
    _write_csv(csv, pd.DataFrame({"acc": ["S1", "S2"], "group": ["a", "b"]}))
    sess = Session.start(Workspace.open(root))

    res = metadata_registry.execute(sess, "extract_metadata", {"path": str(csv)})
    assert not res.is_error, res.error
    h = res.summary["handle"]
    md = sess.variables.get(h)
    assert "acc" in md.df.columns


def test_metadata_overview_takes_handle(tmp_path):
    root = tmp_path / "ws"; (root / "inputs").mkdir(parents=True)
    csv = root / "inputs" / "metadata.csv"
    _write_csv(csv, pd.DataFrame({"acc": ["S1"], "group": ["a"]}))
    sess = Session.start(Workspace.open(root))

    r1 = metadata_registry.execute(sess, "extract_metadata", {"path": str(csv)})
    md_handle = r1.summary["handle"]
    r2 = metadata_registry.execute(sess, "metadata_overview", {"metadata": md_handle})
    assert not r2.is_error, r2.error
    assert r2.summary["type"] == "MetadataOverview"
```

- [ ] **Step 2: Verify failure**

```bash
pytest Tests/agent/test_metadata_tools.py -v
```

- [ ] **Step 3: Implement**

`Agents/tools/metadata_tools.py`:

```python
from __future__ import annotations
from pathlib import Path

import askslm.metadata as md_api
from Engines.MetadataEngine.metadata import Metadata
from Common.contracts.metadata_results import MetadataOverview

from Agents.handle import Handle
from Agents.session import Session
from Agents.tools.registry import Registry

metadata_registry = Registry()


@metadata_registry.tool
def extract_metadata(session: Session, path: str) -> dict:
    """Read a metadata CSV and expand jattr/attributes blobs into real columns.
    Returns a handle to a Metadata object."""
    df = md_api.extract(Path(path))
    obj = Metadata(df=df)
    handle = session.variables.put(obj, hint="meta")
    return session.variables.summary(handle)


@metadata_registry.tool
def metadata_overview(session: Session, metadata: Handle[Metadata]) -> dict:
    """Compute a per-column overview (coverage, top values) for a Metadata handle.
    Returns a handle to a MetadataOverview."""
    md = session.variables.get(metadata)
    overview = md_api.overview(md.df)
    handle = session.variables.put(overview, hint="meta_overview")
    return session.variables.summary(handle)
```

- [ ] **Step 4: Run tests**

```bash
pytest Tests/agent/test_metadata_tools.py -v
```

Expected: 2 PASS.

- [ ] **Step 5: Commit**

```bash
git add Agents/tools/metadata_tools.py Tests/agent/test_metadata_tools.py
git commit -m "feat(agent): metadata tools (extract_metadata, metadata_overview)"
```

---

## Task 11: Taxonomy tools

**Files:**
- Create: `Agents/tools/taxonomy_tools.py`
- Test: `Tests/agent/test_taxonomy_tools.py`

- [ ] **Step 1: Write the failing test**

`Tests/agent/test_taxonomy_tools.py`:

```python
import pandas as pd
from Agents.workspace import Workspace
from Agents.session import Session
from Agents.tools.taxonomy_tools import taxonomy_registry
from Agents.tools.metadata_tools import metadata_registry


# A small taxonomy CSV fixture lives under Tests/agent/fixtures/. For the plan,
# generate it inline.

def _make_tax_csv(path):
    pd.DataFrame({
        "acc": ["S1", "S1", "S2", "S2"],
        "tax_id": [816, 562, 816, 1280],
        "total_count": [10, 5, 7, 12],
    }).to_csv(path, index=False)


def _make_meta_csv(path):
    pd.DataFrame({"acc": ["S1", "S2"], "group": ["a", "b"]}).to_csv(path, index=False)


def test_load_resolve_build_matrix_cohort_chain(tmp_path):
    root = tmp_path / "ws"; (root / "inputs").mkdir(parents=True)
    tax = root / "inputs" / "taxonomy.csv"; _make_tax_csv(tax)
    meta = root / "inputs" / "metadata.csv"; _make_meta_csv(meta)
    sess = Session.start(Workspace.open(root))

    r = taxonomy_registry.execute(sess, "load_taxonomy", {"path": str(tax)})
    assert not r.is_error
    tax_h = r.summary["handle"]

    r = taxonomy_registry.execute(sess, "resolve_taxonomy", {"taxonomy": tax_h})
    assert not r.is_error
    resolved_h = r.summary["handle"]

    r = taxonomy_registry.execute(
        sess, "build_abundance_matrix",
        {"taxonomy": resolved_h, "rank": "genus"},
    )
    assert not r.is_error
    matrix_h = r.summary["handle"]

    r = metadata_registry.execute(sess, "extract_metadata", {"path": str(meta)})
    md_h = r.summary["handle"]

    r = taxonomy_registry.execute(
        sess, "build_cohort", {"matrix": matrix_h, "metadata": md_h},
    )
    assert not r.is_error
    assert r.summary["type"] == "Cohort"
```

- [ ] **Step 2: Verify failure**

```bash
pytest Tests/agent/test_taxonomy_tools.py -v
```

- [ ] **Step 3: Implement**

`Agents/tools/taxonomy_tools.py`:

```python
from __future__ import annotations
from pathlib import Path
from typing import Literal

import askslm.taxonomy as tx_api
from Engines.TaxonomyEngine.abundance_matrix import AbundanceMatrix
from Engines.MetadataEngine.metadata import Metadata
from Common.contracts.taxonomy_results import ResolvedTaxonomy

from Agents.handle import Handle
from Agents.session import Session
from Agents.tools.registry import Registry

taxonomy_registry = Registry()

Rank = Literal["superkingdom", "phylum", "class", "order", "family", "genus", "species"]


@taxonomy_registry.tool
def load_taxonomy(session: Session, path: str) -> dict:
    """Load a taxonomy CSV (acc, tax_id, total_count) into a DataFrame handle."""
    df = tx_api.load(Path(path))
    h = session.variables.put(df, hint="tax")
    return session.variables.summary(h)


@taxonomy_registry.tool
def resolve_taxonomy(session: Session, taxonomy: Handle[object]) -> dict:
    """Resolve deprecated NCBI tax_ids in a taxonomy DataFrame against merged.dmp.
    Returns a handle to a ResolvedTaxonomy."""
    df = session.variables.get(taxonomy)
    resolved = tx_api.resolve(df)
    h = session.variables.put(resolved, hint="resolved_tax")
    return session.variables.summary(h)


@taxonomy_registry.tool
def build_abundance_matrix(
    session: Session,
    taxonomy: Handle[ResolvedTaxonomy],
    rank: Rank = "genus",
) -> dict:
    """Build a single-rank abundance matrix from a ResolvedTaxonomy handle.
    Returns a handle to an AbundanceMatrix."""
    resolved = session.variables.get(taxonomy)
    matrix = tx_api.build_abundance_matrix(resolved.df, rank=rank)
    h = session.variables.put(matrix, hint="matrix")
    return session.variables.summary(h)


@taxonomy_registry.tool
def build_cohort(
    session: Session,
    matrix: Handle[AbundanceMatrix],
    metadata: Handle[Metadata],
) -> dict:
    """Pair an AbundanceMatrix handle with a Metadata handle into a Cohort handle."""
    m = session.variables.get(matrix)
    md = session.variables.get(metadata)
    cohort = tx_api.build_cohort(m, md)
    h = session.variables.put(cohort, hint="cohort")
    return session.variables.summary(h)
```

- [ ] **Step 4: Run tests**

```bash
pytest Tests/agent/test_taxonomy_tools.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add Agents/tools/taxonomy_tools.py Tests/agent/test_taxonomy_tools.py
git commit -m "feat(agent): taxonomy tools (load/resolve/build_matrix/build_cohort)"
```

---

## Task 12: Session-API tools (summarize, list_workspace_inputs)

**Files:**
- Create: `Agents/tools/session_tools.py`
- Test: `Tests/agent/test_session_tools.py`

- [ ] **Step 1: Write the failing test**

`Tests/agent/test_session_tools.py`:

```python
import pandas as pd
from Agents.workspace import Workspace
from Agents.session import Session
from Agents.tools.session_tools import session_registry


def test_summarize_returns_handle_summary(tmp_path):
    root = tmp_path / "ws"; root.mkdir()
    sess = Session.start(Workspace.open(root))
    h = sess.variables.put(pd.DataFrame({"x": [1]}), hint="df")

    r = session_registry.execute(sess, "summarize", {"handle": h})
    assert not r.is_error
    assert r.summary["handle"] == h
    assert r.summary["type"] == "DataFrame"


def test_list_workspace_inputs_lists_files(tmp_path):
    root = tmp_path / "ws"; (root / "inputs").mkdir(parents=True)
    (root / "inputs" / "metadata.csv").write_text("acc\nS1\n")
    (root / "inputs" / "taxonomy.csv").write_text("acc,tax_id\nS1,1\n")
    sess = Session.start(Workspace.open(root))

    r = session_registry.execute(sess, "list_workspace_inputs", {})
    assert not r.is_error
    names = {f["name"] for f in r.summary["value"]}
    assert {"metadata.csv", "taxonomy.csv"} <= names
```

- [ ] **Step 2: Verify failure**

```bash
pytest Tests/agent/test_session_tools.py -v
```

- [ ] **Step 3: Implement**

`Agents/tools/session_tools.py`:

```python
from __future__ import annotations
from Agents.session import Session
from Agents.tools.registry import Registry

session_registry = Registry()


@session_registry.tool
def summarize(session: Session, handle: str) -> dict:
    """Return the summary of a stored handle (does not modify state)."""
    return session.variables.summary(handle)


@session_registry.tool
def list_workspace_inputs(session: Session) -> dict:
    """List input files available in the current workspace's inputs/ directory."""
    out = []
    if session.workspace.inputs_dir.exists():
        for p in sorted(session.workspace.inputs_dir.rglob("*")):
            if p.is_file():
                out.append({
                    "name": p.name,
                    "relative_path": str(p.relative_to(session.workspace.inputs_dir)),
                    "size_bytes": p.stat().st_size,
                })
    return {"value": out}
```

- [ ] **Step 4: Run tests**

```bash
pytest Tests/agent/test_session_tools.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add Agents/tools/session_tools.py Tests/agent/test_session_tools.py
git commit -m "feat(agent): session tools (summarize, list_workspace_inputs)"
```

---

## Task 13: `run_python` sandbox worker

**Files:**
- Create: `Agents/tools/_sandbox_worker.py`

The worker is the subprocess entrypoint. It reads a pickled `{"handles": {...}, "code": "..."}` payload from stdin, exec's the code with the handles loaded into globals plus the curated whitelist pre-imported, and writes a pickled response (`{"stdout", "new_handles", "error", "traceback"}`) to stdout. Tested via integration in the next task.

- [ ] **Step 1: Implement the worker**

`Agents/tools/_sandbox_worker.py`:

```python
"""Subprocess entrypoint for run_python. Reads pickled stdin, writes pickled stdout."""
from __future__ import annotations
import io
import os
import pickle
import sys
import traceback
from contextlib import redirect_stdout, redirect_stderr

WHITELIST_IMPORTS = ("pandas", "numpy", "scipy", "skbio")
RECOGNIZED_TYPE_PATHS = (
    "Engines.MetadataEngine.metadata.Metadata",
    "Engines.TaxonomyEngine.abundance_matrix.AbundanceMatrix",
    "Engines.TaxonomyEngine.cohort.Cohort",
    "Common.contracts.taxonomy_results.ResolvedTaxonomy",
    "Common.contracts.metadata_results.MetadataOverview",
    "pandas.core.frame.DataFrame",
)


def _resolve_types() -> tuple[type, ...]:
    out: list[type] = []
    for path in RECOGNIZED_TYPE_PATHS:
        mod_name, _, cls_name = path.rpartition(".")
        try:
            mod = __import__(mod_name, fromlist=[cls_name])
            out.append(getattr(mod, cls_name))
        except Exception:
            pass
    return tuple(out)


def _build_namespace(workspace_path: str, handles: dict) -> dict:
    ns: dict = {}
    import askslm  # noqa: F401
    ns["askslm"] = askslm
    for mod_name in WHITELIST_IMPORTS:
        try:
            ns[mod_name] = __import__(mod_name)
        except ImportError:
            pass
    os.chdir(workspace_path)
    ns.update(handles)
    return ns


def main() -> None:
    payload = pickle.load(sys.stdin.buffer)
    code: str = payload["code"]
    workspace_path: str = payload["workspace_path"]
    handles: dict = payload["handles"]

    ns = _build_namespace(workspace_path, handles)
    stdout_buf = io.StringIO()
    stderr_buf = io.StringIO()
    recognized = _resolve_types()

    error = None
    tb = None
    try:
        with redirect_stdout(stdout_buf), redirect_stderr(stderr_buf):
            exec(compile(code, "<run_python>", "exec"), ns)
    except Exception as e:
        error = repr(e)
        tb = traceback.format_exc()

    new_handles: dict = {}
    if error is None:
        existing = set(handles)
        for name, val in ns.items():
            if name.startswith("_") or name in existing:
                continue
            if isinstance(val, recognized):
                new_handles[name] = val

    response = {
        "stdout": stdout_buf.getvalue() + stderr_buf.getvalue(),
        "new_handles": new_handles,
        "error": error,
        "traceback": tb,
    }
    sys.stdout.buffer.write(pickle.dumps(response))
    sys.stdout.buffer.flush()


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Smoke-test the worker manually**

```bash
python -c "
import pickle, subprocess
payload = pickle.dumps({'code':'x = 1+1\nprint(x)','workspace_path':'.','handles':{}})
r = subprocess.run(['python','-m','Agents.tools._sandbox_worker'], input=payload, capture_output=True, timeout=10)
print(pickle.loads(r.stdout))
"
```

Expected output contains `'stdout': '2\n'` and `'new_handles': {}`.

- [ ] **Step 3: Commit**

```bash
git add Agents/tools/_sandbox_worker.py
git commit -m "feat(agent): sandbox subprocess worker for run_python"
```

---

## Task 14: `run_python` tool

**Files:**
- Create: `Agents/tools/run_python.py`
- Test: `Tests/agent/test_run_python.py`

The `@tool` function pickles handles into the subprocess, enforces a timeout, parses imports from the snippet AST, and re-registers returned handles in the session's variable store. Returns `{"stdout", "new_handles", "imports_used"}` or an error.

- [ ] **Step 1: Write the failing test**

`Tests/agent/test_run_python.py`:

```python
import pandas as pd
import pytest
from Agents.workspace import Workspace
from Agents.session import Session
from Agents.tools.run_python import run_python_registry


def test_basic_arithmetic(tmp_path):
    root = tmp_path / "ws"; root.mkdir()
    sess = Session.start(Workspace.open(root))
    r = run_python_registry.execute(sess, "run_python", {"code": "print(1+1)"})
    assert not r.is_error, r.error
    assert "2" in r.summary["stdout"]
    assert r.summary["new_handles"] == []
    assert r.summary["imports_used"] == []


def test_handle_roundtrip_creates_new_handle(tmp_path):
    root = tmp_path / "ws"; root.mkdir()
    sess = Session.start(Workspace.open(root))
    h = sess.variables.put(pd.DataFrame({"x": [1, 2, 3]}), hint="df")
    code = f"out = {h}.assign(y=lambda d: d.x*2)"
    r = run_python_registry.execute(sess, "run_python", {"code": code})
    assert not r.is_error, r.error
    assert r.summary["new_handles"]
    new_handle = r.summary["new_handles"][0]
    assert sess.variables.get(new_handle)["y"].tolist() == [2, 4, 6]


def test_imports_used_extracted(tmp_path):
    root = tmp_path / "ws"; root.mkdir()
    sess = Session.start(Workspace.open(root))
    code = "import numpy\nfrom scipy import stats\nprint(numpy.array([1,2]).sum())"
    r = run_python_registry.execute(sess, "run_python", {"code": code})
    assert not r.is_error, r.error
    assert set(r.summary["imports_used"]) >= {"numpy", "scipy"}


def test_exception_is_captured(tmp_path):
    root = tmp_path / "ws"; root.mkdir()
    sess = Session.start(Workspace.open(root))
    r = run_python_registry.execute(sess, "run_python", {"code": "raise ValueError('nope')"})
    assert r.is_error
    assert "nope" in r.error


def test_timeout(tmp_path):
    root = tmp_path / "ws"; root.mkdir()
    sess = Session.start(Workspace.open(root))
    r = run_python_registry.execute(
        sess, "run_python", {"code": "import time; time.sleep(5)", "timeout_s": 1},
    )
    assert r.is_error
    assert "timeout" in r.error.lower()
```

- [ ] **Step 2: Verify failure**

```bash
pytest Tests/agent/test_run_python.py -v
```

- [ ] **Step 3: Implement**

`Agents/tools/run_python.py`:

```python
from __future__ import annotations
import ast
import pickle
import subprocess
import sys

from Agents.session import Session
from Agents.tools.registry import Registry

run_python_registry = Registry()

DEFAULT_TIMEOUT_S = 60
MAX_TIMEOUT_S = 300


def _extract_imports(code: str) -> list[str]:
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return []
    mods: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for n in node.names:
                mods.add(n.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                mods.add(node.module.split(".")[0])
    return sorted(mods)


@run_python_registry.tool
def run_python(session: Session, code: str, timeout_s: int = DEFAULT_TIMEOUT_S) -> dict:
    """Execute a Python snippet in a sandboxed subprocess. Existing handles
    (variable names like meta_1, matrix_1) are pre-loaded into the namespace.
    New top-level variables that are recognized domain objects (Metadata,
    AbundanceMatrix, Cohort, ResolvedTaxonomy, DataFrame) become new handles."""
    timeout_s = max(1, min(int(timeout_s), MAX_TIMEOUT_S))
    imports_used = _extract_imports(code)

    payload = pickle.dumps({
        "code": code,
        "workspace_path": str(session.workspace.root),
        "handles": {h: session.variables.get(h) for h in session.variables.list_handles()},
    })

    try:
        proc = subprocess.run(
            [sys.executable, "-m", "Agents.tools._sandbox_worker"],
            input=payload,
            capture_output=True,
            timeout=timeout_s,
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"run_python timeout after {timeout_s}s")

    if proc.returncode != 0 or not proc.stdout:
        raise RuntimeError(
            f"sandbox worker failed (rc={proc.returncode}): {proc.stderr.decode(errors='replace')[:500]}"
        )

    response = pickle.loads(proc.stdout)
    if response["error"]:
        raise RuntimeError(response["error"] + "\n" + (response["traceback"] or ""))

    new_handles: list[str] = []
    for var_name, obj in response["new_handles"].items():
        # Use the user's variable name as the hint so handles read naturally.
        h = session.variables.put(obj, hint=var_name)
        new_handles.append(h)

    return {
        "stdout": response["stdout"][-4000:],  # cap for LLM context
        "new_handles": new_handles,
        "imports_used": imports_used,
    }
```

- [ ] **Step 4: Run tests**

```bash
pytest Tests/agent/test_run_python.py -v
```

Expected: 5 PASS. (The timeout test is the slowest at ~1s.)

- [ ] **Step 5: Commit**

```bash
git add Agents/tools/run_python.py Tests/agent/test_run_python.py
git commit -m "feat(agent): run_python tool with sandboxed subprocess and handle round-trip"
```

---

## Task 15: Compose tool registry

**Files:**
- Modify: `Agents/tools/__init__.py`
- Test: append to `Tests/agent/test_registry.py`

Build a single `default_registry` that merges the four per-tool registries (metadata, taxonomy, session, run_python).

- [ ] **Step 1: Write the failing test**

Append to `Tests/agent/test_registry.py`:

```python
def test_default_registry_includes_all_tools():
    from Agents.tools import default_registry
    names = {s["name"] for s in default_registry.schemas()}
    assert names >= {
        "extract_metadata", "metadata_overview",
        "load_taxonomy", "resolve_taxonomy", "build_abundance_matrix", "build_cohort",
        "summarize", "list_workspace_inputs",
        "run_python",
    }
```

- [ ] **Step 2: Verify failure**

```bash
pytest Tests/agent/test_registry.py::test_default_registry_includes_all_tools -v
```

- [ ] **Step 3: Implement**

`Agents/tools/__init__.py`:

```python
from __future__ import annotations
from Agents.tools.registry import Registry
from Agents.tools.metadata_tools import metadata_registry
from Agents.tools.taxonomy_tools import taxonomy_registry
from Agents.tools.session_tools import session_registry
from Agents.tools.run_python import run_python_registry


def _merge(*regs: Registry) -> Registry:
    merged = Registry()
    for r in regs:
        for name, tool in r._tools.items():  # noqa: SLF001
            merged._tools[name] = tool        # noqa: SLF001
    return merged


default_registry: Registry = _merge(
    metadata_registry, taxonomy_registry, session_registry, run_python_registry,
)

__all__ = ["default_registry"]
```

- [ ] **Step 4: Run tests**

```bash
pytest Tests/agent/test_registry.py -v
```

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add Agents/tools/__init__.py Tests/agent/test_registry.py
git commit -m "feat(agent): compose default tool registry"
```

---

## Task 16: LLMClient interface + FakeLLMClient

**Files:**
- Create: `Agents/llm_client.py`
- Test: `Tests/agent/test_fake_llm.py`

A normalized response shape (`LLMResponse`) so the loop never touches the Anthropic types directly.

- [ ] **Step 1: Write the failing test**

`Tests/agent/test_fake_llm.py`:

```python
from Agents.llm_client import FakeLLMClient, ToolUse, AssistantText


def test_fake_returns_scripted_responses_in_order():
    fake = FakeLLMClient(responses=[
        [ToolUse(id="u1", name="extract_metadata", input={"path": "m.csv"})],
        [AssistantText(text="done")],
    ])
    r1 = fake.complete(messages=[], tools=[], system="")
    assert r1.tool_uses[0].name == "extract_metadata"
    assert not r1.is_final
    r2 = fake.complete(messages=[], tools=[], system="")
    assert r2.is_final
    assert r2.text == "done"
```

- [ ] **Step 2: Verify failure**

```bash
pytest Tests/agent/test_fake_llm.py -v
```

- [ ] **Step 3: Implement**

`Agents/llm_client.py`:

```python
from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ToolUse:
    id: str
    name: str
    input: dict


@dataclass(frozen=True)
class AssistantText:
    text: str


@dataclass(frozen=True)
class LLMResponse:
    text: str = ""
    tool_uses: list[ToolUse] = field(default_factory=list)
    raw_content: list[Any] = field(default_factory=list)

    @property
    def is_final(self) -> bool:
        return not self.tool_uses


class LLMClient(ABC):
    @abstractmethod
    def complete(self, messages: list[dict], tools: list[dict], system: str) -> LLMResponse: ...


class FakeLLMClient(LLMClient):
    """Returns scripted responses in order. Each script item is a list of
    ToolUse/AssistantText blocks representing one assistant turn."""

    def __init__(self, responses: list[list]) -> None:
        self._responses = list(responses)
        self._i = 0

    def complete(self, messages, tools, system) -> LLMResponse:
        blocks = self._responses[self._i]
        self._i += 1
        tool_uses = [b for b in blocks if isinstance(b, ToolUse)]
        text = "".join(b.text for b in blocks if isinstance(b, AssistantText))
        return LLMResponse(text=text, tool_uses=tool_uses, raw_content=list(blocks))
```

- [ ] **Step 4: Run tests**

```bash
pytest Tests/agent/test_fake_llm.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add Agents/llm_client.py Tests/agent/test_fake_llm.py
git commit -m "feat(agent): LLMClient interface + FakeLLMClient for tests"
```

---

## Task 17: AnthropicClient

**Files:**
- Modify: `Agents/llm_client.py` — append `AnthropicClient`
- Test: `Tests/agent/test_anthropic_client.py`

Wrap the Anthropic SDK. Translate `messages` already in Anthropic's role/content shape (the loop maintains them that way). Tests mock the SDK so they run offline.

- [ ] **Step 1: Write the failing test**

`Tests/agent/test_anthropic_client.py`:

```python
from unittest.mock import MagicMock
from Agents.llm_client import AnthropicClient


def test_anthropic_client_parses_tool_use(monkeypatch):
    fake_msg = MagicMock()
    fake_msg.content = [
        MagicMock(type="text", text="thinking..."),
        MagicMock(type="tool_use", id="u1", name="adder", input={"x": 1}),
    ]
    fake_client = MagicMock()
    fake_client.messages.create.return_value = fake_msg

    import Agents.llm_client as m
    monkeypatch.setattr(m, "_anthropic_client", lambda: fake_client)

    client = AnthropicClient(model="claude-test")
    resp = client.complete(messages=[{"role": "user", "content": "hi"}], tools=[], system="sys")

    assert len(resp.tool_uses) == 1
    assert resp.tool_uses[0].name == "adder"
    assert resp.text == "thinking..."
    fake_client.messages.create.assert_called_once()
```

- [ ] **Step 2: Verify failure**

```bash
pytest Tests/agent/test_anthropic_client.py -v
```

- [ ] **Step 3: Implement**

Append to `Agents/llm_client.py`:

```python
import os
from functools import lru_cache


@lru_cache(maxsize=1)
def _anthropic_client():
    import anthropic
    return anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])


class AnthropicClient(LLMClient):
    def __init__(self, model: str = "claude-opus-4-7", max_tokens: int = 4096) -> None:
        self.model = model
        self.max_tokens = max_tokens

    def complete(self, messages, tools, system) -> LLMResponse:
        msg = _anthropic_client().messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            system=system,
            tools=tools,
            messages=messages,
        )
        text_parts: list[str] = []
        tool_uses: list[ToolUse] = []
        for block in msg.content:
            if getattr(block, "type", None) == "text":
                text_parts.append(block.text)
            elif getattr(block, "type", None) == "tool_use":
                tool_uses.append(ToolUse(id=block.id, name=block.name, input=dict(block.input)))
        return LLMResponse(text="".join(text_parts), tool_uses=tool_uses, raw_content=list(msg.content))
```

- [ ] **Step 4: Run tests**

```bash
pytest Tests/agent/test_anthropic_client.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add Agents/llm_client.py Tests/agent/test_anthropic_client.py
git commit -m "feat(agent): AnthropicClient wrapping the Anthropic SDK"
```

---

## Task 18: ReAct loop

**Files:**
- Create: `Agents/loop.py`
- Test: `Tests/agent/test_loop.py`

Implements the generator from spec §7. Tested entirely with `FakeLLMClient`.

- [ ] **Step 1: Write the failing test**

`Tests/agent/test_loop.py`:

```python
import pandas as pd
from Agents.workspace import Workspace
from Agents.session import Session
from Agents.llm_client import FakeLLMClient, ToolUse, AssistantText
from Agents.loop import run
from Agents.tools import default_registry


def _sess(tmp_path):
    root = tmp_path / "ws"; (root / "inputs").mkdir(parents=True)
    return Session.start(Workspace.open(root))


def test_loop_executes_tool_and_returns_final_answer(tmp_path):
    sess = _sess(tmp_path)
    csv = sess.workspace.inputs_dir / "metadata.csv"
    pd.DataFrame({"acc": ["S1"], "g": ["a"]}).to_csv(csv, index=False)

    fake = FakeLLMClient(responses=[
        [ToolUse(id="u1", name="extract_metadata", input={"path": str(csv)})],
        [AssistantText(text="Loaded the metadata.")],
    ])
    events = list(run(sess, fake, default_registry, user_message="load it"))
    types = [e.type for e in events]
    assert types == ["user", "tool_call", "tool_result", "assistant_final"]
    assert events[-1].payload["content"] == "Loaded the metadata."


def test_loop_recovers_from_bad_args(tmp_path):
    sess = _sess(tmp_path)
    fake = FakeLLMClient(responses=[
        [ToolUse(id="u1", name="extract_metadata", input={"path": 123})],     # bad type
        [ToolUse(id="u2", name="extract_metadata", input={"path": "no.csv"})],  # bad file
        [AssistantText(text="Sorry, the file doesn't exist.")],
    ])
    events = list(run(sess, fake, default_registry, user_message="load it"))
    assert events[-1].type == "assistant_final"
    error_results = [e for e in events if e.type == "tool_result" and e.payload["is_error"]]
    assert len(error_results) == 2


def test_loop_step_limit(tmp_path, monkeypatch):
    sess = _sess(tmp_path)
    import Agents.loop as loop_mod
    monkeypatch.setattr(loop_mod, "MAX_STEPS", 2)
    fake = FakeLLMClient(responses=[
        [ToolUse(id=f"u{i}", name="list_workspace_inputs", input={})] for i in range(5)
    ])
    events = list(run(sess, fake, default_registry, user_message="loop"))
    assert events[-1].type == "error"
```

- [ ] **Step 2: Verify failure**

```bash
pytest Tests/agent/test_loop.py -v
```

- [ ] **Step 3: Implement**

`Agents/loop.py`:

```python
from __future__ import annotations
from typing import Iterator

from Agents.events import Event
from Agents.session import Session
from Agents.llm_client import LLMClient
from Agents.tools.registry import Registry

MAX_STEPS = 20

SYSTEM_PROMPT = (
    "You are Ask-SLM, an agent that helps researchers analyze SRA microbiome data.\n"
    "Workspace: {workspace}.\n"
    "You drive a fixed set of Python tools that wrap the askslm API. Prefer named "
    "tools; use run_python for novel analyses (third-party libs, ad-hoc dataframe "
    "work). When a tool returns a handle, pass that handle to subsequent tools. "
    "Be concise."
)


def run(
    session: Session,
    llm: LLMClient,
    registry: Registry,
    *,
    user_message: str,
) -> Iterator[Event]:
    session.transcript.user(user_message)
    session.messages.append({"role": "user", "content": user_message})
    yield Event.user(user_message)

    for _ in range(MAX_STEPS):
        response = llm.complete(
            messages=session.messages,
            tools=registry.schemas(),
            system=SYSTEM_PROMPT.format(workspace=session.workspace.name),
        )

        # Record raw assistant turn (Anthropic-shaped content) for the next round.
        anthropic_content = _to_anthropic_assistant_content(response)
        session.messages.append({"role": "assistant", "content": anthropic_content})
        if response.text:
            session.transcript.assistant(response.text)

        if response.is_final:
            yield Event.assistant_final(response.text)
            return

        tool_results_payload = []
        for tu in response.tool_uses:
            yield Event.tool_call(tu.name, tu.input)
            # transcript: tool_call (extra fields for run_python)
            extras = {}
            if tu.name == "run_python":
                from Agents.tools.run_python import _extract_imports
                code = tu.input.get("code", "")
                extras = {"code": code, "imports_used": _extract_imports(code)}
            session.transcript.tool_call(tu.name, tu.input, tool_use_id=tu.id, **extras)

            result = registry.execute(session, tu.name, tu.input)

            if result.is_error:
                session.transcript.tool_result_err(
                    tu.id, result.error or "", result.traceback or "",
                    latency_ms=result.latency_ms,
                )
                yield Event.tool_result(
                    tu.name, {"error": result.error}, is_error=True,
                )
                tool_results_payload.append({
                    "type": "tool_result",
                    "tool_use_id": tu.id,
                    "is_error": True,
                    "content": result.error or "error",
                })
            else:
                new_handles = result.summary.get("new_handles") if isinstance(result.summary, dict) else None
                session.transcript.tool_result_ok(
                    tu.id, result.summary or {}, latency_ms=result.latency_ms,
                    new_handles=new_handles,
                )
                yield Event.tool_result(tu.name, result.summary or {})
                import json
                tool_results_payload.append({
                    "type": "tool_result",
                    "tool_use_id": tu.id,
                    "content": json.dumps(result.summary or {}),
                })

        session.messages.append({"role": "user", "content": tool_results_payload})

    session.transcript.error("step limit reached")
    yield Event.error("Step limit reached without final answer.")


def _to_anthropic_assistant_content(response) -> list[dict]:
    blocks: list[dict] = []
    if response.text:
        blocks.append({"type": "text", "text": response.text})
    for tu in response.tool_uses:
        blocks.append({"type": "tool_use", "id": tu.id, "name": tu.name, "input": tu.input})
    return blocks
```

- [ ] **Step 4: Run tests**

```bash
pytest Tests/agent/test_loop.py -v
```

Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add Agents/loop.py Tests/agent/test_loop.py
git commit -m "feat(agent): ReAct loop with tool execution, error recovery, step limit"
```

---

## Task 19: Agent facade + integration test

**Files:**
- Create: `Agents/agent.py`
- Modify: `Agents/__init__.py` — export `Agent`, `Session`
- Test: `Tests/agent/integration/__init__.py`, `Tests/agent/integration/test_full_flow.py`

- [ ] **Step 1: Write the failing integration test**

`Tests/agent/integration/__init__.py`: empty.

`Tests/agent/integration/test_full_flow.py`:

```python
import pandas as pd
from Agents.agent import Agent
from Agents.workspace import Workspace
from Agents.llm_client import FakeLLMClient, ToolUse, AssistantText


def test_full_pipeline_with_scripted_llm(tmp_path):
    root = tmp_path / "ABX"; (root / "inputs").mkdir(parents=True)
    pd.DataFrame({"acc": ["S1","S2"], "g": ["a","b"]}).to_csv(root / "inputs" / "metadata.csv", index=False)
    pd.DataFrame({
        "acc": ["S1","S1","S2","S2"],
        "tax_id": [816, 562, 816, 1280],
        "total_count": [10, 5, 7, 12],
    }).to_csv(root / "inputs" / "taxonomy.csv", index=False)

    ws = Workspace.open(root)
    fake = FakeLLMClient(responses=[
        [ToolUse(id="u1", name="extract_metadata", input={"path": str(root / "inputs" / "metadata.csv")})],
        [ToolUse(id="u2", name="load_taxonomy",     input={"path": str(root / "inputs" / "taxonomy.csv")})],
        [ToolUse(id="u3", name="resolve_taxonomy",  input={"taxonomy": "tax_1"})],
        [ToolUse(id="u4", name="build_abundance_matrix", input={"taxonomy": "resolved_tax_1", "rank": "genus"})],
        [ToolUse(id="u5", name="build_cohort", input={"matrix": "matrix_1", "metadata": "meta_1"})],
        [AssistantText(text="Cohort built.")],
    ])
    agent = Agent(workspace=ws, llm=fake)
    events = list(agent.chat("build a genus cohort"))
    assert events[-1].type == "assistant_final"
    assert "cohort_1" in agent.session.variables.list_handles()


def test_run_python_produces_handle_for_skbio_distance(tmp_path):
    pytest_skip = False
    try:
        import skbio  # noqa: F401
    except ImportError:
        import pytest; pytest.skip("scikit-bio not installed")

    root = tmp_path / "ABX"; (root / "inputs").mkdir(parents=True)
    pd.DataFrame({"acc": ["S1","S2"], "g": ["a","b"]}).to_csv(root / "inputs" / "metadata.csv", index=False)
    pd.DataFrame({
        "acc": ["S1","S1","S2","S2"],
        "tax_id": [816, 562, 816, 1280],
        "total_count": [10, 5, 7, 12],
    }).to_csv(root / "inputs" / "taxonomy.csv", index=False)
    ws = Workspace.open(root)

    code = (
        "from skbio.diversity import beta_diversity\n"
        "df = matrix_1.counts\n"
        "bray = beta_diversity('braycurtis', df.values, ids=list(df.index))\n"
        "bray_df = pd.DataFrame(bray.data, index=bray.ids, columns=bray.ids)\n"
    )
    fake = FakeLLMClient(responses=[
        [ToolUse(id="u1", name="load_taxonomy",            input={"path": str(root / "inputs" / "taxonomy.csv")})],
        [ToolUse(id="u2", name="resolve_taxonomy",         input={"taxonomy": "tax_1"})],
        [ToolUse(id="u3", name="build_abundance_matrix",   input={"taxonomy": "resolved_tax_1", "rank": "genus"})],
        [ToolUse(id="u4", name="run_python",               input={"code": code})],
        [AssistantText(text="Computed Bray-Curtis.")],
    ])
    agent = Agent(workspace=ws, llm=fake)
    events = list(agent.chat("compute bray-curtis"))
    assert events[-1].type == "assistant_final"
    handles = agent.session.variables.list_handles()
    assert any(h.startswith("bray_df") for h in handles)
```

- [ ] **Step 2: Verify failure**

```bash
pytest Tests/agent/integration -v
```

- [ ] **Step 3: Implement**

`Agents/agent.py`:

```python
from __future__ import annotations
from typing import Iterator

from Agents.workspace import Workspace
from Agents.session import Session
from Agents.events import Event
from Agents.llm_client import LLMClient
from Agents.tools import default_registry
from Agents.tools.registry import Registry
from Agents.loop import run


class Agent:
    def __init__(
        self,
        workspace: Workspace,
        llm: LLMClient,
        registry: Registry = default_registry,
    ) -> None:
        self.session = Session.start(workspace)
        self.llm = llm
        self.registry = registry

    def chat(self, message: str) -> Iterator[Event]:
        yield from run(self.session, self.llm, self.registry, user_message=message)
```

`Agents/__init__.py`:

```python
from Agents.agent import Agent
from Agents.session import Session
from Agents.workspace import Workspace

__all__ = ["Agent", "Session", "Workspace"]
```

- [ ] **Step 4: Run tests**

```bash
pytest Tests/agent/integration -v
pytest Tests/agent -q  # full agent suite must still pass
```

Expected: PASS (second test SKIPs if scikit-bio missing).

- [ ] **Step 5: Commit**

```bash
git add Agents/agent.py Agents/__init__.py Tests/agent/integration
git commit -m "feat(agent): Agent facade + full-pipeline integration tests"
```

---

## Task 20: FastAPI app + SSE

**Files:**
- Create: `Web/__init__.py`
- Create: `Web/app.py`
- Create: `Web/sessions_index.py`
- Test: `Tests/web/test_app.py`

Routes:
- `GET /` — workspace picker (lists `Workspaces/*`).
- `GET /w/{workspace}` — chat page for that workspace; creates a new in-memory `Agent` session.
- `POST /w/{workspace}/messages` — SSE stream of agent events for a user message.
- `GET /w/{workspace}/sessions` — list past transcripts.
- `GET /w/{workspace}/sessions/{session_id}` — replay a past transcript.

We hold per-workspace agent sessions in a module-level dict keyed by `(workspace_name, browser_session_cookie)`. Cookie auto-created on first GET. Tests use `httpx` against the FastAPI app without a real browser.

- [ ] **Step 1: Write the failing test**

`Tests/web/test_app.py`:

```python
import pandas as pd
from fastapi.testclient import TestClient


def _ws(tmp_path):
    root = tmp_path / "ABX"; (root / "inputs").mkdir(parents=True)
    pd.DataFrame({"acc": ["S1"]}).to_csv(root / "inputs" / "metadata.csv", index=False)
    return root


def test_index_lists_workspaces(tmp_path, monkeypatch):
    from Web import app as app_mod
    monkeypatch.setattr(app_mod, "WORKSPACES_ROOT", tmp_path)
    _ws(tmp_path)
    client = TestClient(app_mod.app)
    r = client.get("/")
    assert r.status_code == 200
    assert "ABX" in r.text


def test_chat_page_renders(tmp_path, monkeypatch):
    from Web import app as app_mod
    monkeypatch.setattr(app_mod, "WORKSPACES_ROOT", tmp_path)
    _ws(tmp_path)
    client = TestClient(app_mod.app)
    r = client.get("/w/ABX")
    assert r.status_code == 200
    assert "ABX" in r.text


def test_sse_streams_events_with_fake_llm(tmp_path, monkeypatch):
    from Web import app as app_mod
    from Agents.llm_client import FakeLLMClient, AssistantText
    monkeypatch.setattr(app_mod, "WORKSPACES_ROOT", tmp_path)
    monkeypatch.setattr(app_mod, "build_llm", lambda: FakeLLMClient([[AssistantText(text="hi")]]))
    _ws(tmp_path)
    client = TestClient(app_mod.app)
    # establish a session cookie
    client.get("/w/ABX")
    r = client.post("/w/ABX/messages", data={"message": "hello"})
    assert r.status_code == 200
    body = r.text
    assert "assistant_final" in body
    assert "hi" in body


def test_sessions_listing_shows_past_transcripts(tmp_path, monkeypatch):
    from Web import app as app_mod
    monkeypatch.setattr(app_mod, "WORKSPACES_ROOT", tmp_path)
    root = _ws(tmp_path)
    (root / "results" / "agent_log").mkdir(parents=True)
    (root / "results" / "agent_log" / "20260526T120000-abc123.jsonl").write_text(
        '{"ts":"2026-05-26T12:00:00Z","type":"user","content":"hi"}\n'
    )
    client = TestClient(app_mod.app)
    r = client.get("/w/ABX/sessions")
    assert r.status_code == 200
    assert "20260526T120000-abc123" in r.text


def test_replay_renders_transcript(tmp_path, monkeypatch):
    from Web import app as app_mod
    monkeypatch.setattr(app_mod, "WORKSPACES_ROOT", tmp_path)
    root = _ws(tmp_path)
    (root / "results" / "agent_log").mkdir(parents=True)
    sid = "20260526T120000-abc123"
    (root / "results" / "agent_log" / f"{sid}.jsonl").write_text(
        '{"ts":"2026-05-26T12:00:00Z","type":"user","content":"hi"}\n'
        '{"ts":"2026-05-26T12:00:01Z","type":"assistant","content":"hello!"}\n'
    )
    client = TestClient(app_mod.app)
    r = client.get(f"/w/ABX/sessions/{sid}")
    assert r.status_code == 200
    assert "hi" in r.text and "hello!" in r.text
```

- [ ] **Step 2: Verify failure**

```bash
pytest Tests/web -v
```

- [ ] **Step 3: Implement sessions index**

`Web/sessions_index.py`:

```python
from __future__ import annotations
import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SessionEntry:
    id: str
    path: Path
    title: str


def list_sessions(agent_log_dir: Path) -> list[SessionEntry]:
    if not agent_log_dir.is_dir():
        return []
    entries: list[SessionEntry] = []
    for p in sorted(agent_log_dir.glob("*.jsonl"), reverse=True):
        title = _first_user_message(p) or p.stem
        entries.append(SessionEntry(id=p.stem, path=p, title=title))
    return entries


def _first_user_message(path: Path) -> str | None:
    try:
        for line in path.read_text().splitlines():
            rec = json.loads(line)
            if rec.get("type") == "user":
                return str(rec.get("content", ""))[:120]
    except Exception:
        return None
    return None


def load_transcript(path: Path) -> list[dict]:
    return [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
```

- [ ] **Step 4: Implement the app**

`Web/__init__.py`: empty.

`Web/app.py`:

```python
from __future__ import annotations
import json
import os
import uuid
from pathlib import Path
from typing import Iterator

from fastapi import FastAPI, Form, Request, Response
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from Agents.agent import Agent
from Agents.workspace import Workspace
from Agents.llm_client import LLMClient, AnthropicClient
from Agents.events import Event
from Web.sessions_index import list_sessions, load_transcript

WORKSPACES_ROOT = Path(os.environ.get("ASKSLM_WORKSPACES", "./Workspaces"))

BASE = Path(__file__).parent
app = FastAPI()
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")
templates = Jinja2Templates(directory=BASE / "templates")

# {(workspace, cookie_session_id): Agent}
_AGENTS: dict[tuple[str, str], Agent] = {}


def build_llm() -> LLMClient:
    return AnthropicClient()


def _cookie_session(request: Request, response: Response) -> str:
    sid = request.cookies.get("askslm_session")
    if not sid:
        sid = uuid.uuid4().hex
        response.set_cookie("askslm_session", sid, httponly=True, samesite="lax")
    return sid


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    if not WORKSPACES_ROOT.is_dir():
        workspaces = []
    else:
        workspaces = sorted([p.name for p in WORKSPACES_ROOT.iterdir() if p.is_dir()])
    return templates.TemplateResponse("index.html", {"request": request, "workspaces": workspaces})


@app.get("/w/{workspace}", response_class=HTMLResponse)
def chat_page(workspace: str, request: Request, response: Response):
    _cookie_session(request, response)
    return templates.TemplateResponse("chat.html", {"request": request, "workspace": workspace})


@app.post("/w/{workspace}/messages")
def messages(workspace: str, request: Request, response: Response, message: str = Form(...)):
    sid = _cookie_session(request, response)
    key = (workspace, sid)
    agent = _AGENTS.get(key)
    if agent is None:
        ws = Workspace.open(WORKSPACES_ROOT / workspace)
        agent = Agent(workspace=ws, llm=build_llm())
        _AGENTS[key] = agent

    def event_stream() -> Iterator[bytes]:
        for ev in agent.chat(message):
            data = json.dumps({"type": ev.type, **ev.payload})
            yield f"event: {ev.type}\ndata: {data}\n\n".encode()
            # also stream rendered HTML fragment for HTMX consumers
            html = templates.get_template("_event.html").render(event=ev)
            yield f"event: html\ndata: {html}\n\n".encode()

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.get("/w/{workspace}/sessions", response_class=HTMLResponse)
def sessions(workspace: str, request: Request):
    ws = Workspace.open(WORKSPACES_ROOT / workspace)
    entries = list_sessions(ws.agent_log_dir)
    return templates.TemplateResponse("sessions.html", {"request": request, "workspace": workspace, "entries": entries})


@app.get("/w/{workspace}/sessions/{session_id}", response_class=HTMLResponse)
def replay(workspace: str, session_id: str, request: Request):
    ws = Workspace.open(WORKSPACES_ROOT / workspace)
    path = ws.agent_log_dir / f"{session_id}.jsonl"
    records = load_transcript(path)
    return templates.TemplateResponse("replay.html", {"request": request, "workspace": workspace, "records": records})
```

- [ ] **Step 5: Stub the templates and static so tests pass**

Create directories and minimal templates:

`Web/templates/index.html`:

```html
<!doctype html><html><body>
<h1>Ask-SLM</h1>
<ul>{% for w in workspaces %}<li><a href="/w/{{w}}">{{w}}</a></li>{% endfor %}</ul>
</body></html>
```

`Web/templates/chat.html`:

```html
<!doctype html><html><body>
<h1>{{workspace}}</h1>
<div id="log"></div>
<form hx-post="/w/{{workspace}}/messages" hx-target="#log" hx-swap="beforeend">
  <input name="message" placeholder="Ask..."><button>Send</button>
</form>
<script src="https://unpkg.com/htmx.org@1.9.12"></script>
</body></html>
```

`Web/templates/_event.html`:

```html
<div class="event event-{{event.type}}">
{% if event.type == "user" %}<b>You:</b> {{event.payload.content}}
{% elif event.type == "assistant_final" %}<b>Assistant:</b> {{event.payload.content}}
{% elif event.type == "tool_call" %}<code>{{event.payload.tool}}({{event.payload.args}})</code>
{% elif event.type == "tool_result" %}<pre>{{event.payload.summary}}</pre>
{% elif event.type == "error" %}<span style="color:red">{{event.payload.message}}</span>
{% endif %}
</div>
```

`Web/templates/sessions.html`:

```html
<!doctype html><html><body>
<h1>{{workspace}} — past sessions</h1>
<ul>{% for e in entries %}<li><a href="/w/{{workspace}}/sessions/{{e.id}}">{{e.id}} — {{e.title}}</a></li>{% endfor %}</ul>
</body></html>
```

`Web/templates/replay.html`:

```html
<!doctype html><html><body>
<h1>{{workspace}} — replay</h1>
{% for r in records %}
  {% if r.type == "user" %}<div><b>You:</b> {{r.content}}</div>
  {% elif r.type == "assistant" %}<div><b>Assistant:</b> {{r.content}}</div>
  {% elif r.type == "tool_call" %}<div><code>{{r.tool}}({{r.args}})</code></div>
  {% elif r.type == "tool_result" %}<pre>{{r.result_summary or r.error}}</pre>
  {% elif r.type == "error" %}<div style="color:red">{{r.message}}</div>
  {% endif %}
{% endfor %}
</body></html>
```

Create `Web/static/.gitkeep` (empty).

- [ ] **Step 6: Run tests**

```bash
pytest Tests/web -v
```

Expected: 5 PASS.

- [ ] **Step 7: Smoke-test manually (optional, requires API key)**

```bash
export ANTHROPIC_API_KEY=...
export ASKSLM_WORKSPACES=./Workspaces
uvicorn Web.app:app --reload --port 8000
# Open http://localhost:8000
```

- [ ] **Step 8: Commit**

```bash
git add Web Tests/web
git commit -m "feat(web): FastAPI + HTMX shell with SSE chat and session replay"
```

---

## Task 21: `agent-review` command

**Files:**
- Create: `Agents/review.py`
- Create: `Agents/cli.py`
- Test: `Tests/agent/test_review.py`

Reads all `Workspaces/*/results/agent_log/*.jsonl` and prints two sections:
1. Whitelist candidates — `ModuleNotFoundError` counts by module name + successful-import frequencies.
2. Tool-promotion candidates — recurring `run_python` snippets, clustered by AST normalization, reporting clusters with N≥3.

- [ ] **Step 1: Write the failing test**

`Tests/agent/test_review.py`:

```python
import json
from Agents.review import analyze, format_report


def _write_jsonl(path, records):
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n")


def test_counts_module_not_found_errors(tmp_path):
    log = tmp_path / "ws" / "results" / "agent_log"
    log.mkdir(parents=True)
    _write_jsonl(log / "s1.jsonl", [
        {"type": "tool_result", "tool_use_id": "u1", "is_error": True,
         "error": "ModuleNotFoundError: No module named 'biom'", "traceback": ""},
    ])
    _write_jsonl(log / "s2.jsonl", [
        {"type": "tool_result", "tool_use_id": "u1", "is_error": True,
         "error": "ModuleNotFoundError: No module named 'biom'", "traceback": ""},
        {"type": "tool_result", "tool_use_id": "u2", "is_error": True,
         "error": "ModuleNotFoundError: No module named 'biom'", "traceback": ""},
    ])
    result = analyze(tmp_path)
    assert result.module_not_found["biom"] == 3


def test_counts_successful_imports(tmp_path):
    log = tmp_path / "ws" / "results" / "agent_log"
    log.mkdir(parents=True)
    _write_jsonl(log / "s1.jsonl", [
        {"type": "tool_call", "tool": "run_python", "tool_use_id": "u1",
         "code": "import numpy", "imports_used": ["numpy"]},
        {"type": "tool_result", "tool_use_id": "u1", "is_error": False, "result_summary": {}},
    ])
    result = analyze(tmp_path)
    assert result.imports_used["numpy"] == 1


def test_clusters_recurring_snippets(tmp_path):
    log = tmp_path / "ws" / "results" / "agent_log"
    log.mkdir(parents=True)
    _write_jsonl(log / "s1.jsonl", [
        {"type": "tool_call", "tool": "run_python", "tool_use_id": "u1",
         "code": "x = matrix_1.relative.mean()", "imports_used": []},
    ])
    _write_jsonl(log / "s2.jsonl", [
        {"type": "tool_call", "tool": "run_python", "tool_use_id": "u1",
         "code": "y = matrix_2.relative.mean()", "imports_used": []},
    ])
    _write_jsonl(log / "s3.jsonl", [
        {"type": "tool_call", "tool": "run_python", "tool_use_id": "u1",
         "code": "z = matrix_1.relative.mean()", "imports_used": []},
    ])
    result = analyze(tmp_path)
    clusters = [c for c in result.snippet_clusters if c.count >= 3]
    assert len(clusters) == 1
    assert ".relative.mean()" in clusters[0].representative


def test_format_report_includes_both_sections(tmp_path):
    log = tmp_path / "ws" / "results" / "agent_log"
    log.mkdir(parents=True)
    _write_jsonl(log / "s1.jsonl", [
        {"type": "tool_result", "is_error": True, "tool_use_id":"u",
         "error": "ModuleNotFoundError: No module named 'foo'", "traceback":""},
    ])
    text = format_report(analyze(tmp_path))
    assert "Whitelist candidates" in text
    assert "Tool-promotion candidates" in text
```

- [ ] **Step 2: Verify failure**

```bash
pytest Tests/agent/test_review.py -v
```

- [ ] **Step 3: Implement**

`Agents/review.py`:

```python
from __future__ import annotations
import ast
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

_MNF_RE = re.compile(r"ModuleNotFoundError: No module named ['\"]([^'\"]+)['\"]")


@dataclass
class SnippetCluster:
    key: str
    count: int
    representative: str


@dataclass
class ReviewResult:
    module_not_found: Counter = field(default_factory=Counter)
    imports_used: Counter = field(default_factory=Counter)
    snippet_clusters: list[SnippetCluster] = field(default_factory=list)


def _normalize_snippet(code: str) -> str:
    """Strip literals and identifiers, leaving structure for clustering."""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return code.strip()

    class Normalizer(ast.NodeTransformer):
        def visit_Name(self, node):
            return ast.copy_location(ast.Name(id="_N", ctx=node.ctx), node)
        def visit_Constant(self, node):
            return ast.copy_location(ast.Constant(value="_C"), node)
        def visit_arg(self, node):
            node.arg = "_A"
            return node
    Normalizer().visit(tree)
    return ast.dump(tree, annotate_fields=False)


def analyze(workspaces_root: Path) -> ReviewResult:
    result = ReviewResult()
    snippets_by_key: dict[str, list[str]] = defaultdict(list)
    counts_by_key: Counter = Counter()

    for jsonl in workspaces_root.rglob("agent_log/*.jsonl"):
        for line in jsonl.read_text().splitlines():
            if not line.strip():
                continue
            rec = json.loads(line)
            if rec.get("type") == "tool_result" and rec.get("is_error"):
                m = _MNF_RE.search(rec.get("error") or "")
                if m:
                    result.module_not_found[m.group(1)] += 1
            if rec.get("type") == "tool_call" and rec.get("tool") == "run_python":
                for mod in rec.get("imports_used", []):
                    result.imports_used[mod] += 1
                code = rec.get("code", "")
                key = _normalize_snippet(code)
                counts_by_key[key] += 1
                snippets_by_key[key].append(code)

    for key, count in counts_by_key.most_common():
        rep = snippets_by_key[key][0]
        result.snippet_clusters.append(SnippetCluster(key=key, count=count, representative=rep))
    return result


def format_report(result: ReviewResult) -> str:
    lines: list[str] = []
    lines.append("=== Whitelist candidates ===")
    if result.module_not_found:
        for mod, n in result.module_not_found.most_common():
            mark = "  >> add" if n >= 3 else ""
            lines.append(f"  ModuleNotFoundError({mod}): {n}{mark}")
    else:
        lines.append("  (none)")
    lines.append("")
    lines.append("Successful import frequencies:")
    if result.imports_used:
        for mod, n in result.imports_used.most_common():
            lines.append(f"  {mod}: {n}")
    else:
        lines.append("  (none)")
    lines.append("")
    lines.append("=== Tool-promotion candidates ===")
    promoted = [c for c in result.snippet_clusters if c.count >= 3]
    if promoted:
        for c in promoted:
            lines.append(f"  [{c.count}x] {c.representative.strip()[:200]}")
    else:
        lines.append("  (no clusters with N>=3)")
    return "\n".join(lines)
```

- [ ] **Step 4: Run tests**

```bash
pytest Tests/agent/test_review.py -v
```

Expected: 4 PASS.

- [ ] **Step 5: Commit**

```bash
git add Agents/review.py Tests/agent/test_review.py
git commit -m "feat(agent): agent-review mines transcripts for whitelist and tool promotion"
```

---

## Task 22: `agent-show` + CLI entrypoint

**Files:**
- Create: `Agents/show.py`
- Create: `Agents/cli.py`
- Test: `Tests/agent/test_show.py`

- [ ] **Step 1: Write the failing test**

`Tests/agent/test_show.py`:

```python
import json
from Agents.show import format_session


def test_format_session_renders_chronological(tmp_path):
    log = tmp_path / "s.jsonl"
    log.write_text("\n".join(json.dumps(r) for r in [
        {"ts":"t1","type":"user","content":"hi"},
        {"ts":"t2","type":"tool_call","tool":"foo","args":{"a":1},"tool_use_id":"u1"},
        {"ts":"t3","type":"tool_result","tool_use_id":"u1","is_error":False,"result_summary":{"type":"DataFrame"},"latency_ms":12},
        {"ts":"t4","type":"assistant","content":"ok"},
    ]) + "\n")
    text = format_session(log)
    assert "You: hi" in text
    assert "foo(" in text
    assert "DataFrame" in text
    assert "Assistant: ok" in text
```

- [ ] **Step 2: Verify failure**

```bash
pytest Tests/agent/test_show.py -v
```

- [ ] **Step 3: Implement**

`Agents/show.py`:

```python
from __future__ import annotations
import json
from pathlib import Path


def format_session(path: Path | str) -> str:
    lines: list[str] = []
    for raw in Path(path).read_text().splitlines():
        if not raw.strip():
            continue
        r = json.loads(raw)
        t = r.get("type")
        if t == "user":
            lines.append(f"You: {r.get('content','')}")
        elif t == "assistant":
            lines.append(f"Assistant: {r.get('content','')}")
        elif t == "tool_call":
            lines.append(f"  -> {r.get('tool')}({r.get('args')})")
        elif t == "tool_result":
            if r.get("is_error"):
                lines.append(f"     ! ERROR: {r.get('error','')}")
            else:
                lines.append(f"     = {r.get('result_summary')} ({r.get('latency_ms',0)}ms)")
        elif t == "error":
            lines.append(f"  ! {r.get('message','')}")
    return "\n".join(lines)
```

`Agents/cli.py`:

```python
"""Run as: python -m Agents.cli review|show ..."""
from __future__ import annotations
import argparse
from pathlib import Path

from Agents.review import analyze, format_report
from Agents.show import format_session


def main() -> None:
    parser = argparse.ArgumentParser(prog="agents")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_review = sub.add_parser("review", help="Mine transcripts for whitelist & tool promotion")
    p_review.add_argument("--root", default="./Workspaces", help="Workspaces root directory")

    p_show = sub.add_parser("show", help="Pretty-print one session JSONL")
    p_show.add_argument("path", help="Path to a session .jsonl file")

    args = parser.parse_args()
    if args.cmd == "review":
        print(format_report(analyze(Path(args.root))))
    elif args.cmd == "show":
        print(format_session(args.path))


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests + smoke-test CLI**

```bash
pytest Tests/agent/test_show.py -v
python -m Agents.cli --help
python -m Agents.cli review --root ./Workspaces
```

Expected: tests PASS; CLI prints help; review prints empty sections if no logs yet.

- [ ] **Step 5: Commit**

```bash
git add Agents/show.py Agents/cli.py Tests/agent/test_show.py
git commit -m "feat(agent): agent-show pretty-printer and python -m Agents.cli entrypoint"
```

---

## Task 23: LLM smoke tests (opt-in)

**Files:**
- Create: `Tests/agent/llm_smoke/__init__.py`
- Create: `Tests/agent/llm_smoke/test_trajectories.py`

Tagged `@pytest.mark.llm`, skipped by default (pytest.ini already filters them out).

- [ ] **Step 1: Implement the smoke tests**

`Tests/agent/llm_smoke/__init__.py`: empty.

`Tests/agent/llm_smoke/test_trajectories.py`:

```python
import os
import pandas as pd
import pytest

from Agents.agent import Agent
from Agents.workspace import Workspace
from Agents.llm_client import AnthropicClient

pytestmark = pytest.mark.llm


@pytest.fixture
def workspace(tmp_path):
    root = tmp_path / "ABX"; (root / "inputs").mkdir(parents=True)
    pd.DataFrame({"acc":["S1","S2"],"group":["a","b"]}).to_csv(root/"inputs"/"metadata.csv", index=False)
    return Workspace.open(root)


def _trajectory(events) -> list[str]:
    return [e.payload["tool"] for e in events if e.type == "tool_call"]


def test_metadata_summarization_calls_extract_and_overview(workspace):
    if not os.environ.get("ANTHROPIC_API_KEY"):
        pytest.skip("ANTHROPIC_API_KEY not set")
    agent = Agent(workspace=workspace, llm=AnthropicClient())
    events = list(agent.chat("Summarize the metadata in this workspace."))
    traj = _trajectory(events)
    assert "extract_metadata" in traj
    assert "metadata_overview" in traj
    assert events[-1].type == "assistant_final"


def test_lists_workspace_inputs_when_asked(workspace):
    if not os.environ.get("ANTHROPIC_API_KEY"):
        pytest.skip("ANTHROPIC_API_KEY not set")
    agent = Agent(workspace=workspace, llm=AnthropicClient())
    events = list(agent.chat("What files are in this workspace?"))
    traj = _trajectory(events)
    assert "list_workspace_inputs" in traj
```

- [ ] **Step 2: Verify they are skipped by default**

```bash
pytest Tests/agent -q
```

Expected: smoke tests not selected (filtered by `addopts = -m "not llm"`).

- [ ] **Step 3: Run them manually (optional, costs money)**

```bash
ANTHROPIC_API_KEY=... pytest Tests/agent/llm_smoke -v -m llm
```

- [ ] **Step 4: Commit**

```bash
git add Tests/agent/llm_smoke
git commit -m "test(agent): opt-in LLM smoke trajectories for canonical prompts"
```

---

## Task 24: Final wiring — full suite, .gitignore, README pointer

**Files:**
- Modify: `.gitignore`
- Modify: `README.md`

- [ ] **Step 1: Update .gitignore**

Append:

```
# Agent session transcripts
Workspaces/*/results/agent_log/
```

- [ ] **Step 2: Add README pointer**

Append a section to `README.md`:

```markdown
## Agent

Natural-language access to the Ask-SLM API. See:
- Design: `Docs/superpowers/specs/2026-05-26-agent-orchestrator-design.md`
- Run locally: `ANTHROPIC_API_KEY=... uvicorn Web.app:app --reload`
- Mine transcripts: `python -m Agents.cli review`
- Inspect one session: `python -m Agents.cli show Workspaces/<ws>/results/agent_log/<session>.jsonl`
```

- [ ] **Step 3: Run the full suite**

```bash
pytest Tests -q
```

Expected: all non-LLM tests pass.

- [ ] **Step 4: Commit**

```bash
git add .gitignore README.md
git commit -m "chore(agent): gitignore transcripts and add README pointer"
```

---

## Verification at the end

Final manual checks before declaring v1 ready:

1. **Full suite green:**
   ```bash
   pytest Tests -q
   ```

2. **Web smoke test (real LLM):**
   ```bash
   export ANTHROPIC_API_KEY=...
   uvicorn Web.app:app --reload --port 8000
   ```
   Open http://localhost:8000, pick a workspace, try:
   - "What files are here?"
   - "Summarize the metadata."
   - "Build a genus-level abundance matrix and a cohort."
   - "Compute Bray-Curtis between samples using scikit-bio."

3. **Transcripts exist and `agent-review` runs:**
   ```bash
   ls Workspaces/*/results/agent_log/
   python -m Agents.cli review --root ./Workspaces
   ```

4. **Replay works:** click a past session in the sidebar; rendered transcript matches what you saw live.

---

## Notes for the implementer

- **TDD strictly**: every implementation step is preceded by a failing test. Run the failing test first, confirm the failure mode, then implement.
- **Frequent commits**: one commit per task. The history reads as the plan.
- **Don't import from `Engines/` or `Accessors/` directly outside this plan's allowed list** — use the `askslm.metadata` / `askslm.taxonomy` public API. The summary registry and sandbox worker are deliberate exceptions because they need the concrete domain types for `isinstance` checks.
- **Existing project conventions**: capitalized top-level package folders (`Agents/`, `Web/`, `Tests/`); type hints everywhere; no merged DataFrames between Metadata and Taxonomy domains.
