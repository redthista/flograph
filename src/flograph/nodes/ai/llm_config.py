"""LLM Config

One endpoint, one key, one model — wired into as many AI nodes as you like.
Point this at your server and every node reading it follows; move to another
gateway by editing one card instead of six.

Its **config** output goes into the **config** input of **LLM Enrich**,
**LLM Classify** and **LLM Extract**. A node with that input wired ignores
its own copies of these fields completely — the config *is* the connection,
not a set of defaults filled in behind it. Everything about the job stays on
the node where the job is: the prompt, the fields, **Max tokens**,
**Concurrency**.

**Thinking** asks a reasoning model to stop thinking, or to think less.
There is no cross-provider standard for this, so it sends the dialect each
API format actually speaks: `openai` gets OpenRouter's `reasoning` field
(`{"enabled": false}`, or an `effort` of low/high), and `anthropic` gets
Anthropic's opt-in `thinking` block — which means **off is simply the
default there**, since that format only thinks when asked. `default` sends
nothing at all. A gateway wanting some third thing will reject what it is
sent and name the field; that is what the next box is for.

**Extra request JSON** is merged into every request **last**, so it wins
over everything above it — including a Thinking setting that is wrong for
your gateway. It is how you reach anything flograph has never heard of:

```
{"reasoning": {"exclude": true}}                 hide the thinking, keep it
{"reasoning_effort": "minimal"}                  OpenAI's own spelling
{"chat_template_kwargs": {"enable_thinking": false}}   vLLM / Qwen
{"temperature": 0, "provider": {"order": ["deepinfra"]}}
```

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
    {"name": "thinking", "type": "choice", "label": "Thinking",
     "options": ["default", "off", "low", "high"], "default": "default"},
    {"name": "extra_json", "type": "text", "label": "Extra request JSON",
     "default": "", "placeholder": '{"provider": {"order": ["deepinfra"]}}'},
]


def run(ctx):
    from flograph.nodes.ai import _llm

    p = ctx.params
    provider = p.get("provider") or "anthropic"
    model = (p.get("model") or "").strip()
    if not model:
        raise ValueError("no model — set 'Model'")
    base = p.get("base_url") or ""
    thinking = p.get("thinking") or "default"
    # Both resolved here so a bad key or malformed JSON is reported on this
    # card, where the field is, rather than on every node reading it.
    key = _llm.resolve_key(provider, p.get("api_key"))
    extra = _llm.parse_extra(p.get("extra_json"))

    ctx.log(f"{model} ({provider}) at {base or _llm.default_base(provider)}"
            + ("" if key else " — no key (fine for a local server)")
            + ("" if thinking == "default" else f"; thinking {thinking}")
            + ("" if not extra else f"; {len(extra)} extra field(s)"))
    return {"config": {"kind": _llm.CONFIG_KIND, "provider": provider,
                       "base_url": base, "model": model, "api_key": key,
                       "thinking": thinking,
                       "extra_json": p.get("extra_json") or ""}}
