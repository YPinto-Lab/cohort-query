# Agent Orchestrator — Design

**Date:** 2026-05-26
**Status:** Approved design, pending implementation plan
**Scope:** v1 of a natural-language agent that drives Ask-SLM's existing Python API. MetaLOG integration is a separate follow-up spec.

---

## 1. Motivation

Researchers using Ask-SLM today must know the Python API (`askslm.metadata`, `askslm.taxonomy`) to express analyses. We want a natural-language layer that lets them say "build a genus-level cohort for the ABX workspace and compute Bray-Curtis per subject from day 0 to last day" and have the system carry it out by composing existing tools.

The agent must:

- Drive Ask-SLM's existing public API through structured tool calls, not arbitrary SQL
- Handle multi-step chained workflows that pass rich domain objects between steps (`Metadata`, `AbundanceMatrix`, `Cohort`)
- Cover the long tail of analyses (third-party libraries like scikit-bio, MaAsLin2, scipy, ad-hoc Excel parsing) without requiring a named tool for every conceivable operation
- Stay auditable: every step recorded, every snippet reviewable

## 2. Non-goals (v1)

- **MetaLOG integration.** Separate spec.
- **Multi-workspace sessions.** One workspace per session, locked at session start.
- **Conversation resume from transcript.** Transcripts are durable records; new sessions start fresh.
- **Hardened sandbox** (Docker / nsjail). v1 is single-user local trust.
- **Multi-user / SaaS / auth / quotas.** Defer until there are users to need it.
- **Multiple LLM providers.** Interface is ready; only Anthropic is wired up.
- **A "curated agent-friendly tool layer"** separate from the public API. v1 wraps the public API 1:1.

## 3. Locked-in choices (from brainstorming)

| Decision | Choice |
|---|---|
| Tool execution model | **Hybrid**: named tools + one `run_python` escape hatch |
| Session state | **Stateful session** with a named variable store (handles → domain objects) |
| Surface | Python library (`askslm.agent`) + minimal local web shell (FastAPI + HTMX) |
| Orchestrator | Raw Anthropic SDK + custom ReAct loop (~150 lines); thin `LLMClient` interface |
| Tool roster | Wrap existing `askslm.metadata` and `askslm.taxonomy` 1:1; `run_python` for the long tail |
| Workspace scope | One session = one workspace, picked at session start; no `set_workspace` tool |
| `run_python` sandbox | Subprocess, 60s default timeout, `cwd` clamped to workspace, `askslm` + curated whitelist pre-imported |
| Transcript | `Workspaces/<ws>/results/agent_log/<ts>.jsonl` |
| Conversation | In-memory per session; new session = fresh thread |
| Streaming | Server-Sent Events to the HTMX page; same generator drives streaming, transcripts, and tests |

## 4. Architecture & layering

A new top-of-stack layer above today's Engines. Dependency flow stays one-directional, consistent with `Client → Managers → Engines → Accessors`:

```
askslm-web (FastAPI + HTMX)         ← thin surface, streams responses
        │
        ▼
askslm.agent  (new Python package)  ← the agent core (library)
        │
        ▼
askslm.metadata / askslm.taxonomy   ← existing public API (unchanged)
        │
        ▼
Engines → Accessors
```

### Package layout

```
Agents/
├── __init__.py              # public: Agent, Session
├── session.py               # Session: variable store + transcript + workspace
├── loop.py                  # ReAct loop (~150 lines)
├── llm_client.py            # LLMClient interface + AnthropicClient impl
├── tools/
│   ├── __init__.py          # tool registry
│   ├── registry.py          # @tool decorator, schema generation from type hints
│   ├── metadata_tools.py    # wraps askslm.metadata (extract, overview)
│   ├── taxonomy_tools.py    # wraps askslm.taxonomy (load, resolve, build_*)
│   └── run_python.py        # sandboxed code execution tool
└── transcript.py            # JSONL transcript writer
```

### Boundaries

- `askslm.agent` imports only from the public `askslm.*` API — never from Engines or Accessors internals.
- `LLMClient` is an interface; the v1 implementation targets Anthropic. Switching to a different provider means writing one new class.
- The web layer (`askslm-web`) is a separate top-level package depending on `askslm.agent`. The agent is usable without the web shell, and the web shell can be replaced without rewriting the agent.

