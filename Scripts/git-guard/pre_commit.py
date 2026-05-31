#!/usr/bin/env python3
"""Git pre-commit hook: rejects commits on `main` or non-policy branches.

Installed into .git/hooks/pre-commit by Scripts/git-guard/install.sh.
Reads the current branch and consults branch_policy.is_allowed_branch.
"""
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from branch_policy import RULE_MESSAGE, is_allowed_branch


def current_branch() -> str:
    result = subprocess.run(
        ["git", "symbolic-ref", "--short", "HEAD"],
        capture_output=True, text=True, check=True,
    )
    return result.stdout.strip()


def main() -> int:
    try:
        branch = current_branch()
    except subprocess.CalledProcessError:
        # detached HEAD — let git handle it; not our policy concern
        return 0
    if is_allowed_branch(branch):
        return 0
    print(f"\n[git-guard] Refusing commit on branch `{branch}`.", file=sys.stderr)
    print(RULE_MESSAGE, file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
