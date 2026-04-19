from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from Accessors.OntologyAccessor import EnvoOntologyAccessor
from Accessors.SraAccessor import SRAWorkspaceInputAccessor
from Accessors.TaxonomyAccessor import TaxonomyAccessor
from Engines.EnvoResolutionEngine import resolve_envo_columns
from Engines.MetadataMappingEngine.metadata_mapping_engine import MetadataMappingEngine
from Common.Logger import Logger
from Common.RunnerContext import RunnerContext


def _file_state(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {"exists": False}
    stat = path.stat()
    return {
        "exists": True,
        "size": int(stat.st_size),
        "mtime_ns": int(stat.st_mtime_ns),
    }


def _mapping_configs_state(config_dir: Path, project_ids: List[str]) -> Dict[str, Dict[str, Any]]:
    state: Dict[str, Dict[str, Any]] = {}
    for project_id in sorted(project_ids):
        state[project_id] = _file_state(config_dir / f"{project_id}.json")
    return state


def initialize_runner_context(workspace: str, workspace_root: Path = Path("Workspaces")) -> Tuple[RunnerContext, Logger]:
    workspace_dir = workspace_root / workspace
    workspace_input_dir = workspace_dir / "inputs"
    config_dir = workspace_dir / "mapping_configs"
    results_dir = workspace_dir / "results"
    logs_dir = workspace_dir / "Logs"
    cache_dir = results_dir / "_cache"

    workspace_input_dir.mkdir(parents=True, exist_ok=True)
    config_dir.mkdir(parents=True, exist_ok=True)
    results_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)
    cache_dir.mkdir(parents=True, exist_ok=True)

    run_id = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    run_log_path = logs_dir / f"run_{run_id}.log"
    with run_log_path.open("w", encoding="utf-8") as f:
        f.write(f"Ask-SLM runner log for view={workspace}\n")
        f.write(f"run_id={run_id}\n")

    context = RunnerContext(
        view_name=workspace,
        workspace_dir=workspace_dir,
        workspace_input_dir=workspace_input_dir,
        config_dir=config_dir,
        results_dir=results_dir,
        logs_dir=logs_dir,
        cache_dir=cache_dir,
        run_log_path=run_log_path,
    )

    logger = Logger(run_log_path)
    logger.log(f"Workspace initialized: {workspace_dir}")
    logger.log(f"Canonical inputs will be written to: {workspace_input_dir}")
    logger.log(f"Log file path: {run_log_path}", echo=True)

    return context, logger


def prepare_workspace_inputs(context: RunnerContext, logger: Logger) -> Tuple[pd.DataFrame, pd.DataFrame, Path, Path]:
    return SRAWorkspaceInputAccessor.prepare_workspace_inputs(context=context, logger=logger)


def refresh_mapping_templates(metadata_df: pd.DataFrame, context: RunnerContext, logger: Logger) -> Tuple[MetadataMappingEngine, List[str], pd.DataFrame]:
    processor = MetadataMappingEngine(config_dir=context.config_dir)
    project_ids = sorted(metadata_df["bioproject"].dropna().unique())

    rows = []
    for project_id in project_ids:
        project_df = metadata_df[metadata_df["bioproject"] == project_id].copy()
        processor.refresh_template(project_df, project_id, view_name=context.view_name)
        config_path = context.config_dir / f"{project_id}.json"
        rows.append(
            {
                "project_id": project_id,
                "config_exists": config_path.exists(),
                "config_path": str(config_path),
            }
        )

    logger.log(f"Prepared mapping templates for {len(project_ids)} project(s)")
    return processor, project_ids, pd.DataFrame(rows)


