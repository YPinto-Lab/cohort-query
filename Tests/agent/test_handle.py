from typing import get_type_hints
from Agents.handle import Handle


def test_handle_is_str_at_runtime():
    h: Handle[int] = "matrix_1"
    assert isinstance(h, str)
    assert h == "matrix_1"


def test_handle_unwrap_arg_returns_underlying_type():
    from Agents.handle import unwrap_handle_arg
    def fn(x: Handle[int]) -> None: ...
    hint = get_type_hints(fn, include_extras=True)["x"]
    assert unwrap_handle_arg(hint) is int


def test_unwrap_returns_none_for_non_handle():
    from Agents.handle import unwrap_handle_arg
    assert unwrap_handle_arg(str) is None
