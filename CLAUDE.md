# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Ask-SLM is an interactive query engine for microbiome/metagenomic analysis that leverages STAT, LOGEN, and MetaLog to extract statistical insights from SRA (Sequence Read Archive) datasets. It's a Jupyter-notebook-based Python application.

## Setup

```bash
pip install -r requirements.txt
```

The main entry point is `runner.ipynb` — open and run it in Jupyter.

For command-line usage:
```bash
python askslm.py alpha-diversity --view PhagesInBlood --rank species --group Group
python askslm.py taxonomic-abundance --view PhagesInBlood --rank genus --taxon Prevotella --group Group
python askslm.py abundance-matrix --view PhagesInBlood
# Outputs go to results/<view>/
```

## iDesign Architecture Cheat Sheet (How To Think Before Coding)

### 1) Core Philosophy: Volatility-Based Decomposition
- Decompose by **what changes**, not by feature buckets.
- Isolate each volatility axis in one component so changes do not ripple across the codebase.
- Goal: if a requirement/algorithm/technology changes, a single layer or component absorbs most of the change.

### 2) Layer Hierarchy (Dependencies Flow Down Only)

1. **Client (Trigger/UI)**
  - Entry points such as Jupyter notebook cells and CLI command invocation.
  - Captures input and presents output.
  - Should not contain business logic.

2. **Manager (Orchestrator / Use-Case Volatility)**
  - Coordinates steps and ordering for a use case.
  - Knows *what* must happen and *when*.
  - Delegates heavy computation and I/O details.

3. **Engine (Rules/Algorithm Volatility)**
  - Pure computation and business logic.
  - Input -> logic -> output, with no external side effects.
  - No direct DB/API/filesystem/UI access.

4. **Accessor (Resource/Technology Volatility)**
  - Only layer allowed to touch external resources (files, APIs, databases, cloud services).
  - Hides technology-specific complexity from Managers/Engines.

### 3) Rules of Engagement (Who Can Call Whom)
- **Client** -> Managers
- **Manager** -> Managers, Engines, Accessors
- **Engine** -> Engines, Accessors (only when data fetch is required)
- **Accessor** -> Accessors, external systems/utilities
- **Never call upward**. Higher layers do not get imported/called by lower layers.

### 4) Key Terms
- **Contract (Interface):** strict agreement between layers (schema models, typed payloads, expected columns).
- **DTO (Data Transfer Object):** data-only payload moved across layers.
- **Encapsulation:** hide implementation details; callers depend on behavior, not internals.
- **Volatility examples:**
  - Algorithm change (e.g., t-test -> Mann-Whitney) => Engine update.
  - Process order change (pipeline step reorder) => Manager update.
  - Resource change (storage/API migration) => Accessor update.

### 5) Python/Data Science Pro Tips
1. Keep Managers thin: orchestrate, do not become 1000-line pandas calculators.
2. Accessors return validated, clean DataFrames that satisfy contracts.
3. Keep UI in notebook/client and logic in `.py` modules.
4. Prefer explicit artifacts and typed contracts over ad-hoc DataFrame assumptions.
5. Preserve the two-DataFrame rule (`metadata_df` separate from `taxonomy_df`) until narrow, intentional joins.

### 6) Ask-SLM Specific Mapping
- **Client:** `runner.ipynb` cells, `askslm.py` CLI entry.
- **Manager:** orchestration flow modules (for example `managers/runner_pipeline_manager.py`).
- **Engine:** business/UI computation modules under `Engines/` (alpha diversity, taxonomic abundance, mapping config, metadata mapping).
- **Accessor:** classes under `Accessors/` and external I/O boundaries.

### 7) Canonical Folders (Current Migration State)
- `Engines/` is the canonical home for engine code.
- `managers/` is retained for orchestration and backward compatibility wrappers.
- New code should import from `Engines/*` and orchestration managers directly.

## Documentation Maintenance Rule (Mandatory)

Any change that affects **flow, architecture, contracts, component responsibilities, stage order, caching behavior, or outputs** must trigger a docs review in the same PR/change set.

Checklist:
1. Did a layer responsibility change (Client/Manager/Engine/Accessor)?
2. Did call direction or dependency flow change?
3. Did input/output artifacts, file locations, or cache stamps change?
4. Did mapping config schema or manager workflow change?
5. Did UML/sequence diagrams become outdated?

