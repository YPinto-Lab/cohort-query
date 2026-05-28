"""Single source of truth for the branching policy.

Used by both the git pre-commit hook (pre_commit.py) and the Claude Code
PreToolUse hook (claude_guard.py). Pure functions, stdlib only.
"""
import re

ALLOWED_PREFIXES = ("feature", "bug", "refactor", "docs", "chore", "experiment")

BRANCH_REGEX = re.compile(
    r"^(?:feature|bug|refactor|docs|chore|experiment)-[a-z0-9-]+(?:/[a-z0-9-]+)?$"
)


def is_allowed_branch(name: str) -> bool:
    """True if `name` is a valid branch to commit on."""
    if name == "main":
        return False
    return bool(BRANCH_REGEX.match(name))
