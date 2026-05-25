"""Engine for metadata overview analysis and matrix building."""

from pathlib import Path
from typing import Callable, List, Optional

import pandas as pd

from Common.contracts.sra_schema import SRAMetadataSchema
from Engines.MappingEngine.mapping_engine import MappingEngine
from .metadata_matrix_builder import MetadataMatrixBuilder
from .metadata_overview_models import MetadataOverviewResult
from .metadata_value_formatter import format_top_values_with_counts


class MetadataOverviewEngine:
    """Analyze metadata, discover source keys, and build metadata matrix.

    Computes metadata discovery across all sampler within projects, builds
    summarized reports, and expands discovered keys into a canonical matrix.
    """

    def __init__(self, config_dir: str, logger=None) -> None:
        self._mapping_processor = MappingEngine(config_dir=Path(config_dir))
        self._log: Optional[Callable[[str], None]] = logger.log if hasattr(logger, "log") else logger

    def _log_message(self, message: str) -> None:
        if callable(self._log):
            self._log(message)

    def run(
        self,
        metadata_df: pd.DataFrame,
        raw_metadata_df: pd.DataFrame,
    ) -> MetadataOverviewResult:
        """Execute metadata overview analysis.

        Discovers keys from raw metadata, summarizes findings, and builds the matrix.
        """
        self._log_message(
            "Metadata overview: starting "
            f"(metadata_rows={len(metadata_df)}, raw_metadata_rows={len(raw_metadata_df)})"
        )
        discovered_by_project_df = self._scan_and_discover(raw_metadata_df)
        self._log_message(
            f"Metadata overview: discovered rows={len(discovered_by_project_df)} "
            f"across {int(discovered_by_project_df['project_id'].nunique()) if not discovered_by_project_df.empty else 0} project(s)"
        )
        summary_df = self._build_summary(metadata_df, discovered_by_project_df)
        projects_df = self._build_projects_summary(metadata_df)
        discovered_unique_df = self._build_discovered_unique(discovered_by_project_df)
        metadata_matrix_df = self._build_matrix(metadata_df, raw_metadata_df, discovered_by_project_df)

        self._log_message(
            "Metadata overview: completed "
            f"(summary_rows={len(summary_df)}, project_rows={len(projects_df)}, "
            f"unique_key_rows={len(discovered_unique_df)}, matrix_shape={metadata_matrix_df.shape})"
        )

        return MetadataOverviewResult(
            summary_df=summary_df,
            projects_df=projects_df,
            discovered_by_project_df=discovered_by_project_df,
            discovered_unique_df=discovered_unique_df,
            metadata_matrix_df=metadata_matrix_df,
        )

    def _scan_and_discover(self, raw_metadata_df: pd.DataFrame) -> pd.DataFrame:
        """Scan projects for discovered keys and build discovery report."""
        base_cols = set(SRAMetadataSchema.__fields__.keys())
        discovered_rows = []
        project_ids = sorted(raw_metadata_df["bioproject"].dropna().unique()) if "bioproject" in raw_metadata_df.columns else []

        self._log_message(f"Metadata overview: scanning {len(project_ids)} project(s) for discovered keys")

        for project_id in project_ids:
            project_mask = raw_metadata_df["bioproject"] == project_id
            project_df = raw_metadata_df.loc[project_mask].copy()  # type: ignore[assignment]
            project_sample_count = int(len(project_df))  # type: ignore[arg-type]

            self._log_message(
                f"Metadata overview: project={project_id} samples={project_sample_count}"
            )

            self._append_discovered_keys(project_df, project_id, project_sample_count, discovered_rows)  # type: ignore[arg-type]
            self._append_direct_fields(project_df, project_id, base_cols, discovered_rows)  # type: ignore[arg-type]

        return pd.DataFrame(discovered_rows)

    def _append_discovered_keys(
        self,
        project_df: pd.DataFrame,
        project_id: str,
        project_sample_count: int,
        discovered_rows: list,
    ) -> None:
        """Append discovered source keys (jattr, attributes) to rows."""
        discovered = self._mapping_processor._scan_for_keys_and_values(project_df)

        for source_name in ["from_jattr", "from_attributes"]:
            source_items = discovered.get(source_name, [])
            self._log_message(
                f"Metadata overview: project={project_id} source={source_name} discovered_keys={len(source_items)}"
            )
            for item in source_items:
                values_with_counts = item.get("values_with_counts", [])
                if not values_with_counts and item.get("top_values"):
                    values_with_counts = [{"value": v, "count": 0} for v in item.get("top_values", [])]

                discovered_rows.append({
                    "project_id": project_id,
                    "source": source_name,
                    "key_name": item.get("key_name", ""),
                    "unique_values_count": len(values_with_counts),
                    "top_values": self._format_values(values_with_counts, project_sample_count),
                })

    def _append_direct_fields(
        self,
        project_df: pd.DataFrame,
        project_id: str,
        base_cols: set,
        discovered_rows: list,
    ) -> None:
        """Append direct metadata fields to discovery rows."""
        direct_fields = [c for c in project_df.columns if c not in ["jattr", "attributes"]]
        self._log_message(
            f"Metadata overview: project={project_id} direct_metadata_fields={len(direct_fields)}"
        )
        for field_name in direct_fields:
            series = project_df[field_name].dropna().astype(str).str.strip()
            series = series[series != ""]
            unique_values_count = int(series.nunique()) if not series.empty else 0
            values_with_counts = (
                [{"value": str(value), "count": int(count)} for value, count in series.value_counts().items()]
                if not series.empty
                else []
            )

            discovered_rows.append({
                "project_id": project_id,
                "source": "metadata",
                "key_name": field_name,
                "unique_values_count": unique_values_count,
                "top_values": self._format_values(values_with_counts, len(project_df)),
            })

    def _format_values(self, values_with_counts: List[dict], sample_count: int) -> str:
        """Format value samples as `value (count)` with adaptive truncation."""
        return format_top_values_with_counts(values_with_counts, sample_count)

    def _build_summary(self, metadata_df: pd.DataFrame, discovered_by_project_df: pd.DataFrame) -> pd.DataFrame:
        """Build metadata summary statistics."""
        base_cols = set(SRAMetadataSchema.__fields__.keys())
        mapped_cols = sorted([c for c in metadata_df.columns if c not in base_cols])
        unique_keys_count = int(len(discovered_by_project_df["key_name"].unique())) if not discovered_by_project_df.empty else 0
        projects_with_discovered_keys = (
            int(discovered_by_project_df["project_id"].nunique()) if not discovered_by_project_df.empty else 0
        )

        summary_df = pd.DataFrame({
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
        })

        self._log_message(
            "Metadata overview: summary metrics prepared "
            f"(samples={int(len(metadata_df))}, mapped_columns={len(mapped_cols)}, "
            f"unique_discovered_keys={unique_keys_count})"
        )

        return summary_df

    def _build_projects_summary(self, metadata_df: pd.DataFrame) -> pd.DataFrame:
        """Build per-project sample count summary."""
        if "bioproject" in metadata_df.columns:
            projects_df = (
                metadata_df.groupby("bioproject", as_index=False)
                .agg(samples=("acc", "count"))
                .sort_values("bioproject")
            )
            self._log_message(f"Metadata overview: project summary rows={len(projects_df)}")
            return projects_df
        self._log_message("Metadata overview: project summary rows=0")
        return pd.DataFrame(columns=["bioproject", "samples"])

    def _build_discovered_unique(self, discovered_by_project_df: pd.DataFrame) -> pd.DataFrame:
        """Build unique discovered keys across all projects."""
        if discovered_by_project_df.empty:
            self._log_message("Metadata overview: unique discovered keys rows=0")
            return pd.DataFrame(columns=["source", "key_name", "projects_count", "projects", "max_unique_values_count"])

        unique_df = (
            discovered_by_project_df.groupby(["source", "key_name"], as_index=False)
            .agg(
                projects_count=("project_id", "nunique"),
                projects=("project_id", lambda s: ", ".join(sorted(set(map(str, s))))),
                max_unique_values_count=("unique_values_count", "max"),
            )
            .sort_values(["source", "key_name"])
        )
        self._log_message(f"Metadata overview: unique discovered keys rows={len(unique_df)}")
        return unique_df

    def _build_matrix(
        self,
        metadata_df: pd.DataFrame,
        raw_metadata_df: pd.DataFrame,
        discovered_by_project_df: pd.DataFrame,
    ) -> pd.DataFrame:
        """Build canonical metadata matrix with expanded discovered keys."""
        matrix_df = MetadataMatrixBuilder().build(metadata_df, raw_metadata_df, discovered_by_project_df)
        self._log_message(f"Metadata overview: matrix shape={matrix_df.shape}")
        return matrix_df




