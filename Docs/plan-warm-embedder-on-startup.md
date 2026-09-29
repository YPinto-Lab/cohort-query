# Plan: warm the local embedder while the user types

## Problem
Traced a real `ask()` run (`~/plans/20260915_121212_ibd-calprotectin/log.txt` on
the lab server, `ssh biu`): 18.38s of the ~31s total (59%) is
`open_local_embedder()` loading `SapBERT-from-PubMedBERT-fulltext` from disk —
`src/askslm/adapters.py:383-392`. It's memoized per-process
(`src/askslm/runtime.py:100-117`, module-level `_embedder` global), so it only
costs this once per session — but it costs it serially, blocking the first
`translate()` call, right after the user submits their question.

## Fix
Kick off the embedder load on a background thread the instant the interactive
loop starts, so it overlaps with the time the user spends typing their
question instead of running after they hit enter.

File: `src/askslm/cli/session.py`

In `_session()` (around line 129), before the `while True:` loop:

```python
def _session() -> None:
    threading.Thread(target=runtime.embedder, daemon=True).start()
    question = ""
    ...
```

- Import `threading` (stdlib) and `runtime` (already imported or import
  `askslm.runtime`) at the top of the file.
- `runtime.embedder()` already no-ops safely if called when `llm != "gemini"`
  (falls back to the canned backend, no model load) — check
  `runtime.py:100-117` before wiring, no guard needed in `session.py`.
- `daemon=True` so an unfinished load doesn't block process exit if the user
  quits immediately.
- Nothing else changes: `translator()` still calls `embedder()` normally: if
  the thread finished, that call is instant (already memoized); if not, it
  blocks for whatever's left. No new state, no error handling needed — thread
  exceptions inside `embedder()` would need to surface at the point it's
  actually used, so let the real call re-raise naturally on the next
  `embedder()` invocation (it will retry the load rather than swallow the
  error silently).

## Scope check
Don't also:
- Add a loading spinner/progress indicator — the whole point is the user
  shouldn't see this as a step.
- Change the model, add caching layers, or build a daemon process — the
  problem is cold-start-once-per-session, which this fully covers. Only
  revisit if profiling shows typing time is consistently too short to hide
  the load (see Test below).

## Test
One `Tests/` smoke test, no framework: assert that starting the background
thread and then calling `embedder()` from the main thread returns the same
object as calling it a second time (i.e. no double-load, no race creating two
models). Something like:

```python
def test_embedder_warm_thread_no_double_load(monkeypatch):
    calls = []
    monkeypatch.setattr(runtime, "_embedder", None)
    monkeypatch.setattr(runtime, "open_local_embedder", lambda: calls.append(1) or object())
    monkeypatch.setattr(runtime, "_require_settings", lambda: Settings(llm="gemini", ...))
    t = threading.Thread(target=runtime.embedder)
    t.start()
    result = runtime.embedder()
    t.join()
    assert len(calls) == 1
```

(Adjust to however `Settings`/`_require_settings` are actually constructed in
existing tests — check `Tests/` for the pattern already used for `runtime.py`.)

## Branching
Per `CLAUDE.md`: create `feature/warm-embedder-on-startup` off `main` before
touching anything (`git fetch origin && git switch -c
feature/warm-embedder-on-startup origin/main`). Don't work on `main` or the
current `feature/prjna400072-viral-ecology` branch.

## Out of scope / explicitly not doing
- `askslm run plan.json` one-shot invocations (no interactive loop, no idle
  typing time to overlap with) still pay the full 18.4s — not addressed here.
  If that path matters, it's a separate follow-up (e.g. speeding the load
  itself: check the HF cache is `safetensors` not pickled `.bin`, try
  `low_cpu_mem_usage=True`), not part of this plan.
