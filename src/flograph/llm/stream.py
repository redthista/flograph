"""Streamed replies, put back together as the reply they stand for.

With `"stream": true` both formats answer in server-sent events: OpenAI's
`choices[0].delta` chunks, Anthropic's `content_block_*` events. The text
is handed on as it arrives (so a slow local model visibly writes), and the
events are assembled into exactly the JSON the same request would have
returned unstreamed — so everything downstream (`reply_text`, the tool-call
parser, the JSON fallback) is the code that already handles a whole reply,
and a tool call is acted on only once it is complete.

A server that ignores `stream` and answers with plain JSON is fine: the
JSON is the reply. `cancelled` is checked between chunks, so Stop ends a
reply mid-sentence instead of waiting for the server to finish it.
"""
from __future__ import annotations

import json
from typing import Callable, Iterable, Optional

from .wire import Cancelled, LLMError

TextSink = Callable[[str], None]


class _OpenAI:
    def __init__(self, on_text: TextSink) -> None:
        self.on_text = on_text
        self.text: list[str] = []
        self.reasoning: list[str] = []
        self.calls: dict[int, dict] = {}
        self.finish: Optional[str] = None
        self.seen = False

    def feed(self, event: dict) -> None:
        for choice in (event.get("choices") or [])[:1]:
            self.seen = True
            delta = choice.get("delta") or choice.get("message") or {}
            piece = delta.get("content")
            if isinstance(piece, str) and piece:
                self.text.append(piece)
                self.on_text(piece)
            thought = delta.get("reasoning_content") or delta.get("reasoning")
            if isinstance(thought, str):
                self.reasoning.append(thought)
            for index, part in enumerate(delta.get("tool_calls") or []):
                slot = self.calls.setdefault(
                    part.get("index", index),
                    {"id": None, "type": "function",
                     "function": {"name": "", "arguments": ""}})
                if part.get("id"):
                    slot["id"] = part["id"]
                function = part.get("function") or {}
                if function.get("name") and not slot["function"]["name"]:
                    slot["function"]["name"] = function["name"]
                arguments = function.get("arguments")
                if isinstance(arguments, str):
                    slot["function"]["arguments"] += arguments
                elif isinstance(arguments, dict):
                    slot["function"]["arguments"] = json.dumps(arguments)
            if choice.get("finish_reason"):
                self.finish = choice["finish_reason"]

    def result(self) -> dict:
        if not self.seen:
            raise LLMError("the AI server's streamed reply had no content — "
                           "is the API format setting right?")
        message: dict = {"role": "assistant",
                         "content": "".join(self.text) or None}
        if self.reasoning:
            message["reasoning_content"] = "".join(self.reasoning)
        if self.calls:
            message["tool_calls"] = [self.calls[k] for k in sorted(self.calls)]
        return {"choices": [{"message": message, "finish_reason": self.finish}]}


class _Anthropic:
    def __init__(self, on_text: TextSink) -> None:
        self.on_text = on_text
        self.blocks: dict[int, dict] = {}
        self.stop: Optional[str] = None
        self.seen = False

    def feed(self, event: dict) -> None:
        kind = event.get("type")
        if kind == "error":
            error = event.get("error") or {}
            raise LLMError("the AI server stopped with an error mid-reply: "
                           f"{error.get('message') or error}")
        if kind == "message_start":
            self.seen = True
        elif kind == "content_block_start":
            self.seen = True
            block = dict(event.get("content_block") or {})
            if block.get("type") == "tool_use":
                block["_json"] = ""
            elif block.get("type") == "text":
                block.setdefault("text", "")
            self.blocks[event.get("index", len(self.blocks))] = block
        elif kind == "content_block_delta":
            delta = event.get("delta") or {}
            block = self.blocks.setdefault(event.get("index", 0),
                                           {"type": "text", "text": ""})
            if delta.get("type") == "text_delta":
                block["text"] = block.get("text", "") + delta.get("text", "")
                self.on_text(delta.get("text", ""))
            elif delta.get("type") == "input_json_delta":
                block["_json"] = block.get("_json", "") + delta.get("partial_json", "")
            elif delta.get("type") == "thinking_delta":
                block["thinking"] = block.get("thinking", "") + delta.get("thinking", "")
        elif kind == "message_delta":
            self.stop = (event.get("delta") or {}).get("stop_reason") or self.stop

    def result(self) -> dict:
        if not self.seen:
            raise LLMError("the AI server's streamed reply had no content — "
                           "is the API format setting right?")
        content = []
        for index in sorted(self.blocks):
            block = dict(self.blocks[index])
            raw = block.pop("_json", None)
            if block.get("type") == "tool_use":
                if raw:
                    try:
                        block["input"] = json.loads(raw)
                    except ValueError:
                        block["input"] = raw   # the parser reports bad JSON
                else:
                    block.setdefault("input", {})
            content.append(block)
        return {"content": content, "stop_reason": self.stop}


def read(response, provider: str, on_text: TextSink,
         cancelled: Optional[Callable[[], bool]] = None) -> dict:
    """The whole reply from a streamed response (closed by the caller)."""
    kind = str((getattr(response, "headers", None) or {}).get(
        "content-type", "")).lower()
    if "event-stream" not in kind:
        try:
            return response.json()
        except ValueError as exc:
            raise LLMError(f"unexpected response from the AI server: {exc}") from exc
    builder = _Anthropic(on_text) if provider == "anthropic" else _OpenAI(on_text)
    for line in _lines(response):
        if cancelled is not None and cancelled():
            raise Cancelled("stopped while the reply was arriving")
        if not line.startswith("data:"):
            continue          # "event:" names, ": keep-alive" comments
        payload = line[5:].strip()
        if payload == "[DONE]":
            break
        try:
            event = json.loads(payload)
        except ValueError:
            continue
        if isinstance(event, dict):
            if provider != "anthropic" and isinstance(event.get("error"), dict):
                raise LLMError("the AI server stopped with an error mid-reply: "
                               f"{event['error'].get('message') or event['error']}")
            builder.feed(event)
    return builder.result()


def _lines(response) -> Iterable[str]:
    try:
        for line in response.iter_lines():
            yield line.decode("utf-8", "replace") if isinstance(line, bytes) else line
    except LLMError:
        raise
    except Exception as exc:          # the connection dropped mid-reply
        raise LLMError(f"the connection to the AI server dropped mid-reply ({exc})") from exc
