"""Data Quality Gate

Validate a table against a list of rules and let the rest of the flow branch
on the result. Three outputs: **passed** is a single bool (every rule held),
**report** is one row per rule with its violation count and a few example bad
values, and **clean** is the input with every row that broke a row-level rule
removed.

One rule per line, `column check [args]`. Blank lines and lines starting with
`#` are ignored. Checks:

    order_id     not_null
    order_id     unique
    status       in  open | closed | pending
    amount       between 0 and 100000
    amount       >= 0
    email        regex  ^[^@]+@[^@]+\\.[^@]+$
    country      max_null_pct 2
    @rows        >= 1000

`@rows` is the table-level row count. `max_null_pct N` passes when the column
is missing in at most N% of rows. Everything else is a row-level check and
feeds the **clean** output.

**On fail** decides what a failing gate does: `report only` just fills the
outputs, `raise` stops the node (and everything downstream of it) with the
summary as the error — the way you make a bad feed block a report.
"""
NODE = {
    "label": "Data Quality Gate",
    "category": "Transform",
    "version": "1.0",
    "inputs": [("table", "dataframe")],
    "outputs": [
        ("passed", "bool"),
        ("report", "dataframe"),
        ("clean", "dataframe"),
    ],
}
PARAMS = [
    {"name": "on_fail", "type": "choice", "label": "On fail",
     "options": ["report only", "raise"], "default": "report only"},
    {"name": "rules", "type": "text", "label": "Rules",
     "default": "",
     "placeholder": "order_id not_null\nstatus in open | closed\namount between 0 and 1e6\n@rows >= 1"},
]

_COMPARATORS = {
    ">": lambda s, v: s > v,
    ">=": lambda s, v: s >= v,
    "<": lambda s, v: s < v,
    "<=": lambda s, v: s <= v,
    "==": lambda s, v: s == v,
    "!=": lambda s, v: s != v,
}


def _num(token):
    try:
        return float(token)
    except (TypeError, ValueError):
        raise ValueError(f"expected a number, got {token!r}")


def _parse_rules(text):
    rules = []
    for lineno, raw in enumerate((text or "").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) < 2:
            raise ValueError(
                f"rule line {lineno}: expected 'column check [args]', got {line!r}")
        column, check, args = parts[0], parts[1].lower(), parts[2:]
        rules.append((lineno, line, column, check, args))
    return rules


def _examples(series, mask, limit=5):
    bad = series[mask]
    if bad.empty:
        return ""
    seen = list(dict.fromkeys(str(v) for v in bad.tolist()))
    head = ", ".join(seen[:limit])
    return head + (" …" if len(seen) > limit else "")


def run(ctx, table):
    import pandas as pd

    rules = _parse_rules(ctx.params.get("rules"))
    if not rules:
        raise ValueError("no rules given — add at least one 'column check' line")

    rows = []
    row_level_bad = pd.Series(False, index=table.index)

    for lineno, text, column, check, args in rules:
        table_level = column == "@rows"
        if not table_level and column not in table.columns:
            raise ValueError(
                f"rule line {lineno}: column {column!r} is not in the table "
                f"({', '.join(map(str, table.columns))})")

        violations = 0
        example = ""
        removes_rows = False

        if table_level:
            if check not in _COMPARATORS:
                raise ValueError(
                    f"rule line {lineno}: @rows needs a comparator "
                    f"({'/'.join(_COMPARATORS)}), got {check!r}")
            target = _num(args[0]) if args else 0.0
            ok = bool(_COMPARATORS[check](pd.Series([len(table)]), target).iloc[0])
            violations = 0 if ok else len(table)
            example = "" if ok else f"row count is {len(table)}"

        elif check == "not_null":
            mask = table[column].isna()
            violations = int(mask.sum())
            example = _examples(table.index.to_series(), mask)
            row_level_bad |= mask
            removes_rows = True

        elif check == "unique":
            mask = table[column].duplicated(keep=False)
            violations = int(mask.sum())
            example = _examples(table[column], mask)
            row_level_bad |= mask
            removes_rows = True

        elif check == "in":
            allowed = [a.strip() for a in " ".join(args).split("|") if a.strip()]
            if not allowed:
                raise ValueError(
                    f"rule line {lineno}: 'in' needs values, e.g. "
                    f"'{column} in a | b | c'")
            mask = ~table[column].astype("string").isin(allowed) & table[column].notna()
            violations = int(mask.sum())
            example = _examples(table[column], mask)
            row_level_bad |= mask
            removes_rows = True

        elif check == "between":
            # column between LOW and HIGH
            joined = " ".join(args).replace(" and ", " ")
            bits = joined.split()
            if len(bits) != 2:
                raise ValueError(
                    f"rule line {lineno}: 'between' needs two bounds, e.g. "
                    f"'{column} between 0 and 100'")
            low, high = _num(bits[0]), _num(bits[1])
            numeric = pd.to_numeric(table[column], errors="coerce")
            mask = (numeric < low) | (numeric > high) | numeric.isna()
            mask &= table[column].notna()
            violations = int(mask.sum())
            example = _examples(table[column], mask)
            row_level_bad |= mask
            removes_rows = True

        elif check == "regex":
            pattern = " ".join(args)
            if not pattern:
                raise ValueError(f"rule line {lineno}: 'regex' needs a pattern")
            as_text = table[column].astype("string")
            mask = ~as_text.str.fullmatch(pattern).fillna(False) & as_text.notna()
            violations = int(mask.sum())
            example = _examples(table[column], mask)
            row_level_bad |= mask
            removes_rows = True

        elif check == "max_null_pct":
            limit = _num(args[0]) if args else 0.0
            pct = float(table[column].isna().mean() * 100.0)
            ok = pct <= limit
            violations = 0 if ok else int(table[column].isna().sum())
            example = "" if ok else f"{pct:.1f}% null (limit {limit:g}%)"

        elif check in _COMPARATORS:
            target = _num(args[0]) if args else 0.0
            numeric = pd.to_numeric(table[column], errors="coerce")
            ok_mask = _COMPARATORS[check](numeric, target)
            mask = ~ok_mask.fillna(False) & table[column].notna()
            violations = int(mask.sum())
            example = _examples(table[column], mask)
            row_level_bad |= mask
            removes_rows = True

        else:
            raise ValueError(
                f"rule line {lineno}: unknown check {check!r} (not_null, unique, "
                f"in, between, regex, max_null_pct, or a comparator)")

        rows.append({
            "rule": text,
            "column": column,
            "check": check,
            "scope": "table" if table_level else ("row" if removes_rows else "column"),
            "violations": violations,
            "passed": violations == 0,
            "examples": example,
        })

    report = pd.DataFrame(rows, columns=[
        "rule", "column", "check", "scope", "violations", "passed", "examples"])
    passed = bool(report["passed"].all())
    clean = table[~row_level_bad]

    failed = report[~report["passed"]]
    if passed:
        ctx.log(f"all {len(report)} rules passed")
    else:
        summary = "; ".join(
            f"{r.rule} ({r.violations})" for r in failed.itertuples())
        ctx.log(f"{len(failed)}/{len(report)} rules failed: {summary}")
        if ctx.params.get("on_fail") == "raise":
            raise ValueError(f"data quality gate failed — {summary}")

    return {"passed": passed, "report": report, "clean": clean}
