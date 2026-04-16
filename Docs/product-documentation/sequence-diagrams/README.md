# Ask-SLM Sequence Diagrams (WebSequenceDiagrams Sources)

These files are ready to paste into https://www.websequencediagrams.com/app.

Open `index.html` in this folder for the main navigation UI across all diagrams.
Open `viewer.html?diagram=<diagram-id>` for a dedicated per-diagram page with previous/next navigation.

## Recommended Reading Order

1. `00-system-context.wsd`
2. `01-runner-end-to-end.wsd`
3. `04-stage-cache-decisions.wsd`
4. `03-mapping-config-lifecycle.wsd`
5. `05-envo-resolution-flow.wsd`
6. `07-manager-runtime-interaction.wsd`
7. `06-cli-analysis-flow.wsd`
8. `02-input-aggregation-and-canonicalization.wsd`

## Diagram Catalog

- `00-system-context.wsd`  
  High-level architecture and boundaries for Notebook and CLI usage.

- `01-runner-end-to-end.wsd`  
  Main `runner.ipynb` execution sequence with workflows, cache, and managers.

- `02-input-aggregation-and-canonicalization.wsd`  
  How multiple source CSV parts are aggregated into canonical workspace inputs.

- `03-mapping-config-lifecycle.wsd`  
  Template generation, interactive mapping UI flow, and per-project JSON output.

- `04-stage-cache-decisions.wsd`  
  Enrichment/taxonomy/merge cache-hit vs cache-miss decision path.

- `05-envo-resolution-flow.wsd`  
  ENVO term detection, OLS4 lookup, fallback behavior, and dictionary export.

- `06-cli-analysis-flow.wsd`  
  CLI parse/dispatch, load+enrich, analysis execution, and output artifacts.

- `07-manager-runtime-interaction.wsd`  
  Notebook manager startup behavior, logger injection, and shared lineage DB reuse.

## How To Render

1. Open https://www.websequencediagrams.com/app
2. Open any `.wsd` file from this folder
3. Paste content into the editor
4. Select a style theme and export PNG/SVG for docs

## Suggested Use In Product Documentation

- Architecture chapter: `00-system-context.wsd`
- Runtime chapter: `01-runner-end-to-end.wsd` + `04-stage-cache-decisions.wsd`
- Data governance chapter: `02-input-aggregation-and-canonicalization.wsd` + `03-mapping-config-lifecycle.wsd`
- Ontology chapter: `05-envo-resolution-flow.wsd`
- UX/operations chapter: `07-manager-runtime-interaction.wsd`
- Automation chapter: `06-cli-analysis-flow.wsd`

## Maintenance Rule

When changing pipeline contracts (inputs, cache stamps, artifact paths, manager APIs), update the matching `.wsd` file in the same pull request.