"""Option derivation for input controls — Qt-free, so the node scripts, the
engine's introspection and the widgets all agree on one answer.

A control that offers a list of things (a Choice dropdown, a Slicer) has to
answer "what are the options?" in two places: the widget, which asks before
a run so it has something to draw, and the node's run(), which validates
against them. Deriving that twice is how a dropdown ends up offering
something the node then rejects, so both go through here.
"""
from __future__ import annotations

from typing import Any, Optional


def lines_to_values(raw: Any) -> list[str]:
    """A newline-separated param as a list of values: blanks dropped,
    duplicates dropped, order preserved. Commas split too, since that is
    what people type into a one-line box."""
    text = str(raw or "")
    parts = text.splitlines() if "\n" in text else text.split(",")
    seen: set[str] = set()
    values: list[str] = []
    for part in parts:
        part = part.strip()
        if part and part not in seen:
            seen.add(part)
            values.append(part)
    return values


def values_from_source(source: Any,
                       column: str = "") -> Optional[list[str]]:
    """The options a connected upstream value offers, as sorted strings.

    Handles what actually turns up on a wire: a DataFrame (the named column,
    or its first), a Series, or any plain sequence — which is what a
    Slicer's "selected" output is, and what makes controls chain. None means
    there was nothing to derive from.

    Duck-typed rather than isinstance-checked so this stays free of a pandas
    import: core is loaded on every startup and pandas is not cheap.
    """
    if source is None:
        return None
    column = str(column or "").strip()
    if hasattr(source, "columns"):                      # DataFrame
        columns = list(source.columns)
        if not columns:
            return []
        picked = column if column in columns else columns[0]
        return sorted(source[picked].dropna().astype(str).unique())
    if hasattr(source, "dropna") and hasattr(source, "unique"):   # Series
        return sorted(source.dropna().astype(str).unique())
    if isinstance(source, (list, tuple, set, frozenset)):
        return sorted({str(v) for v in source})
    if isinstance(source, dict):
        return sorted(str(k) for k in source)
    return [str(source)]


# What a Date control's blank value means. "fixed" is the old behaviour:
# a blank shows (and emits) today. The others are relative to the day the
# flow runs, which is what a dashboard someone opens every morning wants —
# a typed date goes stale, "start of month" does not.
DATE_PRESETS = ["fixed", "today", "yesterday", "start of week",
                "start of month", "start of year", "days ago"]


def preset_date(preset: str, days: int = 0, today=None) -> str:
    """The ISO date a preset means on `today` (default: the real today);
    "" for "fixed", which is no preset at all."""
    import datetime

    today = today or datetime.date.today()
    if preset == "today":
        day = today
    elif preset == "yesterday":
        day = today - datetime.timedelta(days=1)
    elif preset == "start of week":
        day = today - datetime.timedelta(days=today.weekday())
    elif preset == "start of month":
        day = today.replace(day=1)
    elif preset == "start of year":
        day = today.replace(month=1, day=1)
    elif preset == "days ago":
        day = today - datetime.timedelta(days=max(0, int(days or 0)))
    else:
        return ""
    return day.isoformat()


def date_value(raw: Any, preset: str = "fixed", days: int = 0,
               allow_blank: bool = False) -> str:
    """A date param resolved to the ISO string that actually flows.

    A date somebody picked wins. A blank param is the "never touched"
    state, and a preset is what that state means — "start of month" on a
    control nobody has moved, which is what keeps a dashboard current
    without anyone editing it. Picking a day replaces it; Reset to Default
    (a blank again) brings the preset back. Deciding it this way round, not
    "preset wins", is what lets a hand-picked date stay picked: the widget
    can only ever write the value.

    With no preset, blank shows today — the picker can't display nothing —
    and resolving that here means the date on the card is the date
    downstream receives, instead of the card showing today while the node
    quietly emits "". With `allow_blank` the picker *can* show nothing
    ("No date"), so a blank stays blank.
    """
    import datetime

    text = str(raw or "").strip()[:10]
    if len(text) == 10:
        try:
            return datetime.date.fromisoformat(text).isoformat()
        except ValueError:
            pass
    relative = preset_date(preset, days)
    if relative:
        return relative
    if allow_blank:
        return ""
    return datetime.date.today().isoformat()


# The entry a Choice with "(All)" switched on puts first. Picking it emits
# "" — no choice made — which an Input Panel reads as "don't filter".
ALL_LABEL = "(All)"


def choice_value(raw: Any, options: Optional[list[str]],
                 all_option: bool = False) -> str:
    """A choice param resolved to what the dropdown is actually showing.

    Blank means "never picked", and a dropdown with options always has one
    highlighted — the first. Emitting "" while the card reads "north" is the
    kind of mismatch that makes a dashboard lie, so both land here. With
    `all_option` the first entry *is* "(All)", so blank stays blank.

    A stored value that is no longer offered is passed through unchanged:
    the widget keeps showing it (marked "not in list"), and silently
    swapping it for another value would change someone's dashboard under
    them.
    """
    value = str(raw or "")
    if value or all_option:
        return value
    return options[0] if options else ""


