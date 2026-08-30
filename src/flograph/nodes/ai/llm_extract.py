"""LLM Extract

Pull structured fields out of a free-text column into new columns — the
"turn this messy paragraph into a row" job.

List the fields, one per line, `name: what it means`:

    company: the employer's legal name
    salary_min: lower bound of the pay range, number only, blank if absent
    remote: true if the role is fully remote

The model is asked for a JSON object with exactly those keys; the answer is
parsed and spread into columns (`extracted_` prefix by default). A field it
can't find comes back blank. Identical inputs are extracted once.

Key: `${env:ANTHROPIC_API_KEY}` by default. Needs the `anthropic` package.
"""
NODE = {
    "label": "LLM Extract",
    "category": "AI",
    "version": "1.0",
    "inputs": [("table", "dataframe")],
    "outputs": [("table", "dataframe")],
}
PARAMS = [
    {"name": "text_column", "type": "columns", "label": "Text column",
     "default": "", "multi": False},
    {"name": "fields", "type": "text", "label": "Fields",
     "default": "", "placeholder": "name: description\nprice: the amount in USD"},
    {"name": "prefix", "type": "string", "label": "New-column prefix",
     "default": "extracted_", "placeholder": "blank = no prefix"},
    {"name": "model", "type": "choice", "label": "Model",
     "options": ["claude-sonnet-5", "claude-haiku-4-5", "claude-opus-5"],
     "default": "claude-sonnet-5"},
    {"name": "max_tokens", "type": "int", "label": "Max tokens",
     "default": 1024, "min": 1, "max": 8192},
    {"name": "concurrency", "type": "int", "label": "Concurrency",
     "default": 4, "min": 1, "max": 32},
    {"name": "on_error", "type": "choice", "label": "On row error",
     "options": ["fail", "blank"], "default": "fail"},
    {"name": "dry_run", "type": "bool", "label": "Preview (no API call)",
     "default": False},
    {"name": "api_key", "type": "password", "label": "API key",
     "default": "${env:ANTHROPIC_API_KEY}"},
]


def _fields(raw):
    out = []
    for lineno, line in enumerate((raw or "").splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        name, sep, desc = line.partition(":")
        name = name.strip()
        if not name.isidentifier():
            raise ValueError(
                f"fields line {lineno}: {name!r} is not a valid field name")
        out.append((name, desc.strip()))
    return out


def _parse_json(text):
    import json

    body = text.strip()
    if body.startswith("```"):
        body = body.split("\n", 1)[-1]
        if body.rstrip().endswith("```"):
            body = body.rsplit("```", 1)[0]
    start, end = body.find("{"), body.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"no JSON object in the model's reply: {text[:120]!r}")
    return json.loads(body[start:end + 1])


def _client(api_key):
    import anthropic

    key = (api_key or "").strip()
    if not key or key.startswith("${"):
        raise ValueError(
            "no API key — set 'API key' (or ANTHROPIC_API_KEY in the "
            "project's .env and use ${env:ANTHROPIC_API_KEY})")
    return anthropic.Anthropic(api_key=key)


def run(ctx, table):
    from concurrent.futures import ThreadPoolExecutor

    p = ctx.params
    col = (p.get("text_column") or "").strip()
    fields = _fields(p.get("fields"))
    if not col:
        raise ValueError("no text column — set 'Text column'")
    if col not in table.columns:
        raise ValueError(f"column {col!r} not in the table")
    if not fields:
        raise ValueError("no fields — list at least one 'name: description'")

    prefix = p.get("prefix", "")
    names = [n for n, _ in fields]
    new_cols = [f"{prefix}{n}" for n in names]
    texts = ["" if v is None else str(v) for v in table[col].tolist()]

    schema_lines = "\n".join(
        f'  "{n}": {d or "extract this field"}' for n, d in fields)
    system = (
        "Extract the requested fields from the user's text. Reply with ONLY a "
        "JSON object with exactly these keys:\n{\n" + schema_lines + "\n}\n"
        "Use null for anything the text does not state. No prose, no code "
        "fence.")

    if p.get("dry_run"):
        result = table.copy(deep=False)
        for nc in new_cols:
            result[nc] = "[preview]"
        ctx.log(f"preview: would extract {len(names)} field(s), no API call")
        return result

    unique = list(dict.fromkeys(texts))
    client = _client(p.get("api_key"))
    model = p["model"]
    max_tokens = int(p.get("max_tokens", 1024))
    on_error = p.get("on_error", "fail")
    parsed = {}
    done = [0]

    def one(text):
        try:
            resp = client.messages.create(
                model=model, max_tokens=max_tokens, system=system,
                messages=[{"role": "user", "content": text or "(empty)"}])
            raw = "".join(b.text for b in resp.content
                          if b.type == "text")
            obj = _parse_json(raw)
            return text, {n: obj.get(n) for n in names}
        except Exception as exc:  # noqa: BLE001
            if on_error == "fail":
                raise
            ctx.log(f"row failed ({exc}) — left blank")
            return text, {n: None for n in names}

    with ThreadPoolExecutor(max_workers=int(p.get("concurrency", 4))) as pool:
        for text, obj in pool.map(one, unique):
            parsed[text] = obj
            done[0] += 1
            ctx.check_cancelled()
            ctx.progress(done[0] / len(unique))

    result = table.copy(deep=False)
    for name, nc in zip(names, new_cols):
        result[nc] = [parsed.get(t, {}).get(name) for t in texts]
    ctx.log(f"extracted {len(names)} field(s) from {len(texts)} rows with "
            f"{len(unique)} call(s)")
    return result
