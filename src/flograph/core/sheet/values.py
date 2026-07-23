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
