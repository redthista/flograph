"""Value model shared by the formula engine and its function library.

Formula values are ``float | str | bool | None`` (``None`` is a blank cell).
Errors travel as :class:`FormulaError` instances so they can flow through
operators and functions the way Excel error codes do.
"""
from __future__ import annotations

ERR_VALUE = "#VALUE!"
ERR_DIV0 = "#DIV/0!"
ERR_NAME = "#NAME?"
ERR_REF = "#REF!"
ERR_CYCLE = "#CYCLE!"
ERR_NUM = "#NUM!"
ERR_SYNTAX = "#ERROR!"

ERROR_CODES = (ERR_VALUE, ERR_DIV0, ERR_NAME, ERR_REF, ERR_CYCLE,
               ERR_NUM, ERR_SYNTAX)


class FormulaError:
    """An Excel-style error code travelling through evaluation as a value."""

    __slots__ = ("code", "detail")

    def __init__(self, code: str, detail: str = "") -> None:
        self.code = code
        self.detail = detail

    def __repr__(self) -> str:
        return f"FormulaError({self.code!r})"

    def __eq__(self, other: object) -> bool:
        return isinstance(other, FormulaError) and other.code == self.code

    def __hash__(self) -> int:
        return hash(self.code)


def is_error(value: object) -> bool:
    return isinstance(value, FormulaError)


def to_number(value):
    """Coerce to float: blank is 0, bools are 1/0, numeric text counts,
    other text is #VALUE!."""
    if isinstance(value, FormulaError):
        return value
    if value is None:
        return 0.0
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return FormulaError(ERR_VALUE, f"{value!r} is not a number")
    return FormulaError(ERR_VALUE)


def to_text(value) -> str | FormulaError:
    """Coerce to display/concat text: blank is "", TRUE/FALSE for bools,
    numbers without float noise."""
    if isinstance(value, FormulaError):
        return value
    if value is None:
        return ""
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float)):
        return format_number(float(value))
    return str(value)


def to_bool(value):
    """Coerce to bool: blank is FALSE, numbers by non-zero, TRUE/FALSE text."""
    if isinstance(value, FormulaError):
        return value
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        word = value.strip().upper()
        if word == "TRUE":
            return True
        if word == "FALSE":
            return False
        return FormulaError(ERR_VALUE, f"{value!r} is not TRUE/FALSE")
    return FormulaError(ERR_VALUE)


def format_number(value: float) -> str:
    """Shortest clean text for a float: 5.0 -> "5", 0.1 + 0.2 -> "0.3"."""
    if value != value:
        return "NaN"
    if value in (float("inf"), float("-inf")):
        return "inf" if value > 0 else "-inf"
    rounded = round(value, 10)  # hide binary-float noise like 31.500000000000004
    if rounded == int(rounded) and abs(rounded) < 1e16:
        return str(int(rounded))
    return repr(rounded)


def format_value(value) -> str:
    """Display text for any computed cell value (errors show their code)."""
    if isinstance(value, FormulaError):
        return value.code
    text = to_text(value)
    return text if isinstance(text, str) else str(text)


class RangeValue(list):
    """A range argument: its cells row by row, and how many columns wide it
    is — so a function like VLOOKUP or INDEX can read rows and columns.
    Everything else sees the flat list it always did."""

    # `memo` is a dict while one evaluation shares this range between many
    # formulas (core/sheet/engine.py): SUMIF, COUNTIF and the lookups keep
    # their indexes of it there. None for a range made for one call.
    __slots__ = ("cols", "memo")

    def __init__(self, values=(), cols: int = 1) -> None:
        super().__init__(values)
        self.cols = max(int(cols), 1)
        self.memo = None

    @property
    def rows(self) -> int:
        return len(self) // self.cols if self.cols else 0

    def at(self, row: int, col: int):
        return self[row * self.cols + col]

    def row(self, row: int) -> list:
        return self[row * self.cols:(row + 1) * self.cols]

    def column(self, col: int) -> list:
        return self[col::self.cols]


_as_date_cache: dict = {}


def clear_date_cache() -> None:
    _as_date_cache.clear()


def as_date(value):
    """A text value that reads as a date, as a datetime; else None. Numbers
    are never dates here — the grid keeps dates as text (2026-10-07), and a
    number that happened to look like one would be a surprise."""
    if not isinstance(value, str):
        return None
    try:
        return _as_date_cache[value]
    except KeyError:
        pass
    result = _as_date(value)
    if len(_as_date_cache) >= 50_000:
        _as_date_cache.clear()
    _as_date_cache[value] = result      # a datetime never changes
    return result


def _as_date(value: str):
    text = value.strip()
    if not 6 <= len(text) <= 40 or not any(ch.isdigit() for ch in text):
        return None
    from datetime import datetime
    from .schema import normalize_date
    iso = normalize_date(text)
    if iso is None:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(iso, fmt)
        except ValueError:
            continue
    return None


def date_text(moment, keep_time: bool = False) -> str:
    """A datetime as the grid writes dates: 2026-10-07, with the time only
    when there is one to keep."""
    if keep_time and (moment.hour or moment.minute or moment.second):
        return moment.strftime("%Y-%m-%d %H:%M:%S")
    return moment.strftime("%Y-%m-%d")
