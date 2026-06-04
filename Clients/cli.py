"""askslm scaffold CLI: stamp the locked workspace phase tree. Entry point: main().

Conventions it encodes are the law in AGENTS.md; rationale is in
Docs/superpowers/specs/2026-06-03-workspace-tooling-design.html.
"""
import argparse
from pathlib import Path

WORKSPACES = Path("Workspaces")

SHARED_STUB = '''"""(workspace, {phase}) helpers — study-specific. Promote a step here only when a 2nd script needs it."""
'''

BUILD_PY = '''"""build (ingest + assemble): the atomic community -> community.biom. Run once."""
from askslm import workspace

ws = workspace.phase(__file__)

# read raw sources from ws.inputs (one Accessor each) and assemble ONE biom.Table:
#   counts (atomic self_count) + feature metadata (lineage) + sample metadata.
# then write biom JSON (HDF5 can't round-trip nested lineage metadata):
# (ws.result / "community.biom").write_text(table.to_json("askslm-build"))
'''

BUILD_MD = '''---
kind: build
intent: assemble the atomic community for this study
input: 0_inputs/
outputs: [community.biom]
---
The one run-once building block: counts + lineage feature metadata + sample metadata.
'''

EXPLORE_PY = '''"""transform · {exploration}: shape the community, write result/community.biom."""
from askslm import workspace

ws = workspace.phase(__file__)
community = ws.upstream()                       # 1_build/community.biom

# shape it with biom calls + ws.shared helpers: restrict clade / roll up rank / cohort / norm.
# community = ws.shared.<helper>(community)

(ws.result / "community.biom").write_text(      # biom JSON — HDF5 can't round-trip lineage
    community.to_json("askslm-{exploration}"))
'''

EXPLORE_MD = '''---
kind: transform
intent: one line — what this exploration shapes
input: ../../1_build/community.biom
outputs: [result/community.biom]
---
What this exploration keeps/rolls-up, and why.
'''

ANALYSIS_PY = '''"""analyze · {exploration} / {name}: measure the exploration's community."""
from askslm import workspace

ws = workspace.phase(__file__)
community = ws.upstream()                        # the exploration's result/community.biom

# measure with skbio / scipy + ws.shared, then write:
# result.to_csv(ws.data / "{name}.csv", index=False)
# ws.shared.<plot>(result, ws.plots / "{name}.png")
'''

ANALYSIS_MD = '''---
kind: analysis
intent: one line — what this measures
input: ../../../2_transform/{exploration}/result/community.biom
outputs: [data/{name}.csv, plots/{name}.png]
---
What this analysis measures and the headline finding.
'''


def workspace_new(name: str) -> None:
    root = WORKSPACES / name
    _write(root / "0_inputs" / ".keep", "")
    _write(root / "1_build" / "build.py", BUILD_PY)
    _write(root / "1_build" / "build.md", BUILD_MD)
    _write(root / "2_transform" / "shared.py", SHARED_STUB.format(phase="transform"))
    _write(root / "3_analyze" / "shared.py", SHARED_STUB.format(phase="analyze"))


def transform_add(name: str, exploration: str) -> None:
    folder = WORKSPACES / name / "2_transform" / exploration
    _write(folder / "explore.py", EXPLORE_PY.format(exploration=exploration))
    _write(folder / "explore.md", EXPLORE_MD.format(exploration=exploration))


def analysis_add(name: str, exploration: str, analysis: str) -> None:
    folder = WORKSPACES / name / "3_analyze" / exploration / analysis
    _write(folder / "analysis.py", ANALYSIS_PY.format(exploration=exploration, name=analysis))
    _write(folder / "analysis.md", ANALYSIS_MD.format(exploration=exploration, name=analysis))


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def main(argv=None) -> None:
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
    return analysis_add(args.name, args.exploration, args.analysis)