def run_enrichment_stage(
    metadata_df: pd.DataFrame,
    processor: MetadataMappingEngine,
    project_ids: List[str],
    context: RunnerContext,
    logger: Logger,
    strict_missing_configs: bool = False,
) -> Tuple[pd.DataFrame, List[str], List[str], Dict[str, Any]]:
    cache_dir = context.cache_dir
    enriched_path = cache_dir / "enriched_metadata.csv"
    mapped_cols_path = cache_dir / "mapped_columns.json"
    missing_projects_path = cache_dir / "missing_mapping_projects.json"
    stamp_path = cache_dir / "enrichment_stage_stamp.json"

    current_stamp = {
        "schema_version": "enrichment_v1",
        "view_name": context.view_name,
        "metadata_source": _file_state(context.workspace_input_dir / "metadata.csv"),
        "mapping_configs": _mapping_configs_state(context.config_dir, project_ids),
    }

    cache_ok = all(p.exists() for p in [enriched_path, mapped_cols_path, missing_projects_path, stamp_path])
    if cache_ok:
        try:
            previous_stamp = json.loads(stamp_path.read_text(encoding="utf-8"))
            if previous_stamp == current_stamp:
                logger.log(f"Enrichment cache hit: loaded from {cache_dir}", echo=True)
                enriched = pd.read_csv(enriched_path)
                mapped_cols = json.loads(mapped_cols_path.read_text(encoding="utf-8"))
                missing_projects = json.loads(missing_projects_path.read_text(encoding="utf-8"))
                return enriched, mapped_cols, missing_projects, current_stamp
        except Exception:
            pass

    processed_parts: List[pd.DataFrame] = []
    missing_configs: List[str] = []

    for project_id in project_ids:
        project_metadata = metadata_df[metadata_df["bioproject"] == project_id].copy()
        project_config_path = context.config_dir / f"{project_id}.json"

        if not project_config_path.exists():
            processor.refresh_template(project_metadata, project_id, view_name=context.view_name)
            missing_configs.append(project_id)
            processed_parts.append(project_metadata)
            logger.log(
                f"Missing mapping config for {project_id}. "
                f"Template refreshed at {context.config_dir / f'{project_id}.json.template'}; using raw metadata for this run."
            )
            continue

        processed_parts.append(processor.map(project_metadata, project_id, view_name=context.view_name))

    if strict_missing_configs and missing_configs:
        missing = ", ".join(missing_configs)
        raise FileNotFoundError(f"Missing mapping config for: {missing}. Create configs in {context.config_dir} and rerun.")

    if not processed_parts:
        raise RuntimeError("No projects were processed")

    enriched = pd.concat(processed_parts, ignore_index=True)
    mapped_cols = [c for c in enriched.columns if c not in metadata_df.columns]

    if missing_configs:
        logger.log(f"Proceeding without mappings for {len(missing_configs)} project(s): " + ", ".join(missing_configs))

    enriched.to_csv(enriched_path, index=False)
    mapped_cols_path.write_text(json.dumps(mapped_cols, indent=2), encoding="utf-8")
    missing_projects_path.write_text(json.dumps(missing_configs, indent=2), encoding="utf-8")
    stamp_path.write_text(json.dumps(current_stamp, indent=2), encoding="utf-8")
    logger.log(f"Enrichment cache miss: rebuilt and saved to {cache_dir}", echo=True)

    return enriched, mapped_cols, missing_configs, current_stamp


def enrich_envo_columns(metadata_df: pd.DataFrame, context: RunnerContext, logger: Logger, candidate_columns: Optional[List[str]] = None) -> Tuple[pd.DataFrame, pd.DataFrame]:
    cache_path = context.cache_dir / "ontology_envo_cache.json"
    report_path = context.results_dir / "ENVO_Term_Dictionary.csv"

    if cache_path.exists():
        try:
            envo_cache: Dict[str, Dict[str, str]] = json.loads(cache_path.read_text(encoding="utf-8"))
        except Exception:
            envo_cache = {}
    else:
        envo_cache = {}

    enriched = metadata_df.copy()

    if candidate_columns is None:
        candidate_columns = [
            c for c in enriched.columns
            if "env_" in c.lower() or "envo" in c.lower() or "material" in c.lower() or "biome" in c.lower()
        ]

    ontology_accessor = EnvoOntologyAccessor()
    resolution_result = resolve_envo_columns(
        metadata_df=enriched,
        envo_cache=envo_cache,
        candidate_columns=candidate_columns,
        fetch_term=ontology_accessor.fetch_term,
    )

    cache_path.write_text(json.dumps(resolution_result.envo_cache, indent=2), encoding="utf-8")

    if not resolution_result.found_ids:
        logger.log("ENVO decode: no ENVO-like IDs detected in metadata.")
        return resolution_result.enriched_df, resolution_result.report_df

    report_df = resolution_result.report_df
    report_df.to_csv(report_path, index=False)

    logger.log(
        f"ENVO decode: resolved {len(resolution_result.found_ids)} term(s) "
        f"across {len(resolution_result.used_columns)} column(s)"
    )
    logger.log(f"ENVO dictionary saved to: {report_path}")

    return resolution_result.enriched_df, report_df


