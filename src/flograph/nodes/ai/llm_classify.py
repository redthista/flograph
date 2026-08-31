"""LLM Classify

Sort each row into one of a fixed set of labels. Give it the text column and
the labels; it returns the chosen label in a new column, constrained to the
set you defined (nothing invented).

    Text column:  review_body
    Labels:       positive | neutral | negative
    Instruction:  Judge the sentiment about the product, ignore shipping.

**API format** (`anthropic` / `openai`) plus **Base URL** and **Model** point
this at any endpoint that speaks one of those protocols — the hosted APIs,
Azure, a local Ollama / vLLM server, a gateway. Leave **API key** blank to
use `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` from the environment, or type one
in / use `${env:NAME}`.

Identical inputs are classified once. **Multi-label** allows several labels
per row (comma-joined); **Allow "other"** lets a row fall outside the set.
Needs `httpx`.
"""
NODE = {
    "label": "LLM Classify",
    "category": "AI",
    "version": "2.0",
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
    {"name": "provider", "type": "choice", "label": "API format",
     "options": ["anthropic", "openai"], "default": "anthropic"},
    {"name": "model", "type": "string", "label": "Model",
     "default": "claude-haiku-4-5",
     "placeholder": "claude-haiku-4-5 / gpt-4o-mini / llama3.1 …"},
    {"name": "base_url", "type": "string", "label": "Base URL",
     "default": "",
     "placeholder": "blank = provider default; e.g. http://localhost:11434/v1"},
    {"name": "api_key", "type": "password", "label": "API key",
     "default": "",
     "placeholder": "blank = the provider's env var; ${env:NAME} for a project secret; unset for a local server"},
    {"name": "concurrency", "type": "int", "label": "Concurrency",
     "default": 8, "min": 1, "max": 32},
    {"name": "on_error", "type": "choice", "label": "On row error",
     "options": ["fail", "blank"], "default": "fail"},
    {"name": "dry_run", "type": "bool", "label": "Preview (no API call)",
     "default": False},
]


def _labels(raw):
    parts = [p.strip() for p in (raw or "").replace(",", "|").split("|")]
    return [p for p in parts if p]


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

    from flograph.nodes.ai import _llm

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

    if bool(p.get("dry_run")):
        result = table.copy(deep=False)
        result[out_col] = [f"[preview] would classify: {t[:40]}" for t in texts]
        ctx.log("preview: no API call")
        return result

    provider = p.get("provider", "anthropic")
    key = _llm.resolve_key(provider, p.get("api_key"))
    base = p.get("base_url") or ""
    model = (p.get("model") or "").strip()
    if not model:
        raise ValueError("no model — set 'Model'")
    on_error = p.get("on_error", "fail")

    unique = list(dict.fromkeys(texts))
    answers = {}
    done = [0]

    def one(text):
        try:
            raw = _llm.chat(provider, base, key, model, system,
                            text or "(empty)", 64, 60.0)
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
            f"{len(unique)} {provider} call(s)")
    return result
