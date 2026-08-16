"""askslm scaffold CLI: stamp the locked workspace phase tree. Entry point: main().

Run from the repo root — paths are resolved against `Workspaces/` in the working directory.
Conventions it encodes are the law in AGENTS.md; rationale is in
Docs/superpowers/specs/2026-06-03-workspace-tooling-design.html.
"""
import argparse
from pathlib import Path

WORKSPACES = Path("Workspaces")

SHARED_STUB = '''"""(workspace, {phase}) helpers — study-specific. Promote a step here only when a 2nd script needs it."""
'''

BUILD_PY = '''"""build (ingest + assemble): the atomic feature table -> feature_table.biom. Run once."""
from askslm import workspace

ws = workspace.phase(__file__)

# read raw sources from ws.inputs (one Accessor each) and assemble ONE biom.Table:
#   counts (atomic self_count) + feature metadata (lineage) + sample metadata.
# then write biom JSON (HDF5 can't round-trip nested lineage metadata):
# (ws.result / "feature_table.biom").write_text(table.to_json("askslm-build"))
'''

BUILD_MD = '''---
kind: build
intent: assemble the atomic feature table for this study
input: 0_inputs/
outputs: [feature_table.biom]
---
The one run-once building block: counts + lineage feature metadata + sample metadata.
'''

EXPLORE_PY = '''"""transform · {exploration}: shape the feature table, write result/feature_table.biom."""
from askslm import workspace

ws = workspace.phase(__file__)
feature_table = ws.upstream()                       # 1_build/feature_table.biom

# shape it with biom calls + ws.shared helpers: restrict clade / roll up rank / cohort / norm.
# feature_table = ws.shared.<helper>(feature_table)

(ws.result / "feature_table.biom").write_text(      # biom JSON — HDF5 can't round-trip lineage
    feature_table.to_json("askslm-{exploration}"))
'''

EXPLORE_MD = '''---
kind: transform
intent: one line — what this exploration shapes
input: ../../1_build/feature_table.biom
outputs: [result/feature_table.biom]
---
What this exploration keeps/rolls-up, and why.
'''

ANALYSIS_PY = '''"""analyze · {exploration} / {name}: measure the exploration's feature table."""
from askslm import workspace

ws = workspace.phase(__file__)
feature_table = ws.upstream()                        # the exploration's result/feature_table.biom

# measure with skbio / scipy + ws.shared, then write:
# result.to_csv(ws.result / "{name}.csv", index=False)
# ws.shared.<plot>(result, ws.result / "{name}.png")
'''

ANALYSIS_MD = '''---
kind: analysis
intent: one line — what this measures
input: ../../../2_transform/{exploration}/result/feature_table.biom
outputs: [result/{name}.csv, result/{name}.png]
---
What this analysis measures and the headline finding.
'''


def workspace_new(name: str, root: Path = WORKSPACES) -> None:
    base = root / name
    _write(base / "0_inputs" / ".keep", "")
    _write(base / "1_build" / "build.py", BUILD_PY)
    _write(base / "1_build" / "build.md", BUILD_MD)
    _write(base / "2_transform" / "shared.py", SHARED_STUB.format(phase="transform"))
    _write(base / "3_analyze" / "shared.py", SHARED_STUB.format(phase="analyze"))


def transform_add(name: str, exploration: str) -> None:
    folder = WORKSPACES / name / "2_transform" / exploration
    _write(folder / "explore.py", EXPLORE_PY.format(exploration=exploration))
    _write(folder / "explore.md", EXPLORE_MD)


def analysis_add(name: str, exploration: str, analysis: str) -> None:
    folder = WORKSPACES / name / "3_analyze" / exploration / analysis
    _write(folder / "analysis.py", ANALYSIS_PY.format(exploration=exploration, name=analysis))
    _write(folder / "analysis.md", ANALYSIS_MD.format(exploration=exploration, name=analysis))


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def main(argv: list[str] | None = None) -> None:
    args = _build_parser().parse_args(argv)
    _dispatch(args)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="askslm")
    groups = parser.add_subparsers(dest="group", required=True)
    _add_workspace(groups)
    _add_transform(groups)
    _add_analysis(groups)
    return parser


def _add_workspace(groups) -> None:
    actions = groups.add_parser("workspace").add_subparsers(dest="action", required=True)
    new = actions.add_parser("new")
    new.add_argument("name")


def _add_transform(groups) -> None:
    actions = groups.add_parser("transform").add_subparsers(dest="action", required=True)
    add = actions.add_parser("add")
    add.add_argument("name")
    add.add_argument("exploration")


def _add_analysis(groups) -> None:
    actions = groups.add_parser("analysis").add_subparsers(dest="action", required=True)
    add = actions.add_parser("add")
    add.add_argument("name")
    add.add_argument("exploration")
    add.add_argument("analysis")


def _dispatch(args) -> None:
    if args.group == "workspace":
        return workspace_new(args.name)
    if args.group == "transform":
        return transform_add(args.name, args.exploration)
    if args.group == "analysis":
        return analysis_add(args.name, args.exploration, args.analysis)
