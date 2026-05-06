from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from Accessors.TaxonomyAccessor import TaxonomyAccessor, TaxonomyDumpAccessor
from Engines.MappingEngine.mapping_engine import MappingEngine

from .DeprecatedTaxonomyResolutionEngine import DeprecatedTaxonomyResolutionEngine
from .dataset_assembly_engine import compute_analysis_wide_dataset, compute_taxonomy_matrices
from .runtime_assembly_models import (
    EnrichmentStageRequest,
    MergeStageRequest,
    RuntimeAssemblyPaths,
    TaxonomyAccessorRequest,
    TaxonomyStageRequest,
)


class RuntimeAssemblyStageBase:
    def __init__(self, paths: RuntimeAssemblyPaths, logger=None):
        self.paths = paths
        self._log = logger.log if hasattr(logger, "log") else logger

    def _file_state(self, path: Path) -> Dict[str, Any]:
        if not path.exists():
            return {"exists": False}
        stat = path.stat()
        return {"exists": True, "size": int(stat.st_size), "mtime_ns": int(stat.st_mtime_ns)}

    def _read_json(self, path: Path):
        return json.loads(path.read_text(encoding="utf-8"))

    def _write_json(self, path: Path, payload):
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def _cache_matches(self, stamp_path: Path, current_stamp: Dict[str, Any]) -> bool:
        if not stamp_path.exists():
            return False
        return self._read_json(stamp_path) == current_stamp

    def _load_csv_pair(self, first: Path, second: Path, first_kwargs=None, second_kwargs=None):
        return pd.read_csv(first, **(first_kwargs or {})), pd.read_csv(second, **(second_kwargs or {}))


class EnrichmentStageRunner(RuntimeAssemblyStageBase):
    def run(self, request: EnrichmentStageRequest) -> Tuple[pd.DataFrame, List[str], List[str]]:
        cache = self._load_cache(request)
        if cache is not None:
            return cache
        return self._rebuild(request)

    def _load_cache(self, request: EnrichmentStageRequest):
        enriched_path = self.paths.assembly_db_dir / "enriched_metadata.csv"
        mapped_cols_path = self.paths.assembly_db_dir / "mapped_columns.json"
        missing_projects_path = self.paths.assembly_db_dir / "missing_mapping_projects.json"
        stamp_path = self.paths.assembly_db_dir / "enrichment_stage_stamp.json"
        current_stamp = self._current_stamp(request)
        if not all(p.exists() for p in [enriched_path, mapped_cols_path, missing_projects_path, stamp_path]):
            return None
        if not self._cache_matches(stamp_path, current_stamp):
            return None
        self._log(f"Enrichment cache hit: loaded from {self.paths.assembly_db_dir}", echo=True)
        enriched = pd.read_csv(enriched_path)
        mapped_cols = self._read_json(mapped_cols_path)
        missing_projects = self._read_json(missing_projects_path)
        return enriched, mapped_cols, missing_projects

    def _current_stamp(self, request: EnrichmentStageRequest) -> Dict[str, Any]:
        return {
            "schema_version": "enrichment_v2",
            "view_name": request.view_name,
            "metadata_source": self._file_state(self.paths.workspace_input_dir / "metadata.csv"),
            "mapping_configs": self._mapping_configs_state(request.config_dir, request.project_ids),
        }

    def _mapping_configs_state(self, config_dir: Path, project_ids: List[str]) -> Dict[str, Dict[str, Any]]:
        return {project_id: self._file_state(Path(config_dir) / f"{project_id}.json") for project_id in sorted(project_ids)}

    def _rebuild(self, request: EnrichmentStageRequest):
        processed_parts, missing_configs = self._process_projects(request)
        if request.strict_missing_configs and missing_configs:
            missing = ", ".join(missing_configs)
            raise FileNotFoundError(f"Missing mapping config for: {missing}. Create configs in {request.config_dir} and rerun.")
        if not processed_parts:
            raise RuntimeError("No projects were processed")
        enriched = pd.concat(processed_parts, ignore_index=True)
        mapped_cols = [c for c in enriched.columns if c not in request.metadata_df.columns]
        self._persist(request, enriched, mapped_cols, missing_configs)
        return enriched, mapped_cols, missing_configs

    def _process_projects(self, request: EnrichmentStageRequest):
        processed_parts: List[pd.DataFrame] = []
        missing_configs: List[str] = []
        for project_id in request.project_ids:
            processed, missing = self._process_project(request, project_id)
            processed_parts.append(processed)
            if missing:
                missing_configs.append(project_id)
        if missing_configs:
            self._log(f"Proceeding without mappings for {len(missing_configs)} project(s): " + ", ".join(missing_configs))
        return processed_parts, missing_configs

    def _process_project(self, request: EnrichmentStageRequest, project_id: str):
        project_metadata = request.metadata_df[request.metadata_df["bioproject"] == project_id].copy()
        project_config_path = Path(request.config_dir) / f"{project_id}.json"
        if project_config_path.exists():
            return request.processor.map(project_metadata, project_id, view_name=request.view_name), False
        request.processor.refresh_template(project_metadata, project_id, view_name=request.view_name)
        self._log(
            f"Missing mapping config for {project_id}. Template refreshed at {Path(request.config_dir) / f'{project_id}.json.template'}; using raw metadata for this run."
        )
        return project_metadata, True

    def _persist(self, request: EnrichmentStageRequest, enriched: pd.DataFrame, mapped_cols: List[str], missing_configs: List[str]):
        enriched_path = self.paths.assembly_db_dir / "enriched_metadata.csv"
        mapped_cols_path = self.paths.assembly_db_dir / "mapped_columns.json"
        missing_projects_path = self.paths.assembly_db_dir / "missing_mapping_projects.json"
        stamp_path = self.paths.assembly_db_dir / "enrichment_stage_stamp.json"
        enriched.to_csv(enriched_path, index=False)
        self._write_json(mapped_cols_path, mapped_cols)
        self._write_json(missing_projects_path, missing_configs)
        self._write_json(stamp_path, self._current_stamp(request))
        self._log(f"Enrichment cache miss: rebuilt and saved to {self.paths.assembly_db_dir}", echo=True)


