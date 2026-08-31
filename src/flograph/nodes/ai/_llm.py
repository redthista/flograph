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

    data = resp.json()
    if provider == "anthropic":
        parts = data.get("content") or []
        return "".join(b.get("text", "") for b in parts
                       if b.get("type") == "text").strip()
    choices = data.get("choices") or []
    if not choices:
        return ""
    return (choices[0].get("message") or {}).get("content", "").strip()