def run_taxonomy_stage(taxonomy_df: pd.DataFrame, context: RunnerContext, logger: Logger, taxon_key_sep: str = "||") -> Tuple[pd.DataFrame, pd.DataFrame, Dict[str, Any]]:
    taxa_matrix_path = context.results_dir / "Ask_SLM_Taxon_Abundance_Matrix.csv"
    taxon_lookup_path = context.results_dir / "Ask_SLM_Taxon_Lookup.csv"
    taxonomy_stamp_path = context.cache_dir / "taxonomy_stage_stamp.json"

    current_stamp = {
        "schema_version": "taxonomy_v1",
        "view_name": context.view_name,
        "taxonomy_source": _file_state(context.workspace_input_dir / "taxonomy.csv"),
        "taxon_key_sep": taxon_key_sep,
    }

    cache_ok = all(p.exists() for p in [taxa_matrix_path, taxon_lookup_path, taxonomy_stamp_path])
    if cache_ok:
        try:
            previous_stamp = json.loads(taxonomy_stamp_path.read_text(encoding="utf-8"))
            if previous_stamp == current_stamp:
                abundance_matrix = pd.read_csv(taxa_matrix_path, index_col="acc")
                taxon_lookup_df = pd.read_csv(taxon_lookup_path)
                logger.log(f"Taxonomy cache hit: loaded from {context.results_dir}", echo=True)
                return abundance_matrix, taxon_lookup_df, current_stamp
        except Exception:
            pass

    lineage_columns = [c for c in ["ileft", "iright"] if c in taxonomy_df.columns]

    taxonomy_for_wide = taxonomy_df[["acc", "tax_id", "rank", "name", "total_count"] + lineage_columns].copy()
    taxonomy_for_wide["taxon_key"] = (
        taxonomy_for_wide["rank"].astype(str)
        + taxon_key_sep
        + taxonomy_for_wide["name"].astype(str)
        + taxon_key_sep
        + taxonomy_for_wide["tax_id"].astype(str)
    )
    taxonomy_for_wide = (
        taxonomy_for_wide[["acc", "taxon_key", "total_count"]]
        .groupby(["acc", "taxon_key"], as_index=False)["total_count"]
        .sum()
    )

    abundance_matrix = taxonomy_for_wide.pivot(index="acc", columns="taxon_key", values="total_count").fillna(0)

    lookup_base = taxonomy_df[["tax_id", "rank", "name"] + lineage_columns].copy()
    lookup_base["taxon_key"] = (
        lookup_base["rank"].astype(str)
        + taxon_key_sep
        + lookup_base["name"].astype(str)
        + taxon_key_sep
        + lookup_base["tax_id"].astype(str)
    )
    taxon_lookup_columns = ["taxon_key", "rank", "name", "tax_id"] + lineage_columns
    taxon_lookup_df = lookup_base[taxon_lookup_columns].drop_duplicates(subset=["taxon_key"])

    abundance_matrix.to_csv(taxa_matrix_path)
    taxon_lookup_df.to_csv(taxon_lookup_path, index=False)
    taxonomy_stamp_path.write_text(json.dumps(current_stamp, indent=2), encoding="utf-8")
    logger.log(f"Taxonomy cache miss: rebuilt taxonomy features in {context.results_dir}", echo=True)

    return abundance_matrix, taxon_lookup_df, current_stamp


