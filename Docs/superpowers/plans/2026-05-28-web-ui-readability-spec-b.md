# Web UI Readability (Spec B) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the local chat shell readable: clear visual turn separation, monospace + syntax-highlighted code blocks, auto-scroll behavior, server-rendered markdown for assistant text, a single shared event-rendering partial used by both the live stream and replay, and clickable `written_to` artifact links to a new read-only file endpoint.

**Architecture:** Server-side rendering throughout. Four Jinja filters (`markdown`, `as_pretty_json`, `highlight`, `format_tool_args`) registered on the `Web/app.py` Jinja2 environment. One canonical event partial (`_event.html`) used by both the live SSE stream and the replay view; replay converts each JSONL record into an Event-shaped dict via a small `record_to_event` helper, then renders through the same partial. A vanilla CSS file at `Web/static/chat.css` provides all styling. A new endpoint `GET /w/<ws>/files/<relpath>` serves workspace files read-only with path-traversal protection.

**Tech Stack:** FastAPI + Jinja2 (existing), `markdown-it-py` (new), `Pygments` (new), vanilla CSS. No CDN, no JS framework, no build step.

**Spec reference:** `Docs/superpowers/specs/2026-05-28-web-ui-readability-spec-b-design.md`

**Parallel-safety:** Touches only `Web/` and `Docs/requirements.txt`. Fully independent of the `agent-state-awareness` and `abundance-matrix-refactor` branches.

---

## File Structure

**Create:**
- `Web/static/chat.css` — single stylesheet (~150 lines)
- `Web/templates/chat_base.html` — shared chrome
- `Web/filters.py` — the four Jinja filters as standalone functions
- `Web/records.py` — `record_to_event` helper

**Modify:**
- `Docs/requirements.txt` — add `markdown-it-py` and `Pygments`
- `Web/app.py` — register filters; add `/w/<ws>/files/<relpath>` endpoint; replay endpoint converts records via `record_to_event`
- `Web/templates/_event.html` — rewritten to new structure
- `Web/templates/chat.html` — reduce to a thin shell over `chat_base.html`; add scroll JS
- `Web/templates/replay.html` — reduce to iterating records through `_event.html`
- `Web/templates/index.html` — apply `chat.css`
- `Web/templates/sessions.html` — apply `chat.css`
- `Tests/web/test_app.py` — extend with new test cases

---

## Task 1: Add dependencies and the empty stylesheet scaffold

**Files:**
- Modify: `Docs/requirements.txt`
- Create: `Web/static/chat.css`

- [ ] **Step 1: Add the two pip deps**

Edit `Docs/requirements.txt`, append two lines:

```
markdown-it-py>=3.0
Pygments>=2.17
```

- [ ] **Step 2: Install them**

Run: `pip install -r Docs/requirements.txt`
Expected: both packages installed; existing packages already satisfied.

- [ ] **Step 3: Create an empty stylesheet placeholder**

Write the full final stylesheet to `Web/static/chat.css`:

```css
:root {
  --bg: #fafafa;
  --bg-user: #eef4ff;
  --bg-assistant: #f5f5f5;
  --bg-tool: #fbfbfb;
  --border: #d8d8d8;
  --border-strong: #b5b5b5;
  --text: #1f2328;
  --text-muted: #6a6f76;
  --link: #0a66c2;
  --error: #b3261e;
  --code-bg: #f6f8fa;
  --pill-user: #1f6feb;
  --pill-assistant: #2da44e;
  --pill-tool: #6a737d;
}

body {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
  color: var(--text);
  background: var(--bg);
  margin: 0;
  display: flex;
  flex-direction: column;
  height: 100vh;
}

h1 {
  margin: 0;
  padding: 0.75rem 1rem;
  border-bottom: 1px solid var(--border);
  font-size: 1.1rem;
  font-weight: 600;
}

#log {
  flex: 1;
  overflow-y: auto;
  padding: 1rem;
}

form {
  display: flex;
  gap: 0.5rem;
  padding: 0.75rem 1rem;
  border-top: 1px solid var(--border);
  background: white;
}
form input {
  flex: 1;
  padding: 0.5rem 0.75rem;
  border: 1px solid var(--border);
  border-radius: 6px;
  font-size: 0.95rem;
}
form button {
  padding: 0.5rem 1rem;
  border: 1px solid var(--border-strong);
  background: white;
  border-radius: 6px;
  cursor: pointer;
}

.event {
  margin: 0.75rem 0;
  padding: 0.75rem 1rem;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: white;
}

.event-user { background: var(--bg-user); }
.event-assistant_final { background: var(--bg-assistant); }
.event-tool_call,
.event-tool_result {
  background: var(--bg-tool);
  font-size: 0.9rem;
}
.event-tool_call { border-bottom: none; border-bottom-left-radius: 0; border-bottom-right-radius: 0; margin-bottom: 0; }
.event-tool_result { border-top-left-radius: 0; border-top-right-radius: 0; margin-top: 0; }

.role-pill {
  display: inline-block;
  font-size: 0.7rem;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  padding: 0.1rem 0.5rem;
  border-radius: 999px;
  color: white;
  margin-right: 0.5rem;
}
.role-user { background: var(--pill-user); }
.role-assistant { background: var(--pill-assistant); }
.role-tool { background: var(--pill-tool); font-family: ui-monospace, monospace; text-transform: none; }

.text { display: block; margin-top: 0.25rem; line-height: 1.5; }
.text p:first-child { margin-top: 0; }
.text p:last-child { margin-bottom: 0; }
.text code { background: var(--code-bg); padding: 0.1rem 0.3rem; border-radius: 3px; font-family: ui-monospace, monospace; font-size: 0.9em; }

.code {
  background: var(--code-bg);
  padding: 0.5rem 0.75rem;
  border-radius: 6px;
  overflow-x: auto;
  font-family: ui-monospace, "SF Mono", Menlo, monospace;
  font-size: 0.85rem;
  line-height: 1.45;
  margin: 0.4rem 0 0 0;
}

.written-to {
  display: inline-block;
  margin-bottom: 0.4rem;
  color: var(--link);
  text-decoration: none;
  font-family: ui-monospace, monospace;
  font-size: 0.85rem;
}
.written-to::before { content: "📄 "; }
.written-to:hover { text-decoration: underline; }

.is-error { border-left: 4px solid var(--error); padding-left: 0.75rem; }
.error-banner {
  background: #fdecea;
  color: var(--error);
  padding: 0.5rem 0.75rem;
  border-radius: 6px;
  border: 1px solid var(--error);
}

/* Pygments token colors (subset of "default" style) */
.hl .k  { color: #cf222e; }                /* keyword */
.hl .s, .hl .s1, .hl .s2 { color: #0a3069; } /* string */
.hl .mi, .hl .mf { color: #0550ae; }       /* number */
.hl .nb { color: #8250df; }                /* builtin */
.hl .c1, .hl .c, .hl .cm { color: #6e7781; font-style: italic; } /* comment */
.hl .nt { color: #116329; }                /* JSON key */
.hl .p  { color: #1f2328; }                /* punctuation */
```

- [ ] **Step 4: Commit**

```bash
git add Docs/requirements.txt Web/static/chat.css
git commit -m "feat(web): add markdown-it-py + Pygments deps; ship chat.css"
```

---

## Task 2: Implement and test the Jinja filters

**Files:**
- Create: `Web/filters.py`
- Create or modify: `Tests/web/test_filters.py`

- [ ] **Step 1: Write the failing tests**

Create `Tests/web/test_filters.py`:

```python
from Web.filters import markdown, as_pretty_json, highlight, format_tool_args


def test_markdown_renders_bold():
    rendered = markdown("**bold**")

    assert "<strong>bold</strong>" in rendered


def test_markdown_renders_inline_code():
    rendered = markdown("call `foo()` now")

    assert "<code>foo()</code>" in rendered


def test_as_pretty_json_indents_dicts():
    rendered = as_pretty_json({"a": 1, "b": [1, 2]})

    assert "\n" in rendered
    assert '"a": 1' in rendered


def test_as_pretty_json_falls_back_to_str_for_non_dict():
    rendered = as_pretty_json("plain string")

    assert rendered == "plain string"


def test_highlight_json_contains_pygments_class_spans():
    rendered = highlight('{"a": 1}', "json")

    assert 'class="hl"' in rendered or 'class="hl ' in rendered
    assert "&quot;a&quot;" in rendered or "\"a\"" in rendered


def test_format_tool_args_runs_python_code_uses_python_highlight():
    rendered = format_tool_args({"tool": "run_python", "args": {"code": "x = 1\nprint(x)"}})

    assert "x" in rendered
    assert "print" in rendered


def test_format_tool_args_other_tools_use_json_highlight():
    rendered = format_tool_args({"tool": "extract_metadata", "args": {"path": "metadata.csv"}})

    assert "metadata.csv" in rendered
    assert '"path"' in rendered or "&quot;path&quot;" in rendered
```

