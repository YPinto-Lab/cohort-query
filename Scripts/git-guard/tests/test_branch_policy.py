import pytest

from branch_policy import is_allowed_branch


@pytest.mark.parametrize("name", [
    "feature-add-login",
    "bug-fix-crash",
    "refactor-extract-engine",
    "docs-readme-cleanup",
    "chore-bump-deps",
    "experiment-new-clustering",
    "feature-foo/auth",
    "feature-foo/ui-tweaks",
])
def test_allowed_branches(name):
    assert is_allowed_branch(name) is True


@pytest.mark.parametrize("name", [
    "main",
    "master",
    "develop",
    "Feature-add-login",            # uppercase
    "feature_add_login",            # underscore
    "feature-add login",            # space
    "wip-something",                # unknown prefix
    "feature",                      # no slug
    "feature-",                     # empty slug
    "feature-foo/bar/baz",          # nested too deep
    "feature-foo/",                 # empty sub-slug
])
def test_rejected_branches(name):
    assert is_allowed_branch(name) is False
