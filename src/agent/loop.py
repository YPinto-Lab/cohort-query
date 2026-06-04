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
                system=SYSTEM_PROMPT.format(workspace=session.workspace.name),
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
        blocks.append({"type": "tool_use", "id": tu.id, "name": tu.name, "input": tu.input})
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
