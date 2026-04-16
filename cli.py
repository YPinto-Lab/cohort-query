"""
Ask-SLM Command Line Interface.

Provides non-interactive access to analyses for use on remote servers or
in scripted pipelines. Each command reads from a named view folder
(Inputs/<view>/metadata.csv + taxonomy.csv), applies mapping configs,
runs the requested analysis, and writes structured outputs to results/<view>/.

Usage examples:
    python askslm.py alpha-diversity     --view PhagesInBlood --rank species --group Group
    python askslm.py taxonomic-abundance --view PhagesInBlood --rank genus --taxon Prevotella --group Group
    python askslm.py abundance-matrix    --view PhagesInBlood
"""
import argparse
import sys
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import plotly.express as px

from Common.contracts.sra_schema import SRAMetadataSchema


_BASE_METADATA_COLS = set(SRAMetadataSchema.__fields__.keys())


def _load_and_enrich(view: str, inputs_dir: Path, config_dir: Path):
    """Load both DataFrames for a view and apply mapping configs."""
    import sys, os
    if os.getcwd() not in sys.path:
        sys.path.insert(0, os.getcwd())

    from Accessors.SraAccessor.sra_metadata_accessor import SRAMetadataAccessor
    from Accessors.SraAccessor.sra_taxonomy_accessor import SRATaxonomyAccessor
    from Engines.MetadataMappingEngine.metadata_mapping_engine import MetadataMappingEngine

    view_path = inputs_dir / view
    if not view_path.is_dir():
        print(f"Error: view folder not found: {view_path}", file=sys.stderr)
        sys.exit(1)

    print(f"Loading metadata from {view_path / 'metadata.csv'} ...")
    metadata_df = SRAMetadataAccessor.get(view_path / "metadata.csv")

    print(f"Loading taxonomy from {view_path / 'taxonomy.csv'} ...")
    taxonomy_df = SRATaxonomyAccessor.get(view_path / "taxonomy.csv")

    print(f"Loaded: {len(metadata_df)} samples, {len(taxonomy_df)} taxon observations")

    # Apply mapping configs per project
    processor = MetadataMappingEngine(config_dir=config_dir)
    parts = []
    for project_id in metadata_df['bioproject'].unique():
        config_path = config_dir / f"{project_id}.json"
        if not config_path.exists():
            print(f"  [skip] No config for {project_id} — using raw metadata")
            parts.append(metadata_df[metadata_df['bioproject'] == project_id].copy())
            continue
        project_df = metadata_df[metadata_df['bioproject'] == project_id].copy()
        parts.append(processor.process(project_df, project_id))

    enriched_metadata_df = pd.concat(parts, ignore_index=True)
    return taxonomy_df, enriched_metadata_df


def _ensure_output_dir(output_dir: Path, view: str, analyzer: str | None = None) -> Path:
    out = output_dir / view
    if analyzer:
        out = out / analyzer
    out.mkdir(parents=True, exist_ok=True)
    return out


# ── Commands ──────────────────────────────────────────────────────────────────

