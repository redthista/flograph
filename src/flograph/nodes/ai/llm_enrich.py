"""LLM Enrich

Run a prompt once per row and write the model's answer into a new column.
The prompt is a template — `{column}` is replaced with that row's value:

    Summarise this support ticket in one sentence:
    {subject}
    {body}

Good for summarising, rewriting, translating, drafting, tagging free text —
the "I'd write a loop and call an API" jobs, as one node.

**API format** picks the wire protocol — `anthropic` or `openai` — and
**Base URL** points it anywhere that speaks one of them: the hosted APIs,
Azure OpenAI, a local Ollama / vLLM / LM Studio server, an OpenRouter or
LiteLLM gateway. **Model** is free text (`claude-sonnet-5`, `gpt-4o-mini`,
`llama3.1`, …). Leave **API key** blank to pick up `ANTHROPIC_API_KEY` /
`OPENAI_API_KEY` from the environment, type one in, or use a `${env:NAME}`
project secret; a local server needs none.

Identical prompts are sent once and the answer reused, so enriching a column
with 10k rows and 40 distinct values costs 40 calls. Rows run **Concurrency**
at a time. **Preview (no API call)** fills the column with the rendered
prompt so you can check the template before spending anything. Needs `httpx`.
"""
NODE = {
    "label": "LLM Enrich",
    "category": "AI",
    "version": "2.0",
    "inputs": [("table", "dataframe")],
    "outputs": [("table", "dataframe")],
}
PARAMS = [
    {"name": "prompt", "type": "text", "label": "Prompt template",
     "default": "", "placeholder": "Summarise in one line:\n{text}"},
    {"name": "system", "type": "text", "label": "System prompt",
     "default": "", "placeholder": "optional — sets the model's role/voice"},
    {"name": "output_column", "type": "string", "label": "Output column",
     "default": "llm_output"},
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
     "placeholder": "blank = the provider's env var; ${env:NAME} for a project secret; unset for a local server"},
    {"name": "max_tokens", "type": "int", "label": "Max tokens",
     "default": 512, "min": 1, "max": 8192},
    {"name": "concurrency", "type": "int", "label": "Concurrency",
     "default": 4, "min": 1, "max": 32},
    {"name": "on_error", "type": "choice", "label": "On row error",
     "options": ["fail", "blank"], "default": "fail"},
    {"name": "dry_run", "type": "bool", "label": "Preview (no API call)",
     "default": False},
]


def _render(template, row):
    import string

    fields = [f for _, f, _, _ in string.Formatter().parse(template) if f]
    missing = [f for f in fields if f not in row]
    if missing:
        raise ValueError(
            f"prompt references column(s) {missing} that are not in the table")
    return template.format_map({k: "" if v is None else str(v)
                                for k, v in row.items()})


def run(ctx, table):
    from concurrent.futures import ThreadPoolExecutor

    from flograph.nodes.ai import _llm

    p = ctx.params
    template = (p.get("prompt") or "").strip()
    if not template:
        raise ValueError("no prompt — set 'Prompt template'")
    out_col = (p.get("output_column") or "llm_output").strip()

    rows = table.to_dict("records")
    prompts = [_render(template, r) for r in rows]

    if bool(p.get("dry_run")):
        result = table.copy(deep=False)
        result[out_col] = prompts
        ctx.log(f"preview: rendered {len(prompts)} prompts, no API call")
        return result

    provider = p.get("provider", "anthropic")
    key = _llm.resolve_key(provider, p.get("api_key"))
    base = p.get("base_url") or ""
    model = (p.get("model") or "").strip()
    if not model:
        raise ValueError("no model — set 'Model'")
    system = p.get("system") or ""
    max_tokens = int(p.get("max_tokens", 512))
    on_error = p.get("on_error", "fail")

    unique = list(dict.fromkeys(prompts))
    answers = {}
    done = [0]

    def one(prompt):
        try:
            return prompt, _llm.chat(provider, base, key, model, system,
                                     prompt, max_tokens, 120.0)
        except Exception as exc:  # noqa: BLE001 - surfaced per on_error
            if on_error == "fail":
                raise
            ctx.log(f"row failed ({exc}) — left blank")
            return prompt, None

    with ThreadPoolExecutor(max_workers=int(p.get("concurrency", 4))) as pool:
        for prompt, answer in pool.map(one, unique):
            answers[prompt] = answer
            done[0] += 1
            ctx.check_cancelled()
            ctx.progress(done[0] / len(unique))

    result = table.copy(deep=False)
    result[out_col] = [answers.get(pr) for pr in prompts]
    ctx.log(f"enriched {len(rows)} rows with {len(unique)} {provider} call(s) "
            f"→ column {out_col!r}")
    return result