class TaxonomyStageRunner(RuntimeAssemblyStageBase):
    def run(self, request: TaxonomyStageRequest) -> Tuple[pd.DataFrame, pd.DataFrame]:
        merged_dump_path = Path(request.merged_dump_path)
        if not merged_dump_path.exists() or not merged_dump_path.is_file():
            raise FileNotFoundError(f"merged.dmp not found: {merged_dump_path}")
        cached = self._load_cache(request, merged_dump_path)
        if cached is not None:
            return cached
        return self._rebuild(request, merged_dump_path)

    def _cache_paths(self):
        return {
            "matrix": self.paths.results_dir / "Ask_SLM_Taxon_Abundance_Matrix.csv",
            "lookup": self.paths.results_dir / "Ask_SLM_Taxon_Lookup.csv",
            "summary": self.paths.results_dir / "Ask_SLM_Taxonomy_Resolution_Summary.json",
            "changes": self.paths.results_dir / "Ask_SLM_Taxonomy_Resolution_Changes.csv",
            "stamp": self.paths.assembly_db_dir / "taxonomy_stage_stamp.json",
        }

    def _current_stamp(self, request: TaxonomyStageRequest, merged_dump_path: Path) -> Dict[str, Any]:
        return {
            "schema_version": "taxonomy_v3",
            "view_name": request.view_name,
            "taxonomy_source": self._file_state(self.paths.workspace_input_dir / "taxonomy.csv"),
            "taxon_key_sep": request.taxon_key_sep,
            "merged_dump_source": self._file_state(merged_dump_path),
        }

    def _load_cache(self, request: TaxonomyStageRequest, merged_dump_path: Path):
        paths = self._cache_paths()
        if not all(paths[k].exists() for k in ["matrix", "lookup", "stamp"]):
            return None
        if not self._cache_matches(paths["stamp"], self._current_stamp(request, merged_dump_path)):
            return None
        abundance_matrix = pd.read_csv(paths["matrix"], index_col="acc")
        taxon_lookup_df = pd.read_csv(paths["lookup"])
        self._backfill_resolution_artifacts_if_needed(request, merged_dump_path, paths)
        self._log(f"Taxonomy cache hit: loaded from {self.paths.results_dir}", echo=True)
        self._log_cached_resolution_summary(paths)
        return abundance_matrix, taxon_lookup_df

    def _backfill_resolution_artifacts_if_needed(self, request: TaxonomyStageRequest, merged_dump_path: Path, paths: Dict[str, Path]):
        if paths["summary"].exists() and paths["changes"].exists():
            return
        self._write_resolution_artifacts(request, merged_dump_path, paths)

    def _log_cached_resolution_summary(self, paths: Dict[str, Path]):
        if not paths["summary"].exists():
            return
        try:
            resolution_summary = self._read_json(paths["summary"])
            self._log(
                "Taxonomy resolution summary (cached): "
                f"rows_updated={resolution_summary.get('rows_updated', 0)}, "
                f"unique_old_tax_ids_updated={resolution_summary.get('unique_old_tax_ids_updated', 0)}, "
                f"changes_file={paths['changes']}"
            )
        except Exception:
            self._log(f"Taxonomy cache hit but could not parse taxonomy resolution summary JSON. Expected at: {paths['summary']}")

    def _write_resolution_artifacts(self, request: TaxonomyStageRequest, merged_dump_path: Path, paths: Dict[str, Path]):
        _, resolved_taxonomy_df, resolution_summary, resolution_changes_df, merged_taxid_map = self._resolve_taxonomy(request, merged_dump_path)
        payload = self._resolution_payload(request, merged_dump_path, resolution_summary, resolved_taxonomy_df, merged_taxid_map)
        self._write_json(paths["summary"], payload)
        resolution_changes_df.to_csv(paths["changes"], index=False)
        self._log(
            "Taxonomy cache hit and backfilled resolution artifacts: "
            f"summary={paths['summary']}, changes={paths['changes']}"
        )

    def _rebuild(self, request: TaxonomyStageRequest, merged_dump_path: Path):
        _, resolved_taxonomy_df, resolution_summary, resolution_changes_df, merged_taxid_map = self._resolve_taxonomy(request, merged_dump_path)
        paths = self._cache_paths()
        payload = self._resolution_payload(request, merged_dump_path, resolution_summary, resolved_taxonomy_df, merged_taxid_map)
        self._write_json(paths["summary"], payload)
        resolution_changes_df.to_csv(paths["changes"], index=False)
        self._log(f"Taxonomy merge resolution applied using {merged_dump_path} ({len(merged_taxid_map)} merged ID rules).")
        self._log(
            "Taxonomy resolution details: "
            f"input_rows={payload['input_rows']}, rows_updated={payload['rows_updated']}, "
            f"unique_old_tax_ids_updated={payload['unique_old_tax_ids_updated']}, resolved_rows={payload['resolved_rows']}"
        )
        self._log(f"Taxonomy resolution artifacts saved: summary={paths['summary']}, changes={paths['changes']}")
        abundance_matrix, taxon_lookup_df = compute_taxonomy_matrices(taxonomy_df=resolved_taxonomy_df, taxon_key_sep=request.taxon_key_sep)
        self._persist(request, abundance_matrix, taxon_lookup_df, paths)
        return abundance_matrix, taxon_lookup_df

    def _resolve_taxonomy(self, request: TaxonomyStageRequest, merged_dump_path: Path):
        merged_taxid_map = TaxonomyDumpAccessor(merged_dump_path).load_merged_taxid_map()
        resolver = DeprecatedTaxonomyResolutionEngine(merged_taxid_map)
        resolution_summary, resolution_changes_df = resolver.summarize_resolution(
            taxonomy_df=request.taxonomy_df,
            sample_col="acc",
            tax_id_col="tax_id",
            count_col="total_count",
        )
        resolved_taxonomy_df = resolver.resolve(
            taxonomy_df=request.taxonomy_df,
            sample_col="acc",
            tax_id_col="tax_id",
            count_col="total_count",
        )
        return merged_taxid_map, resolved_taxonomy_df, resolution_summary, resolution_changes_df, merged_taxid_map

    def _resolution_payload(self, request: TaxonomyStageRequest, merged_dump_path: Path, resolution_summary: Dict[str, Any], resolved_taxonomy_df: pd.DataFrame, merged_taxid_map):
        return {
            "schema_version": "taxonomy_resolution_summary_v1",
            "view_name": request.view_name,
            "merged_dump_path": str(merged_dump_path),
            "merged_dump_rule_count": int(len(merged_taxid_map)),
            "input_unique_tax_ids": int(request.taxonomy_df["tax_id"].astype(str).nunique()) if "tax_id" in request.taxonomy_df.columns else 0,
            "resolved_unique_tax_ids": int(resolved_taxonomy_df["tax_id"].astype(str).nunique()) if "tax_id" in resolved_taxonomy_df.columns else 0,
            "input_rows": int(len(request.taxonomy_df)),
            "resolved_rows": int(len(resolved_taxonomy_df)),
            **resolution_summary,
        }

    def _persist(self, request: TaxonomyStageRequest, abundance_matrix: pd.DataFrame, taxon_lookup_df: pd.DataFrame, paths: Dict[str, Path]):
        abundance_matrix.to_csv(paths["matrix"])
        taxon_lookup_df.to_csv(paths["lookup"], index=False)
        self._write_json(paths["stamp"], self._current_stamp(request, Path(request.merged_dump_path)))
        self._log(f"Taxonomy cache miss: rebuilt taxonomy features in {self.paths.results_dir}", echo=True)