def cmd_alpha_diversity(args):
    from Engines.AlphaDiversityComputationEngine.alpha_diversity_computation_engine import compute_alpha_diversity

    taxonomy_df, metadata_df = _load_and_enrich(
        args.view, Path(args.inputs_dir), Path(args.config_dir)
    )
    out_dir = _ensure_output_dir(Path(args.output_dir), args.view, "alpha_diversity")

    print(f"Computing alpha diversity at rank '{args.rank}' ...")
    diversity_df = compute_alpha_diversity(
        taxonomy_df=taxonomy_df,
        metadata_df=metadata_df,
        rank=args.rank,
        group_col=args.group,
        filter_rank=args.filter_rank,
        filter_taxon=args.filter_taxon,
    )

    # Save CSV
    csv_path = out_dir / "alpha_diversity.csv"
    diversity_df.to_csv(csv_path, index=False)
    print(f"  → {csv_path}")

    # Build plot
    color_col = args.group if args.group and args.group in diversity_df.columns else None
    fig = go.Figure()

    metrics = [('richness', f"{args.rank.title()} Richness"),
               ('shannon', "Shannon Index (H')")]

    from plotly.subplots import make_subplots
    fig = make_subplots(rows=2, cols=1,
                        subplot_titles=[m[1] for m in metrics],
                        vertical_spacing=0.25)

    for row_idx, (metric, label) in enumerate(metrics, start=1):
        if color_col:
            for group_name in diversity_df[color_col].dropna().unique():
                gd = diversity_df[diversity_df[color_col] == group_name]
                fig.add_trace(
                    go.Box(y=gd[metric], name=f"{group_name} (n={len(gd)})",
                           boxmean=True, showlegend=(row_idx == 1)),
                    row=row_idx, col=1,
                )
        else:
            fig.add_trace(
                go.Box(y=diversity_df[metric], name=f"All (n={len(diversity_df)})",
                       boxmean=True),
                row=row_idx, col=1,
            )

    fig.update_layout(height=900, template='plotly_white',
                      title_text=f"Alpha Diversity — {args.rank.title()} level")
    html_path = out_dir / "alpha_diversity.html"
    fig.write_html(str(html_path))
    print(f"  → {html_path}")

    # Print summary
    print(f"\nSummary:")
    print(f"  Richness — mean: {diversity_df['richness'].mean():.1f}, "
          f"median: {diversity_df['richness'].median():.1f}")
    print(f"  Shannon  — mean: {diversity_df['shannon'].mean():.2f}, "
          f"median: {diversity_df['shannon'].median():.2f}")


def cmd_taxonomic_abundance(args):
    from Engines.TaxonomicAbundanceComputationEngine.taxonomic_abundance_computation_engine import compute_taxonomic_abundance

    taxonomy_df, metadata_df = _load_and_enrich(
        args.view, Path(args.inputs_dir), Path(args.config_dir)
    )
    out_dir = _ensure_output_dir(Path(args.output_dir), args.view, "taxonomic_abundance")

    print(f"Computing abundance of '{args.taxon}' at rank '{args.rank}' ...")
    abundance_df, summary_df = compute_taxonomic_abundance(
        taxonomy_df=taxonomy_df,
        metadata_df=metadata_df,
        rank=args.rank,
        taxon=args.taxon,
        group_col=args.group,
    )

    safe_taxon = args.taxon.replace(' ', '_')

    # Save CSVs
    csv_path = out_dir / f"taxonomic_abundance_{safe_taxon}.csv"
    abundance_df.to_csv(csv_path, index=False)
    print(f"  → {csv_path}")

    summary_path = out_dir / f"taxonomic_abundance_{safe_taxon}_summary.csv"
    summary_df.to_csv(summary_path, index=False)
    print(f"  → {summary_path}")

    # Build plot
    group_col = args.group if args.group and args.group in abundance_df.columns else None
    title = f"Relative Abundance of {args.taxon} ({args.rank.title()})"

    if group_col:
        group_counts = abundance_df[group_col].value_counts().to_dict()
        abundance_df = abundance_df.copy()
        abundance_df['plot_label'] = abundance_df[group_col].apply(
            lambda x: f"{x} (n={group_counts.get(x, 0)})"
        )
        fig = px.box(
            abundance_df.sort_values(group_col),
            x='plot_label', y='relative_abundance',
            color='plot_label', points='all',
            hover_data=['acc', 'taxon_reads', 'total_sample_reads'],
            title=title, template='plotly_white', height=500,
            labels={'plot_label': group_col},
        )
    else:
        fig = px.bar(
            abundance_df.sort_values('relative_abundance', ascending=False),
            x='acc', y='relative_abundance',
            hover_data=['taxon_reads', 'total_sample_reads'],
            title=title, template='plotly_white', height=500,
        )

    fig.update_layout(yaxis_title="Relative Abundance", yaxis_tickformat=".2%")
    html_path = out_dir / f"taxonomic_abundance_{safe_taxon}.html"
    fig.write_html(str(html_path))
    print(f"  → {html_path}")

    print(f"\nPrevalence Summary:")
    print(summary_df.to_string(index=False))


