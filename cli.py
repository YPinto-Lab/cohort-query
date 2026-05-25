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
from managers.analysis_pipeline_manager import AnalysisPipelineManager

# Delegate detailed CLI helper logic to Engine layer.
from Engines.MetadataOverviewEngine.source_key_extractor import SourceKeyExtractor
from Engines.MetadataOverviewEngine.source_key_attacher import SourceKeyAttacher
# Re-export formatter for backward compatibility with existing tests.
from Engines.MetadataOverviewEngine.metadata_value_formatter import format_top_values_with_counts as _format_top_values_with_counts


_BASE_METADATA_COLS = set(SRAMetadataSchema.__fields__.keys())


def _extract_source_key_value(row: pd.Series, key: str) -> str:
    """Backward-compatible wrapper delegating to SourceKeyExtractor."""
    return SourceKeyExtractor().extract(row, key)


def _attach_source_keys(metadata_df: pd.DataFrame, source_keys: list[str]) -> pd.DataFrame:
    """Backward-compatible wrapper delegating to SourceKeyAttacher."""
    return SourceKeyAttacher(metadata_df).attach(source_keys)


def _resolve_case_insensitive_path(path: Path) -> Path:
    """Resolve path by case-insensitive child lookup when exact casing does not exist."""
    # Simplified: assume callers provide correctly-cased paths. Return as-is.
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
    # Simpler: prefer --workspace, fall back to --view if provided, otherwise error.
    workspace = str(getattr(args, "workspace", "") or "").strip()
    if workspace:
        return workspace
    view_alias = str(getattr(args, "view", "") or "").strip()
    if view_alias:
        return view_alias
    print("Error: missing required argument --workspace.", file=sys.stderr)
    sys.exit(1)


def _resolve_runtime_paths(args) -> None:
    """Fill args paths from workspace defaults when omitted.

    Defaults to Workspaces/<workspace>/* unless explicit overrides are provided.
    """
    workspace = _resolve_workspace_name_arg(args)
    workspace_root = Path(args.workspace_root)
    workspace_dir = workspace_root / workspace

    default_inputs = workspace_dir / "inputs"
    default_configs = workspace_dir / "mapping_configs"
    default_results = workspace_dir / "results"

    inputs_dir = Path(args.inputs_dir) if args.inputs_dir else default_inputs
    config_dir = Path(args.config_dir) if args.config_dir else default_configs
    output_dir = Path(args.output_dir) if args.output_dir else default_results

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
    lineage_root = output_dir / "abundance_matrices" / "stage_05_accessor"

    lineage_db_path = Path(args.lineage_db_path) if getattr(args, "lineage_db_path", None) else lineage_root / "taxon_query_db.json"
    stamp_path = lineage_db_path.parent / "taxon_query_db_stamp.json"
    return lineage_db_path, stamp_path


def _initialize_manager_context(
    workspace: str,
    workspace_root: Path,
    inputs_dir: Path,
    config_dir: Path,
    output_dir: Path,
) -> tuple[AnalysisPipelineManager, "RunnerContext", "Logger"]:
    manager = AnalysisPipelineManager()
    init_result = manager.initialize_workspace(workspace=workspace, workspace_root=workspace_root)
    context = init_result.context
    logger = init_result.logger

    resolved_inputs_dir = _resolve_workspace_input_dir(workspace, inputs_dir)
    context.workspace_input_dir = resolved_inputs_dir

    if config_dir:
        context.config_dir = config_dir
        context.config_dir.mkdir(parents=True, exist_ok=True)

    if output_dir:
        context.results_dir = output_dir
        context.results_dir.mkdir(parents=True, exist_ok=True)
        context.cache_dir = output_dir / "abundance_matrices" / "manifests"
        context.cache_dir.mkdir(parents=True, exist_ok=True)

    return manager, context, logger


