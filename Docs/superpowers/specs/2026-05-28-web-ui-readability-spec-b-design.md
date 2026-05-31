# Web UI Readability (Spec B) — Design

**Date:** 2026-05-28
**Status:** Approved design, pending implementation plan
**Spec B** of two follow-ups discovered during first real chat use. **Spec A** is `2026-05-27-agent-state-awareness-design.md` (in flight).

**Parallel-safety:** Touches only `Web/` (templates, `app.py` endpoints, `static/`) and adds two pip dependencies. Does not touch `Agents/*`, `Engines/*`, `Accessors/*`. Fully independent of the in-flight `agent-state-awareness` work and of the AbundanceMatrix refactor.

---

## 1. Motivation

The first real chat exposed three concrete readability failures in the local web shell, plus a structural duplication issue:

1. **No turn separation.** User, assistant, tool_call, and tool_result events render as bare lines in one `<div id="log">`. The eye can't find where a turn starts or ends.
2. **No monospace for code or JSON.** Tool args render as Python repr; tool result summaries render in `<pre>` but with no styling, indentation, or highlighting. `run_python` snippets are illegible.
3. **No scroll handling.** As new events stream in, the page grows but doesn't follow. The user is constantly scrolling manually.

Plus:

4. **Assistant text is raw.** Bold, lists, links, inline code — the model emits markdown, the UI shows the raw `**` and backticks.
5. **`written_to` paths land in summaries (Spec A change) but are not visually distinct.** The researcher's whole point of the chat is to produce artifacts; the artifact paths should be the most prominent thing in each tool result.
6. **Chat and replay templates duplicate each other** with subtly different rendering, so any future fix has to be applied twice. The live stream renders `_event.html` per event; replay re-implements the same logic inline in `replay.html`.

## 2. Scope (v1)

**In scope:**

- Visual turn separation: role pills, distinct backgrounds, vertical rhythm.
- Monospace + syntax-highlighted code: tool args, tool result summaries, `run_python` snippets, JSON blocks. Server-side via Pygments.
- Markdown rendering for assistant final text. Server-side via `markdown-it-py`.
- Auto-scroll-to-bottom on new events, with "pin only when already at bottom" behavior.
- `written_to` artifact paths rendered as distinct clickable links to a new read-only file endpoint.
- Single `_event.html` partial used by both the live stream and the replay view; `replay.html` reduced to iterating records through it.
- Vanilla CSS in `Web/static/chat.css`. No CDN, no JS framework, no Tailwind.

**Out of scope:**

- Collapsible tool blocks. Tool calls and results stay always-expanded. Defer until clutter actually bites.
- Theming / dark mode / light mode toggle.
- Search across past sessions.
- Diffing two sessions side-by-side.
- Streaming partial tokens for assistant text. Current pattern is "wait for full response, render"; unchanged.

## 3. Locked-in decisions

| Decision | Choice |
|---|---|
| Rendering pipeline | Server-side. Markdown via `markdown-it-py`; syntax highlighting via `Pygments`. |
| Styling | Vanilla CSS, single file `Web/static/chat.css`. No CDN, no build step. |
| Event partial | `_event.html` is the single source of truth; used by both live and replay. |
| Replay records → Event shape | Replay endpoint converts JSONL records into Event-shaped dicts and renders through `_event.html`. No duplicate rendering logic. |
| Scroll behavior | Tiny inline JS in `chat.html`: on `htmx:afterSwap`, if user was within 100px of bottom, scroll to bottom; else do nothing. |
| Tool block visual | Always-expanded. Visually paired (tool_call + tool_result) by indent + connecting border. |
| Artifact paths | `written_to` rendered as `<a href="/w/<ws>/files/<relpath>" class="written-to">`. New endpoint serves files read-only under the workspace, with path-traversal protection. |
| New deps | `markdown-it-py`, `Pygments`. Already-present `fastapi`, `jinja2` unchanged. |

## 4. Event rendering — final shape

### `_event.html` — single source of truth

