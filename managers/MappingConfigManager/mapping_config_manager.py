"""Compatibility wrapper for migrated engine module.

Canonical location: Engines/MappingConfigEngine/mapping_config_engine.py
"""

from Engines.MappingConfigEngine.mapping_config_engine import (  # noqa: F401
    MappingConfigEngine,
    MappingConfigManager,
)

__all__ = ["MappingConfigEngine", "MappingConfigManager"]
