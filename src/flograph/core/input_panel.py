"""The Input Panel: several input fields in one card, each optionally a
filter on a column of the panel's table. Qt-free, so the node's run() and
the card's widget work the field list out the same way — the options a
dropdown offers, the bounds a slider spans, and which rows survive.

**Fields are declared one per line**, in the house style the rules boxes
use (conditional formatting, chart rules), not as JSON:

    Region   = choice region
    City     = choice city
    Price    = between price step=5
    Ordered  = date range order_date
    Customer = text customer contains
    In stock = toggle in_stock
    Top N    = number min=1 max=50 default=10

`Label = shape [column] [comparison] [key=value ...]`. The label is what
the card shows; the field's *name* (its key in `values`, and its variable)
is the label made into an identifier — "In stock" -> `in_stock` — unless a
`name=` says otherwise. A field with a column filters the panel's table on
it; one without is just a value, read through `values` or `${name}`.

**Cascade.** Fields are worked through top to bottom, each one's options
and bounds coming from the rows the fields above it left — so a City list
only offers the picked Region's cities. Turn `cascade` off and every field
looks at the whole table.

**A field that hasn't been set filters nothing.** A choice starts on
"(All)", a multi with nothing ticked, a slider on its column's lowest
value, a Between on the whole range, a date on the earliest day — so a new
panel passes every row, and each field narrows only once it is used.

The filters a panel applied are also emitted as data (`filters_from`), so
an Apply Filters node can apply the same picks to a second table. A Slicer
emits its ticks the same way, as one filter of kind "path"
(`core.slicer.as_filter`).
"""
from __future__ import annotations

import re
from typing import Any, Optional

# shape word(s) on a field line -> the control shape that draws it
SHAPES = {
    "choice": "choice", "dropdown": "choice",
    "multi": "multi", "multichoice": "multi", "chips": "multi",
    "slicer": "list", "list": "list", "checklist": "list",
    "slider": "slider",
    "number": "number",
    "between": "range", "range": "range",
    "date": "date",
    "daterange": "date_range",
    "text": "text", "search": "text",
    "toggle": "toggle", "tick": "toggle", "switch": "toggle",
    "time": "time",
    "datetime": "datetime",
    "colour": "colour", "color": "colour",
}
# comparisons a field line may name, and the shapes they make sense for
COMPARISONS = {">=", "<=", ">", "<", "=", "==", "contains", "startswith",
               "equals"}
_DEFAULT_OP = {
    "choice": "==", "multi": "in", "list": "in",
    "slider": ">=", "number": ">=",
    "range": "between", "date": ">=", "date_range": "between",
    "text": "contains", "toggle": "true",
}
# key=value options a field line understands, and what they become
_OPTION_KEYS = {"name", "step", "decimals", "min", "max", "default",
                "options", "style", "all", "required", "help",
                "placeholder", "text", "cascade"}


class FieldError(ValueError):
    """A field line that can't be read. Collected, not raised one by one,
    so the node can say every problem at once."""


def field_name(label: str) -> str:
    """A label as an identifier: "In stock" -> "in_stock", "2024 sales" ->
    "f_2024_sales" (a variable can't start with a digit)."""
    name = re.sub(r"\W+", "_", str(label).strip().lower()).strip("_")
    if not name:
        name = "field"
    if name[0].isdigit():
        name = "f_" + name
    return name


def _yes(text: str) -> bool:
    return str(text).strip().lower() in ("yes", "true", "on", "1", "y")


