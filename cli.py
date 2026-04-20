"""
Ask-SLM Command Line Interface.

Provides non-interactive access to analyses for use on remote servers or
in scripted pipelines.

Default layout (workspace-native):
    Workspaces/<workspace>/inputs/metadata.csv
    Workspaces/<workspace>/inputs/taxonomy.csv
    Workspaces/<workspace>/mapping_configs/*.json
    Workspaces/<workspace>/results/

Usage examples:
    python askslm.py init                --workspace ABX --location Workspaces
    python askslm.py alpha-diversity     --workspace PhagesInBlood --rank species --group Group
    python askslm.py taxonomic-abundance --workspace PhagesInBlood --rank genus --taxon Prevotella --group Group
    python askslm.py single-taxon-abundance --workspace PhagesInBlood --taxon Viruses --source-keys day_run host_subject_id_sam
    python askslm.py abundance-matrix    --workspace PhagesInBlood
"""
import argparse
import sys
import json
import re
import hashlib
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import plotly.express as px

from Common.contracts.sra_schema import SRAMetadataSchema


_BASE_METADATA_COLS = set(SRAMetadataSchema.__fields__.keys())


def _extract_source_key_value(row: pd.Series, key: str) -> str:
    """Extract a source key value from direct columns, jattr JSON, or attributes text."""
    requested_key = str(key).strip()
    requested_key_lower = requested_key.lower()

    if requested_key in row.index and pd.notna(row.get(requested_key)):
        return str(row.get(requested_key))

    for col in row.index:
        if str(col).strip().lower() == requested_key_lower and pd.notna(row.get(col)):
            return str(row.get(col))

    if 'jattr' in row.index and pd.notna(row.get('jattr')):
        try:
            parsed = json.loads(row['jattr'])
            if isinstance(parsed, dict):
                raw = None
                if requested_key in parsed:
                    raw = parsed[requested_key]
                else:
                    for k, v in parsed.items():
                        if str(k).strip().lower() == requested_key_lower:
                            raw = v
                            break
                if raw is not None:
                    return " ".join(raw) if isinstance(raw, list) else str(raw)
        except (json.JSONDecodeError, TypeError):
            pass

    if 'attributes' in row.index and pd.notna(row.get('attributes')):
        try:
            for attr_key, attr_val in re.findall(r"k\s*=\s*([^,]+),\s*v\s*=\s*([^}]+)", str(row['attributes'])):
                if str(attr_key).strip().lower() == requested_key_lower:
                    return str(attr_val).strip()
        except Exception:
            pass

    return ""


def _attach_source_keys(metadata_df: pd.DataFrame, source_keys: list[str]) -> pd.DataFrame:
    """Return minimal metadata table with requested source keys materialized."""
    def _normalize_scalar(value) -> str:
        if pd.isna(value):
            return ""
        text = str(value).strip()
        if text.lower() in {"", "nan", "none"}:
            return ""
        # Clean float-like integer formatting from CSV inference (e.g. 5.0 -> 5)
        if re.fullmatch(r"-?\d+\.0", text):
            return text[:-2]
        return text

    keep_cols = ['acc', 'bioproject']
    if 'jattr' in metadata_df.columns:
        keep_cols.append('jattr')
    if 'attributes' in metadata_df.columns:
        keep_cols.append('attributes')

    meta = metadata_df[[c for c in keep_cols if c in metadata_df.columns]].drop_duplicates(subset=['acc']).copy()

    for source_key in source_keys:
        if source_key in metadata_df.columns:
            direct = metadata_df[['acc', source_key]].drop_duplicates(subset=['acc']).set_index('acc')[source_key]
            meta = meta.merge(direct.rename(source_key), left_on='acc', right_index=True, how='left')

        extracted = meta.apply(lambda row: _extract_source_key_value(row, source_key), axis=1)
        if source_key in meta.columns:
            meta[source_key] = meta[source_key].where(meta[source_key].notna(), extracted)
            meta[source_key] = meta[source_key].replace({'nan': ''})
        else:
            meta[source_key] = extracted

        meta[source_key] = meta[source_key].apply(_normalize_scalar)

    drop_cols = [c for c in ['jattr', 'attributes'] if c in meta.columns]
    if drop_cols:
        meta = meta.drop(columns=drop_cols)

    return meta


