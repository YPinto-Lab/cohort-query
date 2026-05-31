# CLAUDE.md

## Project Overview

Ask-SLM is a metagenomic analysis toolkit for querying and analyzing SRA (Sequence Read Archive) datasets. 
- analysis and manipulation of metadata,
- Analysis and manipulation of taxonomy
- Facilitates and enables the activation of various existing statistical tools.

## Layer Architecture

Dependencies flow downward only. Never import upward.

| Layer | Folder | Role |
|---|---|---|
| Client | `Clients/` | Public Python API (`askslm.metadata`, `askslm.taxonomy`). A user-facing CLI/UI is deferred to a separate layer. |
| Engine | `Engines/` | Business logic — pure computation, no I/O |
| Accessor | `Accessors/` | External resources — files, APIs, databases |
| Utilities | `Common/` | Cross-cutting — Logger, RunnerContext, contracts |

**Calling rules:** Client → Engine → Accessor. Never call upward.

`Scripts/` and `Queries/` are developer tooling outside the layer model.

## Workspace Structure

`Workspaces/` is the canonical runtime folder (git ignored). Each named workspace:

```
Workspaces/
└── <WorkspaceName>/
    ├── inputs/
    │   ├── metadata_parts/
    │   ├── taxonomy_parts/
    │   ├── mapping_configs/
    │   └── appendix/
    └── results/
        ├── metadata-overview/
        └── ...
```

Entry point: `askslm.py` (thin shell). Implementation: `Clients/cli.py`.

## API Design Decisions

### Two-level structure

```python
api = AskSLMAPI(workspaces_root="./Workspaces")
workspace = api.create_workspace("my_study")   # creates folder skeleton, returns Workspace
workspace = api.open_workspace("my_study")     # opens existing, returns Workspace

workspace.analyze_metadata()
workspace.alpha_diversity(rank="genus")
```

`AskSLMAPI` is the factory. `Workspace` holds paths and config, delegates to engines.

### Disk-first operations

Workspace operations write results to disk under `Workspaces/<name>/results/`. They return a result handle, not raw data. The disk record is the source of truth.

### Idempotency

Every operation is safe to run more than once. If the inputs have not changed since the last run, skip the operation and return the existing result. If they have changed, recompute and overwrite.

### Lazy result objects

Result objects do not load data at construction. Data loads on first property access.

```python
result = workspace.analyze_metadata()
result.summary_path   # instant — just a Path
result.df             # triggers CSV read on first access, cached after
```

## Key Conventions

- **Two-DataFrame rule:** `metadata_df` and `taxonomy_df` are always kept separate. Never merge them into one DataFrame until a narrow, intentional analysis requires it.
- **Each Accessor reads exactly one source.** Joins belong in Managers or Engines, not Accessors.

## Branching Policy (enforced)

All write-tasks happen on a branch off `main`. Direct work on `main` is forbidden.
The rule is enforced by a Claude Code PreToolUse hook and a git pre-commit hook
(see `Scripts/git-guard/`). Disable the hooks only with explicit user authorization.

**Allowed top-level prefixes:** `feature-`, `bug-`, `refactor-`, `docs-`, `chore-`, `experiment-`.

**Sub-branches:** for big features that fan out across subagents, name children
`<parent>/<sub-slug>` (e.g. `feature-foo/auth`). Sub-branches merge back into
their parent with `git merge --no-ff`; only the parent is merged to `main`.

**Merging to `main`:** push the branch, open a PR with `gh pr create --base main`,
then stop. The user squash-merges through GitHub.

**Never delete branches.** Branches are archival history; only the user deletes
them, manually, after a long time. Never run `git branch -d`, `git branch -D`,
or `git push origin --delete`.

**Starting a write-task:** if you're on `main` or any non-prefixed branch, the
first thing you do is create and switch:

    git fetch origin && git switch -c <prefix>-<slug> origin/main

Then announce the branch in your first user-facing message.