- [ ] **Step 2: Run and verify the tests fail**

Run: `pytest Tests/web/test_filters.py -v`
Expected: ImportError — `Web.filters` does not exist.

- [ ] **Step 3: Implement the filters**

Create `Web/filters.py`:

```python
from __future__ import annotations

import json
from typing import Any

from markdown_it import MarkdownIt
from pygments import highlight as _pygments_highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import get_lexer_by_name

_MD = MarkdownIt("commonmark")
_FORMATTER = HtmlFormatter(cssclass="hl", nowrap=False)


def markdown(text: str) -> str:
    return _MD.render(text or "")


def as_pretty_json(value: Any) -> str:
    if isinstance(value, (dict, list)):
        return json.dumps(value, indent=2, default=str)
    return str(value)


def highlight(text: str, lang: str) -> str:
    lexer = get_lexer_by_name(lang)
    return _pygments_highlight(text, lexer, _FORMATTER)


def format_tool_args(payload: dict) -> str:
    if payload.get("tool") == "run_python":
        return highlight(payload.get("args", {}).get("code", ""), "python")
    pretty = as_pretty_json(payload.get("args", {}))
    return highlight(pretty, "json")
```

- [ ] **Step 4: Run filter tests**

Run: `pytest Tests/web/test_filters.py -v`
Expected: All 7 PASS.

- [ ] **Step 5: Commit**

```bash
git add Web/filters.py Tests/web/test_filters.py
git commit -m "feat(web): four Jinja filters for markdown, JSON, code highlighting, tool args"
```

---

## Task 3: Implement and test `record_to_event`

**Files:**
- Create: `Web/records.py`
- Create or modify: `Tests/web/test_records.py`

- [ ] **Step 1: Write the failing tests**

Create `Tests/web/test_records.py`:

```python
from Web.records import record_to_event


def test_user_record_maps_to_user_event():
    record = {"type": "user", "content": "hello", "ts": "2026-05-28T00:00:00"}

    event = record_to_event(record)

    assert event["type"] == "user"
    assert event["payload"]["content"] == "hello"


def test_assistant_record_maps_to_assistant_final_event():
    record = {"type": "assistant", "content": "the answer"}

    event = record_to_event(record)

    assert event["type"] == "assistant_final"
    assert event["payload"]["content"] == "the answer"


def test_tool_call_record_maps_to_tool_call_event():
    record = {"type": "tool_call", "tool": "extract_metadata", "args": {"path": "x.csv"}, "tool_use_id": "u1"}

    event = record_to_event(record)

    assert event["type"] == "tool_call"
    assert event["payload"]["tool"] == "extract_metadata"
    assert event["payload"]["args"] == {"path": "x.csv"}


def test_tool_result_record_preserves_summary_and_error_flag():
    record = {"type": "tool_result", "tool_use_id": "u1", "result_summary": {"ok": True}, "is_error": False}

    event = record_to_event(record)

    assert event["type"] == "tool_result"
    assert event["payload"]["summary"] == {"ok": True}
    assert event["payload"]["is_error"] is False


def test_tool_result_error_uses_error_field_as_summary():
    record = {"type": "tool_result", "tool_use_id": "u1", "error": "boom", "is_error": True}

    event = record_to_event(record)

    assert event["type"] == "tool_result"
    assert event["payload"]["summary"] == {"error": "boom"}
    assert event["payload"]["is_error"] is True


def test_error_record_maps_to_error_event():
    record = {"type": "error", "message": "step limit"}

    event = record_to_event(record)

    assert event["type"] == "error"
    assert event["payload"]["message"] == "step limit"
```

