"""LLM Enrich

Run a prompt once per row and write the model's answer into a new column.
The prompt is a template — `{column}` is replaced with that row's value:

    Summarise this support ticket in one sentence:
    {subject}
    {body}

Good for summarising, rewriting, translating, drafting, tagging free text —
the "I'd write a loop and call an API" jobs, as one node.

Identical prompts are sent once and the answer reused, so enriching a column
with 10k rows and 40 distinct values costs 40 calls. Rows run **Concurrency**
at a time. **Preview (no API call)** fills the column with the rendered
prompt instead of calling the model — use it to check the template before
spending anything.

Put the key in a `.env` file: the default **API key** is
`${env:ANTHROPIC_API_KEY}`. Needs the `anthropic` package.
"""
NODE = {
    "label": "LLM Enrich",
    "category": "AI",
    "version": "1.0",
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
    {"name": "model", "type": "choice", "label": "Model",
     "options": ["claude-sonnet-5", "claude-haiku-4-5", "claude-opus-5"],
     "default": "claude-sonnet-5"},
    {"name": "max_tokens", "type": "int", "label": "Max tokens",
     "default": 512, "min": 1, "max": 8192},
    {"name": "concurrency", "type": "int", "label": "Concurrency",
     "default": 4, "min": 1, "max": 32},
    {"name": "on_error", "type": "choice", "label": "On row error",
     "options": ["fail", "blank"], "default": "fail"},
    {"name": "dry_run", "type": "bool", "label": "Preview (no API call)",
     "default": False},
    {"name": "api_key", "type": "password", "label": "API key",
     "default": "${env:ANTHROPIC_API_KEY}"},
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


def _client(api_key):
    import anthropic

    key = (api_key or "").strip()
    if not key or key.startswith("${"):
        raise ValueError(
            "no API key — set 'API key' (or put ANTHROPIC_API_KEY in the "
            "project's .env file and use ${env:ANTHROPIC_API_KEY})")
    return anthropic.Anthropic(api_key=key)


def _complete(client, model, system, prompt, max_tokens):
    kwargs = {"model": model, "max_tokens": max_tokens,
              "messages": [{"role": "user", "content": prompt}]}
    if system.strip():
        kwargs["system"] = system
    resp = client.messages.create(**kwargs)
    return "".join(b.text for b in resp.content if b.type == "text").strip()


def run(ctx, table):
    from concurrent.futures import ThreadPoolExecutor

    p = ctx.params
    template = (p.get("prompt") or "").strip()
    if not template:
        raise ValueError("no prompt — set 'Prompt template'")
    out_col = (p.get("output_column") or "llm_output").strip()
    dry = bool(p.get("dry_run"))

    rows = table.to_dict("records")
    prompts = [_render(template, r) for r in rows]

    if dry:
        result = table.copy(deep=False)
        result[out_col] = prompts
        ctx.log(f"preview: rendered {len(prompts)} prompts, no API call")
        return result

    unique = list(dict.fromkeys(prompts))
    client = _client(p.get("api_key"))
    model = p["model"]
    system = p.get("system") or ""
    max_tokens = int(p.get("max_tokens", 512))
    on_error = p.get("on_error", "fail")
    answers = {}
    done = [0]

    def one(prompt):
        try:
            return prompt, _complete(client, model, system, prompt, max_tokens)
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
    ctx.log(f"enriched {len(rows)} rows with {len(unique)} model call(s) "
            f"→ column {out_col!r}")
    return result
