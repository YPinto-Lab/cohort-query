from __future__ import annotations
from pathlib import Path
from typing import Literal

import Engines.TaxonomyEngine as tx_api
from Engines.TaxonomyEngine.abundance_matrix import AbundanceMatrix
from Engines.MetadataEngine.metadata import Metadata
from Common.contracts.taxonomy_results import ResolvedTaxonomy

from Agents.handle import Handle
from Agents.session import Session
from Agents.tools.registry import Registry

taxonomy_registry = Registry()

Rank = Literal["superkingdom", "phylum", "class", "order", "family", "genus", "species"]


@taxonomy_registry.tool
def load_taxonomy(session: Session, path: str) -> dict:
    """Load a taxonomy CSV (acc, tax_id, total_count) into a DataFrame handle."""
    df = tx_api.load(Path(path))
    h = session.variables.put(df, hint="tax")
    return session.variables.summary(h)


@taxonomy_registry.tool
def resolve_taxonomy(session: Session, taxonomy: Handle[object]) -> dict:
    """Resolve deprecated NCBI tax_ids in a taxonomy DataFrame against merged.dmp.
    Returns a handle to a ResolvedTaxonomy."""
    df = session.variables.get(taxonomy)
    resolved = tx_api.resolve(df)
    h = session.variables.put(resolved, hint="resolved_tax")
    return session.variables.summary(h)


@taxonomy_registry.tool
def build_abundance_matrix(
    session: Session,
    taxonomy: Handle[ResolvedTaxonomy],
    rank: Rank = "genus",
) -> dict:
    """Build a single-rank abundance matrix from a ResolvedTaxonomy handle.
    Returns a handle to an AbundanceMatrix."""
    resolved = session.variables.get(taxonomy)
    matrix = tx_api.build_abundance_matrix(resolved.df, rank=rank)
    h = session.variables.put(matrix, hint="matrix")
    return session.variables.summary(h)


@taxonomy_registry.tool
def build_cohort(
    session: Session,
    matrix: Handle[AbundanceMatrix],
    metadata: Handle[Metadata],
) -> dict:
    """Pair an AbundanceMatrix handle with a Metadata handle into a Cohort handle."""
    m = session.variables.get(matrix)
    md = session.variables.get(metadata)
    cohort = tx_api.build_cohort(m, md)
    h = session.variables.put(cohort, hint="cohort")
    return session.variables.summary(h)
