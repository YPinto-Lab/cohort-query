from unittest.mock import MagicMock
from agent.llm_client import AnthropicClient


def test_anthropic_client_parses_tool_use(monkeypatch):
    text_block = MagicMock()
    text_block.configure_mock(type="text", text="thinking...")

    tool_block = MagicMock()
    tool_block.configure_mock(type="tool_use", id="u1", name="adder", input={"x": 1})

    fake_msg = MagicMock()
    fake_msg.content = [text_block, tool_block]

    fake_client = MagicMock()
    fake_client.messages.create.return_value = fake_msg

    import agent.llm_client as m
    monkeypatch.setattr(m, "_anthropic_client", lambda: fake_client)

    client = AnthropicClient(model="claude-test")
    resp = client.complete(messages=[{"role": "user", "content": "hi"}], tools=[], system="sys")

    assert len(resp.tool_uses) == 1
    assert resp.tool_uses[0].name == "adder"
    assert resp.text == "thinking..."
    fake_client.messages.create.assert_called_once()
