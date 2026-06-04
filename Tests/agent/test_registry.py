import pytest
from typing import Literal
from Agents.tools.registry import tool, Registry
from Agents.handle import Handle
from Agents.session import Session
from Agents.workspace import Workspace


@pytest.fixture
def session(tmp_path):
    root = tmp_path / "ws"; root.mkdir()
    return Session.start(Workspace.open(root))


def test_tool_schema_omits_session_param(session):
    reg = Registry()

    @reg.tool
    def adder(session: Session, x: int, y: int = 1) -> int:
        """Add two integers."""
        return x + y

    schema = reg.schemas()[0]
    assert schema["name"] == "adder"
    assert schema["description"].startswith("Add two integers")
    assert set(schema["input_schema"]["properties"]) == {"x", "y"}
    assert schema["input_schema"]["required"] == ["x"]


def test_tool_schema_for_handle_param(session):
    reg = Registry()

    @reg.tool
    def use_df(session: Session, df: Handle[int]) -> int:
        """Use it."""
        return 0

    prop = reg.schemas()[0]["input_schema"]["properties"]["df"]
    assert prop["type"] == "string"
    assert "handle" in prop["description"].lower()


def test_execute_validates_args(session):
    reg = Registry()

    @reg.tool
    def adder(session: Session, x: int) -> int:
        """Add."""
        return x + 1

    res = reg.execute(session, "adder", {"x": "not an int"})
    assert res.is_error
    assert "x" in res.error


def test_execute_resolves_handle(session):
    reg = Registry()

    @reg.tool
    def double(session: Session, h: Handle[int]) -> int:
        """Double."""
        return session.variables.get(h) * 2

    h = session.variables.put(21, hint="n")
    res = reg.execute(session, "double", {"h": h})
    assert not res.is_error
    assert res.value == 42


def test_execute_missing_handle_errors(session):
    reg = Registry()

    @reg.tool
    def passer(session: Session, h: Handle[int]) -> int:
        """Pass."""
        return 0

    res = reg.execute(session, "passer", {"h": "n_99"})
    assert res.is_error
    assert "n_99" in res.error


def test_execute_captures_exception(session):
    reg = Registry()

    @reg.tool
    def boom(session: Session) -> int:
        """Boom."""
        raise RuntimeError("kaboom")

    res = reg.execute(session, "boom", {})
    assert res.is_error
    assert "kaboom" in res.error
    assert "Traceback" in res.traceback


def test_unknown_tool_errors(session):
    reg = Registry()
    res = reg.execute(session, "nope", {})
    assert res.is_error
    assert "unknown tool" in res.error.lower()


def test_default_registry_includes_all_tools():
    from Agents.tools import default_registry
    assert set(default_registry._tools) == {"list_workspace_inputs", "run_python", "summarize"}
