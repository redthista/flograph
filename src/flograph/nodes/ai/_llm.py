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
    if key and not key.startswith("${"):
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


def connection(ctx, params: dict, config=None) -> tuple:
    """`(provider, base_url, api_key, model)` — where to send this, as whom.

    A wired **LLM Config** replaces the node's own four connection fields
    outright rather than filling in the blanks. Per-field precedence reads
    fine in a docstring and is unexplainable in front of a flow: every field
    has a non-empty default, so "the config fills what you left blank" would
    mean a config's model never took effect, and a half-overridden endpoint
    is the kind of thing you debug for an hour. One rule instead — plugged
    in, the config is the connection; unplugged, the node's own fields are.
    What the node keeps either way is the shape of its *job*: max tokens,
    concurrency, the prompt.
    """
    source, where = params, "this node"
    if config is not None:
        if not isinstance(config, dict) or config.get("kind") != CONFIG_KIND:
            raise ValueError(
                "the 'config' input expects an LLM Config node — "
                f"got {type(config).__name__}")
        source, where = config, "the wired LLM Config"

    provider = source.get("provider") or "anthropic"
    base = source.get("base_url") or ""
    model = (source.get("model") or "").strip()
    if not model:
        raise ValueError(f"no model — set 'Model' on {where}")
    key = resolve_key(provider, source.get("api_key"))
    if config is not None:
        # Never the key: this line goes in the run log, which is on screen
        # and in the saved project.
        ctx.log(f"connection from LLM Config: {model} ({provider}) at "
                f"{base or default_base(provider)}")
    return provider, base, key, model


def chat(provider: str, base_url: str, api_key: str, model: str,
         system: str, user: str, max_tokens: int, timeout: float) -> str:
    """One completion. Returns the assistant text; raises on an API error."""
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
