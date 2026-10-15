"""One way to talk to a chat model, for everything in flograph that does.

There used to be two: `flograph.ai` (requests, Ask AI) and
`nodes/ai/_llm.py` (httpx, the LLM nodes). They drifted — each learned a
lesson the other didn't, and a gateway that worked for one broke the
other. This module is what both of them call now, so a fix lands once.

Two wire formats are spoken, chosen per connection — they are formats, not
vendors:

- `openai`: `POST …/chat/completions`, `Authorization: Bearer`. Ollama,
  LM Studio, llama.cpp, vLLM, OpenAI, OpenRouter, Azure and most corporate
  gateways.
- `anthropic`: `POST …/messages`, `x-api-key` + `anthropic-version`. The
  Anthropic API and Anthropic-style proxies (LiteLLM, Bedrock gateways).

What it copes with, each one learned from a real server:

- **URL shapes.** People paste the endpoint they were given. A full chat
  URL is used as-is, never doubled; a root without `/v1` tries `/v1` first
  and the bare path on a 404; a `?api-version=` query stays at the end.
- **Errors carry the server's own words.** A 4xx body says which
  parameter, key or model it objected to — that sentence is the message.
- **The 400 climb-down.** Hosted models reject a custom temperature, and
  some want `max_completion_tokens` where others want `max_tokens`. A 400
  naming one of those drops or renames just that and retries.
- **Reply shapes.** `content` may be absent, null, a string or a list of
  parts; a reasoning model may leave it empty and answer in
  `reasoning_content`. An empty reply names its stop reason.
- **Thinking** and **extra request JSON**, merged last so the escape hatch
  outranks everything.

`httpx` is imported inside the functions that need it: this module is
imported at load by node scripts, and a missing optional package should
fail the request that needs it, with a message saying how to install it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

PROVIDERS = ("openai", "anthropic")  # wire formats, not vendors

# The official endpoint for each format, used when Base URL is left blank.
DEFAULT_BASES = {
    "openai": "https://api.openai.com/v1",
    "anthropic": "https://api.anthropic.com/v1",
}
ANTHROPIC_VERSION = "2023-06-01"
DEFAULT_TIMEOUT = 240.0
DEFAULT_MAX_TOKENS = 8192
MODELS_TIMEOUT = 15.0  # metadata, not generation — but a corporate gateway
                       # on a cold connection can take longer than a laptop

THINKING_OPTIONS = ["default", "off", "low", "high"]

_PATHS = {"openai": "/chat/completions", "anthropic": "/messages"}
_ENDPOINT_SUFFIXES = ("/chat/completions", "/messages", "/models")


class LLMError(RuntimeError):
    """The AI server couldn't be reached, refused the request, or its reply
    wasn't usable. The message carries the server's own words.

    A RuntimeError so the LLM nodes, which have always raised and caught
    RuntimeError for an API failure, keep working unchanged.
    """


@dataclass
class Connection:
    """Where a request goes, as whom, in which dialect, and how big a reply
    may be. Everything `chat()` needs besides the messages."""
    provider: str = "openai"
    base_url: str = ""          # blank = the format's official endpoint
    model: str = ""
    api_key: str = ""
    verify_ssl: bool = True
    timeout: float = DEFAULT_TIMEOUT
    max_tokens: int = DEFAULT_MAX_TOKENS
    thinking: str = "default"
    extra: dict = field(default_factory=dict)
    temperature: Optional[float] = None  # None = don't send one


def _httpx():
    try:
        import httpx
        return httpx
    except ImportError:
        raise LLMError(
            "the 'httpx' package is not installed — add it via "
            "Tools > Manage Packages (or install flograph[ai]) to talk to "
            "an AI server") from None


def _post(url: str, headers: dict, body: dict, timeout: float, verify: bool):
    """The one place a request leaves the process. Tests replace this."""
    httpx = _httpx()
    try:
        return httpx.post(url, headers=headers, json=body, timeout=timeout,
                          verify=verify)
    except httpx.HTTPError as exc:
        raise LLMError(
            f"could not reach the AI server at {url} — is it running, and "
            f"is the Base URL right? ({exc})") from exc


def _get(url: str, headers: dict, timeout: float, verify: bool):
    httpx = _httpx()
    try:
        return httpx.get(url, headers=headers, timeout=timeout, verify=verify)
    except httpx.HTTPError as exc:
        raise LLMError(
            f"could not reach the AI server at {url} — is it running, and "
            f"is the Base URL right? ({exc})") from exc


def auth_headers(conn: Connection) -> dict:
    """Whatever the chosen wire format expects for credentials.

    Sending the wrong one at a corporate gateway is a 401 that reads like a
    bad key, which is why the format is a setting and not a guess.
    """
    headers = {"Content-Type": "application/json"}
    if conn.provider == "anthropic":
        headers["anthropic-version"] = ANTHROPIC_VERSION
        if conn.api_key:
            headers["x-api-key"] = conn.api_key
    elif conn.api_key:
        headers["Authorization"] = f"Bearer {conn.api_key}"
    return headers


def candidate_urls(conn: Connection, path: str) -> list[str]:
    """The URL to try, then the one to fall back to on a 404.

    A Base URL that already ends in `path` is the endpoint itself — use it
    and nothing else. Otherwise the suffix of any other endpoint is cut off
    (someone pasted the chat URL into a models call), and a root that
    doesn't end in `/v1` tries `/v1` first, since nearly every server lives
    there, then the bare path for a gateway rooted at the host. A query
    string (`?api-version=…`) is held aside and put back on the end.
    """
    raw = (conn.base_url or "").strip() or DEFAULT_BASES.get(
        conn.provider, DEFAULT_BASES["openai"])
    base, _, query = raw.partition("?")
    base = base.rstrip("/")
    suffix = f"?{query}" if query else ""
    if base.endswith(path):
        return [base + suffix]
    for tail in _ENDPOINT_SUFFIXES:
        if base.endswith(tail):
            base = base[: -len(tail)].rstrip("/")
            break
    if base.endswith("/v1"):
        return [base + path + suffix]
    return [base + "/v1" + path + suffix, base + path + suffix]


def describe_http_error(url: str, status: int, body: str) -> str:
    """Servers explain their 4xx in the response body — show it."""
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


def _send(method: str, urls: list[str], conn: Connection, timeout: float,
          body: Optional[dict] = None):
    """One request across the candidate URLs; raises LLMError on failure."""
    headers = auth_headers(conn)
    for index, url in enumerate(urls):
        if method == "GET":
            response = _get(url, headers, timeout, conn.verify_ssl)
        else:
            response = _post(url, headers, body, timeout, conn.verify_ssl)
        if response.status_code < 400:
            return response
        message = describe_http_error(
            url, response.status_code, getattr(response, "text", "") or "")
        # Only "no such endpoint" is worth retrying at the other URL shape;
        # a 400 or 401 came from the real endpoint and is the answer.
        if response.status_code not in (404, 405) or index == len(urls) - 1:
            raise LLMError(message)
    raise LLMError("the AI server could not be reached")  # pragma: no cover


def thinking_fields(provider: str, mode: str, max_tokens: int) -> dict:
    """The request fields that ask for `mode` on this wire format.

    There is no cross-provider standard here, so this maps to the dialect
    each format actually speaks and says so out loud rather than pretending
    to be universal. A gateway that wants a third thing will reject what it
    is sent, naming the field — which is a readable failure — and **Extra
    request JSON** is how you answer it. `default` sends nothing at all, so
    the model does whatever it was going to do.
    """
    if mode in ("", "default", None):
        return {}
    if provider == "anthropic":
        # Anthropic-format thinking is opt-*in*, so "off" is simply silence.
        if mode == "off":
            return {}
        # budget_tokens must be >= 1024 and leave room for an answer, so a
        # small Max tokens cannot carry it — better to say that than to send
        # a request the server will reject for reasons of our making.
        budget = 1024 if mode == "low" else max(1024, int(max_tokens * 0.6))
        if max_tokens <= budget:
            raise ValueError(
                f"thinking '{mode}' needs room to think: raise 'Max tokens' "
                f"above {budget} (it is {max_tokens}), or set Thinking to "
                f"'default'")
        return {"thinking": {"type": "enabled", "budget_tokens": budget}}
    # OpenAI-format gateways: OpenRouter's `reasoning` object is what most
    # of them read. OpenAI's own `reasoning_effort` is deliberately not sent
    # alongside it — that API rejects unknown fields, so sending both would
    # break the case it was meant to cover.
    if mode == "off":
        return {"reasoning": {"enabled": False}}
    return {"reasoning": {"effort": mode}}


def chat_body(conn: Connection, messages: list[dict],
              tweaks: frozenset = frozenset()) -> dict:
    """The request body for this wire format, minus anything `tweaks` drops.

    `messages` are OpenAI-shaped (`system` is a role). The Anthropic format
    wants the system prompt as a top-level field instead.
    """
    if conn.provider == "anthropic":
        system = "\n\n".join(
            m["content"] for m in messages if m.get("role") == "system")
        body: dict = {
            "model": conn.model,
            "max_tokens": conn.max_tokens,
            "messages": [m for m in messages if m.get("role") != "system"],
        }
        if system.strip():
            body["system"] = system
    else:
        body = {"model": conn.model, "messages": list(messages)}
        if "max_completion_tokens" in tweaks:
            body["max_completion_tokens"] = conn.max_tokens
        elif "no_max_tokens" not in tweaks:
            body["max_tokens"] = conn.max_tokens
    if conn.temperature is not None and "no_temperature" not in tweaks:
        body["temperature"] = conn.temperature
    body.update(thinking_fields(conn.provider, conn.thinking, conn.max_tokens))
    # Last, so it wins: the escape hatch has to be able to correct anything
    # above it, including a Thinking mapping that is wrong for this gateway.
    body.update(conn.extra or {})
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


def _empty_reply(field_name: str, reason) -> str:
    why = str(reason or "unknown")
    hint = ("raise 'Max tokens' — a reasoning model can spend the whole "
            "budget thinking before it writes an answer"
            if why in ("length", "max_tokens") else
            "the model may have hit its token limit")
    return f"the AI server returned an empty reply ({field_name}: {why}) — {hint}"


def reply_text(data: dict, provider: str) -> str:
    """The assistant's text, across the shapes servers actually return."""
    if not isinstance(data, dict):
        raise LLMError("unexpected response from the AI server: not a JSON object")
    if provider == "anthropic":
        parts = data.get("content")
        if isinstance(parts, str) and parts.strip():
            return parts
        if "content" not in data and "stop_reason" not in data:
            raise LLMError(
                "unexpected response from the AI server: no 'content' in "
                "the reply — is the API format setting right?")
        text = "".join(
            block.get("text", "") for block in (parts or [])
            if isinstance(block, dict) and block.get("type") == "text")
        if not text.strip():
            raise LLMError(_empty_reply("stop_reason", data.get("stop_reason")))
        return text

    choices = data.get("choices")
    if choices is None:
        raise LLMError(
            "unexpected response from the AI server: no 'choices' in the "
            "reply — is the API format setting right?")
    if not choices:
        raise LLMError(
            "the AI server returned no choices — the request may have been "
            "filtered by the gateway")
    message = choices[0].get("message") or {}
    content = message.get("content")
    if isinstance(content, list):  # some gateways return OpenAI content parts
        content = "".join(part.get("text", "") for part in content
                          if isinstance(part, dict))
    if not (content or "").strip():
        # Reasoning models put the visible answer here when content is empty.
        content = message.get("reasoning_content") or ""
    if not (content or "").strip():
        if message.get("refusal"):
            raise LLMError(f"the model refused the request: {message['refusal']}")
        raise LLMError(_empty_reply("finish_reason", choices[0].get("finish_reason")))
    return content


def chat(conn: Connection, messages: list[dict]) -> str:
    """POST one chat request in the connection's wire format; return the text."""
    urls = candidate_urls(conn, _PATHS.get(conn.provider, _PATHS["openai"]))
    tweaks: set = set()
    while True:
        try:
            response = _send("POST", urls, conn, conn.timeout,
                             chat_body(conn, messages, frozenset(tweaks)))
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
    return reply_text(data, conn.provider)


def list_models(conn: Connection) -> list[str]:
    """GET …/models — the sorted model ids the server offers.

    Both formats answer this with the same `{"data": [{"id": …}]}` shape,
    which is exactly why it proves nothing about the chat endpoint: a
    server can list models and still refuse to chat in the format chosen.
    """
    response = _send("GET", candidate_urls(conn, "/models"), conn,
                     MODELS_TIMEOUT)
    try:
        data = response.json()
        return sorted(str(entry["id"]) for entry in data["data"])
    except (ValueError, KeyError, TypeError) as exc:
        raise LLMError(f"unexpected response from the AI server: {exc}") from exc
