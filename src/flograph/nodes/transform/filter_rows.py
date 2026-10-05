"""Filter Rows

Keep the rows of a DataFrame that match; the rows that don't come out of
the second port.

Pick a **Column**, how to **Match** and a **Value** — no code.

- **Text:** contains, starts with, ends with, equals (and their
  opposites). `*` stands for any run of characters and `?` for one; every
  other character means itself. Case is ignored unless *Match case* is
  ticked. *matches pattern* takes a regular expression instead.
- **Lists:** *is one of* / *is not one of* take several values, one per
  line or separated by commas: `North, South, East`.
- **Numbers and dates:** `>`, `>=`, `<`, `<=`, equals, and *between*
  (both ends included; the second value goes in *To*). A column of dates —
  or of text that reads as dates, as a CSV's often is — compares the value
  as a date: `2026-10-05`, `5 Oct 2026`, `05/10/2026` (day first),
  `2026-10` (the month) or `2026` (the year).
- **Dates that move:** `today`, `yesterday`, `tomorrow`, `today - 7`,
  `today + 2 weeks`, `now`, `this week` / `month` / `quarter` / `year` (and
  `last` / `next` ones), `last 30 days`, `next 3 months`. A flow that keeps
  "the last 30 days" means the last 30 days whenever it runs.
- A value that names a day, month or year means all of it: `<= 2026-10-05`
  keeps all of the 5th, *equals* `this month` keeps the month, `> 2026`
  starts in 2027.
- **Blanks:** a blank cell matches nothing, so *does not contain* and
  *does not equal* keep it; *is blank* / *is not blank* find the empty
  cells (nothing in them, or only spaces) and need no value.

**Driving it from a dashboard:** wire a control into the **value** input
— a Slider, Date, Choice or Text — and it replaces the Value box; wire a
Between Slider's `low` and `high` into **value** and **value_to** for
*between*. A list wired into **value** suits *is one of* — and so does a
table: its column of the same name (or its only column) gives the values,
so *is one of* keeps the rows whose customer appears in another table.

**Advanced options:**

- **Conditions** — several conditions in Conditional Column's language,
  one per line; a row has to pass every line. `region = North and units >= 100`,
  `status = open or pending`, `name does not contain test`. Operators:
  `=`, `!=`, `<`, `<=`, `>`, `>=`, `contains`, `does not contain`,
  `starts with`, `ends with`, `matches`, `is empty`, `is not empty` — each
  matching as the dropdown of the same name does.
- **Query expression** — a pandas query, e.g. `price > 5 and region == 'North'`.
  A column with a space in its name can be written as it is spelled
  (`unit price > 5`) or in backticks (`` `unit price` > 5 ``).

Everything filled in has to pass: the dropdowns, each Conditions line and
the query.

Untick *Output rejected rows* when nothing reads the second port: it then
carries an empty table, so a large table isn't held twice in the cache.
"""
_CONTROLS = ["flograph.input.slider", "flograph.input.date",
             "flograph.input.choice", "flograph.input.text",
             "flograph.input.number", "flograph.input.between_slider"]
NODE = {
    "label": "Filter Rows",
    "category": "Transform",
    "version": "1.2",
    "inputs": [("table", "dataframe"),
               ("value", "any", {"optional": True, "suggest": _CONTROLS}),
               ("value_to", "any",
                {"optional": True,
                 "suggest": ["flograph.input.between_slider",
                             "flograph.input.slider", "flograph.input.date"]})],
    "outputs": [("filtered", "dataframe"), ("rejected", "dataframe")],
}
# The comparisons, by the label the Match dropdown shows.
ORDER = {"> greater than": "gt", ">= greater than or equal": "ge",
         "< less than": "lt", "<= less than or equal": "le"}
# The matches that look only at the cell, so need no Value.
BLANK = ["is blank", "is not blank"]
ONE_OF = ["is one of", "is not one of"]
PATTERN = "matches pattern (regex)"
MATCHES = ["contains", "does not contain", "starts with", "ends with",
           "equals", "does not equal", *ONE_OF, *ORDER, "between", *BLANK,
           PATTERN]
