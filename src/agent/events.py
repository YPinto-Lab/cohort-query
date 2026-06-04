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
