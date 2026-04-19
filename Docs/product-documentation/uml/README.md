# Ask-SLM UML Diagrams (Code)

These files are UML-as-code using PlantUML (`.puml`).

Use `index.html` in this folder to browse UML diagrams as a mini-website,
and `viewer.html?diagram=<id>` for direct per-diagram pages.

## Important About .wsd

- `.wsd` is designed for sequence diagrams.
- For non-sequence UML (component/class/deployment), use PlantUML or Mermaid.

## Files

- `ask-slm-component-diagram.puml`
  High-level architecture component view.

- `ask-slm-core-class-diagram.puml`
  Core runtime class relationships around the runner pipeline and managers.

## How To Render

### Option 0: Local Docs Website (Recommended)

1. Open `docs/product-documentation/uml/index.html`
2. Click **View UML** on a diagram card
3. Navigate with Previous/Next and return to the main menu

### Option 1: PlantUML Online

1. Open https://www.plantuml.com/plantuml
2. Paste a `.puml` file content
3. Export PNG/SVG

### Option 2: VS Code Extension

1. Install a PlantUML extension
2. Open a `.puml` file
3. Use preview/export commands

## Suggested Placement In Product Docs

- Architecture chapter: `ask-slm-component-diagram.puml`
- Runtime internals chapter: `ask-slm-core-class-diagram.puml`

## Maintenance Rule

When changing workflow contracts, notebook engine dependencies, or cache strategy,
update these UML diagrams in the same pull request.