```html
{# event = {type, payload} where payload is dict-shaped #}
<div class="event event-{{ event.type }}">
  {% if event.type == "user" %}
    <span class="role-pill role-user">You</span>
    <div class="text">{{ event.payload.content | markdown }}</div>

  {% elif event.type == "assistant_final" %}
    <span class="role-pill role-assistant">Assistant</span>
    <div class="text">{{ event.payload.content | markdown }}</div>

  {% elif event.type == "tool_call" %}
    <span class="role-pill role-tool">{{ event.payload.tool }}</span>
    <pre class="code">{{ event.payload | format_tool_args | safe }}</pre>

  {% elif event.type == "tool_result" %}
    <div class="tool-result {% if event.payload.is_error %}is-error{% endif %}">
      {% if event.payload.summary.written_to %}
        <a class="written-to" href="/w/{{ workspace }}/files/{{ event.payload.summary.written_to }}">
          {{ event.payload.summary.written_to }}
        </a>
      {% endif %}
      <pre class="code">{{ event.payload.summary | as_pretty_json | highlight("json") }}</pre>
    </div>

  {% elif event.type == "error" %}
    <div class="error-banner">{{ event.payload.message }}</div>
  {% endif %}
</div>
```

The four custom Jinja filters (`markdown`, `as_pretty_json`, `highlight`, `format_tool_args`) are registered in `Web/app.py` at startup. Each is one short function (≤ 10 lines).

### Filters

| Filter | Implementation |
|---|---|
| `markdown(text)` | `markdown_it.MarkdownIt("commonmark").render(text)`. Returns safe HTML. Inline code spans are styled by `.code` class. |
| `as_pretty_json(obj)` | `json.dumps(obj, indent=2, default=str)` when `obj` is dict-like; else `str(obj)`. |
| `highlight(text, lang)` | `pygments.highlight(text, get_lexer_by_name(lang), HtmlFormatter(cssclass="hl"))`. |
| `format_tool_args(payload)` | Dispatches by tool name. For `run_python`, highlights `payload.args.code` as Python. For all other tools, pretty-prints `payload.args` as JSON and highlights. Two guard-clause returns, no `else`. |

### Pairing tool_call with tool_result

Visually, a tool_call followed by its tool_result should read as one block. CSS handles this:

- `.event-tool_call` has rounded top corners and `border-bottom: none`.
- `.event-tool_result` has rounded bottom corners, shares the same indent and border color.

No JS, no DOM wrapping. Pure CSS adjacency.

## 5. Stylesheet — `Web/static/chat.css`

Structure (~150 lines total):

- **Reset + base typography**: system font, 1.5 line-height, color tokens for backgrounds/borders.
- **Layout**: `body` is a column flexbox; `#log` is the scroll container with `overflow-y: auto`; sticky bottom form.
- **`.event`**: vertical rhythm (`margin: 0.75rem 0`), padding, rounded corners.
- **`.event-user`** background tint; **`.event-assistant_final`** different tint.
- **`.event-tool_call` / `.event-tool_result`** muted, monospace, indented; paired-block borders.
- **`.role-pill`** small caps label, 12px, distinct color per role.
- **`.code`** monospace, scroll-x for long lines, Pygments `.hl` classes for tokens.
- **`.written-to`** prominent link styling (color, underline, small file-icon emoji ✱ prefix).
- **`.is-error`** red left-border + tinted background.
- **`.error-banner`** full-width red.

Pygments token colors emitted by Pygments' default HtmlFormatter classes (`.hl .s2` for strings, etc.) are styled in the same file (one-line entries per token class).

## 6. Scroll behavior

`chat.html` gains ~10 lines of inline JS:

```html
<script>
  const log = document.getElementById('log');
  let pinned = true;
  log.addEventListener('scroll', () => {
    pinned = log.scrollHeight - log.scrollTop - log.clientHeight < 100;
  });
  document.body.addEventListener('htmx:afterSwap', () => {
    if (pinned) log.scrollTop = log.scrollHeight;
  });
</script>
```

Replay view scrolls to top on load (default browser behavior — no special handling needed).

## 7. Artifact path endpoint

New endpoint in `Web/app.py`:

```python
@app.get("/w/{workspace}/files/{relpath:path}")
def get_workspace_file(workspace: str, relpath: str): ...
```

- Resolves `relpath` against `_safe_workspace_dir(workspace)` using the same containment check as `_safe_session_path` (path-traversal protection).
- Refuses anything outside the workspace.
- Streams the file with `FileResponse`; content-type sniffed by FastAPI defaults. CSV/TSV/JSON open in-browser; the user can save-as if they want.

