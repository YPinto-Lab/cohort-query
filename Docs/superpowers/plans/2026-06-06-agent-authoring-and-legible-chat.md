# Agent Authoring & Legible Chat Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the agent durable authoring tools (`write_file` + `run_script`), teach it that `run_python` is stateless, and replace the chat's per-event walls of text with one-line expandable chips.

**Architecture:** Two new workspace-scoped tools land in `session_tools.py` next to the existing read tools. The stateless-execution lesson is documentation only (operating manual + `run_python` docstring). The chat change drops the server's per-event HTML rendering and rebuilds each step client-side as a `<details>` chip from the typed SSE events the loop already emits; the file-changes panel stays server-rendered.

**Tech Stack:** Python 3.14, FastAPI + Jinja2 + htmx (server-sent events), pytest. Spec: `Docs/superpowers/specs/2026-06-06-agent-authoring-and-legible-chat-design.html`.

**Branch:** `feature-legible-agent-authoring` (stacked on PR #9). Do not open a PR until told; the user squash-merges.

---

## File Structure

| File | Responsibility | Change |
|------|----------------|--------|
| `src/agent/tools/session_tools.py` | session-scoped tools | add `write_file`, `run_script`, `_safe_workspace_path` |
| `Tests/agent/test_session_tools.py` | tests for those tools | add write/run tests |
| `Tests/agent/test_registry.py` | default-registry membership | add two tool names |
| `src/agent/operating_manual.md` | the agent's durable briefing | add "How execution works" section |
| `src/agent/tools/run_python.py` | the snippet tool | rewrite docstring to state statelessness |
| `Tests/agent/test_run_python.py` | docstring + manual content lock | new file (2 tests) |
| `src/web/app.py` | SSE event stream | stop streaming per-event HTML; drop `_streams_to_log` |
| `Tests/web/test_app.py` | streaming behavior | replace `_streams_to_log` test; fix html-encoding test |
| `src/web/templates/chat.html` | the chat client | add `renderEvent` + chip CSS; route typed events |
| `src/web/templates/_event.html` | per-event server HTML | delete (no longer used) |

Note: `write_file`/`run_script` register automatically via the `@session_registry.tool` decorator (session_registry is merged into `default_registry` in `tools/__init__.py`), so no wiring change is needed there — only the membership test updates.

---

### Task 1: `write_file` tool

**Files:**
- Modify: `src/agent/tools/session_tools.py`
- Test: `Tests/agent/test_session_tools.py`

- [ ] **Step 1: Write the failing tests**

Add to `Tests/agent/test_session_tools.py` (the `_session` helper already exists there, creating `root = tmp_path / "ws"`):

```python
def test_write_file_creates_file_and_parents(tmp_path):
    sess = _session(tmp_path)
    r = session_registry.execute(
        sess, "write_file", {"path": "1_build/build.py", "content": "print('hi')\n"})
    assert not r.is_error
    written = tmp_path / "ws" / "1_build" / "build.py"
    assert written.read_text() == "print('hi')\n"
    assert r.summary["bytes_written"] == len("print('hi')\n")


def test_write_file_rejects_path_escape(tmp_path):
    sess = _session(tmp_path)
    r = session_registry.execute(
        sess, "write_file", {"path": "../escape.py", "content": "x"})
    assert r.is_error
    assert "escapes" in r.error
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest Tests/agent/test_session_tools.py -k write_file -v`
Expected: FAIL — `unknown tool: write_file` (the registry returns an error result, so `r.is_error` is True but `bytes_written` / the written file are absent → assertions fail).

- [ ] **Step 3: Implement `write_file` and the workspace-path guard**

In `src/agent/tools/session_tools.py`, add the guard helper near `_safe_repo_path` (the `Path` import already exists at the top of the file):

```python
def _safe_workspace_path(session: Session, path: str) -> Path:
    root = session.workspace.root.resolve()
    candidate = (root / path).resolve()
    if not candidate.is_relative_to(root):
        raise ValueError(f"path escapes workspace root: {path}")
    return candidate
```

And add the tool (place it after `read_file`):

```python
@session_registry.tool
def write_file(session: Session, path: str, content: str) -> dict:
    """Write a text file into the current workspace, creating parent directories.
    The path is relative to the workspace root (e.g. "1_build/build.py"). This is
    how you author phase scripts; run them with run_script."""
    target = _safe_workspace_path(session, path)
    target.parent.mkdir(parents=True, exist_ok=True)
    data = content.encode("utf-8")
    target.write_bytes(data)
    return {"path": path, "bytes_written": len(data)}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest Tests/agent/test_session_tools.py -k write_file -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add src/agent/tools/session_tools.py Tests/agent/test_session_tools.py
git commit -m "feat(agent): add workspace-scoped write_file tool"
```

---

### Task 2: `run_script` tool

**Files:**
- Modify: `src/agent/tools/session_tools.py`
- Test: `Tests/agent/test_session_tools.py`

- [ ] **Step 1: Write the failing tests**

Add to `Tests/agent/test_session_tools.py`:

```python
def test_run_script_runs_and_reports_returncode(tmp_path):
    sess = _session(tmp_path)
    session_registry.execute(sess, "write_file", {
        "path": "make.py",
        "content": "open('out.txt','w').write('done')\nprint('ran')\n"})
    r = session_registry.execute(sess, "run_script", {"path": "make.py"})
    assert not r.is_error
    assert r.summary["returncode"] == 0
    assert "ran" in r.summary["stdout"]
    assert (tmp_path / "ws" / "out.txt").read_text() == "done"


def test_run_script_can_import_askslm(tmp_path):
    sess = _session(tmp_path)
    session_registry.execute(sess, "write_file", {
        "path": "imp.py", "content": "import askslm\nprint('ok')\n"})
    r = session_registry.execute(sess, "run_script", {"path": "imp.py"})
    assert not r.is_error
    assert r.summary["returncode"] == 0
    assert "ok" in r.summary["stdout"]


def test_run_script_rejects_non_python(tmp_path):
    sess = _session(tmp_path)
    (tmp_path / "ws" / "data.csv").write_text("a,b\n")
    r = session_registry.execute(sess, "run_script", {"path": "data.csv"})
    assert r.is_error


def test_run_script_rejects_path_outside_workspace(tmp_path):
    sess = _session(tmp_path)
    r = session_registry.execute(sess, "run_script", {"path": "../evil.py"})
    assert r.is_error
    assert "escapes" in r.error
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest Tests/agent/test_session_tools.py -k run_script -v`
Expected: FAIL — `unknown tool: run_script`.

- [ ] **Step 3: Implement `run_script`**

In `src/agent/tools/session_tools.py`, add the standard-library imports at the top (next to `from pathlib import Path`):

```python
import subprocess
import sys
```

Add the caps near the existing `_READ_CAP_BYTES` constant:

```python
_SCRIPT_OUTPUT_CAP = 4000
_SCRIPT_TIMEOUT_S = 300
```

Add the tool after `write_file`:

```python
@session_registry.tool
def run_script(session: Session, path: str) -> dict:
    """Run a Python script that lives in the current workspace as a subprocess,
    returning its exit code and captured output. The path is relative to the
    workspace root and must end in .py. A script's products are files on disk
    (e.g. feature_table.biom) that appear in the workspace, not as handles."""
    target = _safe_workspace_path(session, path)
    if target.suffix != ".py":
        raise ValueError(f"not a Python script: {path}")
    if not target.is_file():
        raise FileNotFoundError(f"script not found: {path}")
    proc = subprocess.run(
        [sys.executable, str(target)], cwd=str(session.workspace.root),
        capture_output=True, text=True, timeout=_SCRIPT_TIMEOUT_S)
    output = (proc.stdout + proc.stderr)[-_SCRIPT_OUTPUT_CAP:]
    return {"path": path, "returncode": proc.returncode, "stdout": output}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest Tests/agent/test_session_tools.py -k run_script -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add src/agent/tools/session_tools.py Tests/agent/test_session_tools.py
git commit -m "feat(agent): add run_script tool for executing workspace phase scripts"
```

---

### Task 3: Register the new tools in the default-registry test

**Files:**
- Modify: `Tests/agent/test_registry.py:104-107`

- [ ] **Step 1: Run the membership test to see it fail**

Run: `python -m pytest Tests/agent/test_registry.py::test_default_registry_includes_all_tools -v`
Expected: FAIL — the actual set now contains `write_file` and `run_script`, which the expected set omits.

- [ ] **Step 2: Update the expected set**

Replace the assertion body at `Tests/agent/test_registry.py:106-107`:

```python
    assert set(default_registry._tools) == {
        "list_workspace_inputs", "run_python", "summarize", "read_file", "list_dir",
        "write_file", "run_script"}
```

- [ ] **Step 3: Run the test to verify it passes**

Run: `python -m pytest Tests/agent/test_registry.py::test_default_registry_includes_all_tools -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add Tests/agent/test_registry.py
git commit -m "test(agent): include write_file/run_script in default-registry set"
```

---

### Task 4: Teach the stateless execution model (#1)

**Files:**
- Modify: `src/agent/operating_manual.md`
- Modify: `src/agent/tools/run_python.py:34-37` (the docstring)
- Test: `Tests/agent/test_run_python.py` (new)

- [ ] **Step 1: Write the failing tests**

Create `Tests/agent/test_run_python.py`:

```python
from pathlib import Path


def test_operating_manual_documents_stateless_execution():
    import agent
    manual = (Path(agent.__file__).parent / "operating_manual.md").read_text()
    assert "fresh subprocess" in manual.lower()
    assert "write_file" in manual and "run_script" in manual


def test_run_python_docstring_warns_about_statelessness():
    from agent.tools.run_python import run_python_registry
    schema = {s["name"]: s for s in run_python_registry.schemas()}["run_python"]
    desc = schema["description"].lower()
    assert "not persist" in desc
    assert "run_script" in desc
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest Tests/agent/test_run_python.py -v`
Expected: FAIL — the manual lacks "fresh subprocess" and the docstring lacks "not persist".

- [ ] **Step 3: Add the manual section**

In `src/agent/operating_manual.md`, insert this section immediately after the `## Phase flow` section (before `## When you need more, read the source`):

```markdown
## How execution works (read before using run_python)
Each `run_python` call runs in a FRESH subprocess. State does NOT persist between calls:
`import` statements and plain variables are gone on the next call. Only recognized domain
objects you create at top level (a `biom.Table`, a `MetadataOverview`, a `DataFrame`) survive,
as *handles* that are pre-loaded by name into later calls. `pandas`, `numpy`, `scipy`, `skbio`,
and `askslm` are pre-imported every call under those names — do not rely on aliases like `pd`.

Use `run_python` only for one-shot inspection (a shape, a dtype, a value). For any multi-step
work — and for everything you want to keep — author a phase script with `write_file` and run it
with `run_script`. The script on disk is the durable artifact; its outputs are files in the
workspace.
```

- [ ] **Step 4: Rewrite the `run_python` docstring**

In `src/agent/tools/run_python.py`, replace the docstring at lines 34-37:

```python
    """Execute a one-shot Python snippet in a fresh sandboxed subprocess.
    State does NOT persist between calls: imports and plain variables vanish
    afterward. Only recognized domain objects created at top level (biom.Table
    feature tables, MetadataOverview, DataFrame) survive as handles, pre-loaded
    by name into later calls. pandas/numpy/scipy/skbio/askslm are pre-imported
    each call. For multi-step or durable work, write a script with write_file
    and run it with run_script instead."""
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python -m pytest Tests/agent/test_run_python.py -v`
Expected: PASS (2 passed)

- [ ] **Step 6: Commit**

```bash
git add src/agent/operating_manual.md src/agent/tools/run_python.py Tests/agent/test_run_python.py
git commit -m "docs(agent): teach run_python statelessness; point to write_file/run_script"
```

---

### Task 5: Stop streaming per-event HTML from the server (#3, server half)

**Files:**
- Modify: `src/web/app.py:17` (drop unused import), `:120-123` (drop `_streams_to_log`), `:137-149` (simplify `event_stream`)
- Test: `Tests/web/test_app.py` (replace one test, fix one test)

- [ ] **Step 1: Update the tests first (they encode the new behavior)**

In `Tests/web/test_app.py`, **delete** the import and test at the bottom of the file (currently lines 292-299):

```python
from web.app import _streams_to_log
from agent.events import Event


def test_user_events_do_not_stream_to_log():
    assert _streams_to_log(Event.user("hi")) is False
    assert _streams_to_log(Event.assistant_final("yo")) is True
    assert _streams_to_log(Event.tool_call("t", {})) is True
```

Replace them with a test that locks the new contract — tool steps stream as typed events, and no per-event HTML block is produced:

```python
def test_tool_events_stream_typed_not_as_html(tmp_path, monkeypatch):
    from web import app as app_mod
    from agent.llm_client import FakeLLMClient, ToolUse, AssistantText
    monkeypatch.setattr(app_mod, "WORKSPACES_ROOT", tmp_path)
    monkeypatch.setattr(app_mod, "build_llm", lambda: FakeLLMClient([
        [ToolUse(id="u1", name="list_workspace_inputs", input={})],
        [AssistantText(text="done")],
    ]))
    _ws(tmp_path)
    client = TestClient(app_mod.app)
    client.get("/w/ABX")
    r = client.post("/w/ABX/messages", data={"message": "go"})
    body = r.text
    assert "event: tool_call" in body
    assert "event: tool_result" in body
    assert "event: assistant_final" in body
    # per-event HTML is retired and no files changed → no html block at all
    assert "event: html" not in body
```

Then fix `test_messages_html_events_are_json_encoded` (currently lines 262-278) — html blocks now appear only when files change, so simulate a file change. Replace the whole function with:

```python
def test_messages_html_events_are_json_encoded(tmp_path, monkeypatch):
    import json as _json
    from web import app as app_mod
    from agent.llm_client import FakeLLMClient, AssistantText
    monkeypatch.setattr(app_mod, "WORKSPACES_ROOT", tmp_path)
    monkeypatch.setattr(app_mod, "build_llm",
                        lambda: FakeLLMClient([[AssistantText(text="hi")]]))
    # one file appears during the turn → the files-changed panel is the lone html block
    snapshots = iter([{}, {"1_build/build.py": 1.0}])
    monkeypatch.setattr(app_mod, "snapshot", lambda _root: next(snapshots))
    _ws(tmp_path)
    client = TestClient(app_mod.app)
    client.get("/w/ABX")
    r = client.post("/w/ABX/messages", data={"message": "hello"})
    html_blocks = [b for b in r.text.split("\n\n") if "event: html" in b]
    assert html_blocks  # the files-changed panel
    for block in html_blocks:
        data_line = [l for l in block.splitlines() if l.startswith("data:")][0]
        payload = _json.loads(data_line[len("data:"):])  # valid single-line JSON
        assert isinstance(payload, str)
```

- [ ] **Step 2: Run the affected tests to verify they fail**

Run: `python -m pytest Tests/web/test_app.py -k "tool_events_stream_typed or html_events_are_json_encoded" -v`
Expected: FAIL — `test_tool_events_stream_typed_not_as_html` fails because the server still emits an `event: html` block per tool event.

- [ ] **Step 3: Simplify `event_stream` and remove `_streams_to_log`**

In `src/web/app.py`, delete the now-unused import at line 17:

```python
from agent.events import Event
```

Delete the helper at lines 120-123:

```python
def _streams_to_log(ev: Event) -> bool:
    # The browser appends the user's own message locally; re-rendering the server's
    # user event would duplicate it in the chat log.
    return ev.type != "user"
```

Replace the `event_stream` body (lines 137-149) so it streams only typed events plus the trailing files panel:

```python
    def event_stream() -> Iterator[bytes]:
        before = snapshot(ws_dir)
        for ev in agent.chat(message):
            data = json.dumps({"type": ev.type, **ev.payload})
            yield f"event: {ev.type}\ndata: {data}\n\n".encode()
        changed = diff(before, snapshot(ws_dir))
        if changed:
            files_html = templates.get_template("_files.html").render(
                workspace=workspace, changed=changed)
            yield f"event: html\ndata: {json.dumps(files_html)}\n\n".encode()
```

- [ ] **Step 4: Run the web suite to verify it passes**

Run: `python -m pytest Tests/web/test_app.py -v`
Expected: PASS (all, including the new typed-events test and the fixed encoding test; `test_sse_streams_events_with_fake_llm` and `test_messages_appends_files_changed_block` still pass unchanged).

- [ ] **Step 5: Commit**

```bash
git add src/web/app.py Tests/web/test_app.py
git commit -m "refactor(web): stream typed events only; drop per-event server HTML"
```

---

### Task 6: Render chips client-side (#3, client half)

**Files:**
- Modify: `src/web/templates/chat.html` (CSS block ~line 42-51; SSE loop ~line 96-100; add render functions in the `<script>`)
- Delete: `src/web/templates/_event.html`

This task is JavaScript + template wiring; it is verified manually in-browser (there is no JS test harness in this repo).

- [ ] **Step 1: Add chip CSS**

In `src/web/templates/chat.html`, replace the now-unused `.event` rule (line 43):

```css
  .event pre,.event code{white-space:pre-wrap;overflow-wrap:anywhere;word-break:break-word}
```

with chip styles:

```css
  .chip{margin:4px 0;font:12px ui-monospace,Menlo,monospace}
  .chip>summary{color:#7d8590;cursor:pointer;list-style:none}
  .chip>summary::-webkit-details-marker{display:none}
  .chip>summary:hover{color:#c9d1d9}
  .chip[open]>summary{color:#c9d1d9}
  .chip pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#161b22;border:1px solid #30363d;border-radius:6px;padding:8px;margin:4px 0 0;color:#c9d1d9}
  .chip.err>summary{color:#ff7b72}
  .asst b{color:#3fb950}
```

- [ ] **Step 2: Route typed events in the SSE loop**

In the `send()` function, replace the single dispatch line (currently line 99):

```javascript
          if(ev==='html' && data){ clearPending(); append(JSON.parse(data)); }
```

with a branch that keeps `html` for the files panel and sends every other typed event to `renderEvent`:

```javascript
          if(!data) continue;
          if(ev==='html'){ clearPending(); append(JSON.parse(data)); }
          else if(ev){ clearPending(); renderEvent(ev, JSON.parse(data)); }
```

- [ ] **Step 3: Add the render functions**

In the `<script>` block of `chat.html`, after the `append` helper (line 79), add:

```javascript
  const VERB={ run_python:'ran code', write_file:'wrote', run_script:'ran',
               read_file:'read', list_dir:'listed', summarize:'summarized',
               list_workspace_inputs:'listed inputs' };
  let lastCall=null;  // remembers the tool_call args so its tool_result chip can show them

  function renderEvent(type, p){
    if(type==='user') return;                                   // already shown locally
    if(type==='tool_call'){ lastCall=p; return; }
    if(type==='tool_result'){ renderToolChip(p); return; }
    if(type==='assistant_final'){ appendText('asst','Assistant: ',p.content); return; }
    if(type==='error'){ appendChip('error',p.message,true); return; }
  }

  function renderToolChip(p){
    const args=(lastCall && lastCall.tool===p.tool) ? lastCall.args : {};
    appendChip(chipLabel(p.tool,args), chipDetail(p.tool,args,p.summary||{}), p.is_error);
    lastCall=null;
  }

  function chipLabel(tool, args){
    if(tool==='write_file'||tool==='run_script'||tool==='read_file'||tool==='list_dir')
      return VERB[tool]+' '+(args.path||'');
    if(tool==='summarize') return 'summarized '+(args.handle||'');
    return VERB[tool]||tool;
  }

  function chipDetail(tool, args, summary){
    if(summary.error) return summary.error;
    if(tool==='run_python') return (args.code||'')+'\n--- output ---\n'+(summary.stdout||'');
    if(tool==='run_script') return summary.stdout||'';
    return JSON.stringify(summary, null, 2);
  }

  function appendChip(label, detail, isError){
    const d=document.createElement('details'); d.className='chip'+(isError?' err':'');
    const s=document.createElement('summary'); s.textContent='· '+label; d.appendChild(s);
    if(detail){ const pre=document.createElement('pre'); pre.textContent=detail; d.appendChild(pre); }
    log.appendChild(d); log.scrollTop=log.scrollHeight;
  }

  function appendText(cls, label, text){
    const d=document.createElement('div'); d.className=cls;
    const b=document.createElement('b'); b.textContent=label;
    d.appendChild(b); d.appendChild(document.createTextNode(text||''));
    log.appendChild(d); log.scrollTop=log.scrollHeight;
  }
```

- [ ] **Step 4: Delete the dead per-event template**

```bash
git rm src/web/templates/_event.html
```

- [ ] **Step 5: Manual in-browser verification**

Run: `python -m uvicorn web.app:app --reload --app-dir src` (or the project's usual start command), open a workspace, and send a message that triggers tools. Verify:
- each tool step shows as one quiet line (e.g. `· ran code`, `· wrote 1_build/build.py`), not a wall of text;
- clicking a chip expands its detail (code+output for `run_python`, stdout for `run_script`, JSON summary otherwise);
- an errored tool result renders the chip in red with the error message inside;
- the assistant's final reply renders as a normal "Assistant: …" line;
- the "⋯ agent is working…" pending row appears after sending and disappears when the first chip/reply arrives;
- when a build writes a `.biom`, the files-changed panel still appears (the one remaining server-rendered html block) and its open/view pills still work.

- [ ] **Step 6: Commit**

```bash
git add src/web/templates/chat.html
git commit -m "feat(web): render tool steps as expandable chips from typed events"
```

---

### Task 7: Full-suite gate

**Files:** none (verification only)

- [ ] **Step 1: Run the whole test suite**

Run: `python -m pytest -q`
Expected: PASS (the prior 141 baseline plus the new tests; no regressions).

- [ ] **Step 2: Stop**

Do not open a PR. Report status to the user; this branch is stacked on PR #9 and the user decides when to retarget/merge.

---

## Notes on scope (from the spec, §7 — not in this plan)

- Raising `MAX_STEPS` or caching repeated reads (#2/#6) — defer; measure step count after authoring tools land first.
- Non-canonical workspace trees, e.g. `inputs/` vs `0_inputs/` (#5) — separate design.
- A persistent Python kernel — explicitly rejected; scripts are the durable path.
- Token-by-token streaming of the final prose — unchanged, out of scope.
