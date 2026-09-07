"""Shared LLM plumbing for the AI nodes.

Not a node (leading underscore — the registry skips it). Imported inside the
`run()` of `llm_enrich` / `llm_classify` / `llm_extract` so one chat-call
implementation covers both wire formats and every gateway that speaks one of
them (OpenAI-compatible: OpenAI, Azure, Ollama, vLLM, LM Studio, Together,
Groq, OpenRouter; Anthropic-compatible: the API itself, LiteLLM, Bedrock
proxies).
"""
from __future__ import annotations

PROVIDER_OPTIONS = ["anthropic", "openai"]


def default_base(provider: str) -> str:
    return ("https://api.anthropic.com" if provider == "anthropic"
            else "https://api.openai.com/v1")


def endpoint(provider: str, base_url: str) -> str:
    base = (base_url or default_base(provider)).rstrip("/")
    if provider == "anthropic":
        if base.endswith("/messages"):
            return base
        return base + ("/messages" if base.endswith("/v1") else "/v1/messages")
    if base.endswith("/chat/completions"):
        return base
    return base + ("/chat/completions" if base.endswith("/v1")
                   else "/v1/chat/completions")


def resolve_key(provider: str, raw: str) -> str:
    """The API key: the node's own field, else the conventional env var.

    A blank field falls back to `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` from
    the environment (or a `.env` reference like `${env:ANTHROPIC_API_KEY}`,
    which the engine resolves before this runs). Empty is fine for `openai`
    — a local server (Ollama, llama.cpp) needs no key — but not `anthropic`.
    """
    import os

    key = (raw or "").strip()
    if "${" in key:
        # The engine substitutes every `${name}` before a node runs and fails
        # the node loudly when it cannot, so one arriving here is a reference
        # it never recognised — almost always an unclosed `${env:OPENAI_API`
        # left behind by a half-finished edit. Falling through to the env var
        # (and, for `openai`, to no key at all) turns that into a remote 401
        # with nothing local to explain it, which is a bad hour.
        raise ValueError(
            f"the API key still reads {key!r} — that is not a resolved "
            "value. A reference must be the whole `${name}` including the "
            "closing brace, and must name either a Variables node's "
            "declaration or, as `${env:NAME}`, a key in the project's "
            ".env file")
    if key:
        return key
    env_name = "ANTHROPIC_API_KEY" if provider == "anthropic" else "OPENAI_API_KEY"
    key = os.environ.get(env_name, "").strip()
    if key:
        return key
    if provider == "openai":
        return ""
    raise ValueError(
        f"no API key — type one into 'API key', set {env_name} in the "
        f"environment, or add it to the project's .env file")


CONFIG_KIND = "llm_connection"      # what an LLM Config node puts on the wire


THINKING_OPTIONS = ["default", "off", "low", "high"]

# The connection: where a request goes, as whom, and in what dialect. Not the
# job — max tokens, concurrency and the prompt describe the work, and stay on
# the node doing it.
CONNECTION_FIELDS = ("provider", "base_url", "model", "api_key",
                     "thinking", "extra_json")


def connection(ctx, params: dict, config=None) -> dict:
    """Where this request goes, as whom, and how the gateway wants speaking to.

    A wired **LLM Config** replaces the node's own connection fields outright
    rather than filling in the blanks. Per-field precedence reads fine in a
    docstring and is unexplainable in front of a flow: every field has a
    non-empty default, so "the config fills what you left blank" would mean a
    config's model never took effect, and a half-overridden endpoint is the
    kind of thing you debug for an hour. One rule instead — plugged in, the
    config is the connection; unplugged, the node's own fields are.
    """
    source, where = params, "this node"
    if config is not None:
        if not isinstance(config, dict) or config.get("kind") != CONFIG_KIND:
            raise ValueError(
                "the 'config' input expects an LLM Config node — "
                f"got {type(config).__name__}")
        source, where = config, "the wired LLM Config"

    provider = source.get("provider") or "anthropic"
    model = (source.get("model") or "").strip()
    if not model:
        raise ValueError(f"no model — set 'Model' on {where}")
    conn = {
        "provider": provider,
        "base_url": source.get("base_url") or "",
        "model": model,
        "api_key": resolve_key(provider, source.get("api_key")),
        "thinking": source.get("thinking") or "default",
        "extra": parse_extra(source.get("extra_json"), where),
    }
    if config is not None:
        # Never the key: this line goes in the run log, which is on screen
        # and in the saved project.
        ctx.log(f"connection from LLM Config: {model} ({provider}) at "
                f"{conn['base_url'] or default_base(provider)}")
    return conn


