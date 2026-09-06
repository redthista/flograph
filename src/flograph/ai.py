"""Local-LLM node assistant (Qt-free).

Turns a plain-English instruction — "format the date column as
YYYY-MM-DD", "filter out rows where price is negative" — into an updated
node script, by asking a local, OpenAI-compatible chat-completions server
(Ollama, LM Studio, llama.cpp server, ...) to rewrite the node's source.

The server can be a local one (Ollama, LM Studio, llama.cpp) or a hosted
or corporate gateway; both OpenAI-format (/chat/completions) and
Anthropic-format (/messages) servers are spoken, chosen by the API format
in AI Assistant Settings.

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
DEFAULT_MAX_TOKENS = 8192
MODELS_TIMEOUT = 15.0  # metadata, not generation — but a corporate gateway
                       # on a cold connection can take longer than a laptop
PROVIDERS = ("openai", "anthropic")  # wire formats, not vendors

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


class LLMError(Exception):
    """The AI server couldn't be reached, refused the request, or its
    reply wasn't usable. The message carries the server's own words —
    a gateway's 400 says which parameter it objected to."""


@dataclass
class LLMConfig:
    base_url: str = DEFAULT_BASE_URL
    model: str = DEFAULT_MODEL
    api_key: Optional[str] = None
    timeout: float = DEFAULT_TIMEOUT
    verify_ssl: bool = True
    provider: str = "openai"  # wire format: see PROVIDERS
    max_tokens: int = DEFAULT_MAX_TOKENS


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
    """Whatever the chosen wire format expects for credentials.

    Anthropic-format servers want `x-api-key` plus a version header;
    OpenAI-format ones want a bearer token. Sending the wrong one at a
    corporate gateway is a 401 that reads like a bad key.
    """
    headers: dict[str, str] = {}
    if config.provider == "anthropic":
        headers["anthropic-version"] = "2023-06-01"
        if config.api_key:
            headers["x-api-key"] = config.api_key
    elif config.api_key:
        headers["Authorization"] = f"Bearer {config.api_key}"
    return headers


def _root_url(base_url: str) -> str:
    """The API root, whatever the user pasted into Base URL.

    People paste the endpoint they were given, which is often the full
    chat URL rather than its root.
    """
    base = (base_url or DEFAULT_BASE_URL).strip().rstrip("/")
    for suffix in ("/chat/completions", "/messages", "/models"):
        if base.endswith(suffix):
            base = base[: -len(suffix)].rstrip("/")
    return base


def _candidate_urls(base_url: str, path: str) -> list[str]:
    """The URL to try, then the version-prefixed one to fall back to.

    Some servers are rooted at `.../v1` and some at the host itself; we
    can't tell from the base alone, so try what the user typed first and
    only then the `/v1` form. A 404 on the first is the signal to retry —
    it costs one wasted round trip on an unusual gateway and nothing on a
    normal one.

    A query string in the Base URL (`?api-version=…`, which some gateways
    require on every call) is held aside while the path is worked out and
    put back on the end, rather than ending up in the middle of the URL.
    """
    base, _, query = (base_url or DEFAULT_BASE_URL).strip().partition("?")
    base = _root_url(base)
    suffix = f"?{query}" if query else ""
    urls = [base + path + suffix]
    if not base.endswith("/v1"):
        urls.append(base + "/v1" + path + suffix)
    return urls


def _describe_http_error(url: str, status: int, body: str) -> str:
    """Servers explain their 4xx in the response body — show it.

    raise_for_status() alone throws away the one sentence that says which
    parameter, key or model the server objected to.
    """
    detail = " ".join((body or "").split())[:400]
    hint = ""
    if status in (401, 403):
        hint = (" — check the API key, and that the API format setting "
                "matches this server")
    elif status == 404:
        hint = (" — check the Base URL, the model name, and the API format "
                "setting (an Anthropic-format server has no "
                "/chat/completions)")
    return f"the AI server at {url} returned HTTP {status}{hint}: {detail}"


def _request(method: str, urls: list[str], config: LLMConfig, timeout: float,
             json_body: Optional[dict] = None):
    """One request across the candidate URLs; raises LLMError on failure."""
    requests = _import_requests()
    headers = {"Content-Type": "application/json", **_auth_headers(config)}
    last_error: Optional[str] = None

    for index, url in enumerate(urls):
        try:
            if method == "GET":
                response = requests.get(
                    url, headers=headers, timeout=timeout,
                    verify=config.verify_ssl)
            else:
                response = requests.post(
                    url, headers=headers, json=json_body, timeout=timeout,
                    verify=config.verify_ssl)
        except requests.RequestException as exc:
            raise LLMError(
                f"could not reach the AI server at {url} — is it running, "
                f"and is the Base URL right? ({exc})") from exc

        if response.status_code < 400:
            return response

        body = getattr(response, "text", "") or ""
        last_error = _describe_http_error(url, response.status_code, body)
        # Only a "no such endpoint" is worth retrying at the other URL shape;
        # a 400 or 401 came from the real endpoint and should be reported.
        if response.status_code not in (404, 405) or index == len(urls) - 1:
            raise LLMError(last_error)

    raise LLMError(last_error or "the AI server could not be reached")


