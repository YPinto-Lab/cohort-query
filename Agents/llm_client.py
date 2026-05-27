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