def cast_choice(value: str, value_type: str) -> Any:
    """A picked option as the type the Choice says it emits: text as is,
    or a number ("2024" -> 2024, "0.5" -> 0.5). A pick that isn't a number
    is passed through as text rather than refused, and blank stays blank."""
    if value_type != "number" or value in ("", None):
        return value
    try:
        number = float(value)
    except (TypeError, ValueError):
        return value
    return int(number) if number.is_integer() else number


def pattern_problem(value: Any, pattern: str, message: str = "") -> Optional[str]:
    """Why a Text control's value doesn't fit its pattern, or None. A
    pattern that is itself broken is reported as such — the author's
    mistake, said plainly, rather than every value being "wrong"."""
    import re

    pattern = str(pattern or "")
    text = str(value or "")
    if not pattern or not text:
        return None
    try:
        ok = re.fullmatch(pattern, text) is not None
    except re.error as exc:
        return f"the pattern {pattern!r} is not a valid regular expression ({exc})"
    if ok:
        return None
    return str(message or "").strip() or f"{text!r} does not match {pattern!r}"


def reduce_bound(source: Any, high: bool) -> Any:
    """One end of a range, from whatever came down a wire.

    A bare number or string is itself. A Series or DataFrame column is
    reduced — `.max()` for the upper bound, `.min()` for the lower — so
    wiring one date column into both a control's `minimum` and `maximum`
    pins its calendar to exactly the period the data covers, which is the
    whole point of letting bounds come from upstream. None when there is
    nothing usable.
    """
    if source is None:
        return None
    if hasattr(source, "columns"):                      # DataFrame
        columns = list(source.columns)
        if not columns:
            return None
        source = source[columns[0]]
    if hasattr(source, "dropna") and hasattr(source, "empty"):   # Series
        series = source.dropna()
        if series.empty:
            return None
        return series.max() if high else series.min()
    if isinstance(source, (list, tuple, set, frozenset)):
        values = [v for v in source if v is not None]
        if not values:
            return None
        return max(values) if high else min(values)
    return source


def as_number(value: Any, fallback: float) -> float:
    """A wired bound as a float, falling back when it isn't one — a bound
    that can't be read should leave the control usable, not break it."""
    if value is None or isinstance(value, bool):
        return fallback
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def as_iso_date(value: Any) -> str:
    """A wired date as "YYYY-MM-DD", or "" when it isn't one. Accepts what
    a date column actually yields — a Timestamp, a date, or a string."""
    if value is None:
        return ""
    text = getattr(value, "isoformat", lambda: str(value))()
    text = str(text).strip()[:10]
    if len(text) != 10:
        return ""
    import datetime
    try:
        return datetime.date.fromisoformat(text).isoformat()
    except ValueError:
        return ""


def range_values(raw: Any, low_default: float,
                 high_default: float) -> tuple:
    """A two-handled control's param as `(low, high)`.

    One control, two numbers, and a host that writes exactly one `value` —
    so the pair travels as JSON in that one param, the way a Slicer carries
    its ticked values. The shape decides what its value means; the host
    stays a host.

    Blank or unreadable is the "never touched" state and falls back to the
    bounds, so a fresh Between node spans its whole range instead of
    emitting a degenerate one. A reversed pair is put back in order rather
    than rejected: a range is the same range whichever handle was dragged
    past the other.
    """
    import json

    pair = None
    if isinstance(raw, (list, tuple)) and len(raw) == 2:
        pair = raw
    else:
        text = str(raw or "").strip()
        if text:
            try:
                parsed = json.loads(text)
                if isinstance(parsed, list) and len(parsed) == 2:
                    pair = parsed
            except ValueError:
                parts = [part.strip() for part in text.split(",")]
                if len(parts) == 2:
                    pair = parts
    if pair is None:
        return low_default, high_default
    low = as_number(pair[0], low_default)
    high = as_number(pair[1], high_default)
    return (low, high) if low <= high else (high, low)


def clamp(value: float, minimum: float, maximum: float) -> float:
    """Keep a control's value inside its range.

    This is what makes wired bounds double as a default: a control nobody
    has touched sits at whatever its param says, and clamping pulls that
    into the range the data actually covers — wire a column's max into a
    date picker and an untouched picker lands on the latest date you have.
    """
    if maximum < minimum:
        maximum = minimum
    return max(minimum, min(maximum, value))


def selected_values(raw: Any) -> list[str]:
    """The ticked values of a slicer-style "selected" param as strings: a
    JSON array normally (the widget writes that), falling back to a
    comma-separated list for hand edits."""
    import json

    text = str(raw or "").strip()
    if not text:
        return []
    try:
        parsed = json.loads(text)
    except ValueError:
        return [part.strip() for part in text.split(",") if part.strip()]
    if isinstance(parsed, list):
        return [str(v) for v in parsed]
    return [str(parsed)]