- [ ] **Step 2: Verify the tests fail**

Run: `pytest Tests/web/test_records.py -v`
Expected: ImportError — `Web.records` does not exist.

- [ ] **Step 3: Implement the helper**

Create `Web/records.py`:

```python
from __future__ import annotations


def record_to_event(record: dict) -> dict:
    record_type = record.get("type")
    if record_type == "user":
        return {"type": "user", "payload": {"content": record.get("content", "")}}
    if record_type == "assistant":
        return {"type": "assistant_final", "payload": {"content": record.get("content", "")}}
    if record_type == "tool_call":
        return {"type": "tool_call", "payload": {"tool": record.get("tool", ""), "args": record.get("args", {})}}
    if record_type == "tool_result":
        summary = record.get("result_summary") if not record.get("is_error") else {"error": record.get("error", "")}
        return {"type": "tool_result", "payload": {"summary": summary, "is_error": bool(record.get("is_error"))}}
    if record_type == "error":
        return {"type": "error", "payload": {"message": record.get("message", "")}}
    return {"type": "error", "payload": {"message": f"unknown record type: {record_type}"}}
```

- [ ] **Step 4: Run records tests**

Run: `pytest Tests/web/test_records.py -v`
Expected: All 6 PASS.

- [ ] **Step 5: Commit**

```bash
git add Web/records.py Tests/web/test_records.py
git commit -m "feat(web): record_to_event converts JSONL transcript records to Event shape"
```

---

## Task 4: Register filters on the Jinja environment

**Files:**
- Modify: `Web/app.py`

- [ ] **Step 1: Find the templates init line**

Run: `grep -n "Jinja2Templates" Web/app.py`

Expected: One match around `templates = Jinja2Templates(directory=BASE / "templates")`.

- [ ] **Step 2: Register the filters**

Right after the `templates = Jinja2Templates(...)` line in `Web/app.py`, add:

```python
from Web.filters import markdown as _md_filter, as_pretty_json, highlight as _hl_filter, format_tool_args

templates.env.filters["markdown"] = _md_filter
templates.env.filters["as_pretty_json"] = as_pretty_json
templates.env.filters["highlight"] = _hl_filter
templates.env.filters["format_tool_args"] = format_tool_args
```

- [ ] **Step 3: Sanity-check the import**

Run: `python -c "from Web.app import app; print('ok')"`
Expected: prints `ok`.

- [ ] **Step 4: Commit**

```bash
git add Web/app.py
git commit -m "feat(web): register markdown/json/highlight/tool-args filters on Jinja env"
```

---

## Task 5: Rewrite `_event.html` and add `chat_base.html`

**Files:**
- Modify: `Web/templates/_event.html`
- Create: `Web/templates/chat_base.html`

- [ ] **Step 1: Replace `_event.html`**

Overwrite `Web/templates/_event.html` with:

```html
{# event = {type, payload}; workspace passed from caller #}
<div class="event event-{{ event.type }}">
{% if event.type == "user" %}
  <span class="role-pill role-user">You</span>
  <div class="text">{{ event.payload.content | markdown | safe }}</div>
{% elif event.type == "assistant_final" %}
  <span class="role-pill role-assistant">Assistant</span>
  <div class="text">{{ event.payload.content | markdown | safe }}</div>
{% elif event.type == "tool_call" %}
  <span class="role-pill role-tool">{{ event.payload.tool }}</span>
  <pre class="code">{{ event.payload | format_tool_args | safe }}</pre>
{% elif event.type == "tool_result" %}
  <div class="tool-result {% if event.payload.is_error %}is-error{% endif %}">
    {% if event.payload.summary and event.payload.summary.written_to %}
      <a class="written-to" href="/w/{{ workspace }}/files/{{ event.payload.summary.written_to }}">
        {{ event.payload.summary.written_to }}
      </a>
    {% endif %}
    <pre class="code">{{ event.payload.summary | as_pretty_json | highlight("json") | safe }}</pre>
  </div>
{% elif event.type == "error" %}
  <div class="error-banner">{{ event.payload.message }}</div>
{% endif %}
</div>
```

- [ ] **Step 2: Create `chat_base.html`**

Write `Web/templates/chat_base.html`:

