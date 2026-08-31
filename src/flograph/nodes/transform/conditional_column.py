"""Conditional Column

Add a column whose value is chosen by a list of *if / then* rules — Power
Query's *Conditional Column*, without dropping into an Expression. Rules are
tried top to bottom and the first one that matches wins; a bare `=> value`
line at the end is the "otherwise" fallback.

```
score >= 90    => A
score >= 80    => B
score >= 70    => C
               => F
```

The left-hand side is `column operator value`. Operators: `=`, `!=`, `<`,
`<=`, `>`, `>=`, `contains`, `starts`, `ends`, `matches` (regex), `is empty`,
`is not empty`. Numbers compare numerically; everything else as text. Results
that look like a number become one; `@column` copies that column's value for
the row.
"""
NODE = {
    "label": "Conditional Column",
    "category": "Transform",
    "version": "1.0",
    "inputs": [("table", "dataframe")],
    "outputs": [("table", "dataframe")],
}
PARAMS = [
    {"name": "output_column", "type": "string", "label": "New column",
     "default": "category"},
    {"name": "rules", "type": "text", "label": "Rules (if => then)",
     "default": "",
     "placeholder": "units >= 100 => high\nunits >= 50 => medium\n=> low"},
]

_SUFFIX_OPS = ["is not empty", "is empty"]
_INFIX_WORD_OPS = [("contains", "contains"), ("starts with", "starts"),
                   ("ends with", "ends"), ("starts", "starts"),
                   ("ends", "ends"), ("matches", "matches")]
_SYM_OPS = ["!=", "<=", ">=", "=", "<", ">"]


def _coerce(text):
    t = text.strip()
    if t.lower() in ("true", "false"):
        return t.lower() == "true"
    try:
        return int(t)
    except ValueError:
        pass
    try:
        return float(t)
    except ValueError:
        return t


def _parse_rule(lineno, line):
    cond, sep, result = line.partition("=>")
    if not sep:
        raise ValueError(f"rule {lineno}: expected 'condition => result', "
                         f"got {line!r}")
    result = result.strip()
    cond = cond.strip()
    if not cond:
        return (None, result)  # else / fallback

    low = cond.lower()
    for op in _SUFFIX_OPS:
        if low == op or low.endswith(f" {op}"):
            column = cond[:len(cond) - len(op)].strip()
            if not column:
                raise ValueError(f"rule {lineno}: no column before {op!r}")
            return ((column, op, None), result)
    for token, canon in _INFIX_WORD_OPS:
        idx = low.find(f" {token} ")
        if idx != -1:
            column = cond[:idx].strip()
            value = cond[idx + len(token) + 2:].strip()
            return ((column, canon, value), result)
    for op in _SYM_OPS:
        if op in cond:
            column, _, value = cond.partition(op)
            return ((column.strip(), op, value.strip()), result)
    raise ValueError(f"rule {lineno}: no operator found in condition {cond!r}")


def _mask(df, column, op, value):
    import pandas as pd

    if column not in df.columns:
        raise ValueError(f"condition column {column!r} not in table")
    s = df[column]

    if op == "is empty":
        return s.isna() | (s.astype("string").str.strip() == "")
    if op == "is not empty":
        return ~(s.isna() | (s.astype("string").str.strip() == ""))
    if op in ("contains", "starts", "ends", "matches"):
        text = s.astype("string")
        if op == "contains":
            return text.str.contains(value, regex=False, na=False)
        if op == "starts":
            return text.str.startswith(value, na=False)
        if op == "ends":
            return text.str.endswith(value, na=False)
        return text.str.match(value, na=False)

    target = _coerce(value)
    if isinstance(target, (int, float)) and not isinstance(target, bool):
        s = pd.to_numeric(s, errors="coerce")
    else:
        s = s.astype("string")
        target = str(value)

    if op == "=":
        return s == target
    if op == "!=":
        return s != target
    if op == "<":
        return s < target
    if op == "<=":
        return s <= target
    if op == ">":
        return s > target
    if op == ">=":
        return s >= target
    raise ValueError(f"unhandled operator {op!r}")


def run(ctx, table):
    import pandas as pd

    p = ctx.params
    name = p["output_column"].strip()
    if not name:
        raise ValueError("'New column' is empty")

    rules, fallback = [], pd.NA
    seen_else = False
    for lineno, raw in enumerate(p["rules"].splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        cond, result = _parse_rule(lineno, line)
        if cond is None:
            fallback = result
            seen_else = True
        elif seen_else:
            raise ValueError(f"rule {lineno}: rules after the '=> {fallback}' "
                             "fallback can never match")
        else:
            rules.append((cond, result))
    if not rules:
        raise ValueError("no rules given — one 'condition => result' per line")

    def resolved(result):
        if isinstance(result, str) and result.startswith("@"):
            ref = result[1:].strip()
            if ref not in table.columns:
                raise ValueError(f"result column {ref!r} not in table")
            return table[ref]
        return _coerce(result) if isinstance(result, str) else result

    fb = resolved(fallback)
    out = pd.Series(list(fb) if isinstance(fb, pd.Series) else [fb] * len(table),
                    index=table.index, dtype=object)

    unassigned = pd.Series(True, index=table.index)
    for (column, op, value), result in rules:
        hit = _mask(table, column, op, value) & unassigned
        val = resolved(result)
        if isinstance(val, pd.Series):
            out.loc[hit] = val.loc[hit]
        else:
            out.loc[hit] = val
        unassigned &= ~hit

    result = table.copy(deep=False)
    result[name] = out.infer_objects()
    ctx.log(f"{name!r} from {len(rules)} rule(s); "
            f"{int((~unassigned).sum())}/{len(table)} rows matched a rule")
    return result