def cmd_abundance_matrix(args):
    taxonomy_df, _ = _load_and_enrich(
        args.view, Path(args.inputs_dir), Path(args.config_dir)
    )
    out_dir = _ensure_output_dir(Path(args.output_dir), args.view, "abundance_matrix")

    print("Building abundance matrix (samples × taxa) ...")
    abundance_matrix = taxonomy_df.pivot_table(
        index='acc',
        columns='name',
        values='total_count',
        aggfunc='sum',
        fill_value=0,
    )

    csv_path = out_dir / "abundance_matrix.csv"
    abundance_matrix.to_csv(csv_path)
    print(f"  → {csv_path}")
    print(f"  Shape: {abundance_matrix.shape[0]} samples × {abundance_matrix.shape[1]} taxa")


def cmd_metadata_overview(args):
    inputs_dir = Path(args.inputs_dir)
    config_dir = Path(args.config_dir)

    _, metadata_df = _load_and_enrich(
        args.view, Path(args.inputs_dir), Path(args.config_dir)
    )
    out_dir = _ensure_output_dir(Path(args.output_dir), args.view, "metadata_overview")

    # Load raw metadata to run discovered-key scanning per project (runner-style insight).
    from Accessors.SraAccessor.sra_metadata_accessor import SRAMetadataAccessor
    from Engines.MetadataMappingEngine.metadata_mapping_engine import MetadataMappingEngine

    raw_metadata_df = SRAMetadataAccessor.get(inputs_dir / args.view / "metadata.csv")
    processor = MetadataMappingEngine(config_dir=config_dir)

    discovered_rows = []
    for project_id in sorted(raw_metadata_df["bioproject"].dropna().unique()):
        project_df = raw_metadata_df[raw_metadata_df["bioproject"] == project_id].copy()
        discovered = processor._scan_for_keys_and_values(project_df)

        for source_name in ["from_jattr", "from_attributes"]:
            for item in discovered.get(source_name, []):
                discovered_rows.append(
                    {
                        "project_id": project_id,
                        "source": source_name,
                        "key_name": item.get("key_name", ""),
                        "unique_values_count": len(item.get("values_with_counts", [])),
                        "top_values": " | ".join(item.get("top_values", [])),
                    }
                )

    discovered_by_project_df = pd.DataFrame(discovered_rows)
    if discovered_by_project_df.empty:
        discovered_unique_df = pd.DataFrame(
            columns=["source", "key_name", "projects_count", "projects", "max_unique_values_count"]
        )
    else:
        discovered_unique_df = (
            discovered_by_project_df.groupby(["source", "key_name"], as_index=False)
            .agg(
                projects_count=("project_id", "nunique"),
                projects=("project_id", lambda s: ", ".join(sorted(set(map(str, s))))),
                max_unique_values_count=("unique_values_count", "max"),
            )
            .sort_values(["source", "key_name"])
        )

    unique_keys_count = int(len(discovered_unique_df))
    projects_with_discovered_keys = (
        int(discovered_by_project_df["project_id"].nunique()) if not discovered_by_project_df.empty else 0
    )

    mapped_cols = sorted([c for c in metadata_df.columns if c not in _BASE_METADATA_COLS])

    summary_df = pd.DataFrame(
        {
            "metric": [
                "samples",
                "projects",
                "metadata_columns",
                "mapped_columns_count",
                "mapped_columns",
                "discovered_source_keys_unique",
                "projects_with_discovered_source_keys",
            ],
            "value": [
                int(len(metadata_df)),
                int(metadata_df["bioproject"].nunique()) if "bioproject" in metadata_df.columns else 0,
                int(len(metadata_df.columns)),
                int(len(mapped_cols)),
                ", ".join(mapped_cols),
                unique_keys_count,
                projects_with_discovered_keys,
            ],
        }
    )

    if "bioproject" in metadata_df.columns:
        projects_df = (
            metadata_df.groupby("bioproject", as_index=False)
            .agg(samples=("acc", "count"))
            .sort_values("bioproject")
        )
    else:
        projects_df = pd.DataFrame(columns=["bioproject", "samples"])

    summary_path = out_dir / "metadata_overview_summary.csv"
    projects_path = out_dir / "metadata_overview_projects.csv"
    discovered_by_project_path = out_dir / "metadata_overview_discovered_keys_by_project.csv"
    discovered_unique_path = out_dir / "metadata_overview_discovered_keys_unique.csv"

    summary_df.to_csv(summary_path, index=False)
    projects_df.to_csv(projects_path, index=False)
    discovered_by_project_df.to_csv(discovered_by_project_path, index=False)
    discovered_unique_df.to_csv(discovered_unique_path, index=False)

    print("Building metadata overview report ...")
    print(f"  → {summary_path}")
    print(f"  → {projects_path}")
    print(f"  → {discovered_by_project_path}")
    print(f"  → {discovered_unique_path}")
    print(f"\n🔍 Discovered Source Keys ({unique_keys_count} unique keys across {projects_with_discovered_keys} projects)")
    print("\nMetadata Summary:")
    print(summary_df.to_string(index=False))


