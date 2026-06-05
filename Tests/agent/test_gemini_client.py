from unittest.mock import MagicMock
import pytest
from agent.llm_client import GeminiClient


# --- Helpers to build mock Gemini SDK responses ---

def _mock_response(parts):
    """Build a fake Gemini response whose .candidates[0].content.parts is `parts`."""
    cand = MagicMock()
    cand.content.parts = parts
    msg = MagicMock()
    msg.candidates = [cand]
    return msg


def _text_part(text):
    p = MagicMock()
    p.text = text
    p.function_call = None
    return p


def _fc_part(name, args):
    p = MagicMock()
    p.text = None
    fc = MagicMock()
    fc.name = name
    fc.args = args
    p.function_call = fc
    return p


@pytest.fixture
def mock_genai(monkeypatch):
    fake_models = MagicMock()
    fake_client = MagicMock()
    fake_client.models = fake_models

    import agent.llm_client as m
    monkeypatch.setattr(m, "_gemini_client", lambda: fake_client)
    return fake_models  # tests call fake_models.generate_content.return_value = ...


# --- Tests ---

def test_translates_user_text_message(mock_genai):
    mock_genai.generate_content.return_value = _mock_response([_text_part("hello back")])

    client = GeminiClient(model="gemini-test")
    resp = client.complete(
        messages=[{"role": "user", "content": "hello"}],
        tools=[],
        system="sys",
    )

    assert resp.text == "hello back"
    assert resp.tool_uses == []
    assert resp.is_final

    call = mock_genai.generate_content.call_args
    cfg = call.kwargs["config"]
    assert cfg.system_instruction == "sys"
    contents = call.kwargs["contents"]
    assert len(contents) == 1
    assert contents[0].role == "user"
    assert contents[0].parts[0].text == "hello"


def test_translates_tool_schema_to_function_declaration(mock_genai):
    mock_genai.generate_content.return_value = _mock_response([_text_part("done")])

    tool = {
        "name": "adder",
        "description": "Add two integers.",
        "input_schema": {
            "type": "object",
            "properties": {"x": {"type": "integer"}, "y": {"type": "integer"}},
            "required": ["x"],
        },
    }
    client = GeminiClient(model="gemini-test")
    client.complete(messages=[{"role": "user", "content": "x"}], tools=[tool], system="sys")

    call = mock_genai.generate_content.call_args
    cfg = call.kwargs["config"]
    assert len(cfg.tools) == 1
    decls = cfg.tools[0].function_declarations
    assert len(decls) == 1
    assert decls[0].name == "adder"
    assert decls[0].description == "Add two integers."
    from google.genai import types as gt
    assert decls[0].parameters == gt.Schema(**tool["input_schema"])


def test_parses_function_call_into_tool_use(mock_genai):
    mock_genai.generate_content.return_value = _mock_response([
        _text_part("calling adder"),
        _fc_part("adder", {"x": 3}),
    ])

    client = GeminiClient(model="gemini-test")
    resp = client.complete(messages=[{"role": "user", "content": "go"}], tools=[], system="")

    assert resp.text == "calling adder"
    assert len(resp.tool_uses) == 1
    assert resp.tool_uses[0].name == "adder"
    assert resp.tool_uses[0].input == {"x": 3}
    assert resp.tool_uses[0].id
    assert not resp.is_final


def test_round_trips_assistant_tool_use_to_model_content(mock_genai):
    mock_genai.generate_content.return_value = _mock_response([_text_part("ok")])

    messages = [
        {"role": "user", "content": "go"},
        {"role": "assistant", "content": [
            {"type": "text", "text": "calling adder"},
            {"type": "tool_use", "id": "u1", "name": "adder", "input": {"x": 3}},
        ]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "u1", "content": "4"},
        ]},
    ]
    client = GeminiClient(model="gemini-test")
    client.complete(messages=messages, tools=[], system="")

    contents = mock_genai.generate_content.call_args.kwargs["contents"]
    assert [c.role for c in contents] == ["user", "model", "user"]
    parts = contents[1].parts
    assert any(getattr(p, "text", None) == "calling adder" for p in parts)
    fc_parts = [p for p in parts if getattr(p, "function_call", None) is not None]
    assert len(fc_parts) == 1
    assert fc_parts[0].function_call.name == "adder"
    assert fc_parts[0].function_call.args == {"x": 3}
    fr_parts = contents[2].parts
    assert len(fr_parts) == 1
    fr = fr_parts[0].function_response
    assert fr.name == "adder"
    assert "4" in str(fr.response)


