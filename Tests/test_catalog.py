"""The catalog is the model's only view of the data. What it omits, the model invents."""
import re

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


def test_high_cardinality_columns_steer_the_model_away_from_equality(catalog):
    """collection_date_sam has 9 distinct values against the fixture's max_distinct=5, so
    it ships as a top-N sample rather than a complete vocabulary. If this branch silently
    regressed to rendering it like a complete list, the model would trust `=` against a
    literal that happens to be missing from the sample -- and get zero rows, believing
    the vocabulary was exhaustive."""
    rendered = catalog.all()

    block = _block_for(rendered, "collection_date_sam")
    assert "ILIKE" in block
    assert "values:" not in block


def test_truncated_numeric_columns_do_not_advise_ilike(catalog):
    """age_years is DOUBLE with 14 distinct values (truncated at the fixture's
    max_distinct=5). DuckDB's ILIKE only binds VARCHAR: `age_years ILIKE '%18%'`
    raises `BinderException: No function matches '~~*(DOUBLE, STRING_LITERAL)'`.
    A model that obeys the catalog's advice writes exactly that query."""
    rendered = catalog.all()

    block = _block_for(rendered, "age_years")
    assert "ILIKE" not in block
    assert "Sample:" in block              # the sample values stay -- they show the scale
    assert re.search(r'"\d+\.0"', block)   # a real age_years literal, not a text vocabulary


def _line_for(rendered: str, column: str) -> str:
    return next(line for line in rendered.splitlines() if line.strip().startswith(column))


def test_system_instruction_states_the_key_and_the_two_sources():
    """The generated SQL is useless unless it returns the join key, and the model must
    know it is writing TWO independent queries, not one join."""
    from askslm.prompt import SYSTEM_INSTRUCTION

    assert "biosample" in SYSTEM_INSTRUCTION
    assert "sample_alias" in SYSTEM_INSTRUCTION
    assert "SELECT" in SYSTEM_INSTRUCTION
    assert "JOIN" in SYSTEM_INSTRUCTION          # to forbid it across the two sources


def _block_for(rendered: str, column: str) -> str:
    """A column's line plus any indented continuation lines under it (the values
    suffix), since that suffix renders on its own line rather than the column's."""
    lines = rendered.splitlines()
    start = next(i for i, line in enumerate(lines) if line.strip().startswith(column))
    block = [lines[start]]
    for line in lines[start + 1:]:
        if not line.startswith("      "):
            break
        block.append(line)
    return "\n".join(block)