def _format_top_values_with_counts(values_with_counts: list[dict], sample_count: int) -> str:
    """Format value samples as `value (count)` with adaptive truncation.

    Show many/all values when cardinality is meaningfully lower than sample count,
    and truncate only for near one-value-per-record fields.
    """
    normalized = []
    for item in values_with_counts:
        value = str(item.get("value", ""))
        try:
            count = int(item.get("count", 0))
        except (TypeError, ValueError):
            count = 0
        normalized.append({"value": value, "count": count})

    if not normalized:
        return ""

    normalized.sort(key=lambda x: -x["count"])
    unique_values_count = len(normalized)
    denominator = max(int(sample_count), 1)
    uniqueness_ratio = unique_values_count / denominator

    # Near one-value-per-record fields can explode in size; trim those.
    if uniqueness_ratio >= 0.8:
        limit = 30
    else:
        # For repeated cohorts (e.g., many tests per subject), show far more values.
        limit = 500

    visible = normalized[:limit]
    rendered = " | ".join(f"{item['value']} ({item['count']})" for item in visible)
    if unique_values_count > limit:
        rendered += f" | ... (+{unique_values_count - limit} more)"
    return rendered


def _resolve_case_insensitive_path(path: Path) -> Path:
    """Resolve path by case-insensitive child lookup when exact casing does not exist."""
    if path.exists():
        return path
    parent = path.parent
    if not parent.exists():
        return path
    matches = [child for child in parent.iterdir() if child.name.lower() == path.name.lower()]
    if len(matches) == 1:
        return matches[0]
    return path


def _resolve_workspace_input_dir(workspace: str, inputs_dir: Path) -> Path:
    """Resolve where metadata.csv/taxonomy.csv live for a given workspace.

    Expects a directory that directly contains metadata.csv and taxonomy.csv.
    """
    inputs_dir = _resolve_case_insensitive_path(inputs_dir)

    if inputs_dir.is_dir() and (inputs_dir / "metadata.csv").exists() and (inputs_dir / "taxonomy.csv").exists():
        return inputs_dir

    print(
        "Error: could not locate inputs. Expected:\n"
        f"  - {inputs_dir}/metadata.csv\n"
        f"  - {inputs_dir}/taxonomy.csv",
        file=sys.stderr,
    )
    sys.exit(1)


def _resolve_workspace_name_arg(args) -> str:
    """Return canonical workspace name from CLI args.

    --workspace is the canonical option.
    --view is accepted as a deprecated alias for backward compatibility.
    """
    workspace = str(getattr(args, "workspace", "") or "").strip()
    view_alias = str(getattr(args, "view", "") or "").strip()

    if workspace and view_alias and workspace != view_alias:
        print(
            "Error: --workspace and --view were both provided with different values. "
            "Please pass only --workspace, or pass matching values.",
            file=sys.stderr,
        )
        sys.exit(1)

    if workspace:
        return workspace

    if view_alias:
        print("Warning: --view is deprecated; use --workspace instead.", file=sys.stderr)
        return view_alias

    print("Error: missing required argument --workspace (or deprecated --view).", file=sys.stderr)
    sys.exit(1)


def _resolve_runtime_paths(args) -> None:
    """Fill args paths from workspace defaults when omitted.

    Defaults to Workspaces/<workspace>/* unless explicit overrides are provided.
    """
    workspace = _resolve_workspace_name_arg(args)
    workspace_root = _resolve_case_insensitive_path(Path(args.workspace_root))
    workspace_dir = _resolve_case_insensitive_path(workspace_root / workspace)

    default_inputs = workspace_dir / "inputs"
    default_configs = workspace_dir / "mapping_configs"
    default_results = workspace_dir / "results"

    if args.inputs_dir:
        inputs_dir = Path(args.inputs_dir)
    else:
        inputs_dir = default_inputs

    if args.config_dir:
        config_dir = Path(args.config_dir)
    else:
        config_dir = default_configs

    if args.output_dir:
        output_dir = Path(args.output_dir)
    else:
        output_dir = default_results

    inputs_dir = _resolve_case_insensitive_path(inputs_dir)
    config_dir = _resolve_case_insensitive_path(config_dir)
    output_dir = _resolve_case_insensitive_path(output_dir)

    workspace_layout = True

    args.inputs_dir = str(inputs_dir)
    args.config_dir = str(config_dir)
    args.output_dir = str(output_dir)
    args.workspace_layout = workspace_layout
    args.workspace = workspace


