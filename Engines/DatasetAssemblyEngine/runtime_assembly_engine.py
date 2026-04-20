from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Tuple

import pandas as pd

from Accessors.TaxonomyAccessor import TaxonomyAccessor, TaxonomyDumpAccessor
from .DeprecatedTaxonomyResolutionEngine import DeprecatedTaxonomyResolutionEngine
from .dataset_assembly_engine import compute_analysis_wide_dataset, compute_taxonomy_matrices
from Engines.MappingEngine.mapping_engine import MappingEngine


class DatasetAssemblyRuntimeEngine:
    """Own cache/stamp and artifact assembly internals for runner stages.

    The manager should orchestrate stage ordering only. Cache DB paths, stamp
    files, and artifact persistence remain implementation details of this class.
    """

    def __init__(
        self,
        workspace_input_dir: Path,
        results_dir: Path,
        assembly_db_dir: Path,
        logger,
    ):
        self.workspace_input_dir = Path(workspace_input_dir)
        self.results_dir = Path(results_dir)
        self.assembly_db_dir = Path(assembly_db_dir)
        self._log = logger.log if hasattr(logger, "log") else logger

        if not self.workspace_input_dir.exists():
            raise FileNotFoundError(f"Workspace input directory does not exist: {self.workspace_input_dir}")
        if not self.results_dir.exists():
            raise FileNotFoundError(f"Results directory does not exist: {self.results_dir}")
        if not self.assembly_db_dir.exists():
            raise FileNotFoundError(f"Assembly DB directory does not exist: {self.assembly_db_dir}")

    def run_enrichment_stage(
        self,
        metadata_df: pd.DataFrame,
        processor: MappingEngine,
        project_ids: List[str],
        view_name: str,
        config_dir: Path,
        strict_missing_configs: bool = False,
    ) -> Tuple[pd.DataFrame, List[str], List[str]]:
        enriched_path = self.assembly_db_dir / "enriched_metadata.csv"
        mapped_cols_path = self.assembly_db_dir / "mapped_columns.json"
        missing_projects_path = self.assembly_db_dir / "missing_mapping_projects.json"
        stamp_path = self.assembly_db_dir / "enrichment_stage_stamp.json"

        current_stamp = {
            "schema_version": "enrichment_v2",
            "view_name": view_name,
            "metadata_source": self._file_state(self.workspace_input_dir / "metadata.csv"),
            "mapping_configs": self._mapping_configs_state(Path(config_dir), project_ids),
        }

        cache_ok = all(p.exists() for p in [enriched_path, mapped_cols_path, missing_projects_path, stamp_path])
        if cache_ok:
            try:
                previous_stamp = json.loads(stamp_path.read_text(encoding="utf-8"))
                if previous_stamp == current_stamp:
                    self._log(f"Enrichment cache hit: loaded from {self.assembly_db_dir}", echo=True)
                    enriched = pd.read_csv(enriched_path)
                    mapped_cols = json.loads(mapped_cols_path.read_text(encoding="utf-8"))
                    missing_projects = json.loads(missing_projects_path.read_text(encoding="utf-8"))
                    return enriched, mapped_cols, missing_projects
            except Exception as exc:
                raise RuntimeError(f"Failed reading enrichment cache artifacts: {exc}") from exc

        processed_parts: List[pd.DataFrame] = []
        missing_configs: List[str] = []

        for project_id in project_ids:
            project_metadata = metadata_df[metadata_df["bioproject"] == project_id].copy()
            project_config_path = Path(config_dir) / f"{project_id}.json"

            if not project_config_path.exists():
                processor.refresh_template(project_metadata, project_id, view_name=view_name)
                missing_configs.append(project_id)
                processed_parts.append(project_metadata)
                self._log(
                    f"Missing mapping config for {project_id}. "
                    f"Template refreshed at {Path(config_dir) / f'{project_id}.json.template'}; using raw metadata for this run."
                )
                continue

            processed_parts.append(processor.map(project_metadata, project_id, view_name=view_name))

        if strict_missing_configs and missing_configs:
            missing = ", ".join(missing_configs)
            raise FileNotFoundError(f"Missing mapping config for: {missing}. Create configs in {config_dir} and rerun.")

        if not processed_parts:
            raise RuntimeError("No projects were processed")

        enriched = pd.concat(processed_parts, ignore_index=True)
        mapped_cols = [c for c in enriched.columns if c not in metadata_df.columns]

        if missing_configs:
            self._log(f"Proceeding without mappings for {len(missing_configs)} project(s): " + ", ".join(missing_configs))

        enriched.to_csv(enriched_path, index=False)
        mapped_cols_path.write_text(json.dumps(mapped_cols, indent=2), encoding="utf-8")
        missing_projects_path.write_text(json.dumps(missing_configs, indent=2), encoding="utf-8")
        stamp_path.write_text(json.dumps(current_stamp, indent=2), encoding="utf-8")
        self._log(f"Enrichment cache miss: rebuilt and saved to {self.assembly_db_dir}", echo=True)

        return enriched, mapped_cols, missing_configs

    def run_taxonomy_stage(
        self,
        taxonomy_df: pd.DataFrame,
        view_name: str,
        taxon_key_sep: str,
        merged_dump_path: Path,
    ) -> Tuple[pd.DataFrame, pd.DataFrame]:
        merged_dump_path = Path(merged_dump_path)
        if not merged_dump_path.exists() or not merged_dump_path.is_file():
            raise FileNotFoundError(f"merged.dmp not found: {merged_dump_path}")

        taxa_matrix_path = self.results_dir / "Ask_SLM_Taxon_Abundance_Matrix.csv"
        taxon_lookup_path = self.results_dir / "Ask_SLM_Taxon_Lookup.csv"
        taxonomy_resolution_summary_path = self.results_dir / "Ask_SLM_Taxonomy_Resolution_Summary.json"
        taxonomy_resolution_changes_path = self.results_dir / "Ask_SLM_Taxonomy_Resolution_Changes.csv"
        taxonomy_stamp_path = self.assembly_db_dir / "taxonomy_stage_stamp.json"

        current_stamp = {
            "schema_version": "taxonomy_v3",
            "view_name": view_name,
            "taxonomy_source": self._file_state(self.workspace_input_dir / "taxonomy.csv"),
            "taxon_key_sep": taxon_key_sep,
            "merged_dump_source": self._file_state(merged_dump_path),
        }

        cache_ok = all(p.exists() for p in [taxa_matrix_path, taxon_lookup_path, taxonomy_stamp_path])
        if cache_ok:
            try:
                previous_stamp = json.loads(taxonomy_stamp_path.read_text(encoding="utf-8"))
                if previous_stamp == current_stamp:
                    abundance_matrix = pd.read_csv(taxa_matrix_path, index_col="acc")
                    taxon_lookup_df = pd.read_csv(taxon_lookup_path)
                    if not taxonomy_resolution_summary_path.exists() or not taxonomy_resolution_changes_path.exists():
                        merged_taxid_map = TaxonomyDumpAccessor(merged_dump_path).load_merged_taxid_map()
                        resolver = DeprecatedTaxonomyResolutionEngine(merged_taxid_map)
                        resolution_summary, resolution_changes_df = resolver.summarize_resolution(
                            taxonomy_df=taxonomy_df,
                            sample_col="acc",
                            tax_id_col="tax_id",
                            count_col="total_count",
                        )
                        resolved_taxonomy_df = resolver.resolve(
                            taxonomy_df=taxonomy_df,
                            sample_col="acc",
                            tax_id_col="tax_id",
                            count_col="total_count",
                        )
                        resolution_summary_payload = {
                            "schema_version": "taxonomy_resolution_summary_v1",
                            "view_name": view_name,
                            "merged_dump_path": str(merged_dump_path),
                            "merged_dump_rule_count": int(len(merged_taxid_map)),
                            "input_unique_tax_ids": int(taxonomy_df["tax_id"].astype(str).nunique()) if "tax_id" in taxonomy_df.columns else 0,
                            "resolved_unique_tax_ids": int(resolved_taxonomy_df["tax_id"].astype(str).nunique()) if "tax_id" in resolved_taxonomy_df.columns else 0,
                            "input_rows": int(len(taxonomy_df)),
                            "resolved_rows": int(len(resolved_taxonomy_df)),
                            **resolution_summary,
                        }
                        taxonomy_resolution_summary_path.write_text(
                            json.dumps(resolution_summary_payload, indent=2),
                            encoding="utf-8",
                        )
                        resolution_changes_df.to_csv(taxonomy_resolution_changes_path, index=False)
                        self._log(
                            "Taxonomy cache hit and backfilled resolution artifacts: "
                            f"summary={taxonomy_resolution_summary_path}, "
                            f"changes={taxonomy_resolution_changes_path}"
                        )
                    self._log(f"Taxonomy cache hit: loaded from {self.results_dir}", echo=True)
                    if taxonomy_resolution_summary_path.exists():
                        try:
                            resolution_summary = json.loads(taxonomy_resolution_summary_path.read_text(encoding="utf-8"))
                            self._log(
                                "Taxonomy resolution summary (cached): "
                                f"rows_updated={resolution_summary.get('rows_updated', 0)}, "
                                f"unique_old_tax_ids_updated={resolution_summary.get('unique_old_tax_ids_updated', 0)}, "
                                f"changes_file={taxonomy_resolution_changes_path}"
                            )
                        except Exception:
                            self._log(
                                "Taxonomy cache hit but could not parse taxonomy resolution summary JSON. "
                                f"Expected at: {taxonomy_resolution_summary_path}"
                            )
                    return abundance_matrix, taxon_lookup_df
            except Exception as exc:
                raise RuntimeError(f"Failed reading taxonomy cache artifacts: {exc}") from exc

        merged_taxid_map = TaxonomyDumpAccessor(merged_dump_path).load_merged_taxid_map()
        resolver = DeprecatedTaxonomyResolutionEngine(merged_taxid_map)
        resolution_summary, resolution_changes_df = resolver.summarize_resolution(
            taxonomy_df=taxonomy_df,
            sample_col="acc",
            tax_id_col="tax_id",
            count_col="total_count",
        )
        resolved_taxonomy_df = resolver.resolve(
            taxonomy_df=taxonomy_df,
            sample_col="acc",
            tax_id_col="tax_id",
            count_col="total_count",
        )
        resolution_summary_payload = {
            "schema_version": "taxonomy_resolution_summary_v1",
            "view_name": view_name,
            "merged_dump_path": str(merged_dump_path),
            "merged_dump_rule_count": int(len(merged_taxid_map)),
            "input_unique_tax_ids": int(taxonomy_df["tax_id"].astype(str).nunique()) if "tax_id" in taxonomy_df.columns else 0,
            "resolved_unique_tax_ids": int(resolved_taxonomy_df["tax_id"].astype(str).nunique()) if "tax_id" in resolved_taxonomy_df.columns else 0,
            "input_rows": int(len(taxonomy_df)),
            "resolved_rows": int(len(resolved_taxonomy_df)),
            **resolution_summary,
        }
        taxonomy_resolution_summary_path.write_text(
            json.dumps(resolution_summary_payload, indent=2),
            encoding="utf-8",
        )
        resolution_changes_df.to_csv(taxonomy_resolution_changes_path, index=False)

        self._log(
            f"Taxonomy merge resolution applied using {merged_dump_path} "
            f"({len(merged_taxid_map)} merged ID rules)."
        )
        self._log(
            "Taxonomy resolution details: "
            f"input_rows={resolution_summary_payload['input_rows']}, "
            f"rows_updated={resolution_summary_payload['rows_updated']}, "
            f"unique_old_tax_ids_updated={resolution_summary_payload['unique_old_tax_ids_updated']}, "
            f"resolved_rows={resolution_summary_payload['resolved_rows']}"
        )
        self._log(
            "Taxonomy resolution artifacts saved: "
            f"summary={taxonomy_resolution_summary_path}, "
            f"changes={taxonomy_resolution_changes_path}"
        )

        abundance_matrix, taxon_lookup_df = compute_taxonomy_matrices(
            taxonomy_df=resolved_taxonomy_df,
            taxon_key_sep=taxon_key_sep,
        )

        abundance_matrix.to_csv(taxa_matrix_path)
        taxon_lookup_df.to_csv(taxon_lookup_path, index=False)
        taxonomy_stamp_path.write_text(json.dumps(current_stamp, indent=2), encoding="utf-8")
        self._log(f"Taxonomy cache miss: rebuilt taxonomy features in {self.results_dir}", echo=True)

        return abundance_matrix, taxon_lookup_df

    def run_merge_stage(
        self,
        enriched_metadata_df: pd.DataFrame,
        abundance_matrix: pd.DataFrame,
        view_name: str,
    ) -> Tuple[pd.DataFrame, List[str]]:
        canonical_dataset_path = self.results_dir / "Ask_SLM_Analysis_Wide_Dataset.csv"
        metadata_columns_path = self.results_dir / "Ask_SLM_Metadata_Columns.json"
        merge_stamp_path = self.assembly_db_dir / "merge_stage_stamp.json"
        compatibility_stamp_path = self.results_dir / "Ask_SLM_Cache_Stamp.json"

        enrichment_stamp_path = self.assembly_db_dir / "enrichment_stage_stamp.json"
        taxonomy_stamp_path = self.assembly_db_dir / "taxonomy_stage_stamp.json"
        if not enrichment_stamp_path.exists() or not taxonomy_stamp_path.exists():
            raise RuntimeError(
                "Missing stage stamps for merge. Run enrichment and taxonomy stages successfully before merge."
            )

        enrichment_stamp = json.loads(enrichment_stamp_path.read_text(encoding="utf-8"))
        taxonomy_stamp = json.loads(taxonomy_stamp_path.read_text(encoding="utf-8"))

        current_stamp = {
            "schema_version": "merge_v2",
            "view_name": view_name,
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
                    self._log(f"Merge cache hit: loaded from {self.results_dir}", echo=True)

                    compatibility_stamp_path.write_text(
                        json.dumps({"schema_version": "combined_v2", "taxonomy_stamp": taxonomy_stamp, "merge_stamp": current_stamp}, indent=2),
                        encoding="utf-8",
                    )
                    return abundance_metadata_matrix, metadata_columns
            except Exception as exc:
                raise RuntimeError(f"Failed reading merge cache artifacts: {exc}") from exc

        abundance_metadata_matrix, metadata_columns = compute_analysis_wide_dataset(
            enriched_metadata_df=enriched_metadata_df,
            abundance_matrix=abundance_matrix,
        )

        abundance_metadata_matrix.to_csv(canonical_dataset_path, index=False)
        metadata_columns_path.write_text(json.dumps(metadata_columns, indent=2), encoding="utf-8")
        merge_stamp_path.write_text(json.dumps(current_stamp, indent=2), encoding="utf-8")

        compatibility_stamp_path.write_text(
            json.dumps({"schema_version": "combined_v2", "taxonomy_stamp": taxonomy_stamp, "merge_stamp": current_stamp}, indent=2),
            encoding="utf-8",
        )

        self._log(f"Merge cache miss: rebuilt merged dataset in {self.results_dir}", echo=True)

        return abundance_metadata_matrix, metadata_columns

    def build_or_load_tax_accessor(
        self,
        taxon_lookup_df: pd.DataFrame,
        lineage_db_path: Path,
    ) -> TaxonomyAccessor:
        lineage_db_path = Path(lineage_db_path)
        stamp_path = self.assembly_db_dir / "taxonomy_lineage_db_stamp.json"
        taxonomy_stamp_path = self.assembly_db_dir / "taxonomy_stage_stamp.json"

        if not taxonomy_stamp_path.exists():
            raise RuntimeError("Missing taxonomy stage stamp. Run taxonomy stage before lineage DB stage.")
        taxonomy_stamp = json.loads(taxonomy_stamp_path.read_text(encoding="utf-8"))

        if lineage_db_path.exists() and stamp_path.exists():
            try:
                previous_stamp = json.loads(stamp_path.read_text(encoding="utf-8"))
                if previous_stamp == taxonomy_stamp:
                    self._log(f"Taxonomy accessor cache hit: loaded lineage DB from {lineage_db_path}", echo=True)
                    return TaxonomyAccessor(lineage_db_path=lineage_db_path)
            except Exception as exc:
                raise RuntimeError(f"Failed reading lineage DB cache artifacts: {exc}") from exc

        accessor = TaxonomyAccessor()
        lineage_df = taxon_lookup_df[["tax_id", "rank", "name", "ileft", "iright"]].drop_duplicates(subset=["tax_id"]).copy()
        lineage_df["acc"] = "__global__"
        accessor.build_from_dataframe(lineage_df)
        accessor.save_database(lineage_db_path)
        stamp_path.write_text(json.dumps(taxonomy_stamp, indent=2), encoding="utf-8")
        self._log(f"Taxonomy accessor cache miss: rebuilt lineage DB at {lineage_db_path}", echo=True)

        return accessor

    @staticmethod
    def _file_state(path: Path) -> Dict[str, Any]:
        if not path.exists():
            return {"exists": False}
        stat = path.stat()
        return {
            "exists": True,
            "size": int(stat.st_size),
            "mtime_ns": int(stat.st_mtime_ns),
        }

    def _mapping_configs_state(self, config_dir: Path, project_ids: List[str]) -> Dict[str, Dict[str, Any]]:
        state: Dict[str, Dict[str, Any]] = {}
        for project_id in sorted(project_ids):
            state[project_id] = self._file_state(config_dir / f"{project_id}.json")
        return state
