from agent.llm_client import FakeLLMClient, ToolUse, AssistantText


def test_fake_returns_scripted_responses_in_order():
    fake = FakeLLMClient(responses=[
        [ToolUse(id="u1", name="extract_metadata", input={"path": "m.csv"})],
        [AssistantText(text="done")],
    ])
    r1 = fake.complete(messages=[], tools=[], system="")
    assert r1.tool_uses[0].name == "extract_metadata"
    assert not r1.is_final
    r2 = fake.complete(messages=[], tools=[], system="")
    assert r2.is_final
    assert r2.text == "done"