# ── Argument parser ───────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ask-slm",
        description="Ask-SLM CLI — run microbiome analyses from the command line.",
    )

    # Shared arguments
    shared = argparse.ArgumentParser(add_help=False)
    shared.add_argument("--view", required=True,
                        help="View name (subfolder under --inputs-dir)")
    shared.add_argument("--inputs-dir", default="Inputs",
                        help="Root folder containing view subfolders (default: Inputs)")
    shared.add_argument("--output-dir", default="results",
                        help="Root folder for output files (default: results)")
    shared.add_argument("--config-dir", default="mapping_configs",
                        help="Folder containing mapping config JSON files (default: mapping_configs)")

    sub = parser.add_subparsers(dest="command", required=True)

    # alpha-diversity
    p_alpha = sub.add_parser("alpha-diversity", parents=[shared],
                              help="Compute richness and Shannon index per sample")
    p_alpha.add_argument("--rank", required=True,
                         help="Taxonomic rank to count unique taxa at (e.g. species)")
    p_alpha.add_argument("--group", default=None,
                         help="Metadata column to group samples by in the plot")
    p_alpha.add_argument("--filter-rank", default=None,
                         help="Rank to filter taxonomy by before computing (e.g. superkingdom)")
    p_alpha.add_argument("--filter-taxon", default=None,
                         help="Taxon name at --filter-rank to keep (e.g. Bacteria)")
    p_alpha.set_defaults(func=cmd_alpha_diversity)

    # taxonomic-abundance
    p_abund = sub.add_parser("taxonomic-abundance", parents=[shared],
                              help="Compute relative abundance of a specific taxon")
    p_abund.add_argument("--rank", required=True,
                         help="Taxonomic rank of the target taxon (e.g. genus)")
    p_abund.add_argument("--taxon", required=True,
                         help="Name of the taxon to analyse (e.g. Prevotella)")
    p_abund.add_argument("--group", default=None,
                         help="Metadata column to group samples by in the plot")
    p_abund.set_defaults(func=cmd_taxonomic_abundance)

    # abundance-matrix (preferred)
    p_abund_matrix = sub.add_parser("abundance-matrix", parents=[shared],
                                    help="Export samples × taxa count matrix as CSV")
    p_abund_matrix.set_defaults(func=cmd_abundance_matrix)

    # feature-matrix (backward-compatible alias)
    p_feat = sub.add_parser("feature-matrix", parents=[shared],
                            help="Alias of abundance-matrix")
    p_feat.set_defaults(func=cmd_abundance_matrix)

    # metadata-overview
    p_meta = sub.add_parser("metadata-overview", parents=[shared],
                            help="Export metadata summary and per-project sample counts")
    p_meta.set_defaults(func=cmd_metadata_overview)

    return parser


if __name__ == "__main__":
    # Backward-compatible wrapper: prefer using askslm.py as primary entrypoint.
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)