```html
<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <title>{{ workspace }} — Ask-SLM</title>
  <link rel="stylesheet" href="/static/chat.css" />
</head>
<body>
  <h1>{{ workspace }}</h1>
  <div id="log">{% block log %}{% endblock %}</div>
  {% block input %}{% endblock %}
</body>
</html>
```

- [ ] **Step 3: Smoke-test that the templates parse**

Run: `python -c "from Web.app import templates; templates.get_template('_event.html'); templates.get_template('chat_base.html'); print('ok')"`
Expected: prints `ok`.

- [ ] **Step 4: Commit**

```bash
git add Web/templates/_event.html Web/templates/chat_base.html
git commit -m "feat(web): rewrite _event.html; add chat_base.html shell"
```

---

## Task 6: Rewrite `chat.html` and add scroll JS

**Files:**
- Modify: `Web/templates/chat.html`

- [ ] **Step 1: Replace `chat.html`**

Overwrite `Web/templates/chat.html`:

```html
{% extends "chat_base.html" %}

{% block input %}
<form hx-post="/w/{{ workspace }}/messages" hx-target="#log" hx-swap="beforeend">
  <input name="message" placeholder="Ask..." autocomplete="off" />
  <button>Send</button>
</form>
<script src="https://unpkg.com/htmx.org@1.9.12"></script>
<script>
  (function () {
    const log = document.getElementById('log');
    let pinned = true;
    log.addEventListener('scroll', function () {
      pinned = (log.scrollHeight - log.scrollTop - log.clientHeight) < 100;
    });
    document.body.addEventListener('htmx:afterSwap', function () {
      if (pinned) { log.scrollTop = log.scrollHeight; }
    });
  })();
</script>
{% endblock %}
```

- [ ] **Step 2: Smoke-test the chat page renders**

Run: `pytest Tests/web/test_app.py::test_chat_page_renders -v`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add Web/templates/chat.html
git commit -m "feat(web): chat.html uses chat_base + pin-to-bottom scroll JS"
```

---

## Task 7: Rewrite the replay route to use `record_to_event` + `_event.html`

**Files:**
- Modify: `Web/app.py`
- Modify: `Web/templates/replay.html`

- [ ] **Step 1: Find the replay route**

Run: `grep -n "def.*replay\|render_replay\|replay.html" Web/app.py`

Find the function that loads `records` and renders `replay.html`.

- [ ] **Step 2: Update the replay route to convert records and pass `workspace`**

In `Web/app.py`, find the replay handler. It currently passes `records` to `replay.html`. Add the conversion:

```python
from Web.records import record_to_event
# ... inside the replay route handler:
events = [record_to_event(r) for r in records]
return templates.TemplateResponse(
    "replay.html",
    {"request": request, "workspace": workspace, "events": events},
)
```

(Replace `records` with `events` in the template context. Keep the existing path-safety logic that loads the JSONL records.)

- [ ] **Step 3: Replace `replay.html`**

Overwrite `Web/templates/replay.html`:

```html
{% extends "chat_base.html" %}

{% block log %}
  {% for event in events %}
    {% include "_event.html" %}
  {% endfor %}
{% endblock %}
```

- [ ] **Step 4: Run replay-related tests**

Run: `pytest Tests/web/test_app.py -v`
Expected: PASS. The existing `test_sessions_listing_shows_past_transcripts` plus any replay test should pass; if any test asserted on the old replay HTML structure (e.g. raw `<b>You:</b>` markup), update the assertion to the new structure (`role-user` class, `event-user` class).

- [ ] **Step 5: Commit**

```bash
git add Web/app.py Web/templates/replay.html
git commit -m "feat(web): replay renders through _event.html via record_to_event"
```

---

## Task 8: Add the `/w/<ws>/files/<relpath>` artifact endpoint

**Files:**
- Modify: `Web/app.py`
- Modify: `Tests/web/test_app.py`

- [ ] **Step 1: Write the failing tests**

Append to `Tests/web/test_app.py`:

```python
def test_files_endpoint_serves_file_under_workspace(tmp_path, monkeypatch):
    from Web import app as app_mod
    monkeypatch.setattr(app_mod, "WORKSPACES_ROOT", tmp_path)
    root = _ws(tmp_path)
    (root / "results" / "source").mkdir(parents=True)
    (root / "results" / "source" / "metadata.csv").write_text("acc\nSRR1\n")

    client = TestClient(app_mod.app)
    r = client.get("/w/ABX/files/results/source/metadata.csv")

    assert r.status_code == 200
    assert "SRR1" in r.text


