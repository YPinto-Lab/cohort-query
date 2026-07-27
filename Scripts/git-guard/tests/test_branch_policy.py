import pytest

from branch_policy import is_allowed_branch


@pytest.mark.parametrize("name", [
    "feature/add-login",
    "bug/fix-crash",
    "refactor/extract-engine",
    "docs/readme-cleanup",
    "chore/bump-deps",
    "experiment/new-clustering",
    "feature/foo/auth",
    "feature/foo/ui-tweaks",
])
def test_allowed_branches(name):
    assert is_allowed_branch(name) is True


@pytest.mark.parametrize("name", [
    "main",
    "master",
    "develop",
    "Feature/add-login",            # uppercase
    "feature_add_login",            # underscore
    "feature/add login",           # space
    "wip/something",                # unknown prefix
    "feature",                      # no slug
    "feature/",                     # empty slug
    "feature/foo/bar/baz",          # nested too deep
    "feature/foo/",                 # empty sub-slug
])
def test_rejected_branches(name):
    assert is_allowed_branch(name) is False


from branch_policy import RULE_MESSAGE, is_dangerous_bash


def test_rule_message_mentions_prefixes_and_main():
    assert "main" in RULE_MESSAGE
    for prefix in ("feature", "bug", "refactor", "docs", "chore", "experiment"):
        assert prefix in RULE_MESSAGE


@pytest.mark.parametrize("cmd", [
    "git commit -m 'x'",
    "git commit",
    "git  commit --amend",
    "git merge feature/foo",
    "git checkout main",
    "git switch main",
    "git branch -d feature/old",
    "git branch -D feature/old",
    "git push origin --delete feature/old",
    "echo hi && git commit -m x",      # compound command
])
def test_dangerous_bash_detected(cmd):
    assert is_dangerous_bash(cmd) is True


@pytest.mark.parametrize("cmd", [
    "git status",
    "git log",
    "git diff",
    "git switch -c feature/new",
    "git checkout feature/foo",
    "git commit-tree",                  # not the same as `git commit`
    "echo committing",                  # word `commit` in plain text
])
def test_safe_bash_not_flagged(cmd):
    assert is_dangerous_bash(cmd) is False


from branch_policy import is_branch_delete


@pytest.mark.parametrize("cmd", [
    "git branch -d feature/old",
    "git branch -D feature/old",
    "git push origin --delete feature/old",
])
def test_branch_delete_detected(cmd):
    assert is_branch_delete(cmd) is True


@pytest.mark.parametrize("cmd", [
    "git commit -m x",
    "git push origin feature/foo",
    "git branch feature/new",
])
def test_non_delete_not_flagged(cmd):
    assert is_branch_delete(cmd) is False
