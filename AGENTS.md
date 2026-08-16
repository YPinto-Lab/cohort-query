# AGENTS.md

## What this repo is
Ask-SLM is a read-only Python package that turns a plain-language research question into a
cross-study metagenomic feature table (`.biom`). An LLM translates the question into SQL per
metadata source; the package previews the cohort cheaply and, on confirmation, materializes one
biom over a prebuilt SRA × Metalog DuckDB mirror. Scope ends at the file — analysis is out.

## Status
**Pre-implementation.** The pre-pivot workspace/agent/web code has been deleted. `src/askslm/`
currently holds only what the new design reuses: `sra_schema.py` and `taxonomy.lineage_table`.
The seven-package layout below is specified but not written.

## Architecture
Layered / hexagonal. The domain core knows nothing about DuckDB, Gemini, or the filesystem;
those are adapters behind two ports (`LlmBackend`, `Database`). The composition root
(`runtime.py`) wires concretes. Dependencies point inward; the core points at nothing.

- `askslm/` (root) — facade (`config`, `ask`, `load_plan`) + `runtime` + `settings`
- `sources/` — the flat source model: one DuckDB table ↔ one `Source`
- `translation/` — question + schemas → one SQL per **metadata** source, behind the LLM port
- `plan/` — the reviewable, persistable artifact and its cohort preview
- `cohort/` — the BioSample key, the SRA/Metalog/shared partition, and the build engine
- `db/` — the read-only DuckDB seam and `BiomFactory`
- `cli/` — the interactive terminal app (the only thing the user touches); owns no domain logic

`Scripts/build_mirror/` is a separate ETL, not part of the package. The package never writes.

## Key invariants
- **One key:** columns are NCBI BioSample, stamped onto every mirror table at build time.
- **One family per biom:** STAT / METAPHLAN / MOTUS — a shared feature namespace *and* abundance
  estimator. Cross-family pooling is rejected on construction.
- **Native granularity:** no rank knob, no build-time roll-up or normalization.
- **Two DataFrames:** metadata and lineage never merge.
- **Trust input, fail fast:** no defensive validation past `config()`.
- **Serialization:** biom **JSON** — HDF5 cannot round-trip nested lineage metadata.

Full model: `Docs/superpowers/specs/2026-06-17-askslm-architecture-hld-lld.html`.

## Validation workflow
- Install: `pip install -r Docs/requirements.txt && pip install -e .`
- Tests: `python -m pytest Tests -q` (currently empty — the suite went with the deleted code).
- The package needs a prebuilt mirror; see `Scripts/build_mirror/` and the README.

## Documentation maintenance
If you change flow, contracts, or outputs, update `CLAUDE.md`, `AGENTS.md`, and the HLD/LLD spec
in the same change set.
