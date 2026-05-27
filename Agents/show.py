from __future__ import annotations
import json
from pathlib import Path


def format_session(path: Path | str) -> str:
    lines: list[str] = []
    for raw in Path(path).read_text().splitlines():
        if not raw.strip():
            continue
        r = json.loads(raw)
        t = r.get("type")
        if t == "user":
            lines.append(f"You: {r.get('content','')}")
        elif t == "assistant":
            lines.append(f"Assistant: {r.get('content','')}")
        elif t == "tool_call":
            lines.append(f"  -> {r.get('tool')}({r.get('args')})")
        elif t == "tool_result":
            if r.get("is_error"):
                lines.append(f"     ! ERROR: {r.get('error','')}")
            else:
                lines.append(f"     = {r.get('result_summary')} ({r.get('latency_ms',0)}ms)")
        elif t == "error":
            lines.append(f"  ! {r.get('message','')}")
    return "\n".join(lines)
