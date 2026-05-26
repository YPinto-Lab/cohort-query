from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
import uuid

from Agents.workspace import Workspace
from Agents.variable_store import VariableStore
from Agents.transcript import TranscriptWriter


@dataclass
class Session:
    workspace: Workspace
    variables: VariableStore
    transcript: TranscriptWriter
    messages: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def start(cls, workspace: Workspace) -> "Session":
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        sid = f"{stamp}-{uuid.uuid4().hex[:6]}"
        path = workspace.agent_log_dir / f"{sid}.jsonl"
        return cls(
            workspace=workspace,
            variables=VariableStore(),
            transcript=TranscriptWriter(path),
        )

    @property
    def id(self) -> str:
        return self.transcript.path.stem
