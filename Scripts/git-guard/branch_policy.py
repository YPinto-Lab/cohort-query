"""Single source of truth for the branching policy.

Used by both the git pre-commit hook (pre_commit.py) and the Claude Code
PreToolUse hook (claude_guard.py). Pure functions, stdlib only.
"""
import re

ALLOWED_PREFIXES = ("feature", "bug", "refactor", "docs", "chore", "experiment")

BRANCH_REGEX = re.compile(
    r"^(?:feature|bug|refactor|docs|chore|experiment)/[a-z0-9-]+(?:/[a-z0-9-]+)?$"
)


def is_allowed_branch(name: str) -> bool:
    """True if `name` is a valid branch to commit on."""
    if name == "main":
        return False
    return bool(BRANCH_REGEX.match(name))


RULE_MESSAGE = (
    "Branching policy violation.\n"
    "  Direct work on `main` is forbidden. Commits and edits must happen on a\n"
    "  branch named: <prefix>/<slug>[/<sub-slug>]\n"
    "  Allowed prefixes: feature, bug, refactor, docs, chore, experiment.\n"
    "  Example: `git fetch origin && git switch -c feature/my-task origin/main`."
)

# Each pattern is a regex that, if matched, means the bash command is forbidden
# while on a disallowed branch (or, in the case of branch-delete commands,
# forbidden unconditionally for agents).
_DANGEROUS_PATTERNS = [
    re.compile(r"(^|[\s;&|()`])git\s+commit(\s|$)"),
    re.compile(r"(^|[\s;&|()`])git\s+merge(\s|$)"),
    re.compile(r"(^|[\s;&|()`])git\s+checkout\s+main(\s|$)"),
    re.compile(r"(^|[\s;&|()`])git\s+switch\s+main(\s|$)"),
    re.compile(r"(^|[\s;&|()`])git\s+branch\s+-[dD](\s|$)"),
    re.compile(r"(^|[\s;&|()`])git\s+push\s+\S+\s+--delete(\s|$)"),
]


def is_dangerous_bash(command: str) -> bool:
    """True if the shell command contains a guarded git operation."""
    return any(p.search(command) for p in _DANGEROUS_PATTERNS)


_DELETE_PATTERNS = [
    re.compile(r"(^|[\s;&|()`])git\s+branch\s+-[dD](\s|$)"),
    re.compile(r"(^|[\s;&|()`])git\s+push\s+\S+\s+--delete(\s|$)"),
]


def is_branch_delete(command: str) -> bool:
    """True if the command tries to delete a branch (always forbidden for agents)."""
    return any(p.search(command) for p in _DELETE_PATTERNS)


# Commands that switch to a protected branch — forbidden regardless of current branch.
_CHECKOUT_PROTECTED_PATTERNS = [
    re.compile(r"(^|[\s;&|()`])git\s+checkout\s+main(\s|$)"),
    re.compile(r"(^|[\s;&|()`])git\s+switch\s+main(\s|$)"),
]


def is_checkout_protected(command: str) -> bool:
    """True if the command attempts to switch to a protected branch (e.g. main)."""
    return any(p.search(command) for p in _CHECKOUT_PROTECTED_PATTERNS)
