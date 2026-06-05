from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ToolUse:
    id: str
    name: str
    input: dict
    # Gemini-only: bytes the API attaches to function_call parts on thinking
    # models. Must be echoed back on the next request or Gemini returns 400.
    # AnthropicClient does not set this and ignores it on incoming messages.
    thought_signature: bytes | None = None


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


import uuid


@lru_cache(maxsize=1)
def _gemini_client():
    from google import genai
    return genai.Client(api_key=os.environ["GEMINI_API_KEY"])


def _to_gemini_tools(tools: list[dict]):
    """Translate Anthropic-shaped tool dicts into Gemini's [Tool(function_declarations=[...])]."""
    if not tools:
        return []
    from google.genai import types as gt
    decls = [
        gt.FunctionDeclaration(
            name=t["name"],
            description=t.get("description", ""),
            parameters=t.get("input_schema", {"type": "object"}),
        )
        for t in tools
    ]
    return [gt.Tool(function_declarations=decls)]


def _to_gemini_contents(messages: list[dict]):
    """Translate Anthropic-shaped messages into Gemini Content objects.

    Anthropic uses 'assistant' role; Gemini uses 'model'. Anthropic correlates
    tool calls and results by tool_use_id; Gemini correlates by function name.
    We map tool_use_id -> name within this single call so that following
    tool_result blocks can be keyed by the right function name.
    """
    from google.genai import types as gt
    contents = []
    last_tool_use_id_to_name: dict[str, str] = {}

    for msg in messages:
        role = msg["role"]
        content = msg["content"]

        if role == "user":
            if isinstance(content, str):
                contents.append(gt.Content(role="user", parts=[gt.Part(text=content)]))
                continue
            parts = []
            for block in content:
                if block.get("type") == "tool_result":
                    name = last_tool_use_id_to_name.get(block["tool_use_id"], "unknown_tool")
                    payload = block.get("content", "")
                    if block.get("is_error"):
                        response = {"error": str(payload)}
                    else:
                        response = {"content": str(payload)}
                    parts.append(gt.Part(function_response=gt.FunctionResponse(name=name, response=response)))
                elif block.get("type") == "text":
                    parts.append(gt.Part(text=block["text"]))
            contents.append(gt.Content(role="user", parts=parts))
            continue

        if role == "assistant":
            parts = []
            for block in content:
                if block.get("type") == "text":
                    parts.append(gt.Part(text=block["text"]))
                elif block.get("type") == "tool_use":
                    last_tool_use_id_to_name[block["id"]] = block["name"]
                    fc_part = gt.Part(function_call=gt.FunctionCall(
                        name=block["name"], args=dict(block.get("input", {})),
                    ))
                    sig = block.get("_gemini_thought_signature")
                    if sig is not None:
                        fc_part.thought_signature = sig
                    parts.append(fc_part)
            contents.append(gt.Content(role="model", parts=parts))
            continue

    return contents


def _from_gemini_response(response) -> "LLMResponse":
    text_parts: list[str] = []
    tool_uses: list[ToolUse] = []
    candidates = getattr(response, "candidates", None) or []
    if not candidates:
        return LLMResponse(text="", tool_uses=[], raw_content=[])
    for part in candidates[0].content.parts:
        if getattr(part, "text", None) is not None:
            text_parts.append(part.text)
        fc = getattr(part, "function_call", None)
        if fc is not None:
            args = fc.args if isinstance(fc.args, dict) else dict(fc.args or {})
            sig = getattr(part, "thought_signature", None)
            tool_uses.append(ToolUse(
                id=f"gemfc_{uuid.uuid4().hex[:8]}", name=fc.name, input=args,
                thought_signature=sig,
            ))
    return LLMResponse(text="".join(text_parts), tool_uses=tool_uses,
                       raw_content=list(candidates[0].content.parts))


DEFAULT_GEMINI_MODEL = "gemini-3.1-flash-lite"


class GeminiClient(LLMClient):
    def __init__(self, model: str | None = None, max_tokens: int = 4096) -> None:
        self.model = model or os.environ.get("GEMINI_MODEL", DEFAULT_GEMINI_MODEL)
        self.max_tokens = max_tokens

    def complete(self, messages, tools, system) -> LLMResponse:
        from google.genai import types as gt
        config = gt.GenerateContentConfig(
            system_instruction=system,
            tools=_to_gemini_tools(tools),
            max_output_tokens=self.max_tokens,
        )
        contents = _to_gemini_contents(messages)
        response = _gemini_client().models.generate_content(
            model=self.model,
            contents=contents,
            config=config,
        )
        return _from_gemini_response(response)
