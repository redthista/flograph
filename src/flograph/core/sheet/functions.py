"""Curated spreadsheet function library.

Functions receive their arguments already evaluated; a range argument
arrives as a flat list of cell values. Aggregates (SUM, AVERAGE, ...)
count numbers across scalars and ranges — numeric text and bools count,
blanks and other text are skipped, matching how Excel treats ranges.
Any error value among the arguments propagates out unchanged.
"""
from __future__ import annotations

import math

from .values import (ERR_DIV0, ERR_NAME, ERR_NUM, ERR_VALUE, FormulaError,
                     to_bool, to_number, to_text)


def _flat(args):
    for arg in args:
        if isinstance(arg, list):
            yield from arg
        else:
            yield arg


def _first_error(args):
    for value in _flat(args):
        if isinstance(value, FormulaError):
            return value
    return None


def _numbers(args) -> list[float]:
    out = []
    for value in _flat(args):
        if value is None:
            continue
        if isinstance(value, bool):
            out.append(1.0 if value else 0.0)
        elif isinstance(value, (int, float)):
            out.append(float(value))
        elif isinstance(value, str):
            try:
                out.append(float(value.strip()))
            except ValueError:
                pass   # plain text is skipped, like Excel ranges
    return out


def _number_arg(args, index, default=None):
    """One scalar numeric argument (or the default when absent)."""
    if index >= len(args):
        return default
    value = args[index]
    if isinstance(value, list):
        return FormulaError(ERR_VALUE, "expected a single value, got a range")
    return to_number(value)


def _text_arg(args, index, default=""):
    if index >= len(args):
        return default
    value = args[index]
    if isinstance(value, list):
        return FormulaError(ERR_VALUE, "expected a single value, got a range")
    return to_text(value)


# ------------------------------------------------------------- aggregates

def _fn_sum(args):
    return float(sum(_numbers(args)))


def _fn_average(args):
    numbers = _numbers(args)
    if not numbers:
        return FormulaError(ERR_DIV0, "AVERAGE of no numbers")
    return sum(numbers) / len(numbers)


def _fn_min(args):
    numbers = _numbers(args)
    return min(numbers) if numbers else 0.0


def _fn_max(args):
    numbers = _numbers(args)
    return max(numbers) if numbers else 0.0


def _fn_count(args):
    return float(len(_numbers(args)))


def _fn_counta(args):
    return float(sum(1 for v in _flat(args) if v is not None and v != ""))


# ------------------------------------------------------------------- math

def _fn_round(args):
    x = _number_arg(args, 0)
    digits = _number_arg(args, 1, 0.0)
    for v in (x, digits):
        if isinstance(v, FormulaError):
            return v
    factor = 10.0 ** int(digits)
    scaled = x * factor
    # Excel rounds halves away from zero (Python's round() goes to even)
    rounded = math.floor(abs(scaled) + 0.5) * (1 if scaled >= 0 else -1)
    return rounded / factor


def _fn_abs(args):
    x = _number_arg(args, 0)
    return x if isinstance(x, FormulaError) else abs(x)


def _fn_sqrt(args):
    x = _number_arg(args, 0)
    if isinstance(x, FormulaError):
        return x
    if x < 0:
        return FormulaError(ERR_NUM, "SQRT of a negative number")
    return math.sqrt(x)


def _fn_power(args):
    a, b = _number_arg(args, 0), _number_arg(args, 1)
    for v in (a, b):
        if isinstance(v, FormulaError):
            return v
    try:
        result = a ** b
    except ZeroDivisionError:
        return FormulaError(ERR_DIV0, "zero to a negative power")
    except (OverflowError, ValueError):
        return FormulaError(ERR_NUM)
    if isinstance(result, complex):
        return FormulaError(ERR_NUM, "negative base with a fractional exponent")
    return float(result)


def _fn_mod(args):
    a, b = _number_arg(args, 0), _number_arg(args, 1)
    for v in (a, b):
        if isinstance(v, FormulaError):
            return v
    if b == 0:
        return FormulaError(ERR_DIV0, "MOD by zero")
    return a - b * math.floor(a / b)   # sign follows the divisor, like Excel


