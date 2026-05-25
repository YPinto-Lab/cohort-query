"""Programmatic API surface for Ask-SLM CLI operations.

This module exposes a class-based interface for invoking analyses programmatically.
"""

import logging
import sys
from typing import Iterable, Optional
from pathlib import Path

from Engines.MetadataOverviewEngine import MetadataOverviewEngine


class AskSLMAPI:
    def __init__(self, name: str = "AskSLM"):
        """Initialize the API and set up logging."""
        self.logger = logging.getLogger(name)
        if not self.logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
            handler.setFormatter(formatter)
            self.logger.addHandler(handler)
            self.logger.setLevel(logging.INFO)

    def init_workspace(self, location: str, workspace: str) -> None:
        """Create a workspace skeleton for splitting large metadata/taxonomy inputs."""
        if not workspace:
            print("Error: --workspace cannot be empty", file=sys.stderr)
            sys.exit(1)

        workspace_dir = location / workspace
        created_paths = []

        inputs_dir = workspace_dir / "inputs"
        for path in [
            workspace_dir,
            inputs_dir,
            inputs_dir / "metadata_parts",
            inputs_dir / "taxonomy_parts",
            inputs_dir / "mapping_configs",
            inputs_dir / "appendix"
        ]:
            if not path.exists():
                path.mkdir(parents=True, exist_ok=True)
                created_paths.append(path)


    def analyze_inputs(self, workspace: str, workspace_root: str = "Workspaces") -> None:
        """Analyze input metadata and taxonomy files for a workspace."""
        self.logger.info(f"Analyzing inputs for workspace: {workspace}")

        # Check if analyzed before and if something changed.
        # create unified metadata.csv and taxonomy.csv under results/analyze_inputs
        self.analyze_metadata(workspace=workspace, workspace_root=workspace_root)
        self.analyze_taxonomy(workspace=workspace, workspace_root=workspace_root)
        raise NotImplementedError("analyze_inputs is not implemented yet")

    def analyze_metadata(self, workspace: str, workspace_root: str = "Workspaces") -> None:
        """Analyze metadata files for a workspace."""
        self.logger.info(f"Analyzing metadata for workspace: {workspace}")
        # Analyze Metadata
        # Create if not exists - metadata enriching json files for each project under inputs/mapping_configs
        # (delete template concept)
        # Enrich: create enriched metadata under results/analyze_inputs
        # Create results/metadata-overview
            # metadata_matrix.csv
            # discovered_keys_by_project.csv
            # discovered_keys_unique.csv
            # projects.csv
            # summary.csv
        raise NotImplementedError("analyze_metadata is not implemented yet")

    def analyze_taxonomy(self, workspace: str, workspace_root: str = "Workspaces") -> None:
        """Analyze taxonomy files for a workspace."""
        self.logger.info(f"Analyzing taxonomy for workspace: {workspace}")

        # Analyze Taxonomy
        # Resolve Old Taxonomies: create (resolved_taxonomy.csv, taxonomy_resolution_changes.csv, taxonomy_resolution_summary.json) files under results/analyze_inputs
        # create taxonomy lineage database under results/analyze_inputs
        # Create results/abundance_matrices
            # abundance_matrix.csv
            # abundance_maaslin.tsv
            # analysis_wide_dataset.csv
        raise NotImplementedError("analyze_taxonomy is not implemented yet")


__all__ = ["AskSLMAPI"]