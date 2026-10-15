"""Local-LLM node assistant (Qt-free).

Turns a plain-English instruction — "format the date column as
YYYY-MM-DD", "filter out rows where price is negative" — into an updated
node script, by asking a local, OpenAI-compatible chat-completions server
(Ollama, LM Studio, llama.cpp server, ...) to rewrite the node's source.

The server can be a local one (Ollama, LM Studio, llama.cpp) or a hosted
or corporate gateway; both OpenAI-format (/chat/completions) and
Anthropic-format (/messages) servers are spoken, chosen by the API format
in AI Assistant Settings.

The HTTP side — URL shapes, auth headers, the 400 climb-down, reply
parsing — is `flograph.llm.wire`, shared with the LLM nodes. Needs the
optional 'httpx' package (extra: `ai`); everything here is a plain function
so it can be exercised headlessly and off the Qt thread.

The LLM's reply becomes source code that will later execute in-process —
callers must never apply it automatically. Route it through the existing
editor review flow (populate the editor, let the user read it, Apply is a
separate explicit action) exactly as if the user had typed it themselves.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from .core import NodeScriptError, parse_spec
from .llm import wire
from .llm.wire import LLMError, PROVIDERS  # noqa: F401  (re-exported)

DEFAULT_BASE_URL = "http://localhost:11434/v1"  # Ollama's OpenAI-compatible endpoint
DEFAULT_MODEL = "llama3.1"
DEFAULT_TIMEOUT = wire.DEFAULT_TIMEOUT
DEFAULT_MAX_TOKENS = wire.DEFAULT_MAX_TOKENS
MODELS_TIMEOUT = wire.MODELS_TIMEOUT

_SYSTEM_PROMPT = """You edit node scripts for flograph, a visual dataflow app. \
Each node is a single Python file with this exact contract:

  NODE = {
      "label": "<Label>",
      "category": "<Category>",
      "inputs":  [("name", "dataframe"|"series"|"number"|"string"|"bool"|"object"|"figure"|"any", {"optional": True})],
      "outputs": [("name", "<same types>")],
  }
  PARAMS = [
      {"name": "...", "type": "string"|"text"|"int"|"float"|"bool"|"choice"|"columns",
       "label": "...", "default": ...},
  ]

  def run(ctx, **inputs):   # kwargs named after input ports; unconnected optional
                            # inputs arrive as None
      ...                   # ctx.params[name] for params, ctx.log(msg) to log
      return {"out_port": value, ...}   # or a bare value iff exactly one output

Rules:
- Treat inputs as read-only. A pandas input is already a copy-on-write
  shallow copy and a list or dict is already rebuilt one level deep, so
  writing to those is safe; a numpy input is read-only, so copy it first.
- Heavy imports (pandas, etc.) go inside run(), never at module top level.
- Raise plain exceptions with actionable messages on bad input.
- Reply with ONLY the complete updated Python source for the node script —
  no explanation, no markdown fences, no partial diff. Keep everything about
  the node that the instruction doesn't ask you to change (ports, other
  params, docstring) as-is unless the change requires otherwise."""

_CODE_FENCE = re.compile(r"```(?:python|py)?[ \t]*\n(.*?)```", re.DOTALL)
_THINK_BLOCK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


@dataclass
class LLMConfig:
    base_url: str = DEFAULT_BASE_URL
    model: str = DEFAULT_MODEL
    api_key: Optional[str] = None
    timeout: float = DEFAULT_TIMEOUT
    verify_ssl: bool = True
    provider: str = "openai"  # wire format: see PROVIDERS
    max_tokens: int = DEFAULT_MAX_TOKENS
    thinking: str = "default"
    extra: dict = field(default_factory=dict)


def _connection(config: LLMConfig) -> wire.Connection:
    return wire.Connection(
        provider=config.provider, base_url=config.base_url,
        model=config.model, api_key=config.api_key or "",
        verify_ssl=config.verify_ssl, timeout=config.timeout,
        max_tokens=config.max_tokens, thinking=config.thinking,
        extra=dict(config.extra or {}),
        # Code wants a steady hand; a server that refuses a custom
        # temperature says so and the request is retried without one.
        temperature=0.2)


def list_models(config: Optional[LLMConfig] = None) -> list[str]:
    """Sorted model ids the configured server offers (see wire.list_models)."""
    return wire.list_models(_connection(config or LLMConfig()))


def chat_completion(messages: list[dict], config: Optional[LLMConfig] = None) -> str:
    """POST one chat request in the configured wire format; return the text."""
    return wire.chat(_connection(config or LLMConfig()), messages)


def _strip_code_fence(text: str) -> str:
    """The code out of a reply that was asked for code and nothing else.

    Models add things anyway: a reasoning block before the answer, a
    sentence of preamble, a fence around the script. Take the largest
    fenced block if there is one, otherwise the text as it stands.
    """
    text = _THINK_BLOCK.sub("", text or "").strip()
    blocks = _CODE_FENCE.findall(text)
    if blocks:
        return max(blocks, key=len).strip("\n")
    return text


def suggest_node_update(
    source: str,
    instruction: str,
    type_id: str = "ai.preview",
    config: Optional[LLMConfig] = None,
) -> str:
    """Ask the configured AI server to rewrite `source` per `instruction`.

    Returns the full updated node script, already checked against the
    NODE/PARAMS/run contract via parse_spec — but still just text. The
    caller is responsible for putting it in front of the user for review
    rather than applying it directly.
    """
    instruction = instruction.strip()
    if not instruction:
        raise ValueError("instruction is empty")

    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": (
            f"Current node script:\n```python\n{source}\n```\n\n"
            f"Instruction: {instruction}\n\n"
            "Reply with the full updated script only."
        )},
    ]
    reply = chat_completion(messages, config)
    code = _strip_code_fence(reply)

    try:
        parse_spec(code, type_id)
    except NodeScriptError as exc:
        raise LLMError(
            f"the LLM's suggested code doesn't satisfy the node contract: {exc}"
        ) from exc
    return code