_NEEDS_VALUE = {"match": [m for m in MATCHES if m not in BLANK]}
PARAMS = [
    {"name": "column", "type": "columns", "label": "Column", "default": "",
     "multi": False},
    {"name": "match", "type": "choice", "label": "Match",
     "options": MATCHES, "default": "contains"},
    {"name": "value", "type": "string", "label": "Value", "default": "",
     "placeholder": "apple, 100, 2026-10-05, today - 7",
     "visible_when": _NEEDS_VALUE},
    {"name": "value_to", "type": "string", "label": "To", "default": "",
     "placeholder": "the other end, included",
     "visible_when": {"match": ["between"]}},
    {"name": "case_sensitive", "type": "bool", "label": "Match case",
     "default": False, "visible_when": _NEEDS_VALUE},
    {"name": "keep_rejected", "type": "bool", "label": "Output rejected rows",
     "default": True},
    {"name": "conditions", "type": "text", "label": "Conditions",
     "default": "", "section": "Advanced options", "folded": True,
     "placeholder": "region = North and units >= 100\n"
                    "status = open or pending"},
    {"name": "query", "type": "string", "label": "Query expression",
     "default": "", "placeholder": "col_a > 0 and col_b == 'x'",
     "section": "Advanced options", "folded": True},
]

# Conditions-box operators as the dropdown entries that match the same way.
_OPERATORS = {"=": "equals", "!=": "does not equal", "<": "< less than",
              "<=": "<= less than or equal", ">": "> greater than",
              ">=": ">= greater than or equal", "contains": "contains",
              "not contains": "does not contain", "starts": "starts with",
              "ends": "ends with", "matches": PATTERN,
              "is empty": "is blank", "is not empty": "is not blank"}


# ---------------------------------------------------------------- condition

def _condition_mask(table, column, match, value, value_to, case):
    """The rows passing `column <match> value` (and `value_to`)."""
    column = str(column or "").strip()
    if not column:
        raise ValueError("Pick the column to match in 'Column'")
    if column not in table.columns:
        raise ValueError(f"No column named {column!r} in the table")
    if match not in MATCHES:
        raise ValueError(f"'Match' can't be {match!r}")
    cells = table[column]

    if match in BLANK:
        blank = cells.map(lambda v: not (t := _cell_text(v)) or not t.strip())
        blank = blank.astype(bool)
        return blank if match == "is blank" else ~blank
    if match in ONE_OF:
        hit = _one_of(cells, _items(value), case, column)
        return hit if match == "is one of" else ~hit
    if match == "between":
        if not value or not value_to:
            raise ValueError("'between' needs a value at both ends — "
                             "fill in Value and To")
        return (_single(cells, ">= greater than or equal", value, case, column)
                & _single(cells, "<= less than or equal", value_to, case,
                          column))
    return _single(cells, match, value, case, column)


def _single(cells, match, value, case, column):
    from pandas.api.types import is_bool_dtype, is_datetime64_any_dtype
    from pandas.api.types import is_numeric_dtype

    negate = match.startswith("does not")
    if match == PATTERN:
        return _pattern_hit(cells, value, case)
    is_date = is_datetime64_any_dtype(cells)
    is_number = is_numeric_dtype(cells) and not is_bool_dtype(cells)
    equality = match in ("equals", "does not equal") \
        and not any(ch in value for ch in "*?")
    if match in ORDER:
        op = ORDER[match]
    elif equality and (is_date or is_number):
        op = "eq"
    elif equality and _number(value) is None \
            and _date_span(value) is not None \
            and (as_dates := _to_dates(cells)).notna().any():
        # text that reads as dates, as a CSV's does: `equals this month`
        hit = _date_hit(as_dates, "eq", value, column).fillna(False)
        return ~hit if negate else hit
    else:
        hit = _text_hit(cells, match, value, case)
        return ~hit if negate else hit

    if is_date:
        hit = _date_hit(cells, op, value, column)
    elif is_number:
        number = _number(value)
        if number is None:
            raise ValueError(
                f"{value!r} isn't a number, and {column!r} holds numbers")
        hit = getattr(cells, op)(number)
    else:
        hit = _mixed_hit(cells, op, value, case)
    hit = hit.fillna(False).astype(bool)
    return ~hit if negate else hit


