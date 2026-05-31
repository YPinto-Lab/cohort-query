#!/usr/bin/env python3
"""Claude Code PreToolUse hook: blocks branch-policy violations before tool calls.

Reads a JSON envelope on stdin (Claude Code PreToolUse format):

    {"tool_name": "...", "tool_input": {...}, "cwd": "/abs/path"}

Writes a JSON object on stdout. To block, emits:

    {"decision": "block", "reason": "..."}

To allow, emits empty `{}` (or anything without `decision: block`).
Always exits 0; the harness uses the JSON to decide.
"""
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from branch_policy import (
    RULE_MESSAGE,
    is_allowed_branch,
    is_branch_delete,
    is_checkout_protected,
    is_dangerous_bash,
)

GUARDED_FILE_TOOLS = {"Edit", "Write", "NotebookEdit"}


def current_branch(cwd: str) -> str | None:
    """Branch name at `cwd`, or None if not inside a git repo."""
    try:
        result = subprocess.run(
            ["git", "-C", cwd, "symbolic-ref", "--short", "HEAD"],
            capture_output=True, text=True, check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None
    return result.stdout.strip() or None


def block(reason: str) -> dict:
    return {"decision": "block", "reason": reason}


def decide(payload: dict) -> dict:
    tool = payload.get("tool_name", "")
    tool_input = payload.get("tool_input", {}) or {}
    cwd = payload.get("cwd") or "."

    if tool == "Bash":
        command = tool_input.get("command", "")
        if is_branch_delete(command):
            return block(
                "Branch deletion is forbidden for agents. Branches are archival "
                "and only the human user deletes them, manually."
            )
        if is_checkout_protected(command):
            return block(
                f"Refused: switching to a protected branch is not allowed for agents.\n"
                f"{RULE_MESSAGE}"
            )
        if is_dangerous_bash(command):
            branch = current_branch(cwd)
            if branch is None or not is_allowed_branch(branch):
                return block(
                    f"Refused: branch `{branch}` is not a valid working branch.\n"
                    f"{RULE_MESSAGE}"
                )
        return {}

    if tool in GUARDED_FILE_TOOLS:
        branch = current_branch(cwd)
        if branch is None:
            return {}  # not in a git repo — not our concern
        if not is_allowed_branch(branch):
            return block(
                f"Refused: cannot edit files on branch `{branch}`.\n{RULE_MESSAGE}"
            )
        return {}

    return {}


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError:
        payload = {}
    sys.stdout.write(json.dumps(decide(payload)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