def test_tool_result_error_is_serialized(mock_genai):
    mock_genai.generate_content.return_value = _mock_response([_text_part("ok")])

    messages = [
        {"role": "assistant", "content": [
            {"type": "tool_use", "id": "u1", "name": "adder", "input": {}},
        ]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "u1", "is_error": True, "content": "bad arg"},
        ]},
    ]
    client = GeminiClient(model="gemini-test")
    client.complete(messages=messages, tools=[], system="")

    contents = mock_genai.generate_content.call_args.kwargs["contents"]
    fr = contents[1].parts[0].function_response
    assert fr.name == "adder"
    assert "bad arg" in str(fr.response)


def test_falsy_text_part_is_preserved(mock_genai):
    """A text part with value '0' (or any falsy-but-not-None string) must round-trip."""
    mock_genai.generate_content.return_value = _mock_response([_text_part("0")])
    client = GeminiClient(model="gemini-test")
    resp = client.complete(messages=[{"role": "user", "content": "?"}], tools=[], system="")
    assert resp.text == "0"


def test_missing_api_key_raises_clear_error(monkeypatch):
    """Calling .complete() with no GEMINI_API_KEY surfaces a KeyError naming the var."""
    import agent.llm_client as m

    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    m._gemini_client.cache_clear()

    client = m.GeminiClient(model="gemini-test")
    with pytest.raises(KeyError) as exc:
        client.complete(messages=[{"role": "user", "content": "hi"}], tools=[], system="")
    assert "GEMINI_API_KEY" in str(exc.value)


def test_default_model_is_flash_lite_and_env_var_overrides(monkeypatch):
    from agent.llm_client import GeminiClient, DEFAULT_GEMINI_MODEL

    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    assert GeminiClient().model == DEFAULT_GEMINI_MODEL == "gemini-3.1-flash-lite"

    monkeypatch.setenv("GEMINI_MODEL", "gemini-2.5-flash")
    assert GeminiClient().model == "gemini-2.5-flash"

    # explicit constructor arg wins over env var
    monkeypatch.setenv("GEMINI_MODEL", "gemini-2.5-flash")
    assert GeminiClient(model="gemini-3-flash").model == "gemini-3-flash"


def test_thought_signature_round_trips(mock_genai):
    """Gemini thinking models attach a thought_signature to function_call parts;
    we must capture it on the response and replay it on the next request."""
    # Mock response with a function_call part carrying a thought_signature.
    fc_part = _fc_part("list_files", {})
    fc_part.thought_signature = b"\x01\x02\x03sig-bytes"
    mock_genai.generate_content.return_value = _mock_response([fc_part])

    client = GeminiClient(model="gemini-test")
    resp = client.complete(messages=[{"role": "user", "content": "go"}], tools=[], system="")

    # Signature is captured on the ToolUse.
    assert len(resp.tool_uses) == 1
    assert resp.tool_uses[0].thought_signature == b"\x01\x02\x03sig-bytes"

    # Echo it back: build an assistant message dict carrying the signature and
    # send it through complete() again, then verify the rebuilt Part has it.
    mock_genai.generate_content.return_value = _mock_response([_text_part("done")])
    messages = [
        {"role": "user", "content": "go"},
        {"role": "assistant", "content": [{
            "type": "tool_use",
            "id": resp.tool_uses[0].id,
            "name": "list_files",
            "input": {},
            "_gemini_thought_signature": b"\x01\x02\x03sig-bytes",
        }]},
        {"role": "user", "content": [{
            "type": "tool_result", "tool_use_id": resp.tool_uses[0].id, "content": "ok",
        }]},
    ]
    client.complete(messages=messages, tools=[], system="")

    contents = mock_genai.generate_content.call_args.kwargs["contents"]
    # The assistant turn's function_call Part carries the signature back to Gemini.
    fc_parts = [p for p in contents[1].parts if getattr(p, "function_call", None) is not None]
    assert len(fc_parts) == 1
    assert fc_parts[0].thought_signature == b"\x01\x02\x03sig-bytes"
