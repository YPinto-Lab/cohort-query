from __future__ import annotations
import inspect
import time
import traceback
from dataclasses import dataclass
from typing import Any, Callable, get_type_hints
from pydantic import ValidationError, create_model

from Agents.handle import unwrap_handle_arg
from Agents.session import Session


@dataclass
class ToolResult:
    is_error: bool
    value: Any = None
    summary: dict | None = None
    error: str | None = None
    traceback: str | None = None
    latency_ms: int = 0


@dataclass
class _Tool:
    name: str
    fn: Callable
    schema: dict
    arg_model: type  # Pydantic model
    handle_params: dict[str, type]  # param name -> wrapped type


class Registry:
    def __init__(self) -> None:
        self._tools: dict[str, _Tool] = {}

    def tool(self, fn: Callable) -> Callable:
        spec = inspect.signature(fn)
        hints = get_type_hints(fn, include_extras=True)
        fields: dict[str, tuple] = {}
        properties: dict[str, dict] = {}
        required: list[str] = []
        handle_params: dict[str, type] = {}

        for pname, param in spec.parameters.items():
            if pname == "session":
                continue
            ann = hints.get(pname, Any)
            wrapped = unwrap_handle_arg(ann)
            if wrapped is not None:
                handle_params[pname] = wrapped
                properties[pname] = {
                    "type": "string",
                    "description": f"handle to a {wrapped.__name__}",
                }
                fields[pname] = (str, ... if param.default is inspect.Parameter.empty else param.default)
            else:
                properties[pname] = _json_schema_for(ann)
                if param.default is inspect.Parameter.empty:
                    fields[pname] = (ann, ...)
                else:
                    fields[pname] = (ann, param.default)
            if param.default is inspect.Parameter.empty:
                required.append(pname)

        arg_model = create_model(f"{fn.__name__}_Args", **fields)  # type: ignore[arg-type]
        doc = (fn.__doc__ or "").strip()
        schema = {
            "name": fn.__name__,
            "description": doc,
            "input_schema": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        }
        self._tools[fn.__name__] = _Tool(
            name=fn.__name__, fn=fn, schema=schema, arg_model=arg_model,
            handle_params=handle_params,
        )
        return fn

    def schemas(self) -> list[dict]:
        return [t.schema for t in self._tools.values()]

    def execute(self, session: Session, name: str, raw_input: dict) -> ToolResult:
        t0 = time.perf_counter()
        if name not in self._tools:
            return ToolResult(
                is_error=True,
                error=f"unknown tool: {name}",
                latency_ms=int((time.perf_counter() - t0) * 1000),
            )
        t = self._tools[name]
        try:
            validated = t.arg_model(**raw_input)
        except ValidationError as e:
            return ToolResult(
                is_error=True,
                error=str(e),
                latency_ms=int((time.perf_counter() - t0) * 1000),
            )

        kwargs = validated.model_dump()
        for pname in t.handle_params:
            handle = kwargs[pname]
            if handle not in session.variables:
                return ToolResult(
                    is_error=True,
                    error=(
                        f"Handle {handle!r} not found for arg {pname!r}. "
                        f"Available: {sorted(session.variables.list_handles())}"
                    ),
                    latency_ms=int((time.perf_counter() - t0) * 1000),
                )

        try:
            value = t.fn(session, **kwargs)
        except Exception as e:
            return ToolResult(
                is_error=True,
                error=str(e),
                traceback=traceback.format_exc(),
                latency_ms=int((time.perf_counter() - t0) * 1000),
            )

        summary = value if isinstance(value, dict) else {"value": _to_jsonable(value)}
        return ToolResult(
            is_error=False, value=value, summary=summary,
            latency_ms=int((time.perf_counter() - t0) * 1000),
        )


_PRIMITIVE_SCHEMA = {
    int: {"type": "integer"},
    float: {"type": "number"},
    str: {"type": "string"},
    bool: {"type": "boolean"},
}


def _json_schema_for(annotation) -> dict:
    from typing import get_origin, get_args, Literal
    if annotation in _PRIMITIVE_SCHEMA:
        return _PRIMITIVE_SCHEMA[annotation]
    if get_origin(annotation) is Literal:
        return {"type": "string", "enum": list(get_args(annotation))}
    return {"type": "string"}


def _to_jsonable(v: Any) -> Any:
    if isinstance(v, (str, int, float, bool, type(None))):
        return v
    if isinstance(v, (list, tuple)):
        return [_to_jsonable(x) for x in v]
    if isinstance(v, dict):
        return {str(k): _to_jsonable(x) for k, x in v.items()}
    return repr(v)[:200]


# Exported for naming consistency, though tests use reg.tool
tool = Registry().tool
