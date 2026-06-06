---
kind: reference
audience: ask-slm runtime agent
intent: the code-quality bar for any code the agent writes or edits
---

# Ask-SLM code standards

Readability is the highest priority — above brevity, cleverness, and convenience.
Code is read far more than written. When any rule trades against readability, readability wins.

## Shape
- No `else`. Use early returns (guard clauses) or polymorphism.
- Functions do one thing; keep them to ~10 lines. Extract helpers past that. (Tests are exempt.)
- 1–3 parameters, never more. Group related params into a dataclass/DTO. Pass only what is used.
- Write classes, not loose collections of functions. One class per file, ~90% of the time. Keep files small.
- Never use `lambda` — always a named `def`.
- KISS: prefer the clearest expression of the design over cleverness.

## Comments
- Sparse, English, explain *why* not *what*. No redundant comments, no commented-out code.
- Exception — opaque library calls: a short inline comment naming the *domain effect* is encouraged
  (e.g. `# removes genus-and-above`, `# merges sub-species into their species`).

## Domain rules (Ask-SLM specific)
- Reuse libraries — skbio / biom / ete3 / pandas. Write new custom code only on explicit authorization.
- Compose over duplicate: before writing a transformation, find the canonical equivalent and route through it.
- Keep taxonomy and metadata as TWO separate DataFrames — never merge them into one.
- Each Accessor reads and validates exactly ONE source. Joins belong in Processors, not Accessors.
- Trust input, fail fast: do the work or let the library raise. Validation only at the Accessor boundary.
- Prefer typed domain objects over raw DataFrames at API boundaries.
- No backward-compatibility aliases or deprecated re-exports. Rename everywhere and commit clean.
