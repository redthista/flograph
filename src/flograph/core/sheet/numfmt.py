"""Number formats for a Table column — how a value *reads*, never what it
is. Qt-free.

A format is a small dict stored on the column (`ColumnSpec.format`):

    {"kind": "number",   "decimals": 2, "thousands": True,
     "negative": "minus" | "red" | "parens" | "red_parens"}
    {"kind": "currency", "symbol": "£", "decimals": 2, "negative": ...}
    {"kind": "percent",  "decimals": 0}
    {"kind": "scientific", "decimals": 2}
    {"kind": "date",     "pattern": "%d %b %Y"}

No format (or kind "general") is the grid as it always was. The value the
cell holds, what formulas see and what the Table sends down the flow are
untouched: Excel's rule, and the only one under which a format can be
changed at any time without losing anything.

`format_value_as` turns a computed value into display text (and says
whether it should be red); `parse_typed` lets a formatted column take what
its format looks like — "£1,200" or "25%" typed into the cell becomes 1200
or 0.25, as in Excel.
"""
from __future__ import annotations

import math
import re
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

KINDS = ("general", "number", "currency", "percent", "scientific", "date")
NEGATIVES = ("minus", "red", "parens", "red_parens")

# (label, strftime pattern) — what the Date list offers, as it reads for
# 7 October 2026
DATE_PATTERNS = (
    ("2026-10-07", "%Y-%m-%d"),
    ("07/10/2026", "%d/%m/%Y"),
    ("10/07/2026", "%m/%d/%Y"),
    ("7 Oct 2026", "%-d %b %Y"),
    ("07-Oct-26", "%d-%b-%y"),
    ("7 October 2026", "%-d %B %Y"),
    ("Wednesday, 7 October 2026", "%A, %-d %B %Y"),
    ("Oct 2026", "%b %Y"),
    ("2026-10-07 14:30", "%Y-%m-%d %H:%M"),
)


def clean(fmt) -> Optional[dict]:
    """A stored format made safe to use, or None for "general"."""
    if not isinstance(fmt, dict):
        return None
    kind = fmt.get("kind")
    if kind not in KINDS or kind == "general":
        return None
    out: dict = {"kind": kind}
    if kind in ("number", "currency", "percent", "scientific"):
        decimals = fmt.get("decimals", 2 if kind != "percent" else 0)
        try:
            decimals = int(decimals)
        except (TypeError, ValueError):
            decimals = 2
        out["decimals"] = max(0, min(decimals, 10))
    if kind in ("number", "currency"):
        out["thousands"] = bool(fmt.get("thousands", kind == "currency"))
        negative = fmt.get("negative", "minus")
        out["negative"] = negative if negative in NEGATIVES else "minus"
    if kind == "currency":
        out["symbol"] = str(fmt.get("symbol") or "$")[:4]
    if kind == "date":
        pattern = fmt.get("pattern")
        out["pattern"] = pattern if isinstance(pattern, str) and pattern \
            else "%Y-%m-%d"
    return out


def _strftime(moment: datetime, pattern: str) -> str:
    """strftime, with `%-d` (day without its zero) working everywhere —
    Windows' C library does not know the dash."""
    pattern = pattern.replace("%-d", str(moment.day)).replace(
        "%-m", str(moment.month))
    return moment.strftime(pattern)


def _as_datetime(value) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str) or not value.strip():
        return None
    from .schema import normalize_date
    iso = normalize_date(value)
    if iso is None:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(iso, fmt)
        except ValueError:
            continue
    return None


def _number(value) -> Optional[float]:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value) if math.isfinite(value) else None
    if isinstance(value, str):
        try:
            number = float(value.strip())
        except ValueError:
            return None
        return number if math.isfinite(number) else None
    return None


def _rounded(number: float, decimals: int) -> Decimal:
    """`number` to `decimals` places, halves away from zero — Excel's rule.
    Python's own formatting rounds halves to even, so 1234.5 would read
    1234 at no decimals where Excel shows 1235."""
    quantum = Decimal(1).scaleb(-decimals)
    return Decimal(repr(number)).quantize(quantum, rounding=ROUND_HALF_UP)


