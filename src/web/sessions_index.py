from __future__ import annotations
import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SessionEntry:
    id: str
    path: Path
    title: str


def list_sessions(agent_log_dir: Path) -> list[SessionEntry]:
    if not agent_log_dir.is_dir():
        return []
    entries: list[SessionEntry] = []
    for p in sorted(agent_log_dir.glob("*.jsonl"), reverse=True):
        title = _first_user_message(p) or p.stem
        entries.append(SessionEntry(id=p.stem, path=p, title=title))
    return entries


def _first_user_message(path: Path) -> str | None:
    try:
        for line in path.read_text().splitlines():
            rec = json.loads(line)
            if rec.get("type") == "user":
                return str(rec.get("content", ""))[:120]
    except Exception:
        return None
    return None


def load_transcript(path: Path) -> list[dict]:
    return [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