def _fn_floor(args):
    x = _number_arg(args, 0)
    sig = _number_arg(args, 1, 1.0)
    for v in (x, sig):
        if isinstance(v, FormulaError):
            return v
    if sig == 0:
        return FormulaError(ERR_DIV0, "FLOOR significance of zero")
    return math.floor(x / sig) * sig


def _fn_ceiling(args):
    x = _number_arg(args, 0)
    sig = _number_arg(args, 1, 1.0)
    for v in (x, sig):
        if isinstance(v, FormulaError):
            return v
    if sig == 0:
        return FormulaError(ERR_DIV0, "CEILING significance of zero")
    return math.ceil(x / sig) * sig


# ------------------------------------------------------------------- text

def _fn_concat(args):
    parts = []
    for value in _flat(args):
        text = to_text(value)
        if isinstance(text, FormulaError):
            return text
        parts.append(text)
    return "".join(parts)


def _fn_len(args):
    text = _text_arg(args, 0)
    return text if isinstance(text, FormulaError) else float(len(text))


def _fn_upper(args):
    text = _text_arg(args, 0)
    return text if isinstance(text, FormulaError) else text.upper()


def _fn_lower(args):
    text = _text_arg(args, 0)
    return text if isinstance(text, FormulaError) else text.lower()


def _fn_trim(args):
    text = _text_arg(args, 0)
    if isinstance(text, FormulaError):
        return text
    return " ".join(text.split())   # Excel TRIM also collapses inner runs


def _fn_left(args):
    text = _text_arg(args, 0)
    count = _number_arg(args, 1, 1.0)
    for v in (text, count):
        if isinstance(v, FormulaError):
            return v
    if count < 0:
        return FormulaError(ERR_VALUE, "LEFT count must be >= 0")
    return text[:int(count)]


def _fn_right(args):
    text = _text_arg(args, 0)
    count = _number_arg(args, 1, 1.0)
    for v in (text, count):
        if isinstance(v, FormulaError):
            return v
    if count < 0:
        return FormulaError(ERR_VALUE, "RIGHT count must be >= 0")
    count = int(count)
    return text[-count:] if count else ""


def _fn_mid(args):
    text = _text_arg(args, 0)
    start = _number_arg(args, 1)
    length = _number_arg(args, 2)
    for v in (text, start, length):
        if isinstance(v, FormulaError):
            return v
    if start < 1:
        return FormulaError(ERR_VALUE, "MID start position is 1-based")
    if length < 0:
        return FormulaError(ERR_VALUE, "MID length must be >= 0")
    start, length = int(start), int(length)
    return text[start - 1:start - 1 + length]


# ---------------------------------------------------------------- logical

def _fn_and(args):
    result = True
    for value in _flat(args):
        if value is None:
            continue
        flag = to_bool(value)
        if isinstance(flag, FormulaError):
            return flag
        result = result and flag
    return result


def _fn_or(args):
    result = False
    for value in _flat(args):
        if value is None:
            continue
        flag = to_bool(value)
        if isinstance(flag, FormulaError):
            return flag
        result = result or flag
    return result


def _fn_not(args):
    flag = to_bool(args[0]) if not isinstance(args[0], list) else FormulaError(
        ERR_VALUE, "expected a single value, got a range")
    return flag if isinstance(flag, FormulaError) else not flag


# name -> (implementation, min args, max args or None for unlimited)
FUNCTIONS = {
    "SUM": (_fn_sum, 1, None),
    "AVERAGE": (_fn_average, 1, None),
    "AVG": (_fn_average, 1, None),
    "MIN": (_fn_min, 1, None),
    "MAX": (_fn_max, 1, None),
    "COUNT": (_fn_count, 1, None),
    "COUNTA": (_fn_counta, 1, None),
    "ROUND": (_fn_round, 1, 2),
    "ABS": (_fn_abs, 1, 1),
    "SQRT": (_fn_sqrt, 1, 1),
    "POWER": (_fn_power, 2, 2),
    "MOD": (_fn_mod, 2, 2),
    "FLOOR": (_fn_floor, 1, 2),
    "CEILING": (_fn_ceiling, 1, 2),
    "CONCAT": (_fn_concat, 1, None),
    "LEN": (_fn_len, 1, 1),
    "UPPER": (_fn_upper, 1, 1),
    "LOWER": (_fn_lower, 1, 1),
    "TRIM": (_fn_trim, 1, 1),
    "LEFT": (_fn_left, 1, 2),
    "RIGHT": (_fn_right, 1, 2),
    "MID": (_fn_mid, 3, 3),
    "AND": (_fn_and, 1, None),
    "OR": (_fn_or, 1, None),
    "NOT": (_fn_not, 1, 1),
}