## 5. Session & state model

A `Session` owns all in-conversation state. One Session per chat, one workspace per Session, picked at construction. Sessions live in memory for their lifetime; the JSONL transcript on disk is the durable record.

```python
class Session:
    workspace: Workspace             # locked at construction
    variables: VariableStore         # named handles → domain objects
    messages: list[Message]          # full conversation incl. tool calls
    transcript: TranscriptWriter     # appends to results/agent_log/<ts>.jsonl
    llm: LLMClient
```

### Variable store — the hybrid's load-bearing piece

Named tools that return rich domain objects (`Metadata`, `AbundanceMatrix`, `Cohort`, `ResolvedTaxonomy`) cause the Session to:

1. Store the object under an auto-generated handle (`matrix_1`, `cohort_a`, …)
2. Return a JSON-safe **summary** to the LLM (shape, rank, sample count, top columns — not the underlying data)

Example summary surfaced to the LLM:

```json
{"handle": "matrix_1", "type": "AbundanceMatrix", "shape": [142, 358], "rank": "genus", "samples_preview": ["SRR..."]}
```

Subsequent tools accept handles as arguments: `build_cohort(matrix="matrix_1", metadata="meta_1")`. The Session resolves the handle to the real object before invoking the underlying function.

### `run_python` and the variable store

The sandboxed subprocess receives existing handles pickled into its namespace under their handle names. The snippet can write `bray = beta_diversity(matrix_1.df)` directly. On return, new top-level variables matching recognized domain types are pickled back and registered as fresh handles. The LLM can then pass `bray` to subsequent tool calls.

### Workspace lock

The workspace is set at Session construction and immutable. There is no `set_workspace` tool. All file I/O is clamped to the session's workspace path.

### Lifecycle

A Session is one chat. Closing the chat ends in-memory state. The JSONL transcript is the durable record — replayable from the web UI (see §9) but not auto-reloaded into a new Session.

## 6. Tools — definition, schemas, invocation

### Definition pattern

A tool is a Python function with type hints and a docstring. A `@tool` decorator registers it and generates the Anthropic tool schema from the signature.

```python
@tool
def build_abundance_matrix(
    taxonomy: Handle[ResolvedTaxonomy],
    rank: Literal["phylum","class","order","family","genus","species"] = "genus",
) -> Handle[AbundanceMatrix]:
    """Build a single-rank abundance matrix from resolved taxonomy.
    Returns a handle to the matrix; use its summary to decide next steps."""
    resolved = session.variables.get(taxonomy)
    matrix = askslm.taxonomy.build_abundance_matrix(resolved.df, rank=rank)
    return session.variables.put(matrix, hint="matrix")
```

The decorator:

- Inspects type hints to produce JSON schema
- Treats `Handle[T]` as `{"type": "string", "description": "handle to <T>"}`
- Pulls `description` from the docstring
- Validates incoming arguments with Pydantic at invocation time

No hand-written schemas.

### v1 tool roster

| Tool | Wraps | Returns |
|---|---|---|
| `extract_metadata(path)` | `metadata.extract` | `Handle[Metadata]` |
| `metadata_overview(metadata)` | `metadata.overview` | `Handle[MetadataOverview]` |
| `load_taxonomy(path)` | `taxonomy.load` | `Handle[DataFrame]` |
| `resolve_taxonomy(taxonomy)` | `taxonomy.resolve` | `Handle[ResolvedTaxonomy]` |
| `build_abundance_matrix(taxonomy, rank)` | `taxonomy.build_abundance_matrix` | `Handle[AbundanceMatrix]` |
| `build_cohort(matrix, metadata)` | `taxonomy.build_cohort` | `Handle[Cohort]` |
| `summarize(handle)` | Session API | JSON summary of a stored object |
| `list_workspace_inputs()` | Workspace API | JSON list of available input files |
| `run_python(code, timeout_s?)` | Sandbox | stdout + new handles |

### Invocation flow

1. LLM emits a `tool_use` block with `name` + JSON `input`.
2. Loop validates `input` against the Pydantic-derived schema. On failure, returns a structured `tool_result` with `is_error: true` and the validation message; LLM retries.
3. Loop resolves any `Handle[...]` args via the Session's variable store. Missing handle → structured error listing available handles; LLM corrects.
4. Tool function runs. Result is wrapped as a `Handle` (for domain objects) or returned as JSON (for primitives/summaries).
5. Loop appends a `tool_result` block to messages and continues.

