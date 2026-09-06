"""LLM Config

One endpoint, one key, one model — wired into as many AI nodes as you like.
Point this at your server and every node reading it follows; move to another
gateway by editing one card instead of six.

Its **config** output goes into the **config** input of **LLM Enrich**,
**LLM Classify** and **LLM Extract**. A node with that input wired ignores
its own **API format**, **Base URL**, **Model** and **API key** completely —
the config *is* the connection, not a set of defaults filled in behind it.
Everything about the job stays on the node where the job is: the prompt, the
fields, **Max tokens**, **Concurrency**.

**Keep the key out of the file.** A key typed in here is stored verbatim in
the saved project, like any other param. Write `${env:ANTHROPIC_API_KEY}`
instead and it is read from the project's .env at run time — and a node
reading a secret that way is never written to the saved cache either, so
the key reaches neither half of the file you hand to someone else.

Leave **API key** blank to use `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` from
the environment. Leave **Base URL** blank for the provider's own endpoint.
"""
NODE = {
    "label": "LLM Config",
    "category": "AI",
    "version": "1.0",
    "inputs": [],
    "outputs": [("config", "object")],
}
PARAMS = [
    {"name": "provider", "type": "choice", "label": "API format",
     "options": ["anthropic", "openai"], "default": "anthropic"},
    {"name": "model", "type": "string", "label": "Model",
     "default": "claude-sonnet-5",
     "placeholder": "claude-sonnet-5 / gpt-4o-mini / llama3.1 …"},
    {"name": "base_url", "type": "string", "label": "Base URL",
     "default": "",
     "placeholder": "blank = provider default; e.g. http://localhost:11434/v1"},
    {"name": "api_key", "type": "password", "label": "API key",
     "default": "",
     "placeholder": "${env:ANTHROPIC_API_KEY} keeps it out of the saved file"},
]


def run(ctx):
    from flograph.nodes.ai import _llm

    p = ctx.params
    provider = p.get("provider") or "anthropic"
    model = (p.get("model") or "").strip()
    if not model:
        raise ValueError("no model — set 'Model'")
    base = p.get("base_url") or ""
    # Resolved here so a missing key is reported on this card, where the
    # field is, rather than on every node reading it.
    key = _llm.resolve_key(provider, p.get("api_key"))

    ctx.log(f"{model} ({provider}) at {base or _llm.default_base(provider)}"
            + ("" if key else " — no key (fine for a local server)"))
    return {"config": {"kind": _llm.CONFIG_KIND, "provider": provider,
                       "base_url": base, "model": model, "api_key": key}}
