# CLAUDE.md

## Project Overview

Ask-SLM is a **read-only pip package** that turns a research question into a cross-study
metagenomic feature table. The user asks in plain language ("fecal metagenomes from adults with
IBD, Western countries"); an LLM translates that into SQL per metadata source; the package
previews the cohort, and on confirmation materializes one `.biom`. Scope ends at the file —
analysis is whatever the user already uses.

The user surface is an **interactive terminal app** (`questionary` + `rich`). Two verbs sit
underneath it: `ask()` understands the question and previews the cohort cheaply; `run()`
materializes the biom and is the only place profile sources are named. A saved plan replays
without the LLM.

All data is read from **one prebuilt DuckDB mirror** of SRA × Metalog, opened read-only. The
package never builds or writes it — `Scripts/build_mirror/` does, run once by the lab.

**Design source of truth:** `Docs/superpowers/specs/2026-06-17-askslm-architecture-hld-lld.html`
(HLD/LLD) and its parent `2026-06-17-askslm-sra-metalog-cohort-design.html` (the why).

## Layout

```
src/askslm/         the package (currently: the material that survived the pivot)
  sra_schema.py     SRA column contracts — seeds SchemaCatalog's LLM prompt
  catalog.py        schema_catalog -> prompt text (columns + REAL value vocabularies)
  prompt.py         the system instruction, isolated so eval can attribute prompt diffs
  translation.py    Translator: question + schemas -> Translation
  plan.py           Plan (the reviewable, re-runnable artifact); save/load_plan JSON round-trip
  settings_file.py  where config() gets its args: env -> ~/.askslm/config.toml -> first-run prompt
  cli/              the terminal app; questionary/rich live here and nowhere else
    render.py       pure formatting (preview line, narrow warning, overlap rows) — unit tested
    session.py      the loop: `$ askslm` and `askslm run plan.json`; glue, verified by running it
  taxonomy/         lineage_table — ete3 tax_id -> lineage, needed for STAT features
Scripts/build_mirror/   the separate ETL that builds the DuckDB mirror
Scripts/eval/       the translation eval set + execution-accuracy scorer (H.3)
Docs/ Tests/ Scripts/git-guard/
```

The pre-pivot workspace/agent/web code was deleted; the HLD's seven-package layout
(`sources/ translation/ plan/ cohort/ db/ cli/`) is not built yet.

## The feature table

One `biom.Table` per cohort: counts (features × samples) + sample metadata + feature metadata
(lineage). Columns are keyed by **NCBI BioSample**, stamped onto every mirror table at build.
One biom holds one **profiler family** (STAT / METAPHLAN / MOTUS) — sources sharing a feature
namespace *and* an abundance estimator; cross-family pooling is rejected. Bioms ship each
source's **native granularity** — no rank knob. We trust input and fail fast: no defensive
validation past `config()`.

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