def parse_extra(raw, where: str = "this node") -> dict:
    """The **Extra request JSON** box as a mapping — `{}` when it is blank.

    The escape hatch, and the reason the Thinking dropdown is allowed to stay
    a short list: whatever a gateway wants that flograph has never heard of
    goes in here and is merged over the request last. Same bargain Show
    Plotly strikes with its JSON boxes.
    """
    import json

    text = str(raw or "").strip()
    if not text:
        return {}
    try:
        value = json.loads(text)
    except ValueError as exc:
        raise ValueError(
            f"'Extra request JSON' on {where} is not valid JSON: {exc}") from None
    if not isinstance(value, dict):
        raise ValueError(
            f"'Extra request JSON' on {where} must be a JSON object "
            f"(a {{...}} of request fields), not {type(value).__name__}")
    return value


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


def chat_with(conn: dict, system: str, user: str, max_tokens: int,
              timeout: float) -> str:
    """One completion over a `connection()` mapping. What nodes call."""
    return chat(conn["provider"], conn["base_url"], conn["api_key"],
                conn["model"], system, user, max_tokens, timeout,
                thinking=conn.get("thinking", "default"),
                extra=conn.get("extra"))


def chat(provider: str, base_url: str, api_key: str, model: str,
         system: str, user: str, max_tokens: int, timeout: float,
         *, thinking: str = "default", extra: dict = None) -> str:
    """One completion. Returns the assistant text; raises on an API error.

    `thinking` and `extra` are keyword-only with defaults so that a node
    forked before they existed — its script is saved inside the .flograph —
    keeps calling this successfully.
    """
    import httpx

    url = endpoint(provider, base_url)
    if provider == "anthropic":
        headers = {"content-type": "application/json",
                   "anthropic-version": "2023-06-01"}
        if api_key:
            headers["x-api-key"] = api_key
        body: dict = {"model": model, "max_tokens": max_tokens,
                      "messages": [{"role": "user", "content": user}]}
        if system.strip():
            body["system"] = system
    else:
        headers = {"content-type": "application/json"}
        if api_key:
            headers["authorization"] = f"Bearer {api_key}"
        messages = []
        if system.strip():
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": user})
        body = {"model": model, "messages": messages, "max_tokens": max_tokens}

    body.update(thinking_fields(provider, thinking, max_tokens))
    # Last, so it wins: the escape hatch has to be able to correct anything
    # above it, including a Thinking mapping that is wrong for this gateway.
    body.update(extra or {})

    with httpx.Client(timeout=timeout) as client:
        resp = client.post(url, headers=headers, json=body)
    if resp.status_code >= 400:
        raise RuntimeError(
            f"{provider} API returned {resp.status_code}: "
            f"{resp.text[:400].strip()}")

    return reply_text(resp.json(), provider).strip()


def reply_text(data: dict, provider: str) -> str:
    """The assistant's text, across the shapes servers actually return.

    The same ground `flograph.ai._reply_text` covers for the AI assistant:
    a gateway can answer 200 with no text at all, and `content` may be
    absent, present-but-null, a plain string, or a list of parts. When
    there is no text the stop reason is the only clue the user gets, so it
    goes in the message rather than into a silently blank cell.
    """
    if provider == "anthropic":
        parts = data.get("content") or []
        if isinstance(parts, str):
            return parts
        text = "".join(
            block.get("text", "") for block in parts
            if isinstance(block, dict) and block.get("type") == "text")
        if not text.strip():
            raise RuntimeError(
                _empty_reply("stop_reason", data.get("stop_reason")))
        return text

    choices = data.get("choices") or []
    if not choices:
        raise RuntimeError(
            "the model returned no choices — the request may have been "
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
            raise RuntimeError(
                f"the model refused the request: {message['refusal']}")
        raise RuntimeError(
            _empty_reply("finish_reason", choices[0].get("finish_reason")))
    return content


def _empty_reply(field: str, reason) -> str:
    why = str(reason or "unknown")
    hint = ("raise 'Max tokens' — a reasoning model can spend the whole "
            "budget thinking before it writes an answer"
            if why in ("length", "max_tokens") else
            "the model may have hit its token limit")
    return f"the model returned an empty reply ({field}: {why}) — {hint}"
