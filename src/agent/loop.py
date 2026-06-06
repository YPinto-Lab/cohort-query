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

_OPERATING_MANUAL = (Path(__file__).parent / "operating_manual.md").read_text()


def build_system_prompt(session: Session) -> str:
    return "\n\n".join([
        IDENTITY_PREAMBLE,
        _OPERATING_MANUAL,
        WorkspaceSnapshot(session.workspace).render(),
    ])


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
        try:
            response = llm.complete(
                messages=session.messages,
                tools=registry.schemas(),
                system=build_system_prompt(session),
            )
        except Exception as e:
            session.transcript.error(f"LLM call failed: {e!r}")
            yield Event.error(f"LLM call failed: {e}")
            return
        session.messages.append({"role": "assistant", "content": _assistant_content(response)})
        if response.text:
            session.transcript.assistant(response.text)

        if response.is_final:
            yield Event.assistant_final(response.text)
            return

        results_payload = []
        for tu in response.tool_uses:
            yield from _handle_tool_use(session, registry, tu, results_payload)
        session.messages.append({"role": "user", "content": results_payload})

    session.transcript.error("step limit reached")
    yield Event.error("Step limit reached without final answer.")


def _handle_tool_use(session, registry, tu, results_payload) -> Iterator[Event]:
    yield Event.tool_call(tu.name, tu.input)
    session.transcript.tool_call(tu.name, tu.input, tool_use_id=tu.id, **_transcript_extras(tu))

    result = registry.execute(session, tu.name, tu.input)

    if result.is_error:
        session.transcript.tool_result_err(
            tu.id, result.error or "", result.traceback or "", latency_ms=result.latency_ms,
        )
        yield Event.tool_result(tu.name, {"error": result.error}, is_error=True)
        results_payload.append(_tool_result_error_block(tu.id, result.error))
        return

    summary = result.summary or {}
    session.transcript.tool_result_ok(
        tu.id, summary, latency_ms=result.latency_ms, new_handles=summary.get("new_handles"),
    )
    yield Event.tool_result(tu.name, summary)
    results_payload.append(_tool_result_ok_block(tu.id, summary))


def _transcript_extras(tu) -> dict:
    # run_python is special: transcript records the source + imports for replay/audit.
    # Inline import keeps this leaky coupling to a private helper local to one branch.
    if tu.name != "run_python":
        return {}
    from agent.tools.run_python import _extract_imports
    code = tu.input.get("code", "")
    return {"code": code, "imports_used": _extract_imports(code)}


def _assistant_content(response) -> list[dict]:
    blocks: list[dict] = []
    if response.text:
        blocks.append({"type": "text", "text": response.text})
    for tu in response.tool_uses:
        block: dict = {"type": "tool_use", "id": tu.id, "name": tu.name, "input": tu.input}
        # Echo Gemini's thought_signature back on the next request (thinking models
        # 400 without it); AnthropicClient never sets this, so the key is absent there.
        if getattr(tu, "thought_signature", None) is not None:
            block["_gemini_thought_signature"] = tu.thought_signature
        blocks.append(block)
    return blocks


def _tool_result_ok_block(tool_use_id: str, summary: dict) -> dict:
    return {"type": "tool_result", "tool_use_id": tool_use_id, "content": json.dumps(summary)}


def _tool_result_error_block(tool_use_id: str, error: str | None) -> dict:
    return {
        "type": "tool_result",
        "tool_use_id": tool_use_id,
        "is_error": True,
        "content": error or "error",
    }