def _load_and_enrich(args) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Load workspace inputs and run the enrichment stage via AnalysisPipelineManager."""
    manager, context, logger = _initialize_manager_context(
        workspace=args.workspace,
        workspace_root=Path(args.workspace_root),
        inputs_dir=Path(args.inputs_dir),
        config_dir=Path(args.config_dir),
        output_dir=Path(args.output_dir),
    )

    inputs_result = manager.prepare_workspace_inputs(context=context, logger=logger)
    mapping_result = manager.refresh_mapping_templates(
        metadata_df=inputs_result.metadata_table,
        context=context,
        logger=logger,
    )
    enrichment_result = manager.run_enrichment_stage(
        metadata_df=inputs_result.metadata_table,
        processor=mapping_result.processor,
        project_ids=mapping_result.project_ids,
        context=context,
        logger=logger,
        assembly_db_dir=context.cache_dir,
        strict_missing_configs=False,
    )

    return inputs_result.taxonomy_table, enrichment_result.enriched_metadata


def _load_taxonomy_only(args) -> tuple[pd.DataFrame, Path]:
    """Load taxonomy dataframe and return its source CSV path via the manager."""
    manager, context, logger = _initialize_manager_context(
        workspace=args.workspace,
        workspace_root=Path(args.workspace_root),
        inputs_dir=Path(args.inputs_dir),
        config_dir=Path(args.config_dir),
        output_dir=Path(args.output_dir),
    )

    inputs_result = manager.prepare_workspace_inputs(context=context, logger=logger)
    return inputs_result.taxonomy_table, inputs_result.taxonomy_source


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

    taxonomy_df, metadata_df = _load_and_enrich(args)
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

    taxonomy_df, metadata_df = _load_and_enrich(args)
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

    taxonomy_df, metadata_df = _load_and_enrich(args)
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
    manager, context, logger = _initialize_manager_context(
        workspace=args.workspace,
        workspace_root=Path(args.workspace_root),
        inputs_dir=Path(args.inputs_dir),
        config_dir=Path(args.config_dir),
        output_dir=Path(args.output_dir),
    )

    inputs_result = manager.prepare_workspace_inputs(context=context, logger=logger)
    mapping_result = manager.refresh_mapping_templates(
        metadata_df=inputs_result.metadata_table,
        context=context,
        logger=logger,
    )
    enrichment_result = manager.run_enrichment_stage(
        metadata_df=inputs_result.metadata_table,
        processor=mapping_result.processor,
        project_ids=mapping_result.project_ids,
        context=context,
        logger=logger,
        assembly_db_dir=context.cache_dir,
        strict_missing_configs=False,
    )
    taxonomy_result = manager.run_taxonomy_stage(
        taxonomy_df=inputs_result.taxonomy_table,
        context=context,
        logger=logger,
        assembly_db_dir=context.cache_dir,
        merged_dump_path=Path("Accessors/TaxonomyAccessor/merged.dmp"),
        taxon_key_sep="||",
    )
    manager.run_final_assembly_stage(
        enriched_metadata_df=enrichment_result.enriched_metadata,
        abundance_matrix=taxonomy_result.abundance_matrix,
        context=context,
        logger=logger,
        assembly_db_dir=context.cache_dir,
        taxon_lookup_df=taxonomy_result.taxon_lookup_df,
    )
    manager.build_or_load_tax_accessor(
        taxon_lookup_df=taxonomy_result.taxon_lookup_df,
        context=context,
        logger=logger,
        assembly_db_dir=context.cache_dir,
    )

    abundance_matrix = taxonomy_result.abundance_matrix
    csv_path = Path(args.output_dir) / "abundance_matrices" / "stage_04_final_assembly" / "abundance_matrix.csv"
    print("Building abundance matrix (samples × taxa) ...")
    print(f"  → {csv_path}")
    print(f"  Shape: {abundance_matrix.shape[0]} samples × {abundance_matrix.shape[1]} taxa")


def cmd_metadata_overview(args):
    """Run metadata overview analysis via Manager orchestration."""
    import re as _re
    from Accessors.SraAccessor.sra_metadata_accessor import SRAMetadataAccessor
    from Accessors.OntologyAccessor.envo_ontology_accessor import EnvoOntologyAccessor

    manager, context, logger = _initialize_manager_context(
        workspace=args.workspace,
        workspace_root=Path(args.workspace_root),
        inputs_dir=Path(args.inputs_dir),
        config_dir=Path(args.config_dir),
        output_dir=Path(args.output_dir),
    )

    _, metadata_df = _load_and_enrich(args)

    inputs_dir = Path(args.inputs_dir)
    resolved_workspace_input_dir = _resolve_workspace_input_dir(args.workspace, inputs_dir)
    if args.inputs_dir is not None:
        print(f"Loading metadata from {resolved_workspace_input_dir / 'metadata.csv'}")
    raw_metadata_df = SRAMetadataAccessor.get(resolved_workspace_input_dir / "metadata.csv")

    result = manager.run_metadata_overview(
        metadata_df=metadata_df,
        raw_metadata_df=raw_metadata_df,
        config_dir=str(Path(args.config_dir)),
        logger=logger,
    )

    out_dir = _ensure_output_dir(
        Path(args.output_dir),
        "metadata-overview",
        workspace_layout=bool(getattr(args, "workspace_layout", False)),
    )

    # Resolve ENVO IDs found in top_values of discovered source keys.
    envo_pattern = _re.compile(r"\bENVO:\d{7,}\b", _re.IGNORECASE)
    envo_cache_path = out_dir / "envo_cache.json"
    envo_cache = json.loads(envo_cache_path.read_text(encoding="utf-8")) if envo_cache_path.exists() else {}
    accessor = EnvoOntologyAccessor()

    top_values_series = result.discovered_by_project_df.get("top_values", pd.Series(dtype=str))
    all_envo_ids = {m.group(0).upper() for val in top_values_series.dropna() for m in envo_pattern.finditer(str(val))}
    for envo_id in all_envo_ids:
        if envo_id not in envo_cache:
            envo_cache[envo_id] = accessor.fetch_term(envo_id)

    if all_envo_ids:
        label_map = {eid: envo_cache[eid].get("label", eid) for eid in all_envo_ids}
        def _replace_envo(val):
            if not isinstance(val, str):
                return val
            return envo_pattern.sub(lambda m: label_map.get(m.group(0).upper(), m.group(0)), val)
        result.discovered_by_project_df["top_values"] = result.discovered_by_project_df["top_values"].apply(_replace_envo)
        result.discovered_unique_df["top_values"] = result.discovered_unique_df["top_values"].apply(_replace_envo)
        envo_cache_path.write_text(json.dumps(envo_cache, indent=2), encoding="utf-8")

    summary_path = out_dir / "metadata_overview_summary.csv"
    projects_path = out_dir / "metadata_overview_projects.csv"
    discovered_by_project_path = out_dir / "metadata_overview_discovered_keys_by_project.csv"
    discovered_unique_path = out_dir / "metadata_overview_discovered_keys_unique.csv"
    metadata_matrix_path = out_dir / "metadata_matrix.csv"

    result.summary_df.to_csv(summary_path, index=False)
    result.projects_df.to_csv(projects_path, index=False)
    result.discovered_by_project_df.to_csv(discovered_by_project_path, index=False)
    result.discovered_unique_df.to_csv(discovered_unique_path, index=False)
    result.metadata_matrix_df.to_csv(metadata_matrix_path)

    written_paths = [
        summary_path,
        projects_path,
        discovered_by_project_path,
        discovered_unique_path,
        metadata_matrix_path,
    ]

    print("Building metadata overview report ...")
    for path in written_paths:
        print(f"  → {path}")

    if all_envo_ids:
        envo_report_rows = [{"envo_id": eid, "label": envo_cache[eid].get("label", eid), "definition": envo_cache[eid].get("definition", "")} for eid in sorted(all_envo_ids)]
        envo_report_path = out_dir / "envo_term_dictionary.csv"
        pd.DataFrame(envo_report_rows).to_csv(envo_report_path, index=False)
        print(f"  → {envo_report_path} ({len(all_envo_ids)} ENVO terms resolved)")

    unique_keys_count = int(len(result.discovered_unique_df))
    projects_with_discovered_keys = int(result.discovered_by_project_df["project_id"].nunique()) if not result.discovered_by_project_df.empty else 0

    print(f"\n🔍 Discovered Source Keys ({unique_keys_count} unique keys across {projects_with_discovered_keys} projects)")
    print("\nMetadata Summary:")
    print(result.summary_df.to_string(index=False))


def cmd_build_taxonomy_lineage(args):
    from Accessors.TaxonomyAccessor import TaxonomyAccessor

    taxonomy_df, taxonomy_csv_path = _load_taxonomy_only(args)
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


def cmd_prepare_inputs(args):
    manager, context, logger = _initialize_manager_context(
        workspace=args.workspace,
        workspace_root=Path(args.workspace_root),
        inputs_dir=Path(args.inputs_dir),
        config_dir=Path(args.config_dir),
        output_dir=Path(args.output_dir),
    )
    print(f"Preparing inputs for workspace: {args.workspace}")
    result = manager.prepare_workspace_inputs(context=context, logger=logger)
    print(f"  metadata: {len(result.metadata_table):,} rows  → {result.metadata_source}")
    print(f"  taxonomy: {len(result.taxonomy_table):,} rows  → {result.taxonomy_source}")


def cmd_resolve_taxonomy(args):
    from Engines.DatasetAssemblyEngine import TaxonomyResolver
    from Accessors.TaxonomyAccessor import TaxonomyDumpAccessor

    print(f"Resolving deprecated taxonomy IDs for workspace: {args.workspace}")

    taxonomy_df, _ = _load_taxonomy_only(args)
    merged_dump_path = Path("Accessors/TaxonomyAccessor/merged.dmp")
    if not merged_dump_path.exists():
        print(f"Error: merged.dmp not found at {merged_dump_path}", file=sys.stderr)
        sys.exit(1)

    merged_taxid_map = TaxonomyDumpAccessor(merged_dump_path).load_merged_taxid_map()
    resolver = TaxonomyResolver(merged_taxid_map)
    summary, report_df = resolver.summarize_resolution(taxonomy_df)
    resolved_df = resolver.resolve(taxonomy_df)

    out_dir = _ensure_output_dir(
        Path(args.output_dir),
        "taxonomy-resolution",
        workspace_layout=bool(getattr(args, "workspace_layout", False)),
    )
    resolved_path = out_dir / "resolved_taxonomy.csv"
    report_path = out_dir / "taxonomy_resolution_report.csv"
    resolved_df.to_csv(resolved_path, index=False)
    report_df.to_csv(report_path, index=False)

    rows_updated = int(summary.get("rows_updated", 0))
    unique_ids = int(summary.get("unique_old_tax_ids_updated", 0))
    print(f"  {rows_updated} rows updated ({unique_ids} unique deprecated IDs remapped)")
    print(f"  → {resolved_path}")
    print(f"  → {report_path}")


def cmd_init_workspace(args):
    """Create a workspace skeleton for splitting large metadata/taxonomy inputs."""
    workspace_name = str(args.workspace).strip()
    if not workspace_name:
        print("Error: --workspace cannot be empty", file=sys.stderr)
        sys.exit(1)

    location = Path(args.location)
    workspace_dir = location / workspace_name
    created_paths = []

    inputs_dir = workspace_dir / "inputs"
    for path in [
        workspace_dir,
        inputs_dir,
        inputs_dir / "metadata_parts",
        inputs_dir / "taxonomy_parts",
        inputs_dir / "appendix",
        workspace_dir / "mapping_configs",
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
                        help="Optional path to taxonomy lineage DB (default: <output-dir>/abundance_matrices/stage_05_accessor/taxon_query_db.json)")

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

    # prepare-inputs
    p_prepare = sub.add_parser("prepare-inputs", parents=[shared],
                               help="Assemble metadata_parts and taxonomy_parts into canonical input files")
    p_prepare.set_defaults(func=cmd_prepare_inputs)

    # resolve-taxonomy
    p_resolve = sub.add_parser("resolve-taxonomy", parents=[shared],
                               help="Resolve deprecated NCBI taxonomy IDs and write corrected taxonomy CSV")
    p_resolve.set_defaults(func=cmd_resolve_taxonomy)

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