def format_value_as(value, fmt) -> Optional[tuple[str, bool]]:
    """(text, red) for `value` under `fmt`, or None when the format does not
    apply to it (no format, text in a number column, an error) and the cell
    shows as it would anyway."""
    fmt = clean(fmt)
    if fmt is None:
        return None
    kind = fmt["kind"]
    if kind == "date":
        moment = _as_datetime(value)
        return (_strftime(moment, fmt["pattern"]), False) if moment else None
    number = _number(value)
    if number is None:
        return None
    decimals = fmt["decimals"]
    if kind == "percent":
        return f"{_rounded(number * 100, decimals):.{decimals}f}%", False
    if kind == "scientific":
        mantissa = f"{number:.{decimals}E}"
        return mantissa.replace("E+0", "E+").replace("E-0", "E-"), False
    magnitude = _rounded(abs(number), decimals)
    body = f"{magnitude:,.{decimals}f}" if fmt["thousands"] \
        else f"{magnitude:.{decimals}f}"
    if kind == "currency":
        body = fmt["symbol"] + body
    negative = number < 0 and magnitude != 0
    if not negative:
        return body, False
    style = fmt["negative"]
    if style in ("parens", "red_parens"):
        return f"({body})", style == "red_parens"
    return f"-{body}", style == "red"


_SEPARATORS = re.compile(r"[,\s]")


def parse_typed(text: str, fmt) -> str:
    """What to store when `text` is typed into a cell of a formatted
    column: "£1,200" → "1200", "25%" → "0.25", "(40)" → "-40". Anything
    that doesn't read as a number under the format comes back as typed."""
    fmt = clean(fmt)
    if fmt is None or fmt["kind"] not in ("number", "currency", "percent"):
        return text
    raw = text.strip()
    if not raw or raw.startswith("="):
        return text
    negative = raw.startswith("(") and raw.endswith(")")
    if negative:
        raw = raw[1:-1].strip()
    percent = raw.endswith("%")
    if percent:
        raw = raw[:-1].strip()
    if fmt["kind"] == "currency":
        symbol = fmt["symbol"]
        if raw.startswith("-" + symbol):
            raw = "-" + raw[1 + len(symbol):]
        elif raw.startswith(symbol):
            raw = raw[len(symbol):]
    raw = _SEPARATORS.sub("", raw)
    try:
        number = float(raw)
    except ValueError:
        return text
    if not math.isfinite(number):
        return text
    if negative:
        number = -number
    if percent or (fmt["kind"] == "percent" and "%" in text):
        number /= 100
    if number.is_integer() and "." not in raw and not percent:
        return str(int(number))
    return repr(number)


def describe(fmt) -> str:
    """A short name for a format, for menus and tooltips."""
    fmt = clean(fmt)
    if fmt is None:
        return "General"
    kind = fmt["kind"]
    if kind == "date":
        sample = datetime(2026, 10, 7, 14, 30)
        return f"Date ({_strftime(sample, fmt['pattern'])})"
    sample = format_value_as(-1234.5678 if kind in ("number", "currency")
                             else 0.1234 if kind == "percent" else 1234.5678,
                             fmt)[0]
    return f"{kind.capitalize()} ({sample})"


def step_decimals(fmt, delta: int, shown: Optional[str] = None) -> dict:
    """Excel's Increase/Decrease Decimal: one more or fewer place. From
    General it starts from how many places the value shows now."""
    current = clean(fmt)
    if current is None or current["kind"] == "date":
        places = 0
        if shown and "." in shown:
            places = len(shown.split(".", 1)[1].rstrip("%"))
        current = {"kind": "number", "decimals": places, "thousands": False,
                   "negative": "minus"}
    out = dict(current)
    out["decimals"] = max(0, min(int(out.get("decimals", 0)) + delta, 10))
    return out
