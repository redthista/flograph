"""PII Scan

Sweep text columns for personal data — emails, phone numbers, credit-card
numbers, IBANs, US SSNs, IPv4 addresses — and either **flag** where it is or
**redact** it in place. No network, no model: a fixed set of patterns, with
a Luhn check on card numbers so a random 16-digit order id isn't mistaken for
one.

Three outputs. **table** is the input, redacted when **Action** is `redact`
(otherwise untouched). **findings** is one row per hit — column, kind, the
matched text (masked), and the row index. **summary** counts hits per column
and kind.

Set **Columns** to limit the sweep (blank = every text-like column). **Kinds**
limits which detectors run.
"""
NODE = {
    "label": "PII Scan",
    "category": "Transform",
    "version": "1.0",
    "inputs": [("table", "dataframe")],
    "outputs": [
        ("table", "dataframe"),
        ("findings", "dataframe"),
        ("summary", "dataframe"),
    ],
}
PARAMS = [
    {"name": "action", "type": "choice", "label": "Action",
     "options": ["flag only", "redact"], "default": "flag only"},
    {"name": "columns", "type": "columns", "label": "Columns",
     "default": "", "placeholder": "empty = all text-like columns"},
    {"name": "kinds", "type": "string", "label": "Kinds",
     "default": "",
     "placeholder": "empty = all: email, phone, credit_card, ssn, iban, ipv4"},
    {"name": "placeholder", "type": "string", "label": "Redaction placeholder",
     "default": "[REDACTED:{kind}]",
     "placeholder": "{kind} is filled in"},
]

# Patterns are deliberately conservative — a missed hit is better than a
# report full of false positives on product codes and order ids.
_PATTERNS = {
    "email": r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}",
    # A separator (space, dot, dash, or parens) somewhere, so a bare integer
    # column isn't read as a phone number.
    "phone": r"(?<![\w.])(?:\+\d{1,3}[ .\-]?)?\(?\d{2,4}\)?[ .\-]\d{2,4}[ .\-]?\d{0,4}(?!\d)",
    "credit_card": r"(?<!\d)(?:\d[ \-]?){13,19}(?!\d)",
    "ssn": r"(?<!\d)\d{3}-\d{2}-\d{4}(?!\d)",
    "iban": r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b",
    "ipv4": r"(?<!\d)(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)(?!\d)",
}


def _luhn_ok(digits):
    total, alt = 0, False
    for ch in reversed(digits):
        d = ord(ch) - 48
        if alt:
            d *= 2
            if d > 9:
                d -= 9
        total += d
        alt = not alt
    return total % 10 == 0


def _mask(text):
    if len(text) <= 4:
        return "*" * len(text)
    return text[:2] + "*" * (len(text) - 4) + text[-2:]


def run(ctx, table):
    import re

    import pandas as pd

    p = ctx.params
    redact = p.get("action") == "redact"
    tmpl = p.get("placeholder") or "[REDACTED:{kind}]"

    wanted = [k.strip().lower() for k in (p.get("kinds") or "").split(",")
              if k.strip()]
    unknown = [k for k in wanted if k not in _PATTERNS]
    if unknown:
        raise ValueError(f"unknown kind(s) {unknown} — pick from "
                         f"{', '.join(_PATTERNS)}")
    kinds = wanted or list(_PATTERNS)

    chosen = [c.strip() for c in (p.get("columns") or "").split(",") if c.strip()]
    if chosen:
        missing = [c for c in chosen if c not in table.columns]
        if missing:
            raise ValueError(f"column(s) {missing} not in the table")
        cols = chosen
    else:
        cols = [c for c in table.columns
                if table[c].dtype == object or pd.api.types.is_string_dtype(table[c])]

    compiled = {k: re.compile(_PATTERNS[k]) for k in kinds}
    out = table.copy(deep=False)
    findings = []

    for col in cols:
        series = table[col].astype("string")
        new_values = {}
        for idx, val in series.items():
            if val is pd.NA or not isinstance(val, str) or not val:
                continue
            replaced = val
            for kind, rx in compiled.items():
                for m in rx.finditer(val):
                    hit = m.group(0)
                    if kind == "credit_card":
                        digits = re.sub(r"\D", "", hit)
                        if not (13 <= len(digits) <= 19) or not _luhn_ok(digits):
                            continue
                    if kind == "phone":
                        digits = re.sub(r"\D", "", hit)
                        if len(digits) < 7 or len(digits) > 15:
                            continue
                    findings.append({
                        "column": col, "kind": kind,
                        "match": _mask(hit), "row": idx,
                    })
                    if redact:
                        replaced = replaced.replace(
                            hit, tmpl.format(kind=kind))
            if redact and replaced != val:
                new_values[idx] = replaced
        if redact and new_values:
            col_copy = out[col].astype("string").copy()
            for idx, v in new_values.items():
                col_copy.at[idx] = v
            out[col] = col_copy

    findings_df = pd.DataFrame(
        findings, columns=["column", "kind", "match", "row"])
    if findings:
        summary = (findings_df.groupby(["column", "kind"])
                   .size().reset_index(name="hits")
                   .sort_values("hits", ascending=False, ignore_index=True))
    else:
        summary = pd.DataFrame(columns=["column", "kind", "hits"])

    verb = "redacted" if redact else "found"
    ctx.log(f"{verb} {len(findings)} PII hit(s) across {len(cols)} column(s)")
    return {"table": out, "findings": findings_df, "summary": summary}
