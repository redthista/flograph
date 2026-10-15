"""flograph.llm.toolcall: tool calling in both wire formats and the JSON
fallback. No network — requests stop at wire._post."""
import json

import pytest

from flograph.llm import toolcall, wire
from flograph.llm.toolcall import ToolCall, ToolSpec

TOOLS = [ToolSpec("add_node", "Add a node",
                  {"type": "object", "properties": {"type_id": {"type": "string"}},
                   "required": ["type_id"]})]

HISTORY = [
    {"role": "system", "content": "sys"},
    {"role": "user", "content": "make a chart"},
    {"role": "assistant", "content": "", "tool_calls": [
        ToolCall("c1", "add_node", {"type_id": "a"}),
        ToolCall("c2", "add_node", {"type_id": "b"})]},
    {"role": "tool", "tool_call_id": "c1", "name": "add_node", "content": "ok 1"},
    {"role": "tool", "tool_call_id": "c2", "name": "add_node", "content": "ok 2"},
]


class _Reply:
    def __init__(self, payload=None, status=200, text=""):
        self._payload, self.status_code, self.text = payload, status, text

    def json(self):
        return self._payload


def _record(monkeypatch, replies):
    calls, queue = [], list(replies)

    def fake_post(url, headers, body, timeout, verify):
        calls.append({"url": url, "body": body})
        return queue.pop(0) if len(queue) > 1 else queue[0]

    monkeypatch.setattr(wire, "_post", fake_post)
    return calls


def _conn(provider="openai"):
    return wire.Connection(provider=provider, model="m",
                           base_url="http://localhost:1/v1")


class TestOutgoing:
    def test_openai_shape(self):
        body = toolcall.request_body(_conn(), HISTORY, TOOLS, "native")
        assert body["tools"][0] == {"type": "function", "function": {
            "name": "add_node", "description": "Add a node",
            "parameters": TOOLS[0].parameters}}
        assistant = body["messages"][2]
        assert assistant["tool_calls"][0]["function"] == {
            "name": "add_node", "arguments": json.dumps({"type_id": "a"})}
        assert body["messages"][3] == {"role": "tool", "tool_call_id": "c1",
                                       "content": "ok 1"}

    def test_anthropic_shape(self):
        body = toolcall.request_body(_conn("anthropic"), HISTORY, TOOLS, "native")
        assert body["system"] == "sys"
        assert body["tools"][0]["input_schema"] == TOOLS[0].parameters
        assistant = body["messages"][1]
        assert [b["type"] for b in assistant["content"]] == ["tool_use", "tool_use"]
        assert assistant["content"][0]["input"] == {"type_id": "a"}
        # both results in ONE user message — the format needs turns to alternate
        results = body["messages"][2]
        assert results["role"] == "user"
        assert [b["tool_use_id"] for b in results["content"]] == ["c1", "c2"]
        assert len(body["messages"]) == 3

    def test_anthropic_never_sends_an_empty_text_block(self):
        body = toolcall.request_body(_conn("anthropic"), HISTORY, TOOLS, "native")
        for message in body["messages"]:
            for block in message["content"]:
                assert block.get("type") != "text" or block["text"]

    def test_fallback_writes_tool_traffic_as_text(self):
        body = toolcall.request_body(_conn(), HISTORY, TOOLS, "json")
        assert "tools" not in body
        system = body["messages"][0]["content"]
        assert system.startswith("sys") and "add_node" in system and "```tool" in system
        assert "```tool" in body["messages"][2]["content"]
        assert body["messages"][3]["role"] == "user"
        assert "ok 1" in body["messages"][3]["content"]
        assert "ok 2" in body["messages"][3]["content"]


