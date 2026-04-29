from typing import Optional

from IPython.display import display

from .taxonomic_abundance_logic import TaxonomicAbundanceInputs, TaxonomicAbundanceLogic
from .taxonomic_abundance_ui import TaxonomicAbundanceUIController


class TaxonomicAbundanceEngine:
    _ACTIVE_UIS = []

    def __init__(self, inputs: Optional[TaxonomicAbundanceInputs] = None, logger=None, **legacy_kwargs):
        resolved_inputs = self._resolve_inputs(inputs, legacy_kwargs)
        self.logic = TaxonomicAbundanceLogic(resolved_inputs, logger=logger)
        self.ui_controller = TaxonomicAbundanceUIController(self.logic)
        self._ui = None

    def _resolve_inputs(self, inputs, legacy_kwargs) -> TaxonomicAbundanceInputs:
        if inputs is not None:
            return inputs
        return TaxonomicAbundanceInputs(**legacy_kwargs)

    def run(self):
        self._close_active_uis()
        self._close_current_ui()
        ui = self.ui_controller.create_ui()
        TaxonomicAbundanceEngine._ACTIVE_UIS.append(ui)
        self._ui = ui
        display(ui)

    def _close_active_uis(self):
        if not hasattr(TaxonomicAbundanceEngine, "_ACTIVE_UIS"):
            TaxonomicAbundanceEngine._ACTIVE_UIS = []
        for ui in list(TaxonomicAbundanceEngine._ACTIVE_UIS):
            try:
                ui.close()
            except Exception:
                pass
        TaxonomicAbundanceEngine._ACTIVE_UIS.clear()

    def _close_current_ui(self):
        if self._ui is None:
            return
        self._ui.close()
        self._ui = None

    @property
    def current_export_df(self):
        return self.ui_controller.current_export_df

    @property
    def current_taxon_name(self):
        return self.ui_controller.current_taxon_name


# Canonical iDesign name for this engine.
TaxonomicAbundanceEngine = TaxonomicAbundanceEngine