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
    "version": "1.1",
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

_SUFFIX_OPS = ["is not empty", "is empty"]
_WORD_OPS = [("contains", "contains"), ("starts with", "starts"),
             ("ends with", "ends"), ("starts", "starts"),
             ("ends", "ends"), ("matches", "matches")]
_SYM_OPS = [("!=", "!="), ("<=", "<="), (">=", ">="), ("==", "="),
            ("=", "="), ("<", "<"), (">", ">")]
# stands in for a backticked column while the operator is looked for, so a
# name with an operator word or symbol in it can't be mistaken for one
_HELD = "\x00"


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


def _find_operator(cond):
    """(column, operator, value) for the left-most operator, or None."""
    low = cond.lower()
    for op in _SUFFIX_OPS:
        if low == op or low.endswith(f" {op}"):
            return cond[:len(cond) - len(op)].strip(), op, None
    found = []
    for token, canon in _WORD_OPS:
        idx = low.find(f" {token} ")
        if idx != -1:
            found.append((idx, -len(token), idx + len(token) + 2, canon))
        elif low.startswith(f"{token} "):
            # `and starts with x`: the column is carried from the last one
            found.append((0, -len(token), len(token) + 1, canon))
    for token, canon in _SYM_OPS:
        idx = cond.find(token)
        if idx != -1:
            found.append((idx, -len(token), idx + len(token), canon))
    if not found:
        return None
    # left-most wins, so `note = it contains x` compares note; at one place
    # the longer token, so `<=` is never read as `<`
    idx, _, value_at, canon = min(found)
    return cond[:idx].strip(), canon, cond[value_at:].strip()


def _parse_clause(lineno, clause, previous):
    from flograph.core.column_refs import is_quoted, unquote

    text = clause.strip()
    if not text:
        raise ValueError(f"rule {lineno}: nothing between 'and' / 'or'")
    held = None
    probe = text
    if text.startswith("`"):
        end = text.find("`", 1)
        if end == -1:
            raise ValueError(f"rule {lineno}: no closing ` in {text!r}")
        held = text[1:end]
        probe = f"{_HELD} {text[end + 1:].strip()}"
    found = _find_operator(probe)
    if found is not None and held is not None and found[0] != _HELD:
        raise ValueError(f"rule {lineno}: expected an operator straight "
                         f"after `{held}` in {text!r}")
    if found is not None:
        column, op, value = found
        if column == _HELD:
            column = held
        elif not column:
            if previous is None:
                raise ValueError(f"rule {lineno}: no column before {op!r} "
                                 f"in {text!r}")
            column = previous[0]
        else:
            column = unquote(column)
    elif previous is not None and previous[2] is not None:
        # a bare value: the column and operator before it, again
        column, op, value = previous[0], previous[1], text
    else:
        raise ValueError(f"rule {lineno}: no operator found in condition "
                         f"{text!r}")
    quoted = value is not None and is_quoted(value)
    if value is not None:
        value = unquote(value)
    return (column, op, value, quoted)


def _parse_rule(lineno, line, columns=()):
    from flograph.core.column_refs import (find_outside_quotes,
                                           quote_bare_columns, split_keyword)

    at = find_outside_quotes(line, "=>")
    if at == -1:
        raise ValueError(f"rule {lineno}: expected 'condition => result', "
                         f"got {line!r}")
    cond, result = line[:at].strip(), line[at + 2:].strip()
    if not cond:
        return (None, result)  # else / fallback
    cond = quote_bare_columns(cond, columns)
    groups, previous = [], None
    for alternative in split_keyword(cond, "or"):
        group = []
        for clause in split_keyword(alternative, "and"):
            previous = _parse_clause(lineno, clause, previous)
            group.append(previous)
        groups.append(group)
    return (groups, result)


def _mask(df, column, op, value, quoted=False):
    import pandas as pd

    if column not in df.columns:
        raise ValueError(f"condition column {column!r} not in table")
    s = df[column]

    if op == "is empty":
        return s.isna() | (s.astype("string").str.strip() == "").fillna(False)
    if op == "is not empty":
        return ~(s.isna() | (s.astype("string").str.strip() == "").fillna(False))
    if op in ("contains", "starts", "ends", "matches"):
        text = s.astype("string")
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
