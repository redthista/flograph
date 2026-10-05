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
`<=`, `>`, `>=`, `contains`, `does not contain`, `starts`, `ends`,
`matches` (regex), `is empty`, `is not empty`. Numbers compare numerically; everything else as text. Results
that look like a number become one; `@column` copies that column's value for
the row.

One rule can test several things, joined with `and` / `or`. `and` binds
tighter, as in maths, so `a and b or c` means *(a and b) or c*:

```
region = North and units >= 100    => big north
status = open or status = pending  => live
status = open or pending           => live
score > 50 and < 80                => middle
```

A condition missing its column or its operator repeats the one before it,
so `open or pending` tests `status` both times. Put a value in quotes when
it has `and` / `or` in it (`name = "Tom and Jerry"`); a quoted value is
always compared as text. A column with a space in its name is written as it
is spelled, or in backticks: `` `unit price` > 5 ``.
"""
NODE = {
    "label": "Conditional Column",
    "category": "Transform",
    "version": "1.2",
    "inputs": [("table", "dataframe")],
    "outputs": [("table", "dataframe")],
}
PARAMS = [
    {"name": "output_column", "type": "string", "label": "New column",
     "default": "category"},
    {"name": "rules", "type": "text", "label": "Rules (if => then)",
     "default": "",
     "placeholder": "units > 200 => top\n"
                    "units >= 100 and region = North => high\n"
                    "units >= 50 or priority = yes => medium\n=> low"},
]


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


def _parse_rule(lineno, line, columns=()):
    from flograph.core.column_refs import find_outside_quotes
    from flograph.core.conditions import parse_condition

    at = find_outside_quotes(line, "=>")
    if at == -1:
        raise ValueError(f"rule {lineno}: expected 'condition => result', "
                         f"got {line!r}")
    cond, result = line[:at].strip(), line[at + 2:].strip()
    if not cond:
        return (None, result)  # else / fallback
    return (parse_condition(f"rule {lineno}", cond, columns), result)


def _mask(df, column, op, value, quoted=False):
    import pandas as pd

    if column not in df.columns:
        raise ValueError(f"condition column {column!r} not in table")
    s = df[column]

    if op == "is empty":
        return s.isna() | (s.astype("string").str.strip() == "").fillna(False)
    if op == "is not empty":
        return ~(s.isna() | (s.astype("string").str.strip() == "").fillna(False))
    if op in ("contains", "not contains", "starts", "ends", "matches"):
        text = s.astype("string")
        if op == "not contains":
            return ~text.str.contains(value, regex=False, na=False)
        if op == "contains":
            return text.str.contains(value, regex=False, na=False)
        if op == "starts":
            return text.str.startswith(value, na=False)
        if op == "ends":
            return text.str.endswith(value, na=False)
        return text.str.match(value, na=False)

    target = value if quoted else _coerce(value)
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

    from flograph.core.column_refs import unquote

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
        groups, result = _parse_rule(lineno, line, table.columns)
        if groups is None:
            fallback = result
            seen_else = True
        elif seen_else:
            raise ValueError(f"rule {lineno}: rules after the '=> {fallback}' "
                             "fallback can never match")
        else:
            rules.append((groups, result))
    if not rules:
        raise ValueError("no rules given — one 'condition => result' per line")

    def resolved(result):
        if isinstance(result, str) and result.startswith("@"):
            ref = unquote(result[1:])
            if ref not in table.columns:
                raise ValueError(f"result column {ref!r} not in table")
            return table[ref]
        return _coerce(result) if isinstance(result, str) else result

    def matches(groups):
        # any group, every clause in it; a missing value is no match
        hit = pd.Series(False, index=table.index)
        for group in groups:
            every = pd.Series(True, index=table.index)
            for column, op, value, quoted in group:
                mask = _mask(table, column, op, value, quoted)
                every &= mask.fillna(False).astype(bool)
            hit |= every
        return hit

    fb = resolved(fallback)
    out = pd.Series(list(fb) if isinstance(fb, pd.Series) else [fb] * len(table),
                    index=table.index, dtype=object)

    unassigned = pd.Series(True, index=table.index)
    for groups, result in rules:
        hit = matches(groups) & unassigned
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