def _sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    """Compute SHA256 hash for a file."""
    digest = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            block = f.read(chunk_size)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def _resolve_lineage_paths(args) -> tuple[Path, Path]:
    """Resolve lineage DB and stamp paths under the active output directory."""
    output_dir = Path(args.output_dir)
    cache_dir = output_dir / "_cache"

    lineage_db_path = Path(args.lineage_db_path) if getattr(args, "lineage_db_path", None) else cache_dir / "taxonomy_lineage_db.json"
    stamp_path = lineage_db_path.parent / "taxonomy_lineage_db_stamp.json"
    return lineage_db_path, stamp_path


def _load_and_enrich(workspace: str, inputs_dir: Path, config_dir: Path):
    """Load both DataFrames for a workspace and apply mapping configs."""
    import sys, os
    if os.getcwd() not in sys.path:
        sys.path.insert(0, os.getcwd())

    from Accessors.SraAccessor.sra_metadata_accessor import SRAMetadataAccessor
    from Accessors.SraAccessor.sra_taxonomy_accessor import SRATaxonomyAccessor
    from Engines.MappingEngine.mapping_engine import MappingEngine

    workspace_path = _resolve_workspace_input_dir(workspace, inputs_dir)

    print(f"Loading metadata from {workspace_path / 'metadata.csv'} ...")
    metadata_df = SRAMetadataAccessor.get(workspace_path / "metadata.csv")

    print(f"Loading taxonomy from {workspace_path / 'taxonomy.csv'} ...")
    taxonomy_df = SRATaxonomyAccessor.get(workspace_path / "taxonomy.csv")

    print(f"Loaded: {len(metadata_df)} samples, {len(taxonomy_df)} taxon observations")

    # Apply mapping configs per project
    processor = MappingEngine(config_dir=config_dir)
    parts = []
    for project_id in metadata_df['bioproject'].unique():
        config_path = config_dir / f"{project_id}.json"
        if not config_path.exists():
            print(f"  [skip] No config for {project_id} — using raw metadata")
            parts.append(metadata_df[metadata_df['bioproject'] == project_id].copy())
            continue
        project_df = metadata_df[metadata_df['bioproject'] == project_id].copy()
        parts.append(processor.map(project_df, project_id))

    enriched_metadata_df = pd.concat(parts, ignore_index=True)
    return taxonomy_df, enriched_metadata_df


def _load_taxonomy_only(workspace: str, inputs_dir: Path) -> tuple[pd.DataFrame, Path]:
    """Load taxonomy dataframe and return its source CSV path."""
    from Accessors.SraAccessor.sra_taxonomy_accessor import SRATaxonomyAccessor

    workspace_path = _resolve_workspace_input_dir(workspace, inputs_dir)
    taxonomy_csv_path = workspace_path / "taxonomy.csv"
    print(f"Loading taxonomy from {taxonomy_csv_path} ...")
    taxonomy_df = SRATaxonomyAccessor.get(taxonomy_csv_path)
    print(f"Loaded: {len(taxonomy_df)} taxon observations")
    return taxonomy_df, taxonomy_csv_path


def _ensure_output_dir(
    output_dir: Path,
    analyzer: str | None = None,
    workspace_layout: bool = False,
) -> Path:
    out = output_dir
    if analyzer:
        out = out / analyzer
    out.mkdir(parents=True, exist_ok=True)
    return out


# ── Commands ──────────────────────────────────────────────────────────────────

