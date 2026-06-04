from __future__ import annotations
from agent.tools.registry import Registry
from agent.tools.session_tools import session_registry
from agent.tools.run_python import run_python_registry


def _merge(*regs: Registry) -> Registry:
    merged = Registry()
    for r in regs:
        for name, tool in r._tools.items():  # noqa: SLF001
            merged._tools[name] = tool        # noqa: SLF001
    return merged


default_registry: Registry = _merge(session_registry, run_python_registry)

__all__ = ["default_registry"]
