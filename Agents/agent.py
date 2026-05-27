from __future__ import annotations
from typing import Iterator

from Agents.workspace import Workspace
from Agents.session import Session
from Agents.events import Event
from Agents.llm_client import LLMClient
from Agents.tools import default_registry
from Agents.tools.registry import Registry
from Agents.loop import run


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