This endpoint is read-only and clamped to the workspace. It's the same trust model as the rest of the app (single-user local).

## 8. Replay unification

Today `replay.html` reimplements per-record rendering inline. After this spec, the replay endpoint in `Web/app.py` converts each JSONL record into an Event-shaped dict and renders through `_event.html`:

```python
def record_to_event(record: dict) -> dict:
    # one short pure function; handles the five record types
    ...
```

`replay.html` becomes:

```html
{% extends "chat_base.html" %}
{% block log %}
  {% for r in records %}{% include "_event.html" %}{% endfor %}
{% endblock %}
```

A small `chat_base.html` is introduced to hold the page chrome shared by `chat.html` and `replay.html`. `chat.html`'s only addition over `chat_base.html` is the message-input form and the scroll JS.

## 9. Files changed

| File | Change |
|---|---|
| `Web/app.py` | Register three Jinja filters (`markdown`, `as_pretty_json`, `highlight`). Add `record_to_event` helper. Add `GET /w/<ws>/files/<relpath>` endpoint. Replay endpoint passes Event-shaped dicts. |
| `Web/templates/_event.html` | Rewritten per §4. |
| `Web/templates/chat.html` | Becomes a thin shell over a new `chat_base.html`; adds scroll JS. |
| `Web/templates/chat_base.html` | **New.** Holds shared chrome (head, log container, css link). |
| `Web/templates/replay.html` | Reduced to iterating records through `_event.html`. |
| `Web/templates/sessions.html`, `Web/templates/index.html` | Apply chat.css for visual consistency. |
| `Web/static/chat.css` | **New.** ~150 lines per §5. |
| `pyproject.toml` (or requirements file) | Add `markdown-it-py`, `Pygments`. |
| `Tests/web/test_app.py` (new or extended) | Tests per §10. |

## 10. Testing

**Unit — filter behavior:**

- `markdown("**bold**")` → contains `<strong>bold</strong>`.
- `as_pretty_json({"a": 1})` is multi-line, key-quoted.
- `highlight("{\"a\": 1}", "json")` contains Pygments class spans (e.g. `class="hl"`).
- `format_tool_args({"tool": "run_python", "args": {"code": "x = 1"}})` produces Python-highlighted HTML (not JSON).
- `format_tool_args({"tool": "extract_metadata", "args": {"path": "metadata.csv"}})` produces JSON-highlighted HTML.

**Unit — `record_to_event`:**

- Each of the 5 JSONL record types maps to the expected Event-shaped dict.
- Error records preserve `is_error: True`.

**Endpoint — `/w/<ws>/files/<relpath>`:**

- Happy path: file under workspace returns 200 with content.
- Path traversal: `../../etc/passwd` returns 404.
- Missing file: 404.
- Workspace not found: 404.

**Snapshot — `_event.html` output:**

- Render each event type with a known payload; assert the resulting HTML contains the role pill, the markdown-rendered text (where applicable), the Pygments classes, the `written-to` anchor when present.

**Replay parity:**

- Render replay over a fixture JSONL; assert the resulting HTML contains the same event-block markers as a live stream over the same events.

**Manual:**

- Open the chat in a browser; verify scroll-to-bottom only kicks in when at-bottom. Verify monospace, role pills, paired tool blocks render distinctly.

## 11. Success criteria

V1 ships if:

1. A real chat session is readable end-to-end without manual scroll, with clear turn boundaries, monospace code, and rendered markdown.
2. `written_to` paths from Spec A appear as clickable links that open the artifact in a new tab.
3. The chat view and the replay view of the same session look identical.
4. `Web/templates/replay.html` contains no per-record `{% if r.type == ... %}` ladder — it iterates through `_event.html`.
5. No JS or CSS from a CDN. One self-hosted stylesheet under `Web/static/`.
6. Full pytest suite passes; new tests cover the four units above.

## 12. Open follow-ups (future specs)

- **Collapsible tool blocks** when chats grow long enough to clutter. Trigger when a typical session exceeds ~30 events.
- **Dark/light theme toggle.** Defer until requested.
- **Inline preview of tabular artifacts** (CSV → small HTML table on click) — defer until researchers ask.
- **Cross-session search.** Defer until session count grows.
