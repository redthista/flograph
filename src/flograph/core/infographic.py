"""The template engine behind **HTML Template**.

Qt-free, and pandas-free: it works on a list of plain dicts, so the whole
grammar is testable without a DataFrame and a node can feed it from anywhere.

The token grammar is **deliberately identical to SVG Template's** — `{{name}}`
or `{{name:format}}`, with the same `$`/`£` currency prefix — because the two
nodes are siblings and somebody who has learned one has learned the other. A
test pins the two implementations to the same output.

What this adds on top is the part that makes a template a *builder* rather
than one static drawing bound to one row:

``{{#each}} … {{/each}}``
    repeats its body once per row. Inside, a name is that row's value, and
    ``_n`` / ``_index`` / ``_count`` / ``_color`` / ``_ci`` describe where in
    the run you are.

``{{#if name}} … {{#else}} … {{/if}}``
    keeps its body only when the value is there and not zero, blank or false.
    A comparison asks something sharper — ``{{#if growth > 0}}``,
    ``{{#if status = fail}}``, ``{{#if name contains ltd}}`` — with the same
    operators Table Style's rules use.

``{{{name}}}``
    triple braces substitute the value **raw**; double braces HTML-escape it,
    which is the default because data holding a ``<`` would otherwise take
    the page apart.

Bindings are `name = expression`, one per line, and are where aggregation
lives — keeping it out of the token grammar, which stays a lookup:

    total   = sum(revenue)      # a scalar, usable anywhere
    share   = share(revenue)    # per row: 0-100, this row's cut of the total
    width   = pct(revenue)      # per row: 0-100, against the column's max
    place   = rank(revenue)     # per row: 1 is the largest
    heading = Q3 performance    # a literal
    money   = revenue           # rename a column

Conditions nest freely — they are resolved from the inside out. **`each`
blocks do not nest**, because a row has no child rows to iterate; a layout
that needs that wants a Python Script, not a bigger template language.
"""
from __future__ import annotations

import re
from typing import Any, Iterable, Optional

TOKEN = re.compile(
    r"\{\{\{\s*(?P<rawname>[\w.\- ]+?)\s*(?::(?P<rawspec>[^}]+?))?\s*\}\}\}"
    r"|\{\{\s*(?P<name>[\w.\- ]+?)\s*(?::(?P<spec>[^}]+?))?\s*\}\}")

_EACH = re.compile(r"\{\{#each\}\}(?P<body>.*?)\{\{/each\}\}", re.S)
# Matches the *innermost* if-block — one whose body holds no further
# `{{#if` and no stray `{{/if}}`. Resolving those repeatedly, inside out,
# is what lets conditions nest without a parser.
_INNER = r"(?:(?!\{\{#if\s)(?!\{\{/if\}\}).)*?"
_IF = re.compile(
    r"\{\{#if\s+(?P<name>[\w.\- ]+?)\s*"
    r"(?:(?P<op>>=|<=|!=|>|<|=|contains)\s*(?P<value>[^}]*?)\s*)?\}\}"
    r"(?P<then>" + _INNER + r")"
    r"(?:\{\{#else\}\}(?P<other>" + _INNER + r"))?\{\{/if\}\}", re.S)

#: How deep conditions may nest before we stop and leave the rest as text.
MAX_IF_DEPTH = 24

_CURRENCY = ("$", "£", "€", "¥", "₹")

#: Aggregate over a whole column, yielding one value for the page.
SCALAR_FUNCTIONS = ("sum", "mean", "avg", "average", "min", "max", "count",
                    "median", "first", "last")
#: Yield one value per row, so they can be used inside an `each` block.
ROW_FUNCTIONS = ("pct", "share", "rank", "index")

_CALL = re.compile(r"^(?P<fn>[a-z]+)\s*\(\s*(?P<arg>[^)]*?)\s*\)$", re.I)

MISSING_MODES = ("leave as-is", "blank", "error")


class TemplateError(ValueError):
    """A template or binding that could not be understood."""


