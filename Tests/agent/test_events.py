from agent.events import Event


def test_event_factories():
    assert Event.user("hi").type == "user"
    assert Event.assistant_final("done").type == "assistant_final"
    tc = Event.tool_call("foo", {"a": 1})
    assert tc.type == "tool_call" and tc.payload["tool"] == "foo"
    tr = Event.tool_result("foo", {"type": "DataFrame"})
    assert tr.type == "tool_result"
    assert Event.error("nope").type == "error"