# ------------------------------------------------------------ date range

# What a Date Range's value can name instead of two dates. Relative, so a
# dashboard opened next month shows next month's "last 30 days" without
# anybody editing it; "whole range" is every day between the bounds (wired
# from a date column, typically). The value is either one of these or a
# picked [start, end] pair, and the card writes whichever the user chose.
RANGE_PRESETS = ["last 7 days", "last 30 days", "last 90 days",
                 "this month", "last month", "year to date", "whole range"]
CUSTOM_RANGE = "custom"


def date_range_values(raw: Any, low: str = "", high: str = "",
                      today=None) -> tuple:
    """A Date Range's value as `(preset or "custom", start, end)`, ISO
    strings clamped into `low`..`high` (either may be "" for unbounded).

    Blank or unreadable falls back to "last 30 days", which is also what a
    fresh control starts on — the window most dashboards open with.
    """
    import datetime
    import json

    today = today or datetime.date.today()
    text = str(raw or "").strip()
    preset, pair = "", None
    if text in RANGE_PRESETS:
        preset = text
    elif text:
        try:
            parsed = json.loads(text)
            if isinstance(parsed, list) and len(parsed) == 2:
                pair = [as_iso_date(parsed[0]), as_iso_date(parsed[1])]
        except ValueError:
            pass
    if pair is None or not all(pair):
        preset = preset or "last 30 days"
        start, end = _preset_window(preset, today, low, high)
    else:
        start, end = sorted(pair)
    if low:
        start, end = max(start, low), max(end, low)
    if high:
        start, end = min(start, high), min(end, high)
    return (preset or CUSTOM_RANGE), start, end


def _preset_window(preset: str, today, low: str, high: str) -> tuple:
    import datetime

    def iso(day):
        return day.isoformat()

    if preset in ("last 7 days", "last 30 days", "last 90 days"):
        days = int(preset.split()[1])
        return iso(today - datetime.timedelta(days=days - 1)), iso(today)
    if preset == "this month":
        return iso(today.replace(day=1)), iso(today)
    if preset == "last month":
        end = today.replace(day=1) - datetime.timedelta(days=1)
        return iso(end.replace(day=1)), iso(end)
    if preset == "year to date":
        return iso(today.replace(month=1, day=1)), iso(today)
    # whole range: the bounds, or the default window where there are none
    if low and high:
        return low, high
    start = iso(today - datetime.timedelta(days=29))
    return (low or start), (high or iso(today))


# ------------------------------------------------------------ multi choice

def multi_values(raw: Any, options: Optional[list[str]],
                 none_means: str = "all") -> list[str]:
    """What a Multi Choice emits: the ticked values, in the options' order
    (a stored pick no longer offered is kept, at the end — the same rule as
    a Choice). Nothing ticked means every option when `none_means` is
    "all", which is how "no filter yet" reads on a dashboard, and an empty
    list when it is "nothing"."""
    picked = selected_values(raw)
    if not picked:
        return list(options or []) if none_means == "all" else []
    order = {v: i for i, v in enumerate(options or [])}
    return sorted(picked, key=lambda v: (v not in order, order.get(v, 0)))


# ------------------------------------------------------------ time, colour

def time_value(raw: Any) -> str:
    """A time param as "HH:MM", or "00:00" when it can't be read — a time
    picker always shows a time, so the flow always gets the one shown."""
    text = str(raw or "").strip()
    parts = text.split(":")
    try:
        hours, minutes = int(parts[0]), int(parts[1]) if len(parts) > 1 else 0
    except (ValueError, IndexError):
        return "00:00"
    if not (0 <= hours < 24 and 0 <= minutes < 60):
        return "00:00"
    return f"{hours:02d}:{minutes:02d}"


def datetime_value(raw: Any) -> str:
    """A date-and-time param as "YYYY-MM-DDTHH:MM" — ISO, so it compares
    against a pandas datetime column as it is. Blank means midnight today:
    a fixed point in the day, so the card and the run agree on it."""
    import datetime

    text = str(raw or "").strip().replace(" ", "T")
    try:
        moment = datetime.datetime.fromisoformat(text[:16])
    except ValueError:
        moment = datetime.datetime.combine(datetime.date.today(),
                                           datetime.time())
    return moment.strftime("%Y-%m-%dT%H:%M")


def colour_value(raw: Any, fallback: str = "#3b82f6") -> str:
    """A colour param as lower-case "#rrggbb". Short hex and a missing # are
    tidied; anything else is the fallback rather than an invalid colour."""
    import re

    text = str(raw or "").strip().lower()
    if text and not text.startswith("#"):
        text = "#" + text
    if re.fullmatch(r"#[0-9a-f]{3}", text):
        text = "#" + "".join(c * 2 for c in text[1:])
    return text if re.fullmatch(r"#[0-9a-f]{6}", text) else fallback