class MergeStageRunner(RuntimeAssemblyStageBase):
    def run(self, request: MergeStageRequest) -> Tuple[pd.DataFrame, List[str]]:
        paths = self._cache_paths()
        self._require_stage_stamps(paths)
        cached = self._load_cache(request, paths)
        if cached is not None:
            return cached
        return self._rebuild(request, paths)

    def _cache_paths(self):
        return {
            "canonical": self.paths.results_dir / "Ask_SLM_Analysis_Wide_Dataset.csv",
            "columns": self.paths.results_dir / "Ask_SLM_Metadata_Columns.json",
            "stamp": self.paths.assembly_db_dir / "merge_stage_stamp.json",
            "compat": self.paths.results_dir / "Ask_SLM_Cache_Stamp.json",
            "enrichment": self.paths.assembly_db_dir / "enrichment_stage_stamp.json",
            "taxonomy": self.paths.assembly_db_dir / "taxonomy_stage_stamp.json",
        }

    def _require_stage_stamps(self, paths: Dict[str, Path]):
        if paths["enrichment"].exists() and paths["taxonomy"].exists():
            return
        raise RuntimeError("Missing stage stamps for merge. Run enrichment and taxonomy stages successfully before merge.")

    def _current_stamp(self, request: MergeStageRequest, paths: Dict[str, Path]):
        return {
            "schema_version": "merge_v2",
            "view_name": request.view_name,
            "enrichment_stamp": self._read_json(paths["enrichment"]),
            "taxonomy_stamp": self._read_json(paths["taxonomy"]),
        }

    def _load_cache(self, request: MergeStageRequest, paths: Dict[str, Path]):
        if not all(paths[k].exists() for k in ["canonical", "columns", "stamp"]):
            return None
        if not self._cache_matches(paths["stamp"], self._current_stamp(request, paths)):
            return None
        abundance_metadata_matrix = pd.read_csv(paths["canonical"])
        metadata_columns = self._read_json(paths["columns"])
        self._write_json(paths["compat"], {"schema_version": "combined_v2", **self._current_stamp(request, paths)})
        self._log(f"Merge cache hit: loaded from {self.paths.results_dir}", echo=True)
        return abundance_metadata_matrix, metadata_columns

    def _rebuild(self, request: MergeStageRequest, paths: Dict[str, Path]):
        abundance_metadata_matrix, metadata_columns = compute_analysis_wide_dataset(
            enriched_metadata_df=request.enriched_metadata_df,
            abundance_matrix=request.abundance_matrix,
        )
        abundance_metadata_matrix.to_csv(paths["canonical"], index=False)
        self._write_json(paths["columns"], metadata_columns)
        self._write_json(paths["stamp"], self._current_stamp(request, paths))
        self._write_json(paths["compat"], {"schema_version": "combined_v2", **self._current_stamp(request, paths)})
        self._log(f"Merge cache miss: rebuilt merged dataset in {self.paths.results_dir}", echo=True)
        return abundance_metadata_matrix, metadata_columns