def list_models(config: Optional[LLMConfig] = None) -> list[str]:
    """GET {base_url}/models — sorted model ids the server has available.

    Both wire formats expose this: any OpenAI-compatible server (Ollama,
    LM Studio, llama.cpp, vLLM, a corporate gateway) and the Anthropic API
    itself return the same `{"data": [{"id": ...}]}` shape.
    """
    config = config or LLMConfig()
    response = _request(
        "GET", _candidate_urls(config.base_url, "/models"), config,
        MODELS_TIMEOUT)

    try:
        data = response.json()
        return sorted(str(entry["id"]) for entry in data["data"])
    except (ValueError, KeyError, TypeError) as exc:
        raise LLMError(f"unexpected response from the AI server: {exc}") from exc


def _chat_body(messages: list[dict], config: LLMConfig, tweaks: set) -> dict:
    """The request body for this wire format, minus anything `tweaks` drops.

    `tweaks` is how we climb down from the ideal request when a server
    rejects part of it — newer hosted models refuse a custom temperature,
    and some want max_completion_tokens where others want max_tokens.
    """
    if config.provider == "anthropic":
        system = "\n\n".join(
            m["content"] for m in messages if m.get("role") == "system")
        body: dict = {
            "model": config.model,
            "max_tokens": config.max_tokens,
            "messages": [m for m in messages if m.get("role") != "system"],
        }
        if system.strip():
            body["system"] = system
        if "no_temperature" not in tweaks:
            body["temperature"] = 0.2
        return body

    body = {"model": config.model, "messages": messages}
    if "no_temperature" not in tweaks:
        body["temperature"] = 0.2
    if "max_completion_tokens" in tweaks:
        body["max_completion_tokens"] = config.max_tokens
    elif "no_max_tokens" not in tweaks:
        body["max_tokens"] = config.max_tokens
    return body


def _tweak_for(message: str) -> Optional[str]:
    """Which part of the request a 400 is complaining about, if any."""
    text = message.lower()
    if "max_completion_tokens" in text:
        return "max_completion_tokens"
    if "temperature" in text:
        return "no_temperature"
    if "max_tokens" in text:
        return "no_max_tokens"
    return None


def _reply_text(data: dict, provider: str) -> str:
    """The assistant's text, across the shapes servers actually return."""
    if provider == "anthropic":
        parts = data.get("content") or []
        if isinstance(parts, str):
            return parts
        text = "".join(
            block.get("text", "") for block in parts
            if isinstance(block, dict) and block.get("type") == "text")
        if not text:
            raise LLMError(
                f"the AI server returned an empty reply (stop_reason: "
                f"{data.get('stop_reason') or 'unknown'}) — the model may "
                f"have hit its token limit")
        return text

    choices = data.get("choices") or []
    if not choices:
        raise LLMError(
            "unexpected response from the AI server: no choices in the "
            "reply — the request may have been filtered")
    message = choices[0].get("message") or {}
    content = message.get("content")
    if isinstance(content, list):  # some gateways return OpenAI content parts
        content = "".join(
            part.get("text", "") for part in content
            if isinstance(part, dict))
    if not content:
        # Reasoning models put the visible answer here when content is empty.
        content = message.get("reasoning_content") or ""
    if not content:
        finish = choices[0].get("finish_reason") or "unknown"
        raise LLMError(
            f"the AI server returned an empty reply (finish_reason: "
            f"{finish}) — the model may have hit its token limit")
    return content


def chat_completion(messages: list[dict], config: Optional[LLMConfig] = None) -> str:
    """POST one chat request in the configured wire format; return the text."""
    config = config or LLMConfig()
    path = "/messages" if config.provider == "anthropic" else "/chat/completions"
    urls = _candidate_urls(config.base_url, path)

    tweaks: set = set()
    while True:
        try:
            response = _request(
                "POST", urls, config, config.timeout,
                _chat_body(messages, config, tweaks))
            break
        except LLMError as exc:
            tweak = _tweak_for(str(exc)) if "HTTP 400" in str(exc) else None
            if tweak is None or tweak in tweaks:
                raise
            tweaks.add(tweak)  # server named a parameter it won't take — drop it

    try:
        data = response.json()
    except ValueError as exc:
        raise LLMError(f"unexpected response from the AI server: {exc}") from exc
    return _reply_text(data, config.provider)


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