### `run_python` sandbox mechanics

- Spawns a Python subprocess with a 60s default timeout (caller-overridable up to 300s).
- `cwd` set to `Workspaces/<ws>/`. The pre-amble sets `os.chdir(workspace)` and logs a warning if the snippet reassigns it.
- `askslm` plus a curated whitelist (`pandas`, `numpy`, `scipy`, `skbio`) is pre-imported into the namespace.
- Existing handles are pickled over stdin into the subprocess under their handle names.
- New top-level variables matching recognized domain types are pickled back and registered as handles.
- stdout/stderr captured and returned to the LLM along with a list of new handles.
- Errors come back as structured `{"error": "...", "traceback": "..."}`; the agent can retry.
- File writes outside the workspace path are not blocked at the OS level in v1 (single-user trust model).

## 7. The loop — control flow, streaming, error handling

### Loop (~150 lines, `Agents/loop.py`)

```python
def run(session: Session, user_message: str) -> Iterator[Event]:
    session.messages.append({"role": "user", "content": user_message})
    yield Event.user(user_message)

    for step in range(MAX_STEPS):  # MAX_STEPS = 20
        response = session.llm.complete(
            messages=session.messages,
            tools=registry.schemas(),
            system=SYSTEM_PROMPT.format(workspace=session.workspace.name),
        )
        session.messages.append({"role": "assistant", "content": response.content})

        tool_uses = [b for b in response.content if b.type == "tool_use"]
        if not tool_uses:
            yield Event.assistant_final(response.text)
            return

        tool_results = []
        for tu in tool_uses:
            yield Event.tool_call(tu.name, tu.input)
            result = execute_tool(session, tu)         # validates, resolves handles, runs
            session.transcript.append(tu, result)
            yield Event.tool_result(tu.name, result.summary)
            tool_results.append({"type": "tool_result", "tool_use_id": tu.id, "content": result.payload})

        session.messages.append({"role": "user", "content": tool_results})

    yield Event.error("Step limit reached without final answer")
```

The whole loop is in this function. No framework, no hidden state, every decision visible.

### Streaming

`run()` is a generator yielding `Event` objects. The FastAPI route wraps it as a Server-Sent Events response; the HTMX page renders each event as it arrives:

- `user` → user bubble
- `assistant_final` → assistant bubble (markdown)
- `tool_call` → collapsible "🔧 build_abundance_matrix(...)"
- `tool_result` → collapsible summary under the tool call
- `error` → red banner

The same generator drives streaming, transcript writing, and tests.

### Error categories

| # | Category | Recovery |
|---|---|---|
| 1 | Schema validation (LLM gave bad args) | `tool_result` with `is_error: true` + Pydantic message. LLM almost always self-corrects. |
| 2 | Handle-not-found | Same shape; error includes list of available handles. Self-corrects. |
| 3 | Tool raised an exception | Wrapped in `tool_result` with traceback. LLM retries or explains failure to user. |
| 4 | Infra (LLM API down, timeout, step-limit) | `Event.error` to user. Session stays alive; user can rephrase. |

### Cancellation

The web UI has a "stop" button that closes the SSE stream. FastAPI detects disconnection between LLM calls and aborts the loop cleanly. Any in-flight `run_python` subprocess is killed.

## 8. Observability — knowing what to grow

The agent should reveal what's missing without manual hunting.

### Transcript JSONL schema

Each line in `Workspaces/<ws>/results/agent_log/<ts>.jsonl` is one of:

```json
{"ts": "...", "type": "user", "content": "..."}
{"ts": "...", "type": "assistant", "content": "..."}
{"ts": "...", "type": "tool_call", "tool": "...", "args": {...}, "tool_use_id": "..."}
{"ts": "...", "type": "tool_result", "tool_use_id": "...", "result_summary": {...}, "is_error": false, "latency_ms": 123}
{"ts": "...", "type": "tool_result", "tool_use_id": "...", "error": "...", "traceback": "...", "is_error": true, "latency_ms": 123}
{"ts": "...", "type": "error", "message": "..."}
```

