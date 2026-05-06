from __future__ import annotations

from .accessor import TaxonomyAccessorRunner
from .enrichment import EnrichmentStageRunner
from .merge import MergeStageRunner
from .taxonomy import TaxonomyStageRunner
from ..runtime_assembly_models import RuntimeAssemblyPaths


class DatasetAssemblyRuntimeEngine:
    def __init__(self, paths: RuntimeAssemblyPaths, logger=None):
        self.paths = self._validate_paths(paths)
        self._enrichment = EnrichmentStageRunner(self.paths, logger=logger)
        self._taxonomy = TaxonomyStageRunner(self.paths, logger=logger)
        self._merge = MergeStageRunner(self.paths, logger=logger)
        self._accessor = TaxonomyAccessorRunner(self.paths, logger=logger)

    def _validate_paths(self, paths: RuntimeAssemblyPaths) -> RuntimeAssemblyPaths:
        from pathlib import Path
        for path in [paths.workspace_input_dir, paths.results_dir, paths.assembly_db_dir]:
            if not Path(path).exists():
                raise FileNotFoundError(f"Required runtime directory does not exist: {path}")
        return RuntimeAssemblyPaths(Path(paths.workspace_input_dir), Path(paths.results_dir), Path(paths.assembly_db_dir))

    def run_enrichment_stage(self, request):
        return self._enrichment.run(request)

    def run_taxonomy_stage(self, request):
        return self._taxonomy.run(request)

    def run_merge_stage(self, request):
        return self._merge.run(request)

    def build_or_load_tax_accessor(self, request):
        return self._accessor.run(request)

