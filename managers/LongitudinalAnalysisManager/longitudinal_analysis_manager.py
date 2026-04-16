"""Compatibility wrapper for migrated engine module.

Canonical location: Engines/LongitudinalAnalysisEngine/longitudinal_analysis_engine.py
"""

from Engines.LongitudinalAnalysisEngine.longitudinal_analysis_engine import (  # noqa: F401
    LongitudinalAnalysisEngine,
    LongitudinalAnalysisManager,
)

__all__ = ["LongitudinalAnalysisEngine", "LongitudinalAnalysisManager"]