def _items(value):
    """The values of an *is one of* list: one per line, or comma-separated."""
    sep = "\n" if "\n" in value else ","
    return [item.strip() for item in value.split(sep) if item.strip()]


def _one_of(cells, items, case, column):
    from pandas.api.types import is_datetime64_any_dtype, is_numeric_dtype

    if not items:
        raise ValueError("'is one of' needs at least one value")
    plain = not any(ch in item for item in items for ch in "*?")
    numbers = [_number(item) for item in items]
    # The common cases as one set lookup rather than a pass per value.
    if plain and is_numeric_dtype(cells) and None not in numbers:
        return cells.isin(numbers).astype(bool)
    if plain and not is_datetime64_any_dtype(cells) \
            and not is_numeric_dtype(cells):
        keys = set(items if case else (i.casefold() for i in items))
        return cells.map(lambda v: (t := _cell_text(v)) is not None and (
            t if case else t.casefold()) in keys).astype(bool)
    hit = None
    for item in items:
        one = _single(cells, "equals", item, case, column)
        hit = one if hit is None else hit | one
    return hit


def _text_hit(cells, match, value, case):
    """A text match: `value` is literal except for the * and ? wildcards."""
    import re

    body = "".join(".*" if ch == "*" else "." if ch == "?" else re.escape(ch)
                   for ch in value)
    pattern = {"starts with": "^" + body, "ends with": body + "$",
               "equals": "^" + body + "$",
               "does not equal": "^" + body + "$"}.get(match, body)
    # DOTALL: a cell with a line break in it is still one value to match.
    rx = re.compile(pattern, (0 if case else re.IGNORECASE) | re.DOTALL)
    return cells.map(lambda v: (t := _cell_text(v)) is not None
                     and bool(rx.search(t))).astype(bool)


def _pattern_hit(cells, value, case):
    import re

    try:
        rx = re.compile(value, 0 if case else re.IGNORECASE)
    except re.error as exc:
        raise ValueError(f"{value!r} isn't a valid pattern ({exc}). To find "
                         f"the text as typed, use 'contains'.") from None
    return cells.map(lambda v: (t := _cell_text(v)) is not None
                     and bool(rx.search(t))).astype(bool)


def _mixed_hit(cells, op, value, case):
    """A comparison on a column of text (or mixed values): as numbers when
    the value is one and the column holds some, then as dates, then as
    text in alphabetical order. Cells that aren't of the kind never pass."""
    import pandas as pd

    number = _number(value)
    if number is not None:
        as_numbers = pd.to_numeric(cells, errors="coerce")
        if as_numbers.notna().any():
            return getattr(as_numbers, op)(number)
    if _date_span(value) is not None:
        as_dates = _to_dates(cells)
        if as_dates.notna().any():
            return _date_hit(as_dates, op, value, None)
    key = value if case else value.casefold()
    return cells.map(lambda v: (t := _cell_text(v)) is not None and getattr(
        t if case else t.casefold(), f"__{op}__")(key)).astype(bool)


def _number(text):
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


# -------------------------------------------------------------------- dates

def _date_hit(cells, op, value, column):
    """`cells <op> value` where the value is a span of time — a day, a
    month, `last 30 days` — or an instant, when it has a time in it."""
    span = _date_span(value)
    if span is None:
        raise ValueError(
            f"{value!r} isn't a date, and {column!r} holds dates — try "
            f"2026-10-05, 05/10/2026 (day first), today - 7 or this month")
    start, end = span
    tz = getattr(cells.dt, "tz", None)
    if tz is not None:
        start, end = (_in_zone(t, tz) for t in (start, end))
    if end is None:
        return getattr(cells, op)(start)
    return {"eq": (cells >= start) & (cells < end), "gt": cells >= end,
            "ge": cells >= start, "lt": cells < start,
            "le": cells < end}[op]


def _in_zone(when, tz):
    if when is None or when.tzinfo is not None:
        return when
    return when.tz_localize(tz)


