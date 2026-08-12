# CLAUDE.md

## Project Overview

Ask-SLM is a workbench that makes metagenomic analysis easy and reproducible. The user works
entirely through a **web UI**, chatting with an **LLM agent** that builds and analyzes the study
with them — from raw inputs to results — and answers questions about the data.

The agent works by authoring and running Python against the `askslm` package and established
libraries (biom, ete3, scikit-bio, scipy, pandas), standardizing everything into one structure:
a **biom feature table** (counts + sample metadata + feature lineage).

Each study is a reproducible **workspace**: a plain folder of files on disk (Python scripts,
`.biom` tables, CSVs, plots), organized into phases (build → transform → analyze). The disk is
the source of truth; the web UI is the driver, not a walled garden. `Workspaces/ABX_new` is the
canonical example. The domain today is metagenomics; the structure is general enough to extend.

Design source of truth: `Docs/feature-table-and-library-palette.html`.

## Layout

```
src/askslm/   the toolbox the agent calls (workspace phase tooling, metadata, taxonomy, accessors, cli)
src/agent/    the LLM agent (run_python + session + registry)
src/web/      the web UI — the only thing the user touches
Workspaces/   runtime studies (git-ignored); ABX_new is canonical
Docs/ Tests/ Scripts/git-guard/
```

## The feature table

One `biom.Table` per community study: counts (features × samples) + sample metadata + feature
metadata (lineage). Five operation kinds — ingest, build, transform, split, analyze — delegate to
the library palette; Ask-SLM adds only the small logic libraries lack (chiefly `lineage_table`).
We trust input and fail fast: no defensive validation outside the accessor boundary.

## Branching Policy (enforced)

All write-tasks happen on a branch off `main`. Direct work on `main` is forbidden.
The rule is enforced by a Claude Code PreToolUse hook and a git pre-commit hook
(see `Scripts/git-guard/`). Disable the hooks only with explicit user authorization.

**Allowed top-level prefixes:** `feature/`, `bug/`, `refactor/`, `docs/`, `chore/`, `experiment/`.

**Sub-branches:** for big features that fan out across subagents, name children
`<parent>/<sub-slug>` (e.g. `feature/foo/auth`). Sub-branches merge back into
their parent with `git merge --no-ff`; only the parent is merged to `main`.

**Merging to `main`:** push the branch, open a PR with `gh pr create --base main`,
then stop. The user squash-merges through GitHub.

**Never delete branches.** Branches are archival history; only the user deletes
them, manually, after a long time. Never run `git branch -d`, `git branch -D`,
or `git push origin --delete`.

**Starting a write-task:** if you're on `main` or any non-prefixed branch, the
first thing you do is create and switch:

    git fetch origin && git switch -c <prefix>/<slug> origin/main

Then announce the branch in your first user-facing message.
