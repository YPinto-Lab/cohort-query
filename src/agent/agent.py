from __future__ import annotations
from typing import Iterator

from agent.workspace import Workspace
from agent.session import Session
from agent.events import Event
from agent.llm_client import LLMClient
from agent.tools import default_registry
from agent.tools.registry import Registry
from agent.loop import run


class Agent:
    def __init__(
        self,
        workspace: Workspace,
        llm: LLMClient,
        registry: Registry = default_registry,
    ) -> None:
        self.session = Session.start(workspace)
        self.llm = llm
        self.registry = registry

    def chat(self, message: str) -> Iterator[Event]:
        yield from run(self.session, self.llm, self.registry, user_message=message)