FUNCTION_NAMES = tuple(sorted([*FUNCTIONS, "IF"]))   # IF lives in the evaluator

# (name, signature, what it does, example) — shown in the editor's formula
# reference; keep in step with FUNCTIONS + the evaluator's IF
FUNCTION_HELP = (
    ("SUM", "SUM(values…)", "Adds numbers; text and blanks in ranges are skipped.", "=SUM(A1:A10)"),
    ("AVERAGE", "AVERAGE(values…)", "Mean of the numbers (AVG works too).", "=AVERAGE(B1:B5)"),
    ("MIN", "MIN(values…)", "Smallest number.", "=MIN(A1:A10)"),
    ("MAX", "MAX(values…)", "Largest number.", "=MAX(A1:A10)"),
    ("COUNT", "COUNT(values…)", "How many values are numbers.", "=COUNT(A1:A10)"),
    ("COUNTA", "COUNTA(values…)", "How many cells aren't blank.", "=COUNTA(A1:A10)"),
    ("IF", "IF(condition, then, [else])", "Picks a value by condition; only the taken branch is evaluated.", '=IF(A1>10, "big", "small")'),
    ("AND", "AND(conditions…)", "TRUE when every condition is true.", "=AND(A1>0, B1>0)"),
    ("OR", "OR(conditions…)", "TRUE when any condition is true.", "=OR(A1>0, B1>0)"),
    ("NOT", "NOT(condition)", "Flips TRUE/FALSE.", "=NOT(A1=B1)"),
    ("ROUND", "ROUND(x, [digits])", "Rounds, halves away from zero.", "=ROUND(A1, 2)"),
    ("ABS", "ABS(x)", "Absolute value.", "=ABS(A1-B1)"),
    ("SQRT", "SQRT(x)", "Square root.", "=SQRT(A1)"),
    ("POWER", "POWER(base, exp)", "base raised to exp (same as ^).", "=POWER(A1, 2)"),
    ("MOD", "MOD(x, divisor)", "Remainder; its sign follows the divisor.", "=MOD(A1, 3)"),
    ("FLOOR", "FLOOR(x, [step])", "Rounds down to a multiple of step.", "=FLOOR(A1, 5)"),
    ("CEILING", "CEILING(x, [step])", "Rounds up to a multiple of step.", "=CEILING(A1, 5)"),
    ("CONCAT", "CONCAT(values…)", "Glues values into one text (same as &).", '=CONCAT(A1, " ", B1)'),
    ("LEN", "LEN(text)", "Number of characters.", "=LEN(A1)"),
    ("UPPER", "UPPER(text)", "UPPERCASE.", "=UPPER(A1)"),
    ("LOWER", "LOWER(text)", "lowercase.", "=LOWER(A1)"),
    ("TRIM", "TRIM(text)", "Strips outer spaces, collapses inner runs.", "=TRIM(A1)"),
    ("LEFT", "LEFT(text, [n])", "First n characters.", "=LEFT(A1, 3)"),
    ("RIGHT", "RIGHT(text, [n])", "Last n characters.", "=RIGHT(A1, 3)"),
    ("MID", "MID(text, start, length)", "length characters from a 1-based start.", "=MID(A1, 2, 3)"),
)


def call_function(name: str, args: list):
    """Dispatch an already-evaluated argument list to a library function."""
    entry = FUNCTIONS.get(name.upper())
    if entry is None:
        return FormulaError(ERR_NAME, f"unknown function {name.upper()}")
    fn, lo, hi = entry
    if len(args) < lo or (hi is not None and len(args) > hi):
        expected = str(lo) if hi == lo else (
            f"at least {lo}" if hi is None else f"{lo}-{hi}")
        return FormulaError(
            ERR_VALUE,
            f"{name.upper()} expects {expected} argument(s), got {len(args)}")
    error = _first_error(args)
    if error is not None:
        return error
    return fn(args)