def cmd_alpha_diversity(args):
    from Engines.DownstreamAnalysis.AlphaDiversity.alpha_diversity_metrics import compute_alpha_diversity_metrics

    taxonomy_df, metadata_df = _load_and_enrich(
        args.workspace, Path(args.inputs_dir), Path(args.config_dir)
    )
    out_dir = _ensure_output_dir(
        Path(args.output_dir),
        "alpha_diversity",
        workspace_layout=bool(getattr(args, "workspace_layout", False)),
    )

    lineage_db_path, _ = _resolve_lineage_paths(args)
    if not lineage_db_path.exists():
        print(
            "Error: lineage DB is required for alpha-diversity and was not found at:\n"
            f"  {lineage_db_path}\n\n"
            "Build it first with:\n"
            f"  python askslm.py build-taxonomy-lineage --workspace {args.workspace}",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"Computing alpha diversity at rank '{args.rank}' ...")
    diversity_df = compute_alpha_diversity_metrics(
        taxonomy_df=taxonomy_df,
        metadata_df=metadata_df,
        rank=args.rank,
        group_col=args.group,
        filter_rank=args.filter_rank,
        filter_taxon=args.filter_taxon,
        lineage_db_path=str(lineage_db_path),
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
    from Engines.DownstreamAnalysis.TaxonomicAbundance.taxonomic_abundance_metrics import compute_single_taxon_abundance

    taxonomy_df, metadata_df = _load_and_enrich(
        args.workspace, Path(args.inputs_dir), Path(args.config_dir)
    )
    out_dir = _ensure_output_dir(
        Path(args.output_dir),
        "taxonomic_abundance",
        workspace_layout=bool(getattr(args, "workspace_layout", False)),
    )

    print(f"Computing abundance of '{args.taxon}' at rank '{args.rank}' ...")
    abundance_df, summary_df = compute_single_taxon_abundance(
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


def cmd_single_taxon_abundance(args):
    from Engines.DownstreamAnalysis.TaxonomicAbundance.taxonomic_abundance_metrics import compute_single_taxon_abundance

    taxonomy_df, metadata_df = _load_and_enrich(
        args.workspace, Path(args.inputs_dir), Path(args.config_dir)
    )
    out_dir = _ensure_output_dir(
        Path(args.output_dir),
        "single_taxon_abundance",
        workspace_layout=bool(getattr(args, "workspace_layout", False)),
    )

    print(
        f"Computing single taxon abundance for taxon='{args.taxon}', "
        f"rank='{args.rank}', source_keys={args.source_keys} ..."
    )
    abundance_df, summary_df = compute_single_taxon_abundance(
        taxonomy_df=taxonomy_df,
        metadata_df=metadata_df,
        rank=args.rank,
        taxon=args.taxon,
        group_col=args.group,
    )

    source_keys = [k for k in args.source_keys if str(k).strip()]
    source_meta = _attach_source_keys(metadata_df, source_keys)
    raw_df = abundance_df.merge(source_meta, on=['acc', 'bioproject'], how='left')

    ordered_cols = ['acc', 'bioproject'] + source_keys + ['total_sample_reads', 'taxon_reads', 'relative_abundance']
    ordered_cols = [c for c in ordered_cols if c in raw_df.columns]
    raw_df = raw_df[ordered_cols]

    safe_taxon = args.taxon.replace(' ', '_')
    raw_path = out_dir / f"single_taxon_abundance_{safe_taxon}_raw.csv"
    summary_path = out_dir / f"single_taxon_abundance_{safe_taxon}_summary.csv"
    html_path = out_dir / f"single_taxon_abundance_{safe_taxon}.html"

    raw_df.to_csv(raw_path, index=False)
    summary_df.to_csv(summary_path, index=False)

    print(f"  → {raw_path}")
    print(f"  → {summary_path}")

    group_col = args.group if args.group and args.group in raw_df.columns else None
    title = f"Single Taxon Abundance — {args.taxon} ({args.rank.title()})"
    if group_col:
        fig = px.box(
            raw_df.sort_values(group_col),
            x=group_col,
            y='relative_abundance',
            color=group_col,
            points='all',
            hover_data=[c for c in ['acc', 'taxon_reads', 'total_sample_reads'] + source_keys if c in raw_df.columns],
            title=title,
            template='plotly_white',
            height=520,
        )
    else:
        fig = px.bar(
            raw_df.sort_values('relative_abundance', ascending=False),
            x='acc',
            y='relative_abundance',
            hover_data=[c for c in ['taxon_reads', 'total_sample_reads'] + source_keys if c in raw_df.columns],
            title=title,
            template='plotly_white',
            height=520,
        )
    fig.update_layout(yaxis_title="Relative Abundance", yaxis_tickformat=".2%")
    fig.write_html(str(html_path))
    print(f"  → {html_path}")

    print("\nPrevalence Summary:")
    print(summary_df.to_string(index=False))


def cmd_abundance_matrix(args):
    taxonomy_df, _ = _load_and_enrich(
        args.workspace, Path(args.inputs_dir), Path(args.config_dir)
    )
    out_dir = _ensure_output_dir(
        Path(args.output_dir),
        "abundance_matrix",
        workspace_layout=bool(getattr(args, "workspace_layout", False)),
    )

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
        args.workspace, Path(args.inputs_dir), Path(args.config_dir)
    )
    out_dir = _ensure_output_dir(
        Path(args.output_dir),
        "metadata_overview",
        workspace_layout=bool(getattr(args, "workspace_layout", False)),
    )

    # Load raw metadata to run discovered-key scanning per project (runner-style insight).
    from Accessors.SraAccessor.sra_metadata_accessor import SRAMetadataAccessor
    from Engines.MappingEngine.mapping_engine import MappingEngine

    resolved_workspace_input_dir = _resolve_workspace_input_dir(args.workspace, inputs_dir)
    raw_metadata_df = SRAMetadataAccessor.get(resolved_workspace_input_dir / "metadata.csv")
    processor = MappingEngine(config_dir=config_dir)

    discovered_rows = []
    for project_id in sorted(raw_metadata_df["bioproject"].dropna().unique()):
        project_df = raw_metadata_df[raw_metadata_df["bioproject"] == project_id].copy()
        project_sample_count = int(len(project_df))
        discovered = processor._scan_for_keys_and_values(project_df)

        for source_name in ["from_jattr", "from_attributes"]:
            for item in discovered.get(source_name, []):
                values_with_counts = item.get("values_with_counts", [])
                if not values_with_counts and item.get("top_values"):
                    # Backward-compatible fallback when only top_values are available.
                    values_with_counts = [{"value": v, "count": 0} for v in item.get("top_values", [])]
                discovered_rows.append(
                    {
                        "project_id": project_id,
                        "source": source_name,
                        "key_name": item.get("key_name", ""),
                        "unique_values_count": len(values_with_counts),
                        "top_values": _format_top_values_with_counts(values_with_counts, project_sample_count),
                    }
                )

        # Also include direct metadata fields in the same discovered reports.
        for field_name in [c for c in project_df.columns if c not in ["jattr", "attributes"]]:
            series = project_df[field_name].dropna().astype(str).str.strip()
            series = series[series != ""]
            unique_values_count = int(series.nunique()) if not series.empty else 0
            values_with_counts = (
                [{"value": str(value), "count": int(count)} for value, count in series.value_counts().items()]
                if not series.empty
                else []
            )
            discovered_rows.append(
                {
                    "project_id": project_id,
                    "source": "metadata",
                    "key_name": field_name,
                    "unique_values_count": unique_values_count,
                    "top_values": _format_top_values_with_counts(values_with_counts, project_sample_count),
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


def cmd_build_taxonomy_lineage(args):
    from Accessors.TaxonomyAccessor import TaxonomyAccessor

    taxonomy_df, taxonomy_csv_path = _load_taxonomy_only(args.workspace, Path(args.inputs_dir))
    lineage_db_path, stamp_path = _resolve_lineage_paths(args)

    required_cols = {"acc", "tax_id", "rank", "name", "ileft", "iright"}
    missing_cols = required_cols - set(taxonomy_df.columns)
    if missing_cols:
        print(
            "Error: taxonomy.csv is missing required lineage columns: "
            f"{sorted(missing_cols)}",
            file=sys.stderr,
        )
        sys.exit(1)

    taxonomy_hash = _sha256_file(taxonomy_csv_path)
    current_stamp = {
        "schema_version": "lineage_v1",
        "workspace_name": args.workspace,
        "taxonomy_csv": str(taxonomy_csv_path),
        "taxonomy_sha256": taxonomy_hash,
        "taxonomy_rows": int(len(taxonomy_df)),
    }

    if lineage_db_path.exists() and stamp_path.exists():
        try:
            previous_stamp = json.loads(stamp_path.read_text(encoding="utf-8"))
            if previous_stamp == current_stamp:
                print(f"✅ Taxonomy lineage cache hit: {lineage_db_path}")
                return
        except Exception:
            pass

    lineage_source = taxonomy_df[["acc", "tax_id", "rank", "name", "ileft", "iright"]].copy()
    lineage_source = lineage_source.dropna(subset=["acc", "tax_id", "rank", "name", "ileft", "iright"])

    accessor = TaxonomyAccessor()
    accessor.build_from_dataframe(lineage_source)
    accessor.save_database(lineage_db_path)
    stamp_path.parent.mkdir(parents=True, exist_ok=True)
    stamp_path.write_text(json.dumps(current_stamp, indent=2), encoding="utf-8")

    print(f"✅ Built taxonomy lineage DB: {lineage_db_path}")
    print(f"✅ Saved lineage stamp: {stamp_path}")


def cmd_init_workspace(args):
    """Create a workspace skeleton for splitting large metadata/taxonomy inputs."""
    workspace_name = str(args.workspace).strip()
    if not workspace_name:
        print("Error: --workspace cannot be empty", file=sys.stderr)
        sys.exit(1)

    location = Path(args.location)
    workspace_dir = location / workspace_name
    created_paths = []

    for path in [
        workspace_dir,
        workspace_dir / "inputs",
        workspace_dir / "metadata_parts",
        workspace_dir / "taxonomy_parts",
    ]:
        if not path.exists():
            path.mkdir(parents=True, exist_ok=True)
            created_paths.append(path)

    print("Workspace initialization complete")
    print(f"  Workspace: {workspace_dir}")
    if created_paths:
        print("  Created:")
        for path in created_paths:
            print(f"    - {path}")
    else:
        print("  No new folders were needed; all required paths already exist.")


# ── Argument parser ───────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ask-slm",
        description="Ask-SLM CLI — run microbiome analyses from the command line.",
    )

    # Shared arguments
    shared = argparse.ArgumentParser(add_help=False)
    shared.add_argument("--workspace", required=False,
                        help="Workspace name (e.g. ABX or PhagesInBlood)")
    shared.add_argument("--view", required=False,
                        help="Deprecated alias for --workspace")
    shared.add_argument("--workspace-root", default="Workspaces",
                        help="Root folder containing workspace directories (default: Workspaces)")
    shared.add_argument("--inputs-dir", default=None,
                        help="Optional override for inputs directory or root")
    shared.add_argument("--output-dir", default=None,
                        help="Optional override for output directory or root")
    shared.add_argument("--config-dir", default=None,
                        help="Optional override for mapping config directory")
    shared.add_argument("--lineage-db-path", default=None,
                        help="Optional path to taxonomy lineage DB (default: <output-dir>/_cache/taxonomy_lineage_db.json)")

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

    # single-taxon-abundance
    p_single = sub.add_parser(
        "single-taxon-abundance",
        parents=[shared],
        help="Run single taxon abundance with selected source keys (defaults to Viruses, day_run, host_subject_id_sam)",
    )
    p_single.add_argument("--rank", default="superkingdom",
                          help="Taxonomic rank of the target taxon (default: superkingdom)")
    p_single.add_argument("--taxon", default="Viruses",
                          help="Name of the taxon to analyse (default: Viruses)")
    p_single.add_argument("--source-keys", nargs="+", default=["day_run", "host_subject_id_sam"],
                          help="Source keys to include in raw output (default: day_run host_subject_id_sam)")
    p_single.add_argument("--group", default=None,
                          help="Optional metadata/source-key column to group samples by in the plot")
    p_single.set_defaults(func=cmd_single_taxon_abundance)

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

    # build-taxonomy-lineage
    p_lineage = sub.add_parser("build-taxonomy-lineage", parents=[shared],
                               help="Build or refresh taxonomy lineage DB in cache")
    p_lineage.set_defaults(func=cmd_build_taxonomy_lineage)

    # init
    p_init = sub.add_parser(
        "init",
        help="Create a workspace skeleton with inputs, metadata_parts, and taxonomy_parts folders",
    )
    p_init.add_argument(
        "--workspace",
        required=True,
        help="Workspace name to create (e.g. ABX)",
    )
    p_init.add_argument(
        "--location",
        required=True,
        help="Directory where the workspace folder should be created",
    )
    p_init.set_defaults(func=cmd_init_workspace)

    return parser


if __name__ == "__main__":
    # Backward-compatible wrapper: prefer using askslm.py as primary entrypoint.
    parser = build_parser()
    args = parser.parse_args()
    if args.command != "init":
        _resolve_runtime_paths(args)
    args.func(args)