_UNITS = {"": "days", "d": "days", "day": "days", "days": "days",
          "w": "weeks", "wk": "weeks", "week": "weeks", "weeks": "weeks",
          "m": "months", "mo": "months", "month": "months",
          "months": "months", "y": "years", "yr": "years", "year": "years",
          "years": "years", "q": "quarters", "quarter": "quarters",
          "quarters": "quarters"}


def _offset(n, unit):
    import pandas as pd

    unit = _UNITS.get(unit)
    if unit is None:
        return None
    if unit == "quarters":
        return pd.DateOffset(months=3 * n)
    return pd.DateOffset(**{unit: n})


def _today():
    import pandas as pd

    return pd.Timestamp.now().normalize()


def _date_span(text):
    """(start, end) for a value that reads as a date, else None. `end` is
    exclusive, or None for an instant (a value with a time in it)."""
    import re

    import pandas as pd

    low = " ".join(str(text).lower().split())
    if not low:
        return None
    day = pd.DateOffset(days=1)

    m = re.fullmatch(r"(today|yesterday|tomorrow|now)"
                     r"(?: ?([+-]) ?(\d+) ?([a-z]*))?", low)
    if m:
        word, sign, n, unit = m.groups()
        now = pd.Timestamp.now()
        base = {"today": _today(), "yesterday": _today() - day,
                "tomorrow": _today() + day, "now": now}[word]
        if n:
            shift = _offset(int(n), unit)
            if shift is None:
                return None
            base = base + shift if sign == "+" else base - shift
        return (base, None) if word == "now" else (base, base + day)

    m = re.fullmatch(r"(this|last|next) (week|month|quarter|year)", low)
    if m:
        which, unit = m.groups()
        today = _today()
        if unit == "week":
            start = today - pd.DateOffset(days=today.weekday())
        elif unit == "month":
            start = today.replace(day=1)
        elif unit == "quarter":
            start = today.replace(month=3 * ((today.month - 1) // 3) + 1,
                                  day=1)
        else:
            start = today.replace(month=1, day=1)
        length = _offset(1, unit)
        step = {"this": 0, "last": -1, "next": 1}[which]
        start = start + step * length if step else start
        return start, start + length

    m = re.fullmatch(r"(last|next) (\d+) ([a-z]+)", low)
    if m:
        which, n, unit = m.groups()
        length = _offset(int(n), unit)
        if length is None:
            return None
        if which == "last":     # up to and including today
            end = _today() + day
            return end - length, end
        return _today(), _today() + length

    if re.fullmatch(r"[12]\d{3}", low):         # a year
        start = pd.Timestamp(int(low), 1, 1)
        return start, start + pd.DateOffset(years=1)
    if re.fullmatch(r"[12]\d{3}-\d{1,2}", low):  # a month, 2026-10
        start = pd.Timestamp(f"{low}-01")
        return start, start + pd.DateOffset(months=1)
    if _number(low) is not None:
        return None
    try:
        # ISO first: day-first parsing turns 2026-10-05 into 10 May.
        if re.match(r"\d{4}-\d{1,2}-\d{1,2}", low):
            when = pd.Timestamp(str(text).strip())
        else:
            when = pd.to_datetime(str(text).strip(), dayfirst=True)
    except (ValueError, TypeError, OverflowError):
        return None
    if when is pd.NaT:
        return None
    if ":" in low or when != when.normalize():
        return when, None
    return when, when + day


def _to_dates(cells):
    """A column of text as dates, read as `_date_span` reads a value;
    anything that isn't one becomes NaT."""
    import pandas as pd

    text = cells.where(cells.map(lambda v: isinstance(v, str)))
    iso = pd.to_datetime(text, errors="coerce", format="ISO8601")
    rest = pd.to_datetime(text.where(iso.isna()), errors="coerce",
                          dayfirst=True, format="mixed")
    others = pd.to_datetime(cells.where(text.isna()), errors="coerce")
    return iso.fillna(rest).fillna(others)


def _cell_text(v):
    """A cell as the text it shows, or None for a blank one."""
    import pandas as pd

    if isinstance(v, str):
        return v
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):  # a list in a cell
        pass
    # 3.0 reads as "3", as it does in the table, so "equals 3" finds it.
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)