`run_python` `tool_call` entries additionally include `code` (raw snippet) and `imports_used` (parsed from the snippet's AST). `tool_result` entries for `run_python` additionally include `new_handles`.

### `askslm agent-review`

Reads `Workspaces/*/results/agent_log/*.jsonl` and reports:

- **Whitelist candidates** — counts of `ModuleNotFoundError`s grouped by module name, plus counts of successfully-used imports. Decision rule: any module with ≥3 `ModuleNotFoundError`s is a whitelist add.
- **Tool-promotion candidates** — `run_python` snippets clustered by AST normalization (strip literals and identifier names, hash). Clusters with N ≥ 3 occurrences across sessions are reported with a representative snippet and count. Decision rule: serious candidates for wrapping as named tools.

## 9. Session inspection — live and after

### Live, during the session

The chat UI renders the event stream from §7: user message → tool call (collapsible) → tool result (collapsible) → next tool call → … → final answer. Nothing is hidden.

### Replay, after the session

**Web UI Sessions sidebar.** A list of past sessions for the current workspace, read from `Workspaces/<ws>/results/agent_log/*.jsonl`, sorted newest first, titled by the first user message. Clicking one renders it in the same chat view, using the same components, from the file instead of a live stream. No LLM call. 100% render-code reuse.

**`askslm agent-show <session-id>`.** Pretty-prints a single transcript to the terminal — user/assistant turns, each tool call with args, each result with summary, errors highlighted. For grepping, pasting into a PR, or reading without a browser.

## 10. Testing strategy

Three layers.

### Unit tests (fast, no LLM)

- `@tool` decorator schema generation: pass a function with typed args, assert the produced JSON schema
- Variable store: put/get, handle naming, summary generation per domain type
- Tool execution wrapper: handle resolution, Pydantic validation errors, exception capture
- `run_python` sandbox: timeout enforcement, handle pickling round-trip, AST import extraction, error capture
- Transcript writer: JSONL schema correctness
- Loop: drive it with a fake `LLMClient` that returns scripted `tool_use` sequences; assert events emitted, transcript contents, error recovery on bad args

### Integration tests (slower, no LLM)

End-to-end agent flow with the fake client, real tools, real Session, real workspace fixture. Verify canonical chained workflows:

- `extract_metadata → metadata_overview`
- `load_taxonomy → resolve_taxonomy → build_abundance_matrix → build_cohort`
- One `run_python` snippet that consumes a handle and produces a new one

### LLM smoke tests (opt-in, cost money)

Tagged `@pytest.mark.llm`, skipped by default, run manually. A handful of fixed natural-language prompts against a real LLM, asserting on the trajectory (which tools got called, in what order), not exact wording. Catches prompt regressions.

## 11. Success criteria for v1

A v1 ship is successful if, in your workspace, the agent can:

1. **Metadata exploration** — "Summarize the metadata in workspace `ABX`" produces a coherent answer driven by `extract_metadata → metadata_overview`.
2. **Taxonomy pipeline** — "Build a genus-level abundance matrix and a cohort against the metadata" runs the full chain end-to-end, with handles passed correctly.
3. **Long-tail analysis via `run_python`** — "Compute Bray-Curtis per subject from day 0 to last day" — agent builds a cohort with named tools, then `run_python`s `skbio.diversity.beta_diversity` over it and returns a distance-matrix handle.
4. **Cohort construction from an external spec** — "Create 4 cohorts as described in `Notebooks/Viral_Ecological_Clusters_Master_Map-v2.xlsx`" — agent uses `run_python` to read the Excel, then named tools to build each cohort.
5. **Graceful failure recovery** — Bad arg → LLM corrects on the next step without the user noticing.
6. **Auditability** — Every session has a complete JSONL transcript on disk; `askslm agent-review` runs and produces non-empty output after ≥10 sessions.

## 12. Open follow-ups (future specs)

- **MetaLOG integration** (Task 1 from the original brief).
- **Hardened sandbox** when the agent is exposed beyond a single local user.
- **Multi-user / SaaS** — auth, multi-tenancy, deployment.
- **Conversation resume from transcript**.
- **Additional named tools** — driven by `agent-review` evidence, not speculation.
- **Additional LLM providers** — interface is ready; add when there's a concrete reason.
