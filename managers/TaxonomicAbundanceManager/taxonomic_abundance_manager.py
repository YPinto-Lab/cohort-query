"""Compatibility wrapper for migrated engine module.

Canonical location: Engines/TaxonomicAbundanceEngine/taxonomic_abundance_engine.py
"""

from Engines.TaxonomicAbundanceEngine.taxonomic_abundance_engine import (  # noqa: F401
    TaxonomicAbundanceEngine,
    TaxonomicAbundanceManager,
)

__all__ = ["TaxonomicAbundanceEngine", "TaxonomicAbundanceManager"]