def parse_fields(text: Any) -> tuple[list[dict], list[str]]:
    """Field lines -> (fields, problems). Blank lines and `#` comments are
    skipped. A bad line is reported and left out; the rest still work."""
    import shlex

    fields: list[dict] = []
    problems: list[str] = []
    seen: set[str] = set()
    for number, line in enumerate(str(text or "").splitlines(), start=1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        label, sep, rest = line.partition("=")
        label = label.strip()
        if not sep or not label:
            problems.append(f"line {number}: expected 'Label = shape …'")
            continue
        try:
            words = shlex.split(rest)
        except ValueError as exc:
            problems.append(f"line {number}: {exc}")
            continue
        if not words:
            problems.append(f"line {number}: no shape after '='")
            continue
        shape_word = words.pop(0).lower()
        if shape_word in ("date", "multi") and words \
                and words[0].lower() in ("range", "choice"):
            shape_word += words.pop(0).lower()
        shape = SHAPES.get(shape_word)
        if shape is None:
            known = ", ".join(sorted({"choice", "multi", "slicer", "slider",
                                      "number",
                                      "between", "date", "date range",
                                      "text", "toggle", "time", "datetime",
                                      "colour"}))
            problems.append(f"line {number}: {shape_word!r} is not a field "
                            f"shape ({known})")
            continue
        field: dict = {"label": label, "shape": shape, "column": "",
                       "op": "", "opts": {}}
        bad = False
        for word in words:
            key, eq, value = word.partition("=")
            if eq and key.lower() in _OPTION_KEYS:
                field["opts"][key.lower()] = value
            elif word.lower() in COMPARISONS or word in COMPARISONS:
                op = word.lower()
                field["op"] = {"=": "==", "equals": "=="}.get(op, op)
            elif not field["column"] and not eq:
                field["column"] = word
            else:
                problems.append(f"line {number}: don't know what {word!r} "
                                f"means here")
                bad = True
                break
        if bad:
            continue
        field["name"] = field_name(field["opts"].get("name") or label)
        if field["name"] in seen:
            problems.append(f"line {number}: a field named "
                            f"{field['name']!r} already exists — give one a "
                            f"name=")
            continue
        seen.add(field["name"])
        if not field["op"]:
            field["op"] = _DEFAULT_OP.get(shape, "")
        fields.append(field)
    return fields, problems


def field_names(text: Any) -> list[str]:
    return [f["name"] for f in parse_fields(text)[0]]


def parse_values(raw: Any) -> dict:
    """The panel's `value` param — a JSON object of field -> stored value —
    as a dict; anything unreadable is "nothing set yet"."""
    import json

    if isinstance(raw, dict):
        return dict(raw)
    try:
        parsed = json.loads(str(raw or "") or "{}")
    except ValueError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


# ------------------------------------------------------------- one field

def _number(text: Any, fallback: Optional[float]) -> Optional[float]:
    from .controls import as_number
    if text in (None, ""):
        return fallback
    return as_number(text, fallback if fallback is not None else 0.0)


def _column(data, column: str):
    if data is None or not column or not hasattr(data, "columns"):
        return None
    return data[column] if column in data.columns else None


def _is_dateish(series) -> bool:
    kind = getattr(getattr(series, "dtype", None), "kind", "")
    return kind == "M"


def context(field: dict, data) -> dict:
    """What a field's widget needs from the rows it sees: the `options` a
    choice or multi offers, the `minimum`/`maximum` a slider or date spans.
    Empty when the field has no column, or the column isn't there."""
    from .controls import as_iso_date, reduce_bound, values_from_source

    shape = field["shape"]
    series = _column(data, field["column"])
    found: dict = {}
    if series is None:
        if field["opts"].get("options"):
            found["options"] = [o for o in
                                str(field["opts"]["options"]).split("|") if o]
        return found
    if shape in ("choice", "multi", "list"):
        found["options"] = values_from_source(series) or []
        if shape == "list":
            # rows behind each value, beside it in the slicer — of the rows
            # this field sees, so a cross-filtered count is the honest one
            counts = series.dropna().astype(str).value_counts()
            found["counts"] = {str(k): int(v) for k, v in counts.items()}
    elif shape in ("slider", "number", "range"):
        numeric = _as_numeric(series)
        low = reduce_bound(numeric, high=False)
        high = reduce_bound(numeric, high=True)
        if low is not None:
            found["minimum"] = float(low)
        if high is not None:
            found["maximum"] = float(high)
    elif shape in ("date", "date_range"):
        dates = _as_dates(series)
        low = as_iso_date(reduce_bound(dates, high=False))
        high = as_iso_date(reduce_bound(dates, high=True))
        if low:
            found["minimum"] = low
        if high:
            found["maximum"] = high
    return found


def _as_numeric(series):
    import pandas as pd
    return pd.to_numeric(series, errors="coerce")


def _as_dates(series):
    import pandas as pd
    if _is_dateish(series):
        return series
    return pd.to_datetime(series, errors="coerce")


def widget_params(field: dict, stored: Any, ctx: dict) -> dict:
    """A field as the params its shape's widget reads — the same params a
    standalone control of that shape has, so the panel draws each field
    with the very widget a Slider or a Choice node uses."""
    opts = field["opts"]
    shape = field["shape"]
    params: dict = {"caption": field["label"], "help": opts.get("help", ""),
                    "required": _yes(opts.get("required", "")),
                    "value": stored}
    for key, target in (("step", "step"), ("decimals", "decimals"),
                        ("placeholder", "placeholder"), ("style", "style"),
                        ("text", "text")):
        if key in opts:
            params[target] = opts[key]
    # typed bounds narrow what the column offers; the column fills the rest
    params["minimum"] = _number(opts.get("min"), ctx.get("minimum")) \
        if shape not in ("date", "date_range") \
        else (opts.get("min") or ctx.get("minimum", ""))
    params["maximum"] = _number(opts.get("max"), ctx.get("maximum")) \
        if shape not in ("date", "date_range") \
        else (opts.get("max") or ctx.get("maximum", ""))
    if shape in ("slider", "number", "range"):
        if params["minimum"] is None:
            params["minimum"] = 0.0
        if params["maximum"] is None:
            params["maximum"] = 100.0
        if "decimals" not in params:
            # a column of fractions wants a fractional slider
            span = params["maximum"] - params["minimum"]
            params["decimals"] = 0 if span >= 20 else 2
        if "step" not in params and params.get("decimals"):
            params["step"] = 10 ** -int(params["decimals"])
        step = _number(params.get("step"), None)
        if step and step > 0 and field["column"]:
            # A column's own ends are rarely on the step (a lowest price of
            # 5.43 with step=5): rounded outward, the notches land on 5, 10,
            # 15… instead of 5.43, 10.43 — and the range still covers every
            # row, so an untouched field still filters nothing.
            import math
            params["minimum"] = math.floor(params["minimum"] / step) * step
            params["maximum"] = math.ceil(params["maximum"] / step) * step
    if shape == "choice":
        # on a column, "(All)" — no filter — unless all=no says otherwise
        params["all_option"] = _yes(opts.get("all", "yes" if field["column"]
                                             else "no"))
        params["items"] = "\n".join(ctx.get("options", []))
    if shape in ("multi", "list"):
        params["items"] = "\n".join(ctx.get("options", []))
    if shape == "list":
        params["counts"] = ctx.get("counts", {})
    if shape == "toggle":
        params.setdefault("text", "")
        params["style"] = opts.get("style", "switch")
    if shape == "date" and field["column"] and stored in (None, ""):
        # an untouched date on a column sits at the end that filters nothing
        params["value"] = params["minimum"] if field["op"] in (">=", ">") \
            else params["maximum"]
    if shape == "date_range" and field["column"] and stored in (None, ""):
        params["value"] = "whole range"
    if stored in (None, "") and "default" in opts \
            and shape not in ("date", "date_range"):
        params["value"] = _typed_default(shape, opts["default"])
    return params


def _typed_default(shape: str, text: str) -> Any:
    if shape in ("slider", "number"):
        return _number(text, 0.0)
    if shape == "toggle":
        return _yes(text)
    return text


def emitted(field: dict, params: dict) -> Any:
    """What the field is worth, given the params its widget shows — the
    same resolution each standalone control's run() makes, so the panel's
    `values` hold what its cards display."""
    from . import controls as c

    shape, value = field["shape"], params.get("value")
    if shape in ("slider", "number"):
        low = c.as_number(params.get("minimum"), 0.0)
        high = c.as_number(params.get("maximum"), 100.0)
        number = c.clamp(c.as_number(value, low), low, high)
        decimals = int(params.get("decimals", 0) or 0)
        return round(number, decimals) if decimals else int(round(number))
    if shape == "range":
        low = c.as_number(params.get("minimum"), 0.0)
        high = c.as_number(params.get("maximum"), 100.0)
        a, b = c.range_values(value, low, high)
        a, b = c.clamp(a, low, high), c.clamp(b, low, high)
        return sorted([a, b])
    if shape == "date":
        day = c.date_value(value)
        low, high = params.get("minimum") or "", params.get("maximum") or ""
        if low and day < low:
            day = low
        if high and day > high:
            day = high
        return day
    if shape == "date_range":
        _p, start, end = c.date_range_values(
            value, params.get("minimum") or "", params.get("maximum") or "")
        return [start, end]
    if shape == "choice":
        options = c.lines_to_values(params.get("items"))
        return c.choice_value(value, options, bool(params.get("all_option")))
    if shape in ("multi", "list"):
        return c.selected_values(value)
    if shape == "toggle":
        return bool(value)
    if shape == "time":
        return c.time_value(value)
    if shape == "datetime":
        return c.datetime_value(value)
    if shape == "colour":
        return c.colour_value(value)
    return "" if value is None else str(value)


# ------------------------------------------------------------- filtering

def filter_of(field: dict, value: Any, params: dict) -> Optional[dict]:
    """The filter a field puts on its column, or None when it filters
    nothing (no column, or not set yet — see the module docstring)."""
    column, shape, op = field["column"], field["shape"], field["op"]
    if not column:
        return None
    kind = "number"
    if shape in ("date", "date_range"):
        kind = "date"
    elif shape in ("choice", "multi", "list", "text"):
        kind = "text"
    elif shape == "toggle":
        kind = "bool"
    if shape == "choice" and value in ("", None):
        return None
    if shape in ("multi", "list") and not value:
        return None
    if shape == "text" and not str(value or "").strip():
        return None
    if shape == "toggle" and not value:
        return None
    if shape in ("slider", "number", "date"):
        # sitting on the end of the range that keeps every row
        low, high = params.get("minimum"), params.get("maximum")
        if (op in (">=",) and value == low) or (op in ("<=",) and value == high):
            return None
    if shape in ("range", "date_range"):
        low, high = params.get("minimum"), params.get("maximum")
        if list(value) == [low, high]:
            return None
        op = "between"
    if shape in ("multi", "list"):
        op = "in"
    return {"field": field["name"], "column": column, "op": op,
            "value": value, "kind": kind}


def filter_columns(flt: dict) -> list[str]:
    """Every column a filter reads: one for a panel field, the levels of
    the tree for a Slicer's (kind "path")."""
    return list(flt.get("columns") or [flt["column"]])


def apply_filter(df, flt: dict, column: Optional[str] = None,
                 columns: Optional[list] = None):
    """Rows of `df` that pass one filter. `column` overrides the filter's
    own — `columns`, all of a Slicer filter's levels — which is how Apply
    Filters maps a filter onto another table."""
    import pandas as pd

    if flt.get("kind") == "path":
        from flograph.core.slicer import paths_mask

        return df[paths_mask(df, columns or filter_columns(flt),
                             flt["value"])]
    column = column or flt["column"]
    series = df[column]
    op, value, kind = flt["op"], flt["value"], flt.get("kind", "number")
    if kind == "date":
        series = _as_dates(series)
        if op == "between":
            start, end = pd.Timestamp(value[0]), pd.Timestamp(value[1])
            # the end day is included whole, for a column with times in it
            mask = (series >= start) & (series < end + pd.Timedelta(days=1))
        else:
            mask = _compare(series, op, pd.Timestamp(value), whole_day=True)
    elif kind == "number":
        series = _as_numeric(series)
        if op == "between":
            mask = series.between(value[0], value[1])
        else:
            mask = _compare(series, op, value)
    elif kind == "bool":
        mask = series.fillna(False).astype(bool)
    else:
        text = series.astype(str)
        if op == "in":
            mask = text.isin([str(v) for v in value])
        elif op == "contains":
            mask = text.str.contains(str(value), case=False, regex=False,
                                     na=False)
        elif op == "startswith":
            mask = text.str.lower().str.startswith(str(value).lower(),
                                                   na=False)
        else:
            mask = text == str(value)
        mask = mask & series.notna()
    return df[mask.fillna(False)]


def _compare(series, op: str, value, whole_day: bool = False):
    import pandas as pd

    if whole_day and op in ("<=", ">", "=="):
        # a date compares as a whole day: "on or before the 5th" includes
        # 5th 17:00, which a bare timestamp comparison would drop
        nxt = value + pd.Timedelta(days=1)
        if op == "<=":
            return series < nxt
        if op == ">":
            return series >= nxt
        return (series >= value) & (series < nxt)
    return {">=": series >= value, "<=": series <= value,
            ">": series > value, "<": series < value,
            "==": series == value}.get(op, series == value)


#: How a panel's fields affect one another (the "Cascade" setting).
EACH_OTHER = "each other"       # Power BI's slicers: every list reflects the rest
TOP_DOWN = "top to bottom"      # each field narrowed by the ones above it
OFF = "off"                     # every field sees the whole table
CASCADE_MODES = [EACH_OTHER, TOP_DOWN, OFF]

# the shapes whose options a cross-filter narrows
_LISTS = ("choice", "multi", "list")


def cascade_mode(raw: Any) -> str:
    """The Cascade setting as one of CASCADE_MODES — a panel saved while
    it was a tick box reads True as "top to bottom" (what it meant then)."""
    if raw is True:
        return TOP_DOWN
    if raw is False:
        return OFF
    return raw if raw in CASCADE_MODES else EACH_OTHER


def run_panel(fields: list[dict], stored: dict, data,
              cascade: Any = EACH_OTHER) -> tuple:
    """Work the panel out: `(filtered, values, filters, contexts)` — the
    rows left, each field's value, the filters applied (for Apply
    Filters), and each field's (context, widget params), which is what its
    widget offers and shows.

    **each other** — every list (choice, multi, slicer) offers the values
    the *other* fields leave, with their row counts, the way slicers on a
    Power BI page filter one another. A range (slider, number, between,
    date) keeps its whole column's span: narrowing it would clamp a value
    someone set, and the card would then show a number the flow isn't
    using. **top to bottom** — each field sees only the rows the fields
    above it left, ranges included. **off** — every field sees the table.
    """
    mode = cascade_mode(cascade)
    rows = data
    values: dict = {}
    filters: dict = {}          # field name -> filter, in field order
    contexts: dict = {}
    for field in fields:
        seen = rows if mode == TOP_DOWN else data
        ctx = context(field, seen)
        params = widget_params(field, stored.get(field["name"]), ctx)
        contexts[field["name"]] = (ctx, params)
        value = emitted(field, params)
        values[field["name"]] = value
        flt = filter_of(field, value, params)
        if flt is not None and rows is not None \
                and _column(rows, field["column"]) is not None:
            filters[field["name"]] = flt
            rows = apply_filter(rows, flt)
    if mode == EACH_OTHER and data is not None and len(filters) > 0:
        for field in fields:
            if field["shape"] not in _LISTS or not field["column"]:
                continue
            # every filter but this field's own
            seen = data
            for name, flt in filters.items():
                if name != field["name"]:
                    seen = apply_filter(seen, flt)
            ctx = context(field, seen)
            params = widget_params(field, stored.get(field["name"]), ctx)
            contexts[field["name"]] = (ctx, params)
    return rows, values, list(filters.values()), contexts


def blank_required(fields: list[dict], values: dict) -> list[str]:
    """Labels of required fields with nothing in them."""
    from .control_apply import is_blank
    return [f["label"] for f in fields
            if _yes(f["opts"].get("required", ""))
            and is_blank(values.get(f["name"]))]


# ------------------------------------------------------------- the wizard

#: the word a field line uses for each shape — the reverse of SHAPES
SHAPE_WORDS = {"choice": "choice", "multi": "multi", "list": "slicer",
               "slider": "slider", "number": "number", "range": "between",
               "date": "date", "date_range": "date range", "text": "text",
               "toggle": "toggle", "time": "time", "datetime": "datetime",
               "colour": "colour"}
#: the comparisons a shape can be given, its default first; a shape not
#: here has one fixed way to filter (a slicer keeps the ticked values)
SHAPE_COMPARISONS = {
    "slider": [">=", "<=", ">", "<", "=="],
    "number": [">=", "<=", ">", "<", "=="],
    "date": [">=", "<=", ">", "<", "=="],
    "text": ["contains", "startswith", "=="],
}


def _quoted(text: Any) -> str:
    """A word for a field line: quoted when it has spaces or quotes in it,
    so shlex reads it back as one word."""
    import shlex
    text = str(text)
    return text if text and all(c not in text for c in " \t\"'=#") \
        else shlex.quote(text)


def dump_field(field: dict) -> str:
    """One field as the line `parse_fields` reads back into the same field
    — what the setup wizard writes. The comparison is left out when it is
    the shape's default, so a written line reads the way a typed one
    would."""
    shape = field["shape"]
    label = str(field.get("label") or "").replace("=", " ").strip() or "Field"
    words = [label, "=", SHAPE_WORDS.get(shape, shape)]
    if field.get("column"):
        words.append(_quoted(field["column"]))
    op = field.get("op") or ""
    if op and op != _DEFAULT_OP.get(shape, ""):
        words.append(op)
    for key, value in (field.get("opts") or {}).items():
        if value in (None, ""):
            continue
        words.append(f"{key}={_quoted(value)}")
    return " ".join(words)


def dump_fields(fields: list[dict]) -> str:
    return "\n".join(dump_field(f) for f in fields)


def _nice_step(span: float) -> float:
    """A round step giving roughly twenty notches across `span` — 5 for a
    0-100 price, 0.05 for a 0-1 ratio, 1000 for a salary."""
    import math
    if span <= 0:
        return 1.0
    raw = span / 20
    power = 10 ** math.floor(math.log10(raw))
    for mult in (1, 2, 5, 10):
        if raw <= mult * power:
            return mult * power
    return 10 * power


def suggest_field(column: Any, series) -> Optional[dict]:
    """A sensible field for one column, or None for a column not worth
    filtering on (an id, an empty column).

    True/false is a switch; dates are a date range; numbers are a between
    with a round step; text with a handful of values is a row of buttons, a
    few dozen a slicer, and text that is nearly all different a search box.
    """
    label = str(column).replace("_", " ").strip().capitalize() or "Field"
    values = series.dropna()
    if values.empty:
        return None
    unique = values.nunique()
    base = {"label": label, "column": str(column), "opts": {}}
    lowered = str(column).lower()
    looks_like_id = (lowered == "id" or lowered.endswith("_id")
                     or lowered.endswith(" id"))
    kind = series.dtype.kind
    truthy = {"True", "False", "true", "false", "1", "0", "yes", "no",
              "Yes", "No"}
    if kind == "b" or (unique <= 2 and kind not in "iuf"
                       and set(map(str, values.unique())) <= truthy):
        return {**base, "shape": "toggle", "op": "true"}
    if kind == "M" or (kind == "O" and _mostly_dates(values)):
        return {**base, "shape": "date_range", "op": "between"}
    if kind in "iuf":
        if looks_like_id or (kind in "iu" and unique == len(values)
                             and unique > 50):
            return None
        span = float(values.max()) - float(values.min())
        return {**base, "shape": "range", "op": "between",
                "opts": {"step": f"{_nice_step(span):g}"}}
    if looks_like_id:
        return None
    if unique <= 5:
        return {**base, "shape": "choice", "op": "==",
                "opts": {"style": "buttons"}}
    if unique <= 60 or unique < len(values) * 0.9:
        return {**base, "shape": "list", "op": "in"}
    return {**base, "shape": "text", "op": "contains"}


def _mostly_dates(values) -> bool:
    import pandas as pd
    sample = values.astype(str).head(200)
    if sample.str.match(r"^\d{4}-\d{2}-\d{2}").mean() < 0.9:
        return False
    return pd.to_datetime(sample, errors="coerce").notna().mean() >= 0.9


def suggest_fields(data) -> list[dict]:
    """A field for every column worth one. Slicers and choices first, then
    dates, then numbers, then switches and search boxes — the order a
    filter pane usually reads in."""
    if data is None or not hasattr(data, "columns"):
        return []
    order = {"list": 0, "choice": 0, "date_range": 1, "range": 2,
             "toggle": 3, "text": 4}
    fields = [f for f in (suggest_field(c, data[c]) for c in data.columns)
              if f is not None]
    return sorted(fields, key=lambda f: order.get(f["shape"], 5))
