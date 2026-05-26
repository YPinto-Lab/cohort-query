from __future__ import annotations
from pathlib import Path

from Engines.MetadataEngine import extract, overview
from Engines.MetadataEngine.metadata import Metadata
from Common.contracts.metadata_results import MetadataOverview

from Agents.handle import Handle
from Agents.session import Session
from Agents.tools.registry import Registry

metadata_registry = Registry()


@metadata_registry.tool
def extract_metadata(session: Session, path: str) -> dict:
    """Read a metadata CSV and expand jattr/attributes blobs into real columns.
    Returns a handle to a Metadata object."""
    df = extract(Path(path))
    obj = Metadata(df=df)
    handle = session.variables.put(obj, hint="meta")
    return session.variables.summary(handle)


@metadata_registry.tool
def metadata_overview(session: Session, metadata: Handle[Metadata]) -> dict:
    """Compute a per-column overview (coverage, top values) for a Metadata handle.
    Returns a handle to a MetadataOverview."""
    md = session.variables.get(metadata)
    overview_obj = overview(md.df)
    handle = session.variables.put(overview_obj, hint="meta_overview")
    return session.variables.summary(handle)
