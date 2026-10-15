"""Streamed replies (llm/stream.py): server-sent events in both formats,
put back together as the reply they stand for, with the text handed on as
it arrives. Only `wire._post_stream` is faked, so the climb-down, the URL
retries and the parsers are the real ones."""
import json

import pytest

from flograph.llm import toolcall, wire
from flograph.llm.toolcall import ToolSpec
from flograph.ui.flo.panel import visible_text


class _SSE:
    """A streamed response: `data:` lines, or a plain JSON body."""

    def __init__(self, events=None, *, status=200, text="", body=None):
        self.status_code = status
        self.text = text
        self.closed = False
        self._body = body
        self.headers = {"content-type": "application/json" if body is not None
                        else "text/event-stream"}
        self._lines = []
        for event in events or []:
            if isinstance(event, str):
                self._lines.append(event)
            else:
                self._lines += [f"data: {json.dumps(event)}", ""]

    def iter_lines(self):
        yield from self._lines

    def json(self):
        return self._body

    def close(self):
        self.closed = True


def _serve(monkeypatch, *responses):
    sent = []
    queue = list(responses)

    def post_stream(url, headers, body, timeout, verify):
        sent.append(body)
        return queue.pop(0)

    monkeypatch.setattr(wire, "_post_stream", post_stream)
    return sent


TOOLS = [ToolSpec("describe_flow", "look", {"type": "object", "properties": {}})]
OPENAI = wire.Connection(provider="openai", model="m", base_url="http://localhost:1/v1")
ANTHROPIC = wire.Connection(provider="anthropic", model="m",
                            base_url="http://localhost:1/v1")


def _chunks(*deltas, finish="stop"):
    out = [{"choices": [{"delta": d}]} for d in deltas]
    out.append({"choices": [{"delta": {}, "finish_reason": finish}]})
    return out + ["data: [DONE]"]


class TestOpenAI:
    def test_text_arrives_in_pieces_and_adds_up(self, monkeypatch):
        sent = _serve(monkeypatch, _SSE(_chunks({"content": "Hel"}, {"content": "lo"})))
        pieces = []
        reply = toolcall.chat_with_tools(OPENAI, [{"role": "user", "content": "hi"}],
                                         TOOLS, on_text=pieces.append)
        assert pieces == ["Hel", "lo"] and reply.text == "Hello" and reply.done
        assert sent[0]["stream"] is True

    def test_tool_call_arguments_are_joined_before_use(self, monkeypatch):
        _serve(monkeypatch, _SSE(_chunks(
            {"tool_calls": [{"index": 0, "id": "c1", "function": {
                "name": "describe_flow", "arguments": '{"sco'}}]},
            {"tool_calls": [{"index": 0, "function": {"arguments": 'pe": "all"}'}}]},
            finish="tool_calls")))
        reply = toolcall.chat_with_tools(OPENAI, [{"role": "user", "content": "x"}],
                                         TOOLS, on_text=lambda t: None)
        assert reply.tool_calls[0].name == "describe_flow"
        assert reply.tool_calls[0].arguments == {"scope": "all"}
        assert reply.tool_calls[0].id == "c1"

    def test_a_server_that_ignores_stream_still_works(self, monkeypatch):
        _serve(monkeypatch, _SSE(body={"choices": [{"message": {"content": "whole"}}]}))
        pieces = []
        reply = toolcall.chat_with_tools(OPENAI, [{"role": "user", "content": "x"}],
                                         TOOLS, on_text=pieces.append)
        assert reply.text == "whole" and pieces == []

    def test_a_server_that_refuses_stream_is_asked_without_it(self, monkeypatch):
        sent = []
        monkeypatch.setattr(wire, "_post_stream", lambda *a: sent.append("stream")
                            or _SSE(status=400, text="'stream' is not supported"))
        monkeypatch.setattr(wire, "_post", lambda url, h, body, t, v: sent.append(body)
                            or _SSE(body={"choices": [{"message": {"content": "ok"}}]}))
        reply = toolcall.chat_with_tools(OPENAI, [{"role": "user", "content": "x"}],
                                         TOOLS, on_text=lambda t: None)
        assert reply.text == "ok"
        assert sent[0] == "stream" and "stream" not in sent[-1]

    def test_stop_mid_reply(self, monkeypatch):
        response = _SSE(_chunks({"content": "a"}, {"content": "b"}, {"content": "c"}))
        _serve(monkeypatch, response)
        pieces = []
        with pytest.raises(wire.Cancelled):
            toolcall.chat_with_tools(OPENAI, [{"role": "user", "content": "x"}],
                                     TOOLS, on_text=pieces.append,
                                     cancelled=lambda: len(pieces) >= 1)
        assert pieces == ["a"] and response.closed

    def test_an_error_mid_stream_says_so(self, monkeypatch):
        _serve(monkeypatch, _SSE([{"choices": [{"delta": {"content": "a"}}]},
                                  {"error": {"message": "overloaded"}}]))
        with pytest.raises(wire.LLMError, match="overloaded"):
            toolcall.chat_with_tools(OPENAI, [{"role": "user", "content": "x"}],
                                     TOOLS, on_text=lambda t: None)

    def test_json_fallback_streams_too(self, monkeypatch):
        text = 'Looking.\n```tool\n{"name": "describe_flow", "arguments": {}}\n```'
        _serve(monkeypatch, _SSE(_chunks({"content": text[:12]}, {"content": text[12:]})))
        reply = toolcall.chat_with_tools(OPENAI, [{"role": "user", "content": "x"}],
                                         TOOLS, mode="json", on_text=lambda t: None)
        assert reply.mode == "json" and reply.tool_calls[0].name == "describe_flow"


