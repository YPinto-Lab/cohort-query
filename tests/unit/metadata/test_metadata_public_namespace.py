from askslm import metadata
from askslm.contracts import MetadataOverview


def test_metadata_exposes_callables():
    assert callable(metadata.extract)
    assert callable(metadata.overview)


def test_contracts_reexports_metadata_overview():
    assert MetadataOverview.__name__ == "MetadataOverview"