def _as_value(v):
    """What a wired input says, as the text the Value box would hold."""
    import datetime

    if v is None:
        return ""
    if isinstance(v, str):
        return v
    if isinstance(v, (list, tuple, set, frozenset)) or (
            hasattr(v, "tolist") and not hasattr(v, "year")):
        items = v.tolist() if hasattr(v, "tolist") else list(v)
        if not isinstance(items, list):     # a numpy scalar
            return _as_value(items)
        return "\n".join(_as_value(item) for item in items)
    if isinstance(v, datetime.datetime):
        if (v.hour, v.minute, v.second, v.microsecond) == (0, 0, 0, 0) \
                and v.tzinfo is None:
            return v.strftime("%Y-%m-%d")
        return v.isoformat(sep=" ")
    if isinstance(v, datetime.date):
        return v.isoformat()
    return _cell_text(v) or ""


# --------------------------------------------------------------- the boxes

def _conditions_mask(table, text, case):
    """Every line of the Conditions box, each in Conditional Column's
    language; a row has to pass them all."""
    from flograph.core.conditions import parse_condition

    mask = None
    for lineno, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        groups = parse_condition(f"Conditions line {lineno}", line,
                                 table.columns)
        hit = None
        for group in groups:
            every = None
            for column, op, value, _quoted in group:
                one = _condition_mask(table, column, _OPERATORS[op],
                                      value or "", "", case)
                every = one if every is None else every & one
            hit = every if hit is None else hit | every
        mask = hit if mask is None else mask & hit
    return mask


def _query_mask(table, query):
    import re

    from flograph.core.column_refs import quote_bare_columns

    try:
        return table.eval(quote_bare_columns(query, table.columns))
    except Exception as exc:
        # re.error from Python's regex engine; pyarrow-backed strings say
        # "Invalid regular expression" in an ArrowInvalid instead.
        if not (isinstance(exc, re.error)
                or "regular expression" in str(exc).lower()):
            raise
        raise ValueError(
            f"The text in .str.contains(...) is read as a pattern, and it "
            f"isn't a valid one ({exc}). `contains` already matches anywhere, "
            f"so leave out * wildcards, or add regex=False to match the text "
            f"exactly — or clear the query and use Column, Match and Value.") from None


def _wired(v, column):
    """A wired table or column as its values; anything else as it is."""
    import pandas as pd

    if isinstance(v, pd.DataFrame):
        if column in v.columns:
            v = v[column]
        elif v.shape[1] == 1:
            v = v.iloc[:, 0]
        else:
            raise ValueError(
                f"A table wired into 'value' needs a column named {column!r} "
                f"or only one column; it has {v.shape[1]}")
    if isinstance(v, pd.Series):
        return v.dropna().unique().tolist()
    return v


def run(ctx, table, value=None, value_to=None):
    p = ctx.params
    match = p.get("match") or "contains"
    case = bool(p.get("case_sensitive"))
    column = str(p.get("column") or "").strip()
    value, value_to = _wired(value, column), _wired(value_to, column)
    # A wired input stands in for its box.
    low = (_as_value(value) if value is not None
           else str(p.get("value") or "")).strip()
    high = (_as_value(value_to) if value_to is not None
            else str(p.get("value_to") or "")).strip()
    conditions = str(p.get("conditions") or "").strip()
    query = str(p.get("query") or "").strip()

    masks = []
    # The dropdowns are on once they have a value to look for — or need none.
    if low or high or match in BLANK:
        masks.append(_condition_mask(table, column, match, low, high, case))
    if conditions:
        masks.append(_conditions_mask(table, conditions, case))
    if query:
        masks.append(_query_mask(table, query))
    masks = [m for m in masks if m is not None]
    if not masks:
        return {"filtered": table, "rejected": table.iloc[0:0]}
    mask = masks[0]
    for more in masks[1:]:
        mask = mask & more
    ctx.log(f"kept {int(mask.sum())} / {len(table)} rows")
    rejected = table[~mask] if p.get("keep_rejected", True) else table.iloc[0:0]
    return {"filtered": table[mask], "rejected": rejected}