class TaxonomyAccessorRunner(RuntimeAssemblyStageBase):
    def run(self, request: TaxonomyAccessorRequest) -> TaxonomyAccessor:
        paths = self._cache_paths()
        self._require_taxonomy_stamp(paths)
        cached = self._load_cache(request, paths)
        if cached is not None:
            return cached
        return self._rebuild(request, paths)

    def _cache_paths(self):
        return {"stamp": self.paths.assembly_db_dir / "taxonomy_lineage_db_stamp.json", "taxonomy": self.paths.assembly_db_dir / "taxonomy_stage_stamp.json"}

    def _require_taxonomy_stamp(self, paths: Dict[str, Path]):
        if paths["taxonomy"].exists():
            return
        raise RuntimeError("Missing taxonomy stage stamp. Run taxonomy stage before lineage DB stage.")

    def _load_cache(self, request: TaxonomyAccessorRequest, paths: Dict[str, Path]):
        lineage_db_path = Path(request.lineage_db_path)
        if not lineage_db_path.exists() or not paths["stamp"].exists():
            return None
        if not self._cache_matches(paths["stamp"], self._read_json(paths["taxonomy"])):
            return None
        self._log(f"Taxonomy accessor cache hit: loaded lineage DB from {lineage_db_path}", echo=True)
        return TaxonomyAccessor(lineage_db_path=lineage_db_path)

    def _rebuild(self, request: TaxonomyAccessorRequest, paths: Dict[str, Path]) -> TaxonomyAccessor:
        lineage_db_path = Path(request.lineage_db_path)
        taxonomy_stamp = self._read_json(paths["taxonomy"])
        accessor = TaxonomyAccessor()
        lineage_df = request.taxon_lookup_df[["tax_id", "rank", "name", "ileft", "iright"]].drop_duplicates(subset=["tax_id"]).copy()
        lineage_df["acc"] = "__global__"
        accessor.build_from_dataframe(lineage_df)
        accessor.save_database(lineage_db_path)
        self._write_json(paths["stamp"], taxonomy_stamp)
        self._log(f"Taxonomy accessor cache miss: rebuilt lineage DB at {lineage_db_path}", echo=True)
        return accessor