def run_merge_stage(
    enriched_metadata_df: pd.DataFrame,
    abundance_matrix: pd.DataFrame,
    enrichment_stamp: Dict[str, Any],
    taxonomy_stamp: Dict[str, Any],
    context: RunnerContext,
    logger: Logger,
) -> Tuple[pd.DataFrame, List[str], Dict[str, Any]]:
    canonical_dataset_path = context.results_dir / "Ask_SLM_Analysis_Wide_Dataset.csv"
    metadata_columns_path = context.results_dir / "Ask_SLM_Metadata_Columns.json"
    merge_stamp_path = context.cache_dir / "merge_stage_stamp.json"
    compatibility_stamp_path = context.results_dir / "Ask_SLM_Cache_Stamp.json"

    current_stamp = {
        "schema_version": "merge_v1",
        "view_name": context.view_name,
        "enrichment_stamp": enrichment_stamp,
        "taxonomy_stamp": taxonomy_stamp,
    }

    cache_ok = all(p.exists() for p in [canonical_dataset_path, metadata_columns_path, merge_stamp_path])
    if cache_ok:
        try:
            previous_stamp = json.loads(merge_stamp_path.read_text(encoding="utf-8"))
            if previous_stamp == current_stamp:
                abundance_metadata_matrix = pd.read_csv(canonical_dataset_path)
                metadata_columns = json.loads(metadata_columns_path.read_text(encoding="utf-8"))
                logger.log(f"Merge cache hit: loaded from {context.results_dir}", echo=True)

                compatibility_stamp_path.write_text(
                    json.dumps({"schema_version": "combined_v2", "taxonomy_stamp": taxonomy_stamp, "merge_stamp": current_stamp}, indent=2),
                    encoding="utf-8",
                )
                return abundance_metadata_matrix, metadata_columns, current_stamp
        except Exception:
            pass

    metadata_columns = list(enriched_metadata_df.columns)
    abundance_features = abundance_matrix.copy()
    abundance_features.index.name = "acc"
    merged = enriched_metadata_df.set_index("acc", drop=False).join(abundance_features, how="left")
    abundance_metadata_matrix = merged.reset_index(drop=True)

    taxa_feature_columns = list(abundance_features.columns)
    abundance_metadata_matrix[taxa_feature_columns] = abundance_metadata_matrix[taxa_feature_columns].fillna(0)

    abundance_metadata_matrix.to_csv(canonical_dataset_path, index=False)
    metadata_columns_path.write_text(json.dumps(metadata_columns, indent=2), encoding="utf-8")
    merge_stamp_path.write_text(json.dumps(current_stamp, indent=2), encoding="utf-8")

    compatibility_stamp_path.write_text(
        json.dumps({"schema_version": "combined_v2", "taxonomy_stamp": taxonomy_stamp, "merge_stamp": current_stamp}, indent=2),
        encoding="utf-8",
    )

    logger.log(f"Merge cache miss: rebuilt merged dataset in {context.results_dir}", echo=True)

    return abundance_metadata_matrix, metadata_columns, current_stamp


def build_or_load_tax_accessor(taxon_lookup_df: pd.DataFrame, taxonomy_stamp: Dict[str, Any], context: RunnerContext, logger: Logger) -> TaxonomyAccessor:
    db_path = context.cache_dir / "taxonomy_lineage_db.json"
    stamp_path = context.cache_dir / "taxonomy_lineage_db_stamp.json"

    if db_path.exists() and stamp_path.exists():
        try:
            previous_stamp = json.loads(stamp_path.read_text(encoding="utf-8"))
            if previous_stamp == taxonomy_stamp:
                logger.log(f"Taxonomy accessor cache hit: loaded lineage DB from {db_path}", echo=True)
                return TaxonomyAccessor(lineage_db_path=db_path)
        except Exception:
            pass

    accessor = TaxonomyAccessor()
    lineage_df = taxon_lookup_df[["tax_id", "rank", "name", "ileft", "iright"]].drop_duplicates(subset=["tax_id"]).copy()
    lineage_df["acc"] = "__global__"
    accessor.build_from_dataframe(lineage_df)
    accessor.save_database(db_path)
    stamp_path.write_text(json.dumps(taxonomy_stamp, indent=2), encoding="utf-8")
    logger.log(f"Taxonomy accessor cache miss: rebuilt lineage DB at {db_path}", echo=True)

    return accessor
