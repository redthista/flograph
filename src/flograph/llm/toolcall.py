"""Tool calling, in both wire formats and without either (Qt-free).

The Flo Assistant works by calling tools — `describe_flow`, `add_node`,
`connect` — and every server it may talk to does that differently, or not
at all:

- **openai** format: `tools: [{type: function, function: {…}}]` out,
  `message.tool_calls[].function.arguments` (a JSON *string*) back, and a
  `role: tool` message per result.
- **anthropic** format: `tools: [{name, input_schema}]` out, `tool_use`
  content blocks back, and the results as `tool_result` blocks inside the
  next *user* message.
- **json** — the fallback, for a local model or a gateway that has no
  tool support: the tools are described in the system prompt and the model
  answers with one fenced ```tool block. Small local models are uneven at
  native tool calling and often better at this.

Callers speak one neutral shape and never see the difference:

    {"role": "system" | "user", "content": str}
    {"role": "assistant", "content": str, "tool_calls": [ToolCall-as-dict]}
    {"role": "tool", "tool_call_id": str, "name": str, "content": str}

`chat_with_tools(..., mode="auto")` tries native first and, when the
server refuses tools outright (a 400/422 that talks about tools — Ollama's
"does not support tools", a gateway's "extra inputs not permitted"), drops
to the fallback for that request. The `Reply` says which mode answered, so
the caller can stay there for the rest of a conversation instead of being
refused every turn.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Optional

from . import wire

MODES = ("auto", "native", "json")

_THINK_BLOCK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
# ```tool {...}```, or ```json {...}``` holding "calls" — models do both.
_TOOL_FENCE = re.compile(r"```(tool|json)?[ \t]*\n(.*?)```", re.DOTALL)


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: dict = field(default_factory=lambda: {
        "type": "object", "properties": {}})


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict
    # The arguments as the model sent them when they were not valid JSON —
    # the tool is still "called" so the model is told exactly what was wrong.
    bad_arguments: Optional[str] = None

    def to_dict(self) -> dict:
        return {"id": self.id, "name": self.name, "arguments": self.arguments}


@dataclass
class Reply:
    text: str
    tool_calls: list = field(default_factory=list)
    mode: str = "native"     # which protocol produced this reply
    stop: str = ""           # finish/stop reason, for an empty reply
    usage: Optional[dict] = None   # {"input", "output"} tokens, if reported

    @property
    def done(self) -> bool:
        return not self.tool_calls


# -- outgoing -------------------------------------------------------------------


def _calls_of(message: dict) -> list[dict]:
    calls = []
    for call in message.get("tool_calls") or []:
        if isinstance(call, ToolCall):
            call = call.to_dict()
        calls.append(call)
    return calls


def _openai_messages(messages: list[dict]) -> list[dict]:
    out = []
    for m in messages:
        role = m.get("role")
        if role == "assistant" and m.get("tool_calls"):
            out.append({
                "role": "assistant",
                "content": m.get("content") or None,
                "tool_calls": [{
                    "id": c["id"], "type": "function",
                    "function": {"name": c["name"],
                                 "arguments": json.dumps(c.get("arguments") or {})},
                } for c in _calls_of(m)],
            })
        elif role == "tool":
            out.append({"role": "tool", "tool_call_id": m["tool_call_id"],
                        "content": m.get("content") or ""})
        else:
            out.append({"role": role, "content": m.get("content") or ""})
    return out


def _append_merged(out: list[dict], role: str, blocks: list[dict]) -> None:
    """Anthropic wants user and assistant turns to alternate, so a run of
    same-role messages (tool results, then a note) becomes one message."""
    if out and out[-1]["role"] == role and isinstance(out[-1]["content"], list):
        out[-1]["content"].extend(blocks)
    else:
        out.append({"role": role, "content": list(blocks)})


def _anthropic_messages(messages: list[dict]) -> list[dict]:
    out: list[dict] = []
    for m in messages:
        role = m.get("role")
        if role == "system":
            out.append({"role": "system", "content": m.get("content") or ""})
        elif role == "assistant":
            blocks = []
            if (m.get("content") or "").strip():
                blocks.append({"type": "text", "text": m["content"]})
            for c in _calls_of(m):
                blocks.append({"type": "tool_use", "id": c["id"],
                               "name": c["name"],
                               "input": c.get("arguments") or {}})
            if blocks:  # Anthropic rejects an empty text block outright
                _append_merged(out, "assistant", blocks)
        elif role == "tool":
            _append_merged(out, "user", [{
                "type": "tool_result", "tool_use_id": m["tool_call_id"],
                "content": m.get("content") or ""}])
        else:
            _append_merged(out, "user", [{"type": "text",
                                          "text": m.get("content") or ""}])
    return out


def _fallback_prompt(tools: list[ToolSpec]) -> str:
    lines = [
        "You can use tools. To use them, reply with ONLY one fenced block "
        "like this and nothing else:",
        "",
        "```tool",
        '{"calls": [{"name": "<tool name>", "arguments": {<arguments>}}]}',
        "```",
        "",
        "You may put several calls in the list. The results come back in "
        "the next message. When you have finished, reply in plain text with "
        "no tool block — that reply is shown to the user.",
        "",
        "Tools:",
    ]
    for tool in tools:
        lines.append(f"- {tool.name}: {tool.description}")
        lines.append(f"  arguments (JSON Schema): "
                     f"{json.dumps(tool.parameters, separators=(',', ':'))}")
    return "\n".join(lines)


def _fallback_messages(messages: list[dict], tools: list[ToolSpec]) -> list[dict]:
    """The conversation with tool traffic written out as plain text."""
    out: list[dict] = []
    prompt = _fallback_prompt(tools)
    system_seen = False
    for m in messages:
        role = m.get("role")
        content = m.get("content") or ""
        if role == "system":
            out.append({"role": "system", "content": f"{content}\n\n{prompt}"})
            system_seen = True
        elif role == "assistant":
            calls = _calls_of(m)
            if calls:
                block = json.dumps({"calls": [
                    {"name": c["name"], "arguments": c.get("arguments") or {}}
                    for c in calls]})
                content = (content + "\n\n" if content.strip() else "") + \
                    f"```tool\n{block}\n```"
            out.append({"role": "assistant", "content": content})
        elif role == "tool":
            note = f"Result of {m.get('name') or 'tool'}:\n{content}"
            if out and out[-1]["role"] == "user" and \
                    out[-1]["content"].startswith("Result of "):
                out[-1]["content"] += "\n\n" + note
            else:
                out.append({"role": "user", "content": note})
        else:
            out.append({"role": "user", "content": content})
    if not system_seen:
        out.insert(0, {"role": "system", "content": prompt})
    return out


def request_body(conn: wire.Connection, messages: list[dict],
                 tools: list[ToolSpec], mode: str,
                 tweaks: frozenset = frozenset()) -> dict:
    """The full request for `mode` ("native" or "json")."""
    if mode == "json":
        return wire.chat_body(conn, _fallback_messages(messages, tools), tweaks)
    if conn.provider == "anthropic":
        body = wire.chat_body(conn, _anthropic_messages(messages), tweaks)
        if tools:
            body["tools"] = [{"name": t.name, "description": t.description,
                              "input_schema": t.parameters} for t in tools]
        return body
    body = wire.chat_body(conn, _openai_messages(messages), tweaks)
    if tools:
        body["tools"] = [{"type": "function", "function": {
            "name": t.name, "description": t.description,
            "parameters": t.parameters}} for t in tools]
    return body


# -- incoming -------------------------------------------------------------------


def _decode_arguments(raw) -> tuple[dict, Optional[str]]:
    if isinstance(raw, dict):
        return raw, None
    if raw in (None, ""):
        return {}, None
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return {}, str(raw)
    return (value, None) if isinstance(value, dict) else ({}, str(raw))


def _parse_native(data: dict, provider: str) -> Reply:
    if not isinstance(data, dict):
        raise wire.LLMError("unexpected response from the AI server: not a JSON object")
    calls = []
    if provider == "anthropic":
        blocks = data.get("content")
        if isinstance(blocks, list):
            for block in blocks:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    args, bad = _decode_arguments(block.get("input"))
                    calls.append(ToolCall(str(block.get("id") or f"call_{len(calls)+1}"),
                                          str(block.get("name") or ""), args, bad))
        stop = str(data.get("stop_reason") or "")
    else:
        choices = data.get("choices") or [{}]
        message = choices[0].get("message") or {}
        for index, call in enumerate(message.get("tool_calls") or []):
            function = call.get("function") or {}
            args, bad = _decode_arguments(function.get("arguments"))
            calls.append(ToolCall(str(call.get("id") or f"call_{index+1}"),
                                  str(function.get("name") or ""), args, bad))
        stop = str(choices[0].get("finish_reason") or "")
    if calls:
        try:
            text = wire.reply_text(data, provider)
        except wire.LLMError:
            text = ""  # a tool call with no words beside it is normal
        return Reply(text, calls, "native", stop)
    return Reply(wire.reply_text(data, provider), [], "native", stop)


def parse_fallback(text: str) -> Reply:
    """A plain-text reply: tool calls in a fenced block, or a final answer."""
    text = _THINK_BLOCK.sub("", text or "").strip()
    for match in _TOOL_FENCE.finditer(text):
        try:
            payload = json.loads(match.group(2))
        except ValueError:
            if match.group(1) == "tool":
                return Reply(text, [ToolCall("call_1", "", {}, match.group(2).strip())],
                             "json")
            continue
        entries = None
        if isinstance(payload, dict):
            if isinstance(payload.get("calls"), list):
                entries = payload["calls"]
            elif "name" in payload:
                entries = [payload]
        elif isinstance(payload, list):
            entries = payload
        if entries is None:
            continue
        calls = []
        for index, entry in enumerate(entries):
            if not isinstance(entry, dict):
                continue
            args, bad = _decode_arguments(entry.get("arguments", {}))
            calls.append(ToolCall(f"call_{index + 1}", str(entry.get("name") or ""),
                                  args, bad))
        if calls:
            words = (text[:match.start()] + text[match.end():]).strip()
            return Reply(words, calls, "json")
    return Reply(text, [], "json")


def _refuses_tools(exc: wire.LLMError) -> bool:
    message = str(exc).lower()
    return (("http 400" in message or "http 422" in message
             or "http 501" in message) and "tool" in message)


def chat_with_tools(conn: wire.Connection, messages: list[dict],
                    tools: list[ToolSpec], mode: str = "auto", *,
                    on_text=None, cancelled=None) -> Reply:
    """One model turn: the text it wrote, and the tools it wants called.

    `on_text` streams the reply's text as it arrives (see `llm.stream`);
    the Reply is still built from the whole of it."""
    if mode not in MODES:
        mode = "auto"
    stream = {"on_text": on_text, "cancelled": cancelled}

    def counted(reply: Reply, data) -> Reply:
        reply.usage = wire.usage_of(data, conn.provider)
        return reply

    if not tools:
        converted = (_openai_messages(messages) if conn.provider != "anthropic"
                     else _anthropic_messages(messages))
        data = wire.exchange(conn, lambda tweaks: wire.chat_body(
            conn, converted, tweaks), **stream)
        return counted(Reply(wire.reply_text(data, conn.provider), [],
                             "native"), data)
    if mode in ("auto", "native"):
        try:
            data = wire.exchange(conn, lambda tweaks: request_body(
                conn, messages, tools, "native", tweaks), **stream)
            return counted(_parse_native(data, conn.provider), data)
        except wire.LLMError as exc:
            if mode == "native" or not _refuses_tools(exc):
                raise
    data = wire.exchange(conn, lambda tweaks: request_body(
        conn, messages, tools, "json", tweaks), **stream)
    return counted(parse_fallback(wire.reply_text(data, conn.provider)), data)
