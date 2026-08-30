"""LLM Classify

Sort each row into one of a fixed set of labels. Give it the text column and
the labels; it returns the chosen label in a new column, constrained to the
set you defined (nothing invented).

    Text column:  review_body
    Labels:       positive | neutral | negative
    Instruction:  Judge the sentiment about the product, ignore shipping.

Defaults to Claude Haiku — classification is the kind of short, high-volume
call it's built for. Identical inputs are classified once. **Multi-label**
allows several labels per row (returned comma-joined); **Allow "other"** lets
a row fall outside the set instead of being forced.

Key: `${env:ANTHROPIC_API_KEY}` by default. Needs the `anthropic` package.
"""
NODE = {
    "label": "LLM Classify",
    "category": "AI",
    "version": "1.0",
    "inputs": [("table", "dataframe")],
    "outputs": [("table", "dataframe")],
}
PARAMS = [
    {"name": "text_column", "type": "columns", "label": "Text column",
     "default": "", "multi": False},
    {"name": "labels", "type": "string", "label": "Labels",
     "default": "", "placeholder": "positive | neutral | negative"},
    {"name": "instruction", "type": "text", "label": "Instruction",
     "default": "", "placeholder": "optional — how to decide"},
    {"name": "output_column", "type": "string", "label": "Output column",
     "default": "label"},
    {"name": "multi_label", "type": "bool", "label": "Multi-label",
     "default": False},
    {"name": "allow_other", "type": "bool", "label": 'Allow "other"',
     "default": False},
    {"name": "model", "type": "choice", "label": "Model",
     "options": ["claude-haiku-4-5", "claude-sonnet-5", "claude-opus-5"],
     "default": "claude-haiku-4-5"},
    {"name": "concurrency", "type": "int", "label": "Concurrency",
     "default": 8, "min": 1, "max": 32},
    {"name": "on_error", "type": "choice", "label": "On row error",
     "options": ["fail", "blank"], "default": "fail"},
    {"name": "dry_run", "type": "bool", "label": "Preview (no API call)",
     "default": False},
    {"name": "api_key", "type": "password", "label": "API key",
     "default": "${env:ANTHROPIC_API_KEY}"},
]


def _labels(raw):
    parts = [p.strip() for p in (raw or "").replace(",", "|").split("|")]
    return [p for p in parts if p]


def _client(api_key):
    import anthropic

    key = (api_key or "").strip()
    if not key or key.startswith("${"):
        raise ValueError(
            "no API key — set 'API key' (or ANTHROPIC_API_KEY in the "
            "project's .env and use ${env:ANTHROPIC_API_KEY})")
    return anthropic.Anthropic(api_key=key)


def _match(answer, labels, multi, allow_other):
    low = {la.lower(): la for la in labels}
    a = answer.strip().lower().strip(".")
    if a in low:
        return low[a]
    found = list(dict.fromkeys(orig for key, orig in low.items() if key in a))
    if multi and found:
        return ", ".join(found)
    if found:
        return found[0]
    return "other" if allow_other else ""


def run(ctx, table):
    from concurrent.futures import ThreadPoolExecutor

    p = ctx.params
    col = (p.get("text_column") or "").strip()
    labels = _labels(p.get("labels"))
    if not col:
        raise ValueError("no text column — set 'Text column'")
    if col not in table.columns:
        raise ValueError(f"column {col!r} not in the table")
    if len(labels) < 2:
        raise ValueError("give at least two labels, e.g. 'yes | no'")

    out_col = (p.get("output_column") or "label").strip()
    multi = bool(p.get("multi_label"))
    allow_other = bool(p.get("allow_other"))
    instruction = (p.get("instruction") or "").strip()

    texts = ["" if v is None else str(v) for v in table[col].tolist()]

    system = (
        "You are a precise text classifier. Reply with "
        + ("one or more labels from this list, comma-separated"
           if multi else "exactly one label from this list")
        + ", and nothing else. Labels: " + " | ".join(labels)
        + (' | other' if allow_other else "")
        + (f"\n\nHow to decide: {instruction}" if instruction else "")
    )

    if p.get("dry_run"):
        result = table.copy(deep=False)
        result[out_col] = [f"[preview] would classify: {t[:40]}" for t in texts]
        ctx.log("preview: no API call")
        return result

    unique = list(dict.fromkeys(texts))
    client = _client(p.get("api_key"))
    model = p["model"]
    on_error = p.get("on_error", "fail")
    answers = {}
    done = [0]

    def one(text):
        try:
            resp = client.messages.create(
                model=model, max_tokens=32, system=system,
                messages=[{"role": "user", "content": text or "(empty)"}])
            raw = "".join(b.text for b in resp.content
                          if b.type == "text").strip()
            return text, _match(raw, labels, multi, allow_other)
        except Exception as exc:  # noqa: BLE001
            if on_error == "fail":
                raise
            ctx.log(f"row failed ({exc}) — left blank")
            return text, None

    with ThreadPoolExecutor(max_workers=int(p.get("concurrency", 8))) as pool:
        for text, label in pool.map(one, unique):
            answers[text] = label
            done[0] += 1
            ctx.check_cancelled()
            ctx.progress(done[0] / len(unique))

    result = table.copy(deep=False)
    result[out_col] = [answers.get(t) for t in texts]
    ctx.log(f"classified {len(texts)} rows into {len(labels)} label(s) with "
            f"{len(unique)} call(s)")
    return result