If yes to any item, update relevant docs immediately (for example: `CLAUDE.md`, `README.md`, `docs/product-documentation/sequence-diagrams/*`, `docs/product-documentation/uml/*`).

## Engineering Standards & Principles Cheat Sheet

### 1) SOLID Principles

- **Single Responsibility (SRP):** a class/module has one reason to change.
- **Open/Closed (OCP):** extend behavior with new code; avoid editing stable code paths.
- **Liskov Substitution (LSP):** subtypes must preserve base contracts.
- **Interface Segregation (ISP):** prefer focused interfaces over large, mixed interfaces.
- **Dependency Inversion (DIP):** depend on abstractions, not concrete infrastructure.

### 2) Essential Design Patterns (Use Pragmatically)

- **Factory / Abstract Factory / Builder:** controlled construction of objects and families.
- **Adapter / Facade / Decorator / Proxy:** integration boundaries and composition.
- **Strategy / Observer / Command:** pluggable algorithms and decoupled behavior flow.
- Avoid pattern overuse; choose the simplest pattern that solves the current volatility.

### 3) Clean Code (Uncle Bob)

#### Naming
- Use intention-revealing, pronounceable, searchable names.
- Avoid vague distinctions (`data`, `info`, `obj`) and misleading type hints in names.

#### Functions
- Keep functions small and single-purpose.
- Use one abstraction level per function.
- Prefer 0-2 parameters; justify larger signatures.
- Apply Command Query Separation: mutate or return, not both when avoidable.

#### Comments
- Prefer self-explanatory code over verbose comments.
- Keep comments for context/warnings/contracts/TODOs, not narration.
- Delete commented-out dead code (source control retains history).

#### Error Handling
- Prefer exceptions to return-code branching.
- Provide context-rich exception messages.
- Avoid returning `None` where empty objects/collections are safer.

### 4) KISS + YAGNI

- Default to simple, explicit solutions.
- Do not build speculative features.
- Optimize for readability and maintainability over cleverness.
- If two solutions are valid, choose the one future maintainers can understand fastest.

### 5) Implementation Rules For AI/Contributors

1. Before coding, identify the volatility axis (process, algorithm, or resource).
2. Place code in the correct layer (`Accessors`, `Engines`, `managers`, `Client`).
3. Keep dependency direction downward only.
4. Prefer adding new modules/classes over editing stable, reused flows.
5. If changing architecture/flow/contracts, update docs in the same change.

## Input Folder Structure

Each "view" is a named research collection — a folder under `Inputs/` containing two CSV files:

```
Inputs/
└── <ViewName>/          # e.g. PhagesInBlood
    ├── metadata.csv     # 1 row per acc (from sra.metadata Athena table)
    └── taxonomy.csv     # many rows per acc, one per taxon (from sra.tax_analysis)
```

Use `queries/blood_wgs_queries.sql` as a template for the Athena queries. Replace `{project_ids}` with the actual bioproject IDs, run both queries, and export to CSVs in the view folder.

## Mapping Config Format

Each project needs a JSON config in `mapping_configs/`:

```json
{
  "project_id": "PRJEB12345",
  "filters": {
    "exclude_project": false,
    "sample_filters": []
  },
  "mappings": {
    "sex": {"static_value": "female"},
    "subject_id": {"key_name": "submitter_id_sam", "value_mappings": {}},
    "timepoint": {"key_name": "run_file_create_date", "value_mappings": {}}
  },
  "description": ""
}
```

The `.json.template` file (auto-generated by `MetadataMappingEngine`, legacy alias: `SRAProcessor`) shows all discoverable keys and their sample values to inform manual config creation.

## Key Conventions

- **Data validation happens only in Accessors** via pandera schemas — not downstream
- **Taxonomy nested-set model**: `ileft`/`iright` columns encode tree structure; TaxonomyAccessor uses these for lineage queries rather than recursive traversal
- **Two versions of MappingConfigManager exist** (`mapping_config_manager.py` vs `mapping_config_manager_v2.py`); v2 is the current one with target-field-first design
- **Metalog schema** (`scrape_metalog.py`) should be re-run when the remote schema at metalog.embl.de is updated

## Dependencies

`pandas`, `pandera`, `numpy`, `plotly`, `seaborn`, `ipywidgets`, `nbformat`, `rich`, `scipy`