def escape(text: Any) -> str:
    return (str(text).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def to_number(value: Any) -> Optional[float]:
    """A number if the value can honestly be read as one, else None."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return None if value != value else value      # NaN
    text = str(value).strip().replace(",", "")
    for symbol in _CURRENCY:
        text = text.replace(symbol, "")
    text = text.strip()
    if text.endswith("%"):
        text = text[:-1].strip()
    try:
        number = float(text)
    except (TypeError, ValueError):
        return None
    return int(number) if number.is_integer() else number


def format_value(value: Any, spec: str) -> str:
    """`{{x:$,.0f}}` — a Python format spec, with a currency prefix allowed.

    Kept byte-compatible with SVG Template's `_format`, including falling
    back to `str(value)` rather than raising when a spec does not fit the
    value: a template is drawn live while it is being written, and a
    half-typed format should not blank the card.
    """
    if value is None:
        return ""
    if isinstance(value, float) and value != value:
        return ""
    if not spec:
        return str(value)
    prefix = ""
    if spec[0] in _CURRENCY:
        prefix, spec = spec[0], spec[1:]
    for candidate in (value, to_number(value)):
        if candidate is None:
            continue
        try:
            return prefix + format(candidate, spec)
        except (ValueError, TypeError):
            continue
    return prefix + str(value)


def compare(value: Any, op: str, other: str) -> bool:
    """`{{#if growth > 0}}` — the same operators Table Style's rules use.

    Numeric when both sides read as numbers, text otherwise, and text is
    compared case-insensitively: a template is written against data somebody
    else typed, and `Fail` matching `fail` is what they meant.
    """
    left_num, right_num = to_number(value), to_number(other)
    if left_num is not None and right_num is not None:
        left, right = left_num, right_num
    else:
        left = "" if value is None else str(value).strip().lower()
        right = str(other).strip().lower()
        if op in ("<", "<=", ">", ">="):
            # An ordering test against text nobody can order is a mistake in
            # the template, not a reason to blank the page.
            return False
    if op == "=":
        return left == right
    if op == "!=":
        return left != right
    if op == "contains":
        return str(right) in str(left)
    if op == ">":
        return left > right
    if op == ">=":
        return left >= right
    if op == "<":
        return left < right
    if op == "<=":
        return left <= right
    return False


def truthy(value: Any) -> bool:
    """What `{{#if}}` means by "there": not missing, blank, zero or false."""
    if value is None or value is False:
        return False
    if isinstance(value, float) and value != value:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    number = to_number(value)
    if number is not None:
        return number != 0
    return bool(value)


# --- bindings ---------------------------------------------------------------

def parse_bindings(raw: str) -> list[tuple[str, str]]:
    """`name = expression` lines, in order — later lines may use earlier ones."""
    out: list[tuple[str, str]] = []
    for lineno, line in enumerate((raw or "").splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        name, sep, expression = line.partition("=")
        name, expression = name.strip(), expression.strip()
        if not sep or not name:
            raise TemplateError(
                f"bindings line {lineno}: expected 'name = value'")
        out.append((name, expression))
    return out


def _column(rows: list[dict], name: str) -> list:
    return [row.get(name) for row in rows]


def _numbers(rows: list[dict], name: str) -> list[Optional[float]]:
    return [to_number(v) for v in _column(rows, name)]


def aggregate(fn: str, values: list) -> Any:
    fn = fn.lower()
    if fn == "count":
        return len(values)
    if fn == "first":
        return values[0] if values else None
    if fn == "last":
        return values[-1] if values else None
    numbers = [v for v in (to_number(x) for x in values) if v is not None]
    if not numbers:
        return None
    if fn == "sum":
        return sum(numbers)
    if fn in ("mean", "avg", "average"):
        return sum(numbers) / len(numbers)
    if fn == "min":
        return min(numbers)
    if fn == "max":
        return max(numbers)
    if fn == "median":
        ordered = sorted(numbers)
        middle = len(ordered) // 2
        if len(ordered) % 2:
            return ordered[middle]
        return (ordered[middle - 1] + ordered[middle]) / 2
    raise TemplateError(f"unknown function {fn!r}")


def per_row(fn: str, rows: list[dict], column: str) -> list:
    fn = fn.lower()
    if fn == "index":
        return list(range(1, len(rows) + 1))
    numbers = _numbers(rows, column)
    known = [n for n in numbers if n is not None]
    if fn == "pct":
        top = max((abs(n) for n in known), default=0) or 0
        return [None if n is None else (0.0 if not top else 100.0 * n / top)
                for n in numbers]
    if fn == "share":
        total = sum(known)
        return [None if n is None else (0.0 if not total
                                        else 100.0 * n / total)
                for n in numbers]
    if fn == "rank":
        order = sorted(range(len(numbers)),
                       key=lambda i: (numbers[i] is None,
                                      -(numbers[i] or 0)))
        places: list[Any] = [None] * len(numbers)
        for place, index in enumerate(order, 1):
            places[index] = None if numbers[index] is None else place
        return places
    raise TemplateError(f"unknown function {fn!r}")


def evaluate_bindings(bindings: Iterable[tuple[str, str]],
                      rows: list[dict]) -> tuple[dict, dict]:
    """Resolve bindings against the data.

    Returns ``(scalars, series)`` — page-level values, and per-row columns
    that an `each` block can read.
    """
    scalars: dict[str, Any] = {}
    series: dict[str, list] = {}
    columns: set[str] = set()
    for row in rows[:1]:
        columns |= set(row)
    # With no rows there are no column names to check against, and refusing
    # every binding would turn an empty table into a wall of errors instead
    # of an empty page. Take the names on trust and render nothing.
    blind = not rows

    for name, expression in bindings:
        call = _CALL.match(expression)
        if call:
            fn, arg = call.group("fn").lower(), call.group("arg").strip()
            if fn in ROW_FUNCTIONS:
                if fn != "index" and arg not in columns and not blind:
                    raise TemplateError(
                        f"binding {name!r}: no column named {arg!r}")
                series[name] = per_row(fn, rows, arg)
                continue
            if fn in SCALAR_FUNCTIONS:
                if (arg and arg not in columns and arg not in series
                        and not blind):
                    raise TemplateError(
                        f"binding {name!r}: no column named {arg!r}")
                values = (series.get(arg) if arg in series
                          else _column(rows, arg) if arg else
                          [1] * len(rows))
                scalars[name] = aggregate(fn, values)
                continue
            raise TemplateError(
                f"binding {name!r}: unknown function {fn!r} — one of: "
                + ", ".join(sorted(SCALAR_FUNCTIONS + ROW_FUNCTIONS)))
        if expression in columns:
            series[name] = _column(rows, expression)
        elif expression in series:
            series[name] = list(series[expression])
        elif expression in scalars:
            scalars[name] = scalars[expression]
        else:
            scalars[name] = expression          # a literal
    return scalars, series


# --- rendering --------------------------------------------------------------

def _substitute(text: str, values: dict, missing: str,
                unresolved: list) -> str:
    def replace(match):
        raw = match.group("rawname") is not None
        name = match.group("rawname") if raw else match.group("name")
        spec = (match.group("rawspec") if raw else match.group("spec")) or ""
        if name in values:
            rendered = format_value(values[name], spec)
            return rendered if raw else escape(rendered)
        unresolved.append(name)
        if missing == "blank":
            return ""
        return match.group(0)

    return TOKEN.sub(replace, text)


def _conditionals(text: str, values: dict) -> str:
    """Resolve `{{#if}}` blocks from the inside out, so they may nest."""
    def resolve(match):
        name, op = match.group("name"), match.group("op")
        value = values.get(name)
        keep = (compare(value, op, match.group("value") or "") if op
                else truthy(value))
        return match.group("then") if keep else (match.group("other") or "")

    for _ in range(MAX_IF_DEPTH):
        resolved = _IF.sub(resolve, text)
        if resolved == text:
            return resolved
        text = resolved
    return text


def _scope(text: str, values: dict, missing: str, unresolved: list) -> str:
    return _substitute(_conditionals(text, values), values, missing,
                       unresolved)


def render(template: str, rows: Optional[list[dict]] = None, *,
           bindings: str = "", missing: str = "leave as-is",
           row: int = 0, palette: Optional[list[str]] = None,
           limit: int = 0,
           values: Optional[dict] = None) -> tuple[str, list[str]]:
    """Fill a template from data. Returns ``(html, unresolved_names)``.

    Outside an `each` block a bare name is column *row* of the data, which
    matches SVG Template — a template with no `each` in it behaves exactly
    like an SVG one.
    """
    rows = list(rows or [])
    if limit and limit > 0:
        rows = rows[:limit]
    palette = list(palette or []) or ["#2563eb"]
    if missing not in MISSING_MODES:
        missing = "leave as-is"

    scalars, series = evaluate_bindings(parse_bindings(bindings), rows)

    page_values: dict[str, Any] = {}
    if rows:
        index = max(0, min(int(row or 0), len(rows) - 1))
        page_values.update(rows[index])
        for name, column in series.items():
            if index < len(column):
                page_values[name] = column[index]
    page_values.update(scalars)
    page_values.update(values or {})
    page_values["_count"] = len(rows)

    unresolved: list[str] = []

    def each(match):
        body = match.group("body")
        out = []
        for index, source in enumerate(rows):
            scope = dict(scalars)
            scope.update(values or {})
            scope.update(source)
            for name, column in series.items():
                scope[name] = column[index] if index < len(column) else None
            scope.update({
                "_index": index,
                "_n": index + 1,
                "_count": len(rows),
                "_color": palette[index % len(palette)],
                "_ci": (index % len(palette)) + 1,
                "_first": index == 0,
                "_last": index == len(rows) - 1,
            })
            out.append(_scope(body, scope, missing, unresolved))
        return "".join(out)

    rendered = _EACH.sub(each, template or "")
    rendered = _scope(rendered, page_values, missing, unresolved)

    if unresolved and missing == "error":
        raise TemplateError("unresolved token(s): "
                            + ", ".join(sorted(set(unresolved))))
    return rendered, unresolved


def rows_from_frame(data) -> list[dict]:
    """A DataFrame to the list of dicts this module works on.

    Kept here so the pandas import stays in one place and the node script
    does not have to know the shape.
    """
    if data is None:
        return []
    try:
        records = data.to_dict("records")
    except AttributeError:
        return list(data)
    out = []
    for record in records:
        out.append({str(k): _plain(v) for k, v in record.items()})
    return out


def _plain(value):
    """numpy scalars out, plain Python in — a payload has to be printable."""
    if value is None:
        return None
    if hasattr(value, "item") and not isinstance(value, (str, bytes)):
        try:
            return value.item()
        except (ValueError, AttributeError):
            return value
    return value