class TestAnthropic:
    def test_text_and_tool_use(self, monkeypatch):
        _serve(monkeypatch, _SSE([
            "event: message_start", {"type": "message_start", "message": {}},
            {"type": "content_block_start", "index": 0,
             "content_block": {"type": "text", "text": ""}},
            {"type": "content_block_delta", "index": 0,
             "delta": {"type": "text_delta", "text": "Let me look."}},
            {"type": "content_block_start", "index": 1, "content_block": {
                "type": "tool_use", "id": "t1", "name": "describe_flow", "input": {}}},
            {"type": "content_block_delta", "index": 1,
             "delta": {"type": "input_json_delta", "partial_json": '{"scope"'}},
            {"type": "content_block_delta", "index": 1,
             "delta": {"type": "input_json_delta", "partial_json": ': "all"}'}},
            {"type": "message_delta", "delta": {"stop_reason": "tool_use"}},
            {"type": "message_stop"},
        ]))
        pieces = []
        reply = toolcall.chat_with_tools(ANTHROPIC, [{"role": "user", "content": "x"}],
                                         TOOLS, on_text=pieces.append)
        assert pieces == ["Let me look."] and reply.text == "Let me look."
        assert reply.tool_calls[0].arguments == {"scope": "all"}
        assert reply.stop == "tool_use"

    def test_broken_tool_json_is_reported_not_guessed(self, monkeypatch):
        _serve(monkeypatch, _SSE([
            {"type": "message_start", "message": {}},
            {"type": "content_block_start", "index": 0, "content_block": {
                "type": "tool_use", "id": "t1", "name": "describe_flow", "input": {}}},
            {"type": "content_block_delta", "index": 0,
             "delta": {"type": "input_json_delta", "partial_json": '{"scope": '}},
            {"type": "message_delta", "delta": {"stop_reason": "max_tokens"}},
        ]))
        reply = toolcall.chat_with_tools(ANTHROPIC, [{"role": "user", "content": "x"}],
                                         TOOLS, on_text=lambda t: None)
        assert reply.tool_calls[0].bad_arguments == '{"scope": '

    def test_error_event(self, monkeypatch):
        _serve(monkeypatch, _SSE([{"type": "message_start", "message": {}},
                                  {"type": "error", "error": {"message": "overloaded"}}]))
        with pytest.raises(wire.LLMError, match="overloaded"):
            toolcall.chat_with_tools(ANTHROPIC, [{"role": "user", "content": "x"}],
                                     TOOLS, on_text=lambda t: None)


def test_without_on_text_nothing_streams(monkeypatch):
    monkeypatch.setattr(wire, "_post_stream",
                        lambda *a: pytest.fail("streamed without being asked"))
    monkeypatch.setattr(wire, "_post", lambda url, h, body, t, v:
                        _SSE(body={"choices": [{"message": {"content": "ok"}}]}))
    assert toolcall.chat_with_tools(OPENAI, [{"role": "user", "content": "x"}],
                                    TOOLS).text == "ok"


class TestVisibleText:
    def test_reasoning_is_hidden_even_unfinished(self):
        assert visible_text("<think>hmm</think>Hello") == "Hello"
        assert visible_text("Hi <think>still thinking") == "Hi"

    def test_a_json_tool_call_is_not_shown(self):
        assert visible_text('Looking.\n```tool\n{"name"') == "Looking."
        assert visible_text("```json\n{") == ""

    def test_ordinary_code_is_shown(self):
        assert "```python" in visible_text("Try:\n```python\nx = 1\n```")
