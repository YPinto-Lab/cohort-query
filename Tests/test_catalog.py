"""The catalog is the model's only view of the data. What it omits, the model invents."""
import pytest

from askslm.adapters import DuckDbConnection
from askslm.catalog import SchemaCatalog

from fixtures.mirror import build_fixture_mirror


@pytest.fixture
def catalog(tmp_path):
    path = build_fixture_mirror(tmp_path / "fixture.duckdb")
    connection = DuckDbConnection(path)
    yield SchemaCatalog(connection)
    connection.close()


def test_names_both_metadata_tables_and_no_profile_table(catalog):
    """The LLM writes metadata SQL only (HLD E.2). A profile table in the prompt
    invites it to write a query nothing will ever run."""
    rendered = catalog.all()

    assert "sra_metadata" in rendered
    assert "metalog_metadata" in rendered
    assert "sra_taxonomy" not in rendered
    assert "metalog_motus3" not in rendered


def test_low_cardinality_columns_ship_their_real_values(catalog):
    """A question says "IBD"; the data says "Crohn's disease". The model can only bridge
    that if it is shown the literal actually stored. Given only a column name it invents
    a plausible spelling and gets zero rows back."""
    rendered = catalog.all()

    assert "subject_disease_status" in rendered
    assert "Crohn's disease" in rendered          # the fixture's real value, not "IBD"


def test_array_columns_are_flagged_so_equality_is_not_used(catalog):
    """geo_loc_name_sam is VARCHAR[]. `WHERE geo_loc_name_sam = 'Israel'` matches
    nothing at all -- silently."""
    rendered = catalog.all()

    line = _line_for(rendered, "geo_loc_name_sam")
    assert "[]" in line
    assert "list_contains" in line


def _line_for(rendered: str, column: str) -> str:
    return next(line for line in rendered.splitlines() if line.strip().startswith(column))
