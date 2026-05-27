from __future__ import annotations
from Agents.tools.registry import Registry
from Agents.tools.metadata_tools import metadata_registry
from Agents.tools.taxonomy_tools import taxonomy_registry
from Agents.tools.session_tools import session_registry
from Agents.tools.run_python import run_python_registry


def _merge(*regs: Registry) -> Registry:
    merged = Registry()
    for r in regs:
        for name, tool in r._tools.items():  # noqa: SLF001
            merged._tools[name] = tool        # noqa: SLF001
    return merged


default_registry: Registry = _merge(
    metadata_registry, taxonomy_registry, session_registry, run_python_registry,
)

__all__ = ["default_registry"]
