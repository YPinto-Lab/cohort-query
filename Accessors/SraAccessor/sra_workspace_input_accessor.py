"""
Accessor for preparing canonical workspace inputs from Workspaces/<workspace>/inputs.

This accessor owns file discovery, fallback loading, and metadata/taxonomy aggregation
before writing canonical metadata.csv and taxonomy.csv into the workspace input folder.
"""

from pathlib import Path
from typing import List, Tuple

import pandas as pd

from Common.Logger import Logger
from Common.RunnerContext import RunnerContext

from .sra_metadata_accessor import SRAMetadataAccessor
from .sra_taxonomy_accessor import SRATaxonomyAccessor


class SRAWorkspaceInputAccessor:
    @staticmethod
    def _collect_input_files(view_dir: Path, kind: str, logger: Logger) -> List[Path]:
        patterns = [
            f"{kind}.csv",
            f"{kind}_*.csv",
            f"{kind}/*.csv",
            f"{kind}_parts/*.csv",
        ]

        discovered: List[Path] = []
        seen = set()

        logger.log(f"Scanning {kind} files in {view_dir}")
        for pattern in patterns:
            matches = sorted(view_dir.glob(pattern))
            logger.log(f"  pattern '{pattern}' -> {len(matches)} file(s)")
            for path in matches:
                resolved = str(path.resolve())
                if resolved not in seen:
                    seen.add(resolved)
                    discovered.append(path)

        return discovered

    @staticmethod
    def _aggregate_metadata(parts: List[pd.DataFrame], logger: Logger) -> pd.DataFrame:
        metadata_df = pd.concat(parts, ignore_index=True)
        before = len(metadata_df)
        if "acc" in metadata_df.columns:
            metadata_df = metadata_df.drop_duplicates(subset=["acc"], keep="last")
        else:
            metadata_df = metadata_df.drop_duplicates()
        logger.log(f"Metadata rows: before={before}, after_dedup={len(metadata_df)}")
        return metadata_df

    @staticmethod
    def _aggregate_taxonomy(parts: List[pd.DataFrame], logger: Logger) -> pd.DataFrame:
        taxonomy_df = pd.concat(parts, ignore_index=True)

        count_cols = [c for c in ["total_count", "self_count"] if c in taxonomy_df.columns]
        key_cols = [c for c in ["acc", "tax_id", "rank", "name", "ileft", "iright"] if c in taxonomy_df.columns]

        if key_cols and count_cols:
            before = len(taxonomy_df)
            grouped = taxonomy_df.groupby(key_cols, as_index=False)[count_cols].sum()
            passthrough_cols = [c for c in taxonomy_df.columns if c not in set(key_cols + count_cols)]
            if passthrough_cols:
                passthrough = taxonomy_df[key_cols + passthrough_cols].drop_duplicates(subset=key_cols)
                taxonomy_df = grouped.merge(passthrough, on=key_cols, how="left")
            else:
                taxonomy_df = grouped
            logger.log(f"Taxonomy rows aggregated: before={before}, after_groupby={len(taxonomy_df)}")
        else:
            before = len(taxonomy_df)
            taxonomy_df = taxonomy_df.drop_duplicates()
            logger.log(f"Taxonomy rows deduped: before={before}, after={len(taxonomy_df)}")

        return taxonomy_df

    @classmethod
    def prepare_workspace_inputs(
        cls,
        context: RunnerContext,
        logger: Logger,
    ) -> Tuple[pd.DataFrame, pd.DataFrame, Path, Path]:
        metadata_output = context.workspace_input_dir / "metadata.csv"
        taxonomy_output = context.workspace_input_dir / "taxonomy.csv"
        input_dir = context.workspace_input_dir

        logger.log(f"Preparing workspace inputs for view={context.view_name}")
        metadata_files = cls._collect_input_files(input_dir, "metadata", logger)
        taxonomy_files = cls._collect_input_files(input_dir, "taxonomy", logger)

        if not metadata_files or not taxonomy_files:
            logger.log("No input CSV files found in workspace inputs folder.")
            if metadata_output.exists() and taxonomy_output.exists():
                logger.log("Falling back to existing canonical workspace inputs.")
                metadata_df = SRAMetadataAccessor.get(metadata_output)
                taxonomy_df = SRATaxonomyAccessor.get(taxonomy_output)
                logger.log(f"Loaded fallback metadata rows={len(metadata_df)} from {metadata_output}")
                logger.log(f"Loaded fallback taxonomy rows={len(taxonomy_df)} from {taxonomy_output}")
                return metadata_df, taxonomy_df, metadata_output, taxonomy_output

            missing = []
            if not metadata_files:
                missing.append("metadata")
            if not taxonomy_files:
                missing.append("taxonomy")

            guidance = (
                f"Drop your CSV files into Workspaces/{context.view_name}/inputs/metadata_parts/ "
                f"and taxonomy_parts/, then run: python askslm.py prepare-inputs --workspace {context.view_name}"
            )
            logger.log(f"ERROR: missing input CSVs for {', '.join(missing)}")
            logger.log(guidance)
            raise FileNotFoundError(
                f"Error: could not locate inputs for {', '.join(missing)}.\n{guidance}\n"
                f"See log file: {context.run_log_path}"
            )

        # When the workspace already has canonical files and no split parts are used,
        # avoid rewriting these files. Rewrites change mtime and can invalidate
        # downstream cache stamps even when data is unchanged.
        metadata_canonical_only = (
            len(metadata_files) == 1 and metadata_files[0].resolve() == metadata_output.resolve()
        )
        taxonomy_canonical_only = (
            len(taxonomy_files) == 1 and taxonomy_files[0].resolve() == taxonomy_output.resolve()
        )
        if metadata_canonical_only and taxonomy_canonical_only:
            logger.log("Using canonical workspace inputs directly (no rewrite needed).")
            metadata_df = SRAMetadataAccessor.get(metadata_output)
            taxonomy_df = SRATaxonomyAccessor.get(taxonomy_output)
            logger.log(f"Loaded canonical metadata rows={len(metadata_df)} from {metadata_output}")
            logger.log(f"Loaded canonical taxonomy rows={len(taxonomy_df)} from {taxonomy_output}")
            return metadata_df, taxonomy_df, metadata_output, taxonomy_output

        metadata_parts = [pd.read_csv(path) for path in metadata_files]
        taxonomy_parts = [pd.read_csv(path) for path in taxonomy_files]

        metadata_df = cls._aggregate_metadata(metadata_parts, logger)
        taxonomy_df = cls._aggregate_taxonomy(taxonomy_parts, logger)

        metadata_df.to_csv(metadata_output, index=False)
        taxonomy_df.to_csv(taxonomy_output, index=False)

        logger.log(f"Metadata sources ({len(metadata_files)}):")
        for p in metadata_files:
            logger.log(f"  - {p}")
        logger.log(f"Taxonomy sources ({len(taxonomy_files)}):")
        for p in taxonomy_files:
            logger.log(f"  - {p}")
        logger.log(f"Wrote canonical metadata: {metadata_output}")
        logger.log(f"Wrote canonical taxonomy: {taxonomy_output}")

        return metadata_df, taxonomy_df, metadata_output, taxonomy_output