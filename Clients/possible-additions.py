"""Programmatic API surface for Ask-SLM CLI operations.

This module exposes a class-based interface for invoking analyses programmatically.
"""

import logging
import sys
from typing import Iterable, Optional
from pathlib import Path

from Engines.MetadataOverviewEngine import MetadataOverviewEngine


def alpha_diversity(
        self,
        workspace: str,
        rank: str,
        group: Optional[str] = None,
        filter_rank: Optional[str] = None,
        filter_taxon: Optional[str] = None,
        workspace_root: str = "Workspaces",
        inputs_dir: Optional[str] = None,
        output_dir: Optional[str] = None,
        config_dir: Optional[str] = None,
        lineage_db_path: Optional[str] = None,
) -> None:
    """Compute alpha diversity for a workspace."""
    self.logger.info(f"Computing alpha diversity for {workspace} at rank {rank}")
    raise NotImplementedError("alpha_diversity is not implemented yet")


def taxonomic_abundance(
        self,
        workspace: str,
        rank: str,
        taxon: str,
        group: Optional[str] = None,
        workspace_root: str = "Workspaces",
        inputs_dir: Optional[str] = None,
        output_dir: Optional[str] = None,
        config_dir: Optional[str] = None,
) -> None:
    """Compute relative abundance for a specific taxon."""
    self.logger.info(f"Computing taxonomic abundance for {taxon} ({rank}) in {workspace}")
    raise NotImplementedError("taxonomic_abundance is not implemented yet")


def single_taxon_abundance(
        self,
        workspace: str,
        taxon: str = "Viruses",
        rank: str = "superkingdom",
        source_keys: Optional[Iterable[str]] = None,
        group: Optional[str] = None,
        workspace_root: str = "Workspaces",
        inputs_dir: Optional[str] = None,
        output_dir: Optional[str] = None,
        config_dir: Optional[str] = None,
) -> None:
    """Run single taxon abundance analysis."""
    self.logger.info(f"Running single taxon abundance for {taxon} in {workspace}")
    raise NotImplementedError("single_taxon_abundance is not implemented yet")