class TestIncoming:
    def test_openai_tool_calls(self, monkeypatch):
        _record(monkeypatch, [_Reply({"choices": [{"message": {
            "content": None, "tool_calls": [{"id": "x", "type": "function",
                "function": {"name": "add_node", "arguments": '{"type_id": "t"}'}}]},
            "finish_reason": "tool_calls"}]})])
        reply = toolcall.chat_with_tools(_conn(), HISTORY[:2], TOOLS)
        assert reply.tool_calls[0].to_dict() == {
            "id": "x", "name": "add_node", "arguments": {"type_id": "t"}}
        assert reply.text == "" and reply.mode == "native" and not reply.done

    def test_bad_arguments_are_kept_for_the_error(self, monkeypatch):
        _record(monkeypatch, [_Reply({"choices": [{"message": {
            "tool_calls": [{"id": "x", "function": {
                "name": "add_node", "arguments": "{type_id: t"}}]}}]})])
        call = toolcall.chat_with_tools(_conn(), HISTORY[:2], TOOLS).tool_calls[0]
        assert call.arguments == {} and call.bad_arguments == "{type_id: t"

    def test_anthropic_tool_use_with_words(self, monkeypatch):
        _record(monkeypatch, [_Reply({"content": [
            {"type": "text", "text": "Adding it."},
            {"type": "tool_use", "id": "tu", "name": "add_node",
             "input": {"type_id": "t"}}], "stop_reason": "tool_use"})])
        reply = toolcall.chat_with_tools(_conn("anthropic"), HISTORY[:2], TOOLS)
        assert reply.text == "Adding it."
        assert reply.tool_calls[0].arguments == {"type_id": "t"}

    def test_final_answer(self, monkeypatch):
        _record(monkeypatch, [_Reply({"choices": [{"message": {"content": "Done."}}]})])
        reply = toolcall.chat_with_tools(_conn(), HISTORY, TOOLS)
        assert reply.done and reply.text == "Done."


class TestFallback:
    def test_auto_drops_to_json_when_tools_are_refused(self, monkeypatch):
        calls = _record(monkeypatch, [
            _Reply(status=400, text='{"error": "llama3 does not support tools"}'),
            _Reply({"choices": [{"message": {"content":
                'Sure.\n```tool\n{"calls": [{"name": "add_node", '
                '"arguments": {"type_id": "t"}}]}\n```'}}]}),
        ])
        reply = toolcall.chat_with_tools(_conn(), HISTORY[:2], TOOLS)
        assert reply.mode == "json"
        assert reply.text == "Sure."
        assert reply.tool_calls[0].arguments == {"type_id": "t"}
        assert "tools" in calls[0]["body"] and "tools" not in calls[1]["body"]

    def test_native_mode_does_not_fall_back(self, monkeypatch):
        _record(monkeypatch, [_Reply(status=400, text="does not support tools")])
        with pytest.raises(wire.LLMError, match="tools"):
            toolcall.chat_with_tools(_conn(), HISTORY[:2], TOOLS, mode="native")

    def test_other_400s_are_not_mistaken_for_no_tools(self, monkeypatch):
        calls = _record(monkeypatch, [_Reply(status=400, text="model not found")])
        with pytest.raises(wire.LLMError, match="model not found"):
            toolcall.chat_with_tools(_conn(), HISTORY[:2], TOOLS)
        assert len(calls) == 1

    def test_json_mode_skips_native(self, monkeypatch):
        calls = _record(monkeypatch, [_Reply({"choices": [{"message": {
            "content": "All done."}}]})])
        reply = toolcall.chat_with_tools(_conn(), HISTORY[:2], TOOLS, mode="json")
        assert reply.done and reply.mode == "json"
        assert len(calls) == 1 and "tools" not in calls[0]["body"]

    @pytest.mark.parametrize("text", [
        '```tool\n{"calls": [{"name": "add_node", "arguments": {"type_id": "t"}}]}\n```',
        '```json\n{"calls": [{"name": "add_node", "arguments": {"type_id": "t"}}]}\n```',
        '```tool\n{"name": "add_node", "arguments": {"type_id": "t"}}\n```',
        '<think>hmm ```tool {} ```</think>```tool\n[{"name": "add_node", '
        '"arguments": "{\\"type_id\\": \\"t\\"}"}]\n```',
    ])
    def test_shapes_models_actually_write(self, text):
        reply = toolcall.parse_fallback(text)
        assert [(c.name, c.arguments) for c in reply.tool_calls] == [
            ("add_node", {"type_id": "t"})]

    def test_a_json_example_in_an_answer_is_not_a_call(self):
        reply = toolcall.parse_fallback('Here:\n```json\n{"a": 1}\n```')
        assert reply.done

    def test_broken_tool_block_is_reported_not_ignored(self):
        reply = toolcall.parse_fallback("```tool\n{nope\n```")
        assert reply.tool_calls[0].bad_arguments == "{nope"


def test_no_tools_is_a_plain_chat(monkeypatch):
    calls = _record(monkeypatch, [_Reply({"choices": [{"message": {"content": "hi"}}]})])
    reply = toolcall.chat_with_tools(_conn(), [{"role": "user", "content": "x"}], [])
    assert reply.text == "hi" and "tools" not in calls[0]["body"]
