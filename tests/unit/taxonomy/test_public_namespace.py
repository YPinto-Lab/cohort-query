from askslm import taxonomy


def test_taxonomy_exposes_core_callables():
    for name in ("load", "lineage_table"):
        assert callable(getattr(taxonomy, name))