def test_files_endpoint_blocks_path_traversal(tmp_path, monkeypatch):
    from Web import app as app_mod
    monkeypatch.setattr(app_mod, "WORKSPACES_ROOT", tmp_path)
    _ws(tmp_path)

    client = TestClient(app_mod.app)
    r = client.get("/w/ABX/files/../../etc/passwd")

    assert r.status_code == 404


def test_files_endpoint_missing_file_returns_404(tmp_path, monkeypatch):
    from Web import app as app_mod
    monkeypatch.setattr(app_mod, "WORKSPACES_ROOT", tmp_path)
    _ws(tmp_path)

    client = TestClient(app_mod.app)
    r = client.get("/w/ABX/files/results/nope.csv")

    assert r.status_code == 404


def test_files_endpoint_unknown_workspace_returns_404(tmp_path, monkeypatch):
    from Web import app as app_mod
    monkeypatch.setattr(app_mod, "WORKSPACES_ROOT", tmp_path)

    client = TestClient(app_mod.app)
    r = client.get("/w/DOES_NOT_EXIST/files/anything.csv")

    assert r.status_code == 404
```

- [ ] **Step 2: Verify they fail**

Run: `pytest Tests/web/test_app.py -k files_endpoint -v`
Expected: 404 vs. likely 404 from FastAPI default (route not registered) — some may pass by accident. Read each failure carefully; the goal is that `test_files_endpoint_serves_file_under_workspace` fails because the route is missing.

- [ ] **Step 3: Add the endpoint to `Web/app.py`**

Add this route handler (near the existing `_safe_workspace_dir` helper):

```python
from fastapi.responses import FileResponse


@app.get("/w/{workspace}/files/{relpath:path}")
def get_workspace_file(workspace: str, relpath: str):
    ws_dir = _safe_workspace_dir(workspace)
    candidate = (ws_dir / relpath).resolve()
    if not candidate.is_relative_to(ws_dir):
        raise HTTPException(status_code=404, detail="file not found")
    if not candidate.is_file():
        raise HTTPException(status_code=404, detail="file not found")
    return FileResponse(candidate)
```

- [ ] **Step 4: Run the tests**

Run: `pytest Tests/web/test_app.py -k files_endpoint -v`
Expected: All 4 PASS.

- [ ] **Step 5: Commit**

```bash
git add Web/app.py Tests/web/test_app.py
git commit -m "feat(web): /w/<ws>/files/<relpath> serves artifacts read-only, path-safe"
```

---

## Task 9: Apply chrome to `index.html` and `sessions.html`

**Files:**
- Modify: `Web/templates/index.html`
- Modify: `Web/templates/sessions.html`

- [ ] **Step 1: Replace `index.html`**

Overwrite `Web/templates/index.html`:

```html
<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <title>Ask-SLM</title>
  <link rel="stylesheet" href="/static/chat.css" />
</head>
<body>
  <h1>Ask-SLM</h1>
  <div id="log">
    <ul>
      {% for w in workspaces %}<li><a href="/w/{{ w }}">{{ w }}</a></li>{% endfor %}
    </ul>
  </div>
</body>
</html>
```

- [ ] **Step 2: Replace `sessions.html`**

Overwrite `Web/templates/sessions.html`:

```html
<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <title>{{ workspace }} — past sessions</title>
  <link rel="stylesheet" href="/static/chat.css" />
</head>
<body>
  <h1>{{ workspace }} — past sessions</h1>
  <div id="log">
    <ul>
      {% for e in entries %}<li><a href="/w/{{ workspace }}/sessions/{{ e.id }}">{{ e.id }} — {{ e.title }}</a></li>{% endfor %}
    </ul>
  </div>
</body>
</html>
```

- [ ] **Step 3: Run all web tests**

Run: `pytest Tests/web/ -v`
Expected: All PASS.

- [ ] **Step 4: Commit**

```bash
git add Web/templates/index.html Web/templates/sessions.html
git commit -m "feat(web): style index and sessions pages with chat.css"
```

---

## Task 10: Snapshot tests for the rendered partial

**Files:**
- Modify: `Tests/web/test_app.py`

- [ ] **Step 1: Add snapshot-style assertions**

Append to `Tests/web/test_app.py`:

```python
def test_event_partial_renders_user_with_role_pill(tmp_path, monkeypatch):
    from Web import app as app_mod
    monkeypatch.setattr(app_mod, "WORKSPACES_ROOT", tmp_path)
    _ws(tmp_path)
    rendered = app_mod.templates.get_template("_event.html").render(
        event={"type": "user", "payload": {"content": "**hi**"}},
        workspace="ABX",
    )

    assert "role-user" in rendered
    assert "<strong>hi</strong>" in rendered


def test_event_partial_renders_tool_call_with_python_highlight(tmp_path, monkeypatch):
    from Web import app as app_mod
    monkeypatch.setattr(app_mod, "WORKSPACES_ROOT", tmp_path)
    rendered = app_mod.templates.get_template("_event.html").render(
        event={"type": "tool_call", "payload": {"tool": "run_python", "args": {"code": "x = 1"}}},
        workspace="ABX",
    )

    assert "role-tool" in rendered
    assert "class=\"hl\"" in rendered or "class='hl'" in rendered


def test_event_partial_renders_written_to_as_link(tmp_path, monkeypatch):
    from Web import app as app_mod
    rendered = app_mod.templates.get_template("_event.html").render(
        event={"type": "tool_result", "payload": {"summary": {"written_to": "results/source/metadata.csv", "ok": True}, "is_error": False}},
        workspace="ABX",
    )

    assert "written-to" in rendered
    assert "/w/ABX/files/results/source/metadata.csv" in rendered


def test_event_partial_marks_error_tool_result(tmp_path, monkeypatch):
    from Web import app as app_mod
    rendered = app_mod.templates.get_template("_event.html").render(
        event={"type": "tool_result", "payload": {"summary": {"error": "boom"}, "is_error": True}},
        workspace="ABX",
    )

    assert "is-error" in rendered
```

- [ ] **Step 2: Run snapshot tests**

Run: `pytest Tests/web/test_app.py -k event_partial -v`
Expected: All 4 PASS.

- [ ] **Step 3: Commit**

```bash
git add Tests/web/test_app.py
git commit -m "test(web): snapshot tests for _event.html partial"
```

---

## Task 11: Full test sweep + manual browser check

- [ ] **Step 1: Run the whole suite**

Run: `pytest -v`
Expected: All PASS.

- [ ] **Step 2: Manual smoke test in a browser**

Start the server: `ASKSLM_LLM_PROVIDER=... uvicorn Web.app:app --reload`

In a browser:
1. Open `http://localhost:8000/` — index lists workspaces with the new chrome.
2. Click into a workspace — chat page has the new styling.
3. Send a message — observe role pills, monospace tool blocks, markdown rendering, written_to links (if a tool wrote anything).
4. Scroll up partway through the response — observe that new events do NOT auto-scroll. Scroll to bottom — observe that subsequent events DO auto-scroll.
5. Click a `written_to` link — file opens in a new tab via `/w/<ws>/files/<relpath>`.
6. Visit `/w/<ws>/sessions/<id>` — replay renders the same way as live.

- [ ] **Step 3: Final commit (if anything tidied during manual test)**

```bash
git status
# commit any final polish
```

---

## Self-Review Checklist (run before declaring done)

- [ ] No CDN links in templates (other than the existing HTMX one): `grep -rn "unpkg\|cdnjs\|cdn\." Web/templates/`
- [ ] Replay template contains no per-record `{% if r.type == ... %}` ladder: `grep -n "r.type" Web/templates/replay.html` returns no hits
- [ ] Filters are registered exactly once on `templates.env.filters`: `grep -n "env.filters" Web/app.py`
- [ ] `/w/<ws>/files/<relpath>` is the only file-serving endpoint added: `grep -n "files/{relpath" Web/app.py`
- [ ] `pytest` exits 0
- [ ] Manual browser pass complete
