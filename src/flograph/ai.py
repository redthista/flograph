"""Local-LLM node assistant (Qt-free).

Turns a plain-English instruction — "format the date column as
YYYY-MM-DD", "filter out rows where price is negative" — into an updated
node script, by asking a local, OpenAI-compatible chat-completions server
(Ollama, LM Studio, llama.cpp server, ...) to rewrite the node's source.

Needs the optional 'requests' package (extra: `ai`); everything here is a
plain function so it can be exercised headlessly and off the Qt thread.

The LLM's reply becomes source code that will later execute in-process —
callers must never apply it automatically. Route it through the existing
editor review flow (populate the editor, let the user read it, Apply is a
separate explicit action) exactly as if the user had typed it themselves.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from .core import NodeScriptError, parse_spec

DEFAULT_BASE_URL = "http://localhost:11434/v1"  # Ollama's OpenAI-compatible endpoint
DEFAULT_MODEL = "llama3.1"
DEFAULT_TIMEOUT = 240
MODELS_TIMEOUT = 5.0  # GET /models is metadata, not generation — fail fast

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
- Treat inputs as read-only; call df.copy() before mutating shape.
- Heavy imports (pandas, etc.) go inside run(), never at module top level.
- Raise plain exceptions with actionable messages on bad input.
- Reply with ONLY the complete updated Python source for the node script —
  no explanation, no markdown fences, no partial diff. Keep everything about
  the node that the instruction doesn't ask you to change (ports, other
  params, docstring) as-is unless the change requires otherwise."""

_CODE_FENCE = re.compile(r"^```(?:python)?\s*\n(.*?)\n?```\s*$", re.DOTALL)


class LLMError(Exception):
    """The local LLM couldn't be reached, or its reply wasn't usable."""


@dataclass
class LLMConfig:
    base_url: str = DEFAULT_BASE_URL
    model: str = DEFAULT_MODEL
    api_key: Optional[str] = None
    timeout: float = DEFAULT_TIMEOUT
    verify_ssl: bool = True


def _import_requests():
    try:
        import requests
        return requests
    except ImportError:
        raise LLMError(
            "the 'requests' package is not installed — add it via "
            "Tools > Manage Packages (or install flograph[ai]) to use the "
            "AI node assistant"
        ) from None


def _auth_headers(config: LLMConfig) -> dict:
    headers = {}
    if config.api_key:
        headers["Authorization"] = f"Bearer {config.api_key}"
    return headers


def list_models(config: Optional[LLMConfig] = None) -> list[str]:
    """GET {base_url}/models — sorted model ids the server currently has
    loaded/available. Any OpenAI-compatible server (Ollama, LM Studio,
    llama.cpp server, ...) implements this."""
    config = config or LLMConfig()
    requests = _import_requests()

    url = config.base_url.rstrip("/") + "/models"
    try:
        response = requests.get(
            url, headers=_auth_headers(config), timeout=MODELS_TIMEOUT,
            verify=config.verify_ssl)
        response.raise_for_status()
    except requests.RequestException as exc:
        raise LLMError(
            f"could not reach local LLM at {url} — is it running? ({exc})"
        ) from exc

    try:
        data = response.json()
        return sorted(entry["id"] for entry in data["data"])
    except (ValueError, KeyError, TypeError) as exc:
        raise LLMError(f"unexpected response from local LLM: {exc}") from exc


def chat_completion(messages: list[dict], config: Optional[LLMConfig] = None) -> str:
    """POST an OpenAI-style chat-completions request; return the reply text."""
    config = config or LLMConfig()
    requests = _import_requests()

    headers = {"Content-Type": "application/json", **_auth_headers(config)}
    url = config.base_url.rstrip("/") + "/chat/completions"
    try:
        response = requests.post(
            url,
            headers=headers,
            json={
                "model": config.model,
                "messages": messages,
                "temperature": 0.2,
            },
            timeout=config.timeout,
            verify=config.verify_ssl,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        raise LLMError(
            f"could not reach local LLM at {url} — is it running? ({exc})"
        ) from exc

    try:
        data = response.json()
        return data["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError) as exc:
        raise LLMError(f"unexpected response from local LLM: {exc}") from exc


def _strip_code_fence(text: str) -> str:
    text = text.strip()
    match = _CODE_FENCE.match(text)
    return match.group(1) if match else text


def suggest_node_update(
    source: str,
    instruction: str,
    type_id: str = "ai.preview",
    config: Optional[LLMConfig] = None,
) -> str:
    """Ask the local LLM to rewrite `source` per `instruction`.

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
