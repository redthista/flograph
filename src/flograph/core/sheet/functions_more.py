"""The rest of the function library: lookups, conditional aggregates, the
IS… checks and IFERROR, more maths, text and dates — the functions people
reach for first after SUM.

Registered into `functions.FUNCTIONS` by that module, so a formula finds
them exactly as it finds SUM. Behaviour follows Excel's wherever Excel has
one to follow, including its defaults (VLOOKUP's fourth argument defaults to
an approximate match, as in Excel; XLOOKUP's to exact).

Dates are text in the grid (2026-10-07), so date functions take any text
that reads as a date and give back ISO text — which the grid shows as a
date, and a date column's format can dress.

`LENIENT` names the functions that are handed error values instead of
having the first one returned for them: IFERROR has to see the error to
replace it, and a lookup should not fail because some *other* row of the
table holds one.
"""
from __future__ import annotations

import calendar
import math
import re
import statistics
from datetime import date, datetime, timedelta

from .functions import _flat, _number_arg, _numbers, _text_arg
from .values import (ERR_DIV0, ERR_NUM, ERR_VALUE, FormulaError, RangeValue,
                     as_date, date_text, format_number, to_bool, to_number,
                     to_text)

ERR_NA = "#N/A"


def _na(detail: str = "") -> FormulaError:
    return FormulaError(ERR_NA, detail or "no match found")


def _arg(args, index, default=None):
    return args[index] if index < len(args) else default


def _scalar(value):
    """A single value from what may be a one-cell range."""
    if isinstance(value, list):
        return value[0] if len(value) == 1 else FormulaError(
            ERR_VALUE, "expected a single value, got a range")
    return value


def _as_list(value) -> list:
    return list(value) if isinstance(value, list) else [value]


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


# --------------------------------------------------------------- matching

def _same(a, b) -> bool:
    """Equality the way a lookup means it: numbers by value, text without
    regard to case, dates as dates."""
    if isinstance(a, FormulaError) or isinstance(b, FormulaError):
        return False
    if _is_number(a) and _is_number(b):
        return float(a) == float(b)
    if isinstance(a, bool) or isinstance(b, bool):
        return a is b or (isinstance(a, bool) and isinstance(b, bool)
                          and a == b)
    if isinstance(a, str) and isinstance(b, str):
        if a.casefold() == b.casefold():
            return True
        da, db = as_date(a), as_date(b)
        return da is not None and da == db
    if a is None or b is None:
        return (a in (None, "")) and (b in (None, ""))
    return False


def _wildcard(pattern: str) -> re.Pattern:
    """Excel's wildcards: * any run, ? one character, ~ escapes either."""
    out, i = [], 0
    while i < len(pattern):
        ch = pattern[i]
        if ch == "~" and i + 1 < len(pattern) and pattern[i + 1] in "*?~":
            out.append(re.escape(pattern[i + 1]))
            i += 2
            continue
        out.append(".*" if ch == "*" else "." if ch == "?" else re.escape(ch))
        i += 1
    return re.compile("^" + "".join(out) + "$", re.IGNORECASE | re.DOTALL)


def _order_key(value):
    """(kind, key) for ordering mixed values: numbers, then text, then
    bools — Excel's order for MATCH and the approximate lookups."""
    if _is_number(value):
        return (0, float(value))
    if isinstance(value, str):
        moment = as_date(value)
        if moment is not None:
            return (0.5, moment)
        return (1, value.casefold())
    if isinstance(value, bool):
        return (2, value)
    return (3, 0)


def _criterion(crit):
    """A COUNTIF-style criterion as a predicate: 5, "North", ">5", "<>x",
    "=", "<>", "N*", ">=2026-01-01"."""
    if isinstance(crit, FormulaError):
        return None
    if crit is None:
        return lambda v: v in (None, "")
    if isinstance(crit, bool):
        return lambda v: isinstance(v, bool) and v == crit
    if _is_number(crit):
        target = float(crit)
        return lambda v: (_is_number(v) and float(v) == target) or (
            isinstance(v, str) and _maybe_number(v) == target)
    text = str(crit)
    op = ""
    for candidate in ("<=", ">=", "<>", "<", ">", "="):
        if text.startswith(candidate):
            op, text = candidate, text[len(candidate):]
            break
    number = _maybe_number(text)
    moment = as_date(text)
    if op in ("<", "<=", ">", ">="):
        def compare(x, y):
            return {"<": x < y, "<=": x <= y, ">": x > y, ">=": x >= y}[op]
        if number is not None:
            return lambda v: _is_number(v) and compare(float(v), number)
        if moment is not None:
            return lambda v: (as_date(v) is not None
                              and compare(as_date(v), moment))
        low = text.casefold()
        return lambda v: isinstance(v, str) and compare(v.casefold(), low)
    if text == "":
        if op == "<>":
            return lambda v: v not in (None, "")
        return lambda v: v in (None, "")

    def equals(v) -> bool:
        if number is not None and _is_number(v):
            return float(v) == number
        if moment is not None and isinstance(v, str):
            other = as_date(v)
            if other is not None:
                return other == moment
        if isinstance(v, bool):
            return text.upper() == ("TRUE" if v else "FALSE")
        if v is None:
            return False
        shown = format_number(float(v)) if _is_number(v) else str(v)
        if "*" in text or "?" in text:
            return bool(_wildcard(text).match(shown))
        return shown.casefold() == text.casefold()

    if op == "<>":
        return lambda v: not equals(v)
    return equals


def _maybe_number(text):
    try:
        number = float(str(text).strip())
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _pairs(args, start: int):
    """(range, predicate) pairs from criteria arguments laid out as range,
    criterion, range, criterion…"""
    pairs = []
    rest = args[start:]
    if len(rest) % 2:
        return FormulaError(ERR_VALUE, "criteria come in pairs: "
                                       "range, criterion")
    for i in range(0, len(rest), 2):
        rng = _as_list(rest[i])
        test = _criterion(_scalar(rest[i + 1]))
        if test is None:
            return rest[i + 1]
        pairs.append((rng, test))
    return pairs


def _matching(pairs, length: int) -> list[int]:
    for rng, _test in pairs:
        if len(rng) != length:
            raise ValueError("the ranges must be the same size")
    return [i for i in range(length)
            if all(test(rng[i]) for rng, test in pairs)]


# ------------------------------------------------------ conditional sums

def _fn_sumif(args):
    rng = _as_list(args[0])
    test = _criterion(_scalar(args[1]))
    if test is None:
        return args[1]
    values = _as_list(args[2]) if len(args) > 2 else rng
    total = 0.0
    for i, cell in enumerate(rng):
        if i < len(values) and test(cell):
            value = values[i]
            if isinstance(value, FormulaError):
                return value
            if _is_number(value):
                total += float(value)
    return total


def _conditional(args, combine, first_values: bool):
    """SUMIFS / AVERAGEIFS / MAXIFS / MINIFS (values first, then pairs) and
    COUNTIFS (pairs only)."""
    values = _as_list(args[0]) if first_values else None
    pairs = _pairs(args, 1 if first_values else 0)
    if isinstance(pairs, FormulaError):
        return pairs
    length = len(values) if values is not None else len(pairs[0][0])
    hits = _matching(pairs, length)
    if values is None:
        return combine(hits)
    picked = []
    for i in hits:
        value = values[i]
        if isinstance(value, FormulaError):
            return value
        if _is_number(value):
            picked.append(float(value))
    return combine(picked)


def _fn_sumifs(args):
    return _conditional(args, lambda xs: float(sum(xs)), True)


def _fn_countif(args):
    rng = _as_list(args[0])
    test = _criterion(_scalar(args[1]))
    if test is None:
        return args[1]
    return float(sum(1 for cell in rng if test(cell)))


def _fn_countifs(args):
    return _conditional(args, lambda hits: float(len(hits)), False)


def _average(xs):
    return sum(xs) / len(xs) if xs else FormulaError(
        ERR_DIV0, "no values match")


def _fn_averageif(args):
    rng = _as_list(args[0])
    test = _criterion(_scalar(args[1]))
    if test is None:
        return args[1]
    values = _as_list(args[2]) if len(args) > 2 else rng
    picked = [float(values[i]) for i, cell in enumerate(rng)
              if i < len(values) and test(cell) and _is_number(values[i])]
    return _average(picked)


def _fn_averageifs(args):
    return _conditional(args, _average, True)


def _fn_maxifs(args):
    return _conditional(args, lambda xs: max(xs) if xs else 0.0, True)


def _fn_minifs(args):
    return _conditional(args, lambda xs: min(xs) if xs else 0.0, True)


def _fn_countblank(args):
    return float(sum(1 for v in _flat(args) if v in (None, "")))


# ---------------------------------------------------------------- lookups

def _table(value) -> RangeValue:
    if isinstance(value, RangeValue):
        return value
    return RangeValue(_as_list(value), 1)


def _approximate(keys: list, target, descending: bool = False):
    """The position Excel's approximate match lands on: the last key not
    greater than the target in a sorted list (or not less, descending)."""
    want = _order_key(target)
    found = None
    for i, key in enumerate(keys):
        if key in (None, "") or isinstance(key, FormulaError):
            continue
        have = _order_key(key)
        if have[0] != want[0]:
            continue
        if (have <= want) if not descending else (have >= want):
            found = i
        else:
            break
    return found


def _find(keys: list, target, mode: int = 0, reverse: bool = False):
    """Index of `target` in `keys`. mode 0 exact (wildcards in text), 2
    wildcard, -1 exact-or-next-smaller, 1 exact-or-next-larger."""
    order = range(len(keys) - 1, -1, -1) if reverse else range(len(keys))
    if mode in (0, 2):
        pattern = (_wildcard(target) if isinstance(target, str)
                   and any(ch in target for ch in "*?") else None)
        for i in order:
            key = keys[i]
            if pattern is not None:
                if isinstance(key, str) and pattern.match(key):
                    return i
            elif _same(key, target):
                return i
        return None
    want = _order_key(target)
    best, best_key = None, None
    for i in order:
        key = keys[i]
        if key in (None, "") or isinstance(key, FormulaError):
            continue
        have = _order_key(key)
        if have[0] != want[0]:
            continue
        if have == want:
            return i
        if mode == -1 and have < want and (best_key is None or have > best_key):
            best, best_key = i, have
        if mode == 1 and have > want and (best_key is None or have < best_key):
            best, best_key = i, have
    return best


def _fn_vlookup(args):
    target = _scalar(args[0])
    if isinstance(target, FormulaError):
        return target
    table = _table(args[1])
    col = to_number(_scalar(args[2]))
    if isinstance(col, FormulaError):
        return col
    col = int(col)
    if not 1 <= col <= table.cols:
        return FormulaError("#REF!", f"column {col} is outside the table")
    approximate = to_bool(_scalar(_arg(args, 3, True)))
    if isinstance(approximate, FormulaError):
        return approximate
    keys = table.column(0)
    row = (_approximate(keys, target) if approximate
           else _find(keys, target, 0))
    if row is None:
        return _na(f"{to_text(target)} is not in the first column")
    return table.at(row, col - 1)


def _fn_hlookup(args):
    target = _scalar(args[0])
    if isinstance(target, FormulaError):
        return target
    table = _table(args[1])
    row = to_number(_scalar(args[2]))
    if isinstance(row, FormulaError):
        return row
    row = int(row)
    if not 1 <= row <= table.rows:
        return FormulaError("#REF!", f"row {row} is outside the table")
    approximate = to_bool(_scalar(_arg(args, 3, True)))
    if isinstance(approximate, FormulaError):
        return approximate
    keys = table.row(0)
    col = (_approximate(keys, target) if approximate
           else _find(keys, target, 0))
    if col is None:
        return _na(f"{to_text(target)} is not in the first row")
    return table.at(row - 1, col)


def _fn_xlookup(args):
    target = _scalar(args[0])
    if isinstance(target, FormulaError):
        return target
    keys = _as_list(args[1])
    results = _table(args[2])
    missing = _arg(args, 3, None)
    mode = to_number(_scalar(_arg(args, 4, 0)))
    search = to_number(_scalar(_arg(args, 5, 1)))
    if isinstance(mode, FormulaError) or isinstance(search, FormulaError):
        return FormulaError(ERR_VALUE, "match and search modes are numbers")
    index = _find(keys, target, int(mode), reverse=int(search) < 0)
    if index is None:
        if len(args) > 3:
            return _scalar(missing)
        return _na(f"{to_text(target)} was not found")
    # a lookup down a column returns from the same row of the result
    # range; across a row, from the same column
    if results.cols == 1 or len(keys) == results.rows:
        return results.at(index, 0) if results.cols >= 1 else _na()
    return results.at(0, index)


def _fn_match(args):
    target = _scalar(args[0])
    if isinstance(target, FormulaError):
        return target
    keys = _as_list(args[1])
    kind = to_number(_scalar(_arg(args, 2, 1)))
    if isinstance(kind, FormulaError):
        return kind
    kind = int(kind)
    if kind == 0:
        index = _find(keys, target, 0)
    else:
        index = _approximate(keys, target, descending=kind < 0)
    if index is None:
        return _na(f"{to_text(target)} was not found")
    return float(index + 1)


def _fn_index(args):
    table = _table(args[0])
    row = to_number(_scalar(_arg(args, 1, 0)))
    col = to_number(_scalar(_arg(args, 2, 0)))
    if isinstance(row, FormulaError):
        return row
    if isinstance(col, FormulaError):
        return col
    row, col = int(row), int(col)
    if len(args) == 2 and table.rows == 1:
        row, col = 1, row               # one row: the index is a column
    if row == 0 and table.rows == 1:
        row = 1
    if col == 0 and table.cols == 1:
        col = 1
    if not (1 <= row <= table.rows and 1 <= col <= table.cols):
        return FormulaError("#REF!", "the index is outside the range")
    return table.at(row - 1, col - 1)


def _fn_choose(args):
    index = to_number(_scalar(args[0]))
    if isinstance(index, FormulaError):
        return index
    index = int(index)
    if not 1 <= index < len(args):
        return FormulaError(ERR_VALUE, f"CHOOSE has no value number {index}")
    return _scalar(args[index])


# ----------------------------------------------------------------- logic

def _fn_iferror(args):
    value = _scalar(args[0])
    return _scalar(args[1]) if isinstance(value, FormulaError) else value


def _fn_ifna(args):
    value = _scalar(args[0])
    if isinstance(value, FormulaError) and value.code == ERR_NA:
        return _scalar(args[1])
    return value


def _fn_ifs(args):
    if len(args) % 2:
        return FormulaError(ERR_VALUE, "IFS takes condition, value pairs")
    for i in range(0, len(args), 2):
        cond = to_bool(_scalar(args[i]))
        if isinstance(cond, FormulaError):
            return cond
        if cond:
            return _scalar(args[i + 1])
    return _na("no condition was TRUE")


def _fn_switch(args):
    value = _scalar(args[0])
    if isinstance(value, FormulaError):
        return value
    rest = args[1:]
    default = None
    if len(rest) % 2:
        default = rest[-1]
        rest = rest[:-1]
    for i in range(0, len(rest), 2):
        if _same(value, _scalar(rest[i])):
            return _scalar(rest[i + 1])
    return _scalar(default) if default is not None else _na(
        "no case matched")


def _fn_xor(args):
    count = 0
    for value in _flat(args):
        if value is None:
            continue
        flag = to_bool(value)
        if isinstance(flag, FormulaError):
            return flag
        count += bool(flag)
    return count % 2 == 1


def _fn_isblank(args):
    return _scalar(args[0]) in (None, "")


def _fn_isnumber(args):
    return _is_number(_scalar(args[0]))


def _fn_istext(args):
    value = _scalar(args[0])
    return isinstance(value, str) and value != ""


def _fn_iserror(args):
    return isinstance(_scalar(args[0]), FormulaError)


def _fn_isna(args):
    value = _scalar(args[0])
    return isinstance(value, FormulaError) and value.code == ERR_NA


def _fn_islogical(args):
    return isinstance(_scalar(args[0]), bool)


# ------------------------------------------------------------------ maths

def _digits(args):
    digits = _number_arg(args, 1, 0.0)
    return digits if isinstance(digits, FormulaError) else int(digits)


def _fn_roundup(args):
    x, digits = _number_arg(args, 0), _digits(args)
    for v in (x, digits):
        if isinstance(v, FormulaError):
            return v
    scale = 10.0 ** digits
    return math.copysign(math.ceil(abs(x) * scale - 1e-9) / scale, x)


def _fn_rounddown(args):
    x, digits = _number_arg(args, 0), _digits(args)
    for v in (x, digits):
        if isinstance(v, FormulaError):
            return v
    scale = 10.0 ** digits
    return math.copysign(math.floor(abs(x) * scale + 1e-9) / scale, x)


def _fn_int(args):
    x = _number_arg(args, 0)
    return x if isinstance(x, FormulaError) else float(math.floor(x))


def _fn_trunc(args):
    return _fn_rounddown(args)


def _fn_sign(args):
    x = _number_arg(args, 0)
    if isinstance(x, FormulaError):
        return x
    return float((x > 0) - (x < 0))


def _fn_product(args):
    values = _numbers(args)
    out = 1.0
    for v in values:
        out *= v
    return out if values else 0.0


def _fn_sumproduct(args):
    arrays = [_as_list(a) for a in args]
    length = len(arrays[0])
    if any(len(a) != length for a in arrays):
        return FormulaError(ERR_VALUE, "SUMPRODUCT's ranges must be the "
                                       "same size")
    total = 0.0
    for i in range(length):
        product = 1.0
        for array in arrays:
            value = array[i]
            if isinstance(value, FormulaError):
                return value
            product *= float(value) if _is_number(value) else 0.0
        total += product
    return total


def _stat(fn, minimum: int = 1):
    def run(args):
        values = _numbers(args)
        if len(values) < minimum:
            return FormulaError(ERR_DIV0, "not enough numbers")
        return float(fn(values))
    return run


def _kth(largest: bool):
    def run(args):
        values = sorted(_numbers([args[0]]), reverse=largest)
        k = _number_arg(args, 1)
        if isinstance(k, FormulaError):
            return k
        k = int(k)
        if not 1 <= k <= len(values):
            return FormulaError(ERR_NUM, f"there is no number {k}")
        return values[k - 1]
    return run


def _fn_rank(args):
    x = _number_arg(args, 0)
    if isinstance(x, FormulaError):
        return x
    values = _numbers([args[1]])
    ascending = to_bool(_scalar(_arg(args, 2, 0)))
    if isinstance(ascending, FormulaError):
        return ascending
    if x not in values:
        return _na(f"{format_number(x)} is not in the range")
    ordered = sorted(values, reverse=not ascending)
    return float(ordered.index(x) + 1)


def _unary(fn, check=None):
    def run(args):
        x = _number_arg(args, 0)
        if isinstance(x, FormulaError):
            return x
        if check is not None and not check(x):
            return FormulaError(ERR_NUM, "outside what the function takes")
        try:
            return float(fn(x))
        except (OverflowError, ValueError):
            return FormulaError(ERR_NUM)
    return run


def _fn_log(args):
    x = _number_arg(args, 0)
    base = _number_arg(args, 1, 10.0)
    for v in (x, base):
        if isinstance(v, FormulaError):
            return v
    if x <= 0 or base <= 0 or base == 1:
        return FormulaError(ERR_NUM, "LOG needs positive numbers")
    return math.log(x, base)


def _fn_pi(_args):
    return math.pi


# ------------------------------------------------------------------- text

def _fn_substitute(args):
    text, old, new = (_text_arg(args, i) for i in range(3))
    for v in (text, old, new):
        if isinstance(v, FormulaError):
            return v
    if not old:
        return text
    if len(args) > 3:
        nth = _number_arg(args, 3)
        if isinstance(nth, FormulaError):
            return nth
        nth, start = int(nth), -1
        for _ in range(nth):
            start = text.find(old, start + 1)
            if start < 0:
                return text
        return text[:start] + new + text[start + len(old):]
    return text.replace(old, new)


def _locate(args, case_blind: bool):
    needle, haystack = _text_arg(args, 0), _text_arg(args, 1)
    start = _number_arg(args, 2, 1.0)
    for v in (needle, haystack, start):
        if isinstance(v, FormulaError):
            return v
    start = int(start)
    if start < 1 or start > len(haystack) + 1:
        return FormulaError(ERR_VALUE, "the start is outside the text")
    if case_blind:
        pattern = _wildcard(needle).pattern[1:-1] if any(
            ch in needle for ch in "*?") else re.escape(needle)
        found = re.compile(pattern, re.IGNORECASE | re.DOTALL).search(
            haystack, start - 1)
        index = found.start() if found else -1
    else:
        index = haystack.find(needle, start - 1)
    if index < 0:
        return FormulaError(ERR_VALUE, f"{needle!r} is not in the text")
    return float(index + 1)


def _fn_find(args):
    return _locate(args, case_blind=False)


def _fn_search(args):
    return _locate(args, case_blind=True)


def _fn_replace(args):
    text = _text_arg(args, 0)
    start, count = _number_arg(args, 1), _number_arg(args, 2)
    new = _text_arg(args, 3)
    for v in (text, start, count, new):
        if isinstance(v, FormulaError):
            return v
    start, count = int(start) - 1, int(count)
    if start < 0 or count < 0:
        return FormulaError(ERR_VALUE, "start and length must be positive")
    return text[:start] + new + text[start + count:]


def _fn_proper(args):
    text = _text_arg(args, 0)
    if isinstance(text, FormulaError):
        return text
    return re.sub(r"[A-Za-z]+", lambda m: m.group(0).capitalize(),
                  text.lower())


def _fn_rept(args):
    text, times = _text_arg(args, 0), _number_arg(args, 1)
    for v in (text, times):
        if isinstance(v, FormulaError):
            return v
    if times < 0:
        return FormulaError(ERR_VALUE, "REPT needs a count of 0 or more")
    return text * int(times)


def _fn_exact(args):
    a, b = _text_arg(args, 0), _text_arg(args, 1)
    for v in (a, b):
        if isinstance(v, FormulaError):
            return v
    return a == b


def _fn_textjoin(args):
    delimiter = _text_arg(args, 0)
    skip = to_bool(_scalar(args[1]))
    for v in (delimiter, skip):
        if isinstance(v, FormulaError):
            return v
    parts = []
    for value in _flat(args[2:]):
        text = to_text(value)
        if isinstance(text, FormulaError):
            return text
        if skip and text == "":
            continue
        parts.append(text)
    return delimiter.join(parts)


def _fn_value(args):
    text = _scalar(args[0])
    if _is_number(text):
        return float(text)
    if isinstance(text, FormulaError):
        return text
    raw = to_text(text).strip()
    negative = raw.startswith("(") and raw.endswith(")")
    if negative:
        raw = raw[1:-1]
    percent = raw.endswith("%")
    raw = re.sub(r"[,\s£$€¥%]", "", raw)
    try:
        number = float(raw)
    except ValueError:
        return FormulaError(ERR_VALUE, f"{text!r} is not a number")
    number = -number if negative else number
    return number / 100 if percent else number


_DATE_CODES = (("yyyy", "%Y"), ("yy", "%y"), ("mmmm", "%B"), ("mmm", "%b"),
               ("dddd", "%A"), ("ddd", "%a"), ("dd", "%d"), ("hh", "%H"),
               ("ss", "%S"))


def _text_date(moment: datetime, code: str) -> str:
    out, i = [], 0
    lower = code.lower()
    while i < len(code):
        for token, directive in _DATE_CODES:
            if lower.startswith(token, i):
                out.append(moment.strftime(directive))
                i += len(token)
                break
        else:
            if lower.startswith("mm", i):
                # mm after an hour is minutes, else the month
                minute = any(t in lower[:i] for t in ("h", ":"))
                out.append(moment.strftime("%M" if minute else "%m"))
                i += 2
            elif lower[i] == "m":
                out.append(str(moment.month))
                i += 1
            elif lower[i] == "d":
                out.append(str(moment.day))
                i += 1
            else:
                out.append(code[i])
                i += 1
    return "".join(out)


def _fn_text(args):
    value = _scalar(args[0])
    code = _text_arg(args, 1)
    if isinstance(value, FormulaError):
        return value
    if isinstance(code, FormulaError):
        return code
    moment = as_date(value) if isinstance(value, str) else None
    if moment is not None and any(ch in code.lower() for ch in "ydm"):
        return _text_date(moment, code)
    number = to_number(value)
    if isinstance(number, FormulaError):
        return to_text(value)
    percent = "%" in code
    if percent:
        number *= 100
    body = re.search(r"[#0][#0,]*(\.[0#]+)?", code)
    if body is None:
        return code
    decimals = len(body.group(1)) - 1 if body.group(1) else 0
    thousands = "," in body.group(0).split(".")[0]
    from .numfmt import _rounded
    rounded = _rounded(number, decimals)
    shown = f"{abs(rounded):,.{decimals}f}" if thousands else \
        f"{abs(rounded):.{decimals}f}"
    if rounded < 0:
        shown = "-" + shown
    return code[:body.start()] + shown + code[body.end():]


# ------------------------------------------------------------------ dates

def _date_arg(args, index):
    value = _scalar(_arg(args, index))
    if isinstance(value, FormulaError):
        return value
    moment = as_date(value)
    if moment is None:
        return FormulaError(ERR_VALUE, f"{to_text(value)!r} is not a date")
    return moment


def _fn_today(_args):
    return date.today().isoformat()


def _fn_now(_args):
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _fn_date(args):
    parts = [_number_arg(args, i) for i in range(3)]
    for v in parts:
        if isinstance(v, FormulaError):
            return v
    year, month, day = (int(v) for v in parts)
    # Excel rolls over: month 13 is next January, day 0 the month's eve
    year += (month - 1) // 12
    month = (month - 1) % 12 + 1
    if not 1 <= year <= 9999:
        return FormulaError(ERR_NUM, "the year is out of range")
    return (date(year, month, 1) + timedelta(days=day - 1)).isoformat()


def _part(getter):
    def run(args):
        moment = _date_arg(args, 0)
        return moment if isinstance(moment, FormulaError) else float(
            getter(moment))
    return run


def _fn_weekday(args):
    moment = _date_arg(args, 0)
    kind = _number_arg(args, 1, 1.0)
    if isinstance(moment, FormulaError):
        return moment
    if isinstance(kind, FormulaError):
        return kind
    monday0 = moment.weekday()
    if int(kind) == 2:
        return float(monday0 + 1)
    if int(kind) == 3:
        return float(monday0)
    return float((monday0 + 1) % 7 + 1)      # Sunday = 1


def _fn_weeknum(args):
    moment = _date_arg(args, 0)
    kind = _number_arg(args, 1, 1.0)
    if isinstance(moment, FormulaError):
        return moment
    if isinstance(kind, FormulaError):
        return kind
    if int(kind) == 21:
        return float(moment.isocalendar()[1])
    jan1 = date(moment.year, 1, 1)
    start = (jan1.weekday() + 1) % 7 if int(kind) != 2 else jan1.weekday()
    return float((moment.timetuple().tm_yday - 1 + start) // 7 + 1)


def _add_months(moment: datetime, months: int) -> date:
    total = moment.year * 12 + moment.month - 1 + months
    year, month = divmod(total, 12)
    last = calendar.monthrange(year, month + 1)[1]
    return date(year, month + 1, min(moment.day, last))


def _fn_edate(args):
    moment = _date_arg(args, 0)
    months = _number_arg(args, 1)
    if isinstance(moment, FormulaError):
        return moment
    if isinstance(months, FormulaError):
        return months
    return _add_months(moment, int(months)).isoformat()


def _fn_eomonth(args):
    moment = _date_arg(args, 0)
    months = _number_arg(args, 1)
    if isinstance(moment, FormulaError):
        return moment
    if isinstance(months, FormulaError):
        return months
    landed = _add_months(moment.replace(day=1), int(months))
    last = calendar.monthrange(landed.year, landed.month)[1]
    return landed.replace(day=last).isoformat()


def _fn_days(args):
    end, start = _date_arg(args, 0), _date_arg(args, 1)
    for v in (end, start):
        if isinstance(v, FormulaError):
            return v
    return float((end.date() - start.date()).days)


def _fn_datedif(args):
    start, end = _date_arg(args, 0), _date_arg(args, 1)
    unit = _text_arg(args, 2)
    for v in (start, end, unit):
        if isinstance(v, FormulaError):
            return v
    if end < start:
        return FormulaError(ERR_NUM, "the end is before the start")
    s, e = start.date(), end.date()
    months = (e.year - s.year) * 12 + e.month - s.month - (e.day < s.day)
    unit = unit.upper()
    if unit == "D":
        return float((e - s).days)
    if unit == "M":
        return float(months)
    if unit == "Y":
        return float(months // 12)
    if unit == "YM":
        return float(months % 12)
    if unit == "MD":
        anchor = _add_months(datetime(s.year, s.month, s.day), months)
        return float((e - anchor).days)
    if unit == "YD":
        anchor = _add_months(datetime(s.year, s.month, s.day),
                             (months // 12) * 12)
        return float((e - anchor).days)
    return FormulaError(ERR_NUM, "unit is one of D, M, Y, YM, MD, YD")


def _fn_networkdays(args):
    start, end = _date_arg(args, 0), _date_arg(args, 1)
    for v in (start, end):
        if isinstance(v, FormulaError):
            return v
    holidays = {as_date(v).date() for v in _as_list(_arg(args, 2, []))
                if as_date(v) is not None}
    s, e = start.date(), end.date()
    sign = 1
    if e < s:
        s, e, sign = e, s, -1
    count, day = 0, s
    while day <= e:
        if day.weekday() < 5 and day not in holidays:
            count += 1
        day += timedelta(days=1)
    return float(sign * count)


# ---------------------------------------------------------------- tables

FUNCTIONS = {
    "SUMIF": (_fn_sumif, 2, 3), "SUMIFS": (_fn_sumifs, 3, None),
    "COUNTIF": (_fn_countif, 2, 2), "COUNTIFS": (_fn_countifs, 2, None),
    "AVERAGEIF": (_fn_averageif, 2, 3),
    "AVERAGEIFS": (_fn_averageifs, 3, None),
    "MAXIFS": (_fn_maxifs, 3, None), "MINIFS": (_fn_minifs, 3, None),
    "COUNTBLANK": (_fn_countblank, 1, None),
    "VLOOKUP": (_fn_vlookup, 3, 4), "HLOOKUP": (_fn_hlookup, 3, 4),
    "XLOOKUP": (_fn_xlookup, 3, 6), "MATCH": (_fn_match, 2, 3),
    "INDEX": (_fn_index, 2, 3), "CHOOSE": (_fn_choose, 2, None),
    "IFERROR": (_fn_iferror, 2, 2), "IFNA": (_fn_ifna, 2, 2),
    "IFS": (_fn_ifs, 2, None), "SWITCH": (_fn_switch, 3, None),
    "XOR": (_fn_xor, 1, None),
    "ISBLANK": (_fn_isblank, 1, 1), "ISNUMBER": (_fn_isnumber, 1, 1),
    "ISTEXT": (_fn_istext, 1, 1), "ISERROR": (_fn_iserror, 1, 1),
    "ISNA": (_fn_isna, 1, 1), "ISLOGICAL": (_fn_islogical, 1, 1),
    "ROUNDUP": (_fn_roundup, 1, 2), "ROUNDDOWN": (_fn_rounddown, 1, 2),
    "INT": (_fn_int, 1, 1), "TRUNC": (_fn_trunc, 1, 2),
    "SIGN": (_fn_sign, 1, 1), "PRODUCT": (_fn_product, 1, None),
    "SUMPRODUCT": (_fn_sumproduct, 1, None),
    "MEDIAN": (_stat(statistics.median), 1, None),
    "STDEV": (_stat(statistics.stdev, 2), 1, None),
    "STDEVP": (_stat(statistics.pstdev), 1, None),
    "VAR": (_stat(statistics.variance, 2), 1, None),
    "VARP": (_stat(statistics.pvariance), 1, None),
    "LARGE": (_kth(True), 2, 2), "SMALL": (_kth(False), 2, 2),
    "RANK": (_fn_rank, 2, 3),
    "EXP": (_unary(math.exp), 1, 1),
    "LN": (_unary(math.log, lambda x: x > 0), 1, 1),
    "LOG10": (_unary(math.log10, lambda x: x > 0), 1, 1),
    "LOG": (_fn_log, 1, 2), "PI": (_fn_pi, 0, 0),
    "SUBSTITUTE": (_fn_substitute, 3, 4), "FIND": (_fn_find, 2, 3),
    "SEARCH": (_fn_search, 2, 3), "REPLACE": (_fn_replace, 4, 4),
    "PROPER": (_fn_proper, 1, 1), "REPT": (_fn_rept, 2, 2),
    "EXACT": (_fn_exact, 2, 2), "TEXTJOIN": (_fn_textjoin, 3, None),
    "VALUE": (_fn_value, 1, 1), "TEXT": (_fn_text, 2, 2),
    "TODAY": (_fn_today, 0, 0), "NOW": (_fn_now, 0, 0),
    "DATE": (_fn_date, 3, 3),
    "YEAR": (_part(lambda d: d.year), 1, 1),
    "MONTH": (_part(lambda d: d.month), 1, 1),
    "DAY": (_part(lambda d: d.day), 1, 1),
    "WEEKDAY": (_fn_weekday, 1, 2), "WEEKNUM": (_fn_weeknum, 1, 2),
    "EDATE": (_fn_edate, 2, 2), "EOMONTH": (_fn_eomonth, 2, 2),
    "DAYS": (_fn_days, 2, 2), "DATEDIF": (_fn_datedif, 3, 3),
    "NETWORKDAYS": (_fn_networkdays, 2, 3),
}

# handed error values rather than stopped by the first one
LENIENT = frozenset({
    "IFERROR", "IFNA", "ISERROR", "ISNA", "ISBLANK", "ISNUMBER", "ISTEXT",
    "ISLOGICAL", "COUNTIF", "COUNTIFS", "COUNTBLANK", "SUMIF", "SUMIFS",
    "AVERAGEIF", "AVERAGEIFS", "MAXIFS", "MINIFS", "VLOOKUP", "HLOOKUP",
    "XLOOKUP", "MATCH", "INDEX", "CHOOSE", "SWITCH", "IFS", "SUMPRODUCT",
})

# (name, signature, what it does, example, category) — the formula
# reference and the ribbon's Insert Function list read this
HELP = (
    ("VLOOKUP", "VLOOKUP(value, table, column, [approximate])",
     "Finds the value in the table's first column and returns the cell from "
     "that row in the given column. Put FALSE last for an exact match — "
     "without it, as in Excel, the first column must be sorted.",
     '=VLOOKUP("Gadget", A2:C20, 3, FALSE)', "Lookup"),
    ("XLOOKUP", "XLOOKUP(value, look_in, return_from, [if_not_found], "
     "[match_mode], [search_mode])",
     "Finds the value in one range and returns the matching cell of another. "
     "Exact by default; match_mode -1/1 takes the next smaller/larger, 2 "
     "wildcards; search_mode -1 searches from the end.",
     '=XLOOKUP([@Product], [Product], [Price], "none")', "Lookup"),
    ("HLOOKUP", "HLOOKUP(value, table, row, [approximate])",
     "VLOOKUP across: finds the value in the first row.",
     "=HLOOKUP(2026, A1:F3, 2, FALSE)", "Lookup"),
    ("MATCH", "MATCH(value, range, [type])",
     "The position of the value in the range. type 0 is exact; 1 (the "
     "default) the last value not above it in a sorted range.",
     '=MATCH("East", A1:A10, 0)', "Lookup"),
    ("INDEX", "INDEX(range, row, [column])",
     "The cell at a row and column of the range, counting from 1.",
     "=INDEX(A1:C10, 4, 2)", "Lookup"),
    ("CHOOSE", "CHOOSE(n, value1, value2, …)",
     "The nth of the values listed.", '=CHOOSE(2, "low", "mid", "high")',
     "Lookup"),
    ("SUMIF", "SUMIF(range, criterion, [sum_range])",
     "Adds the cells that meet a criterion: 5, \"North\", \">100\", "
     "\"<>done\", \"N*\".", '=SUMIF([Region], "North", [Total])',
     "Conditional"),
    ("SUMIFS", "SUMIFS(sum_range, range1, criterion1, …)",
     "Adds the cells whose rows meet every criterion.",
     '=SUMIFS([Total], [Region], "North", [Units], ">10")', "Conditional"),
    ("COUNTIF", "COUNTIF(range, criterion)",
     "How many cells meet the criterion.", '=COUNTIF([Status], "Open")',
     "Conditional"),
    ("COUNTIFS", "COUNTIFS(range1, criterion1, …)",
     "How many rows meet every criterion.",
     '=COUNTIFS([Region], "East", [Paid], TRUE)', "Conditional"),
    ("AVERAGEIF", "AVERAGEIF(range, criterion, [average_range])",
     "The mean of the cells that meet a criterion.",
     '=AVERAGEIF([Region], "West", [Price])', "Conditional"),
    ("AVERAGEIFS", "AVERAGEIFS(average_range, range1, criterion1, …)",
     "The mean of the cells whose rows meet every criterion.",
     '=AVERAGEIFS([Price], [Product], "Widget*")', "Conditional"),
    ("MAXIFS", "MAXIFS(max_range, range1, criterion1, …)",
     "The largest value whose row meets every criterion.",
     '=MAXIFS([Total], [Region], "South")', "Conditional"),
    ("MINIFS", "MINIFS(min_range, range1, criterion1, …)",
     "The smallest value whose row meets every criterion.",
     '=MINIFS([Total], [Region], "South")', "Conditional"),
    ("COUNTBLANK", "COUNTBLANK(range)", "How many cells are empty.",
     "=COUNTBLANK(A1:A20)", "Conditional"),
    ("IFERROR", "IFERROR(value, if_error)",
     "The value, or the second argument when it is an error.",
     "=IFERROR(A1/B1, 0)", "Logic"),
    ("IFNA", "IFNA(value, if_na)", "Like IFERROR, for #N/A only.",
     '=IFNA(VLOOKUP(A1, B:C, 2, FALSE), "missing")', "Logic"),
    ("IFS", "IFS(condition1, value1, …)",
     "The value of the first TRUE condition.",
     '=IFS(A1>90, "A", A1>75, "B", TRUE, "C")', "Logic"),
    ("SWITCH", "SWITCH(value, case1, result1, …, [default])",
     "The result of the case that equals the value.",
     '=SWITCH([@Code], "N", "North", "S", "South", "?")', "Logic"),
    ("XOR", "XOR(conditions…)", "TRUE when an odd number are TRUE.",
     "=XOR(A1, B1)", "Logic"),
    ("ISBLANK", "ISBLANK(value)", "TRUE for an empty cell.",
     "=ISBLANK(A1)", "Logic"),
    ("ISNUMBER", "ISNUMBER(value)", "TRUE for a number.", "=ISNUMBER(A1)",
     "Logic"),
    ("ISTEXT", "ISTEXT(value)", "TRUE for text.", "=ISTEXT(A1)", "Logic"),
    ("ISERROR", "ISERROR(value)", "TRUE for any error.", "=ISERROR(A1/B1)",
     "Logic"),
    ("ISNA", "ISNA(value)", "TRUE for #N/A.", "=ISNA(MATCH(A1, B1:B9, 0))",
     "Logic"),
    ("ISLOGICAL", "ISLOGICAL(value)", "TRUE for TRUE or FALSE.",
     "=ISLOGICAL(A1)", "Logic"),
    ("ROUNDUP", "ROUNDUP(x, [digits])", "Rounds away from zero.",
     "=ROUNDUP(2.341, 1)", "Maths"),
    ("ROUNDDOWN", "ROUNDDOWN(x, [digits])", "Rounds toward zero.",
     "=ROUNDDOWN(2.349, 2)", "Maths"),
    ("INT", "INT(x)", "Rounds down to a whole number.", "=INT(-2.5)",
     "Maths"),
    ("TRUNC", "TRUNC(x, [digits])", "Cuts off the decimals.",
     "=TRUNC(3.99)", "Maths"),
    ("SIGN", "SIGN(x)", "1, 0 or -1.", "=SIGN(A1)", "Maths"),
    ("PRODUCT", "PRODUCT(values…)", "Multiplies the numbers.",
     "=PRODUCT(A1:A4)", "Maths"),
    ("SUMPRODUCT", "SUMPRODUCT(range1, range2, …)",
     "Multiplies the ranges cell by cell and adds the results.",
     "=SUMPRODUCT([Units], [Price])", "Maths"),
    ("MEDIAN", "MEDIAN(values…)", "The middle number.", "=MEDIAN(A1:A9)",
     "Maths"),
    ("STDEV", "STDEV(values…)", "Standard deviation of a sample.",
     "=STDEV([Total])", "Maths"),
    ("STDEVP", "STDEVP(values…)", "Standard deviation of everything.",
     "=STDEVP([Total])", "Maths"),
    ("VAR", "VAR(values…)", "Variance of a sample.", "=VAR(A1:A9)",
     "Maths"),
    ("VARP", "VARP(values…)", "Variance of everything.", "=VARP(A1:A9)",
     "Maths"),
    ("LARGE", "LARGE(range, k)", "The kth largest number.",
     "=LARGE([Total], 3)", "Maths"),
    ("SMALL", "SMALL(range, k)", "The kth smallest number.",
     "=SMALL([Total], 1)", "Maths"),
    ("RANK", "RANK(x, range, [ascending])",
     "Where the number comes in the range, largest first by default.",
     "=RANK([@Total], [Total])", "Maths"),
    ("EXP", "EXP(x)", "e to the power x.", "=EXP(1)", "Maths"),
    ("LN", "LN(x)", "Natural logarithm.", "=LN(A1)", "Maths"),
    ("LOG", "LOG(x, [base])", "Logarithm, base 10 by default.",
     "=LOG(8, 2)", "Maths"),
    ("LOG10", "LOG10(x)", "Base-10 logarithm.", "=LOG10(1000)", "Maths"),
    ("PI", "PI()", "π.", "=PI()*A1^2", "Maths"),
    ("SUBSTITUTE", "SUBSTITUTE(text, old, new, [which])",
     "Replaces text — every occurrence, or only the nth.",
     '=SUBSTITUTE(A1, "-", " ")', "Text"),
    ("FIND", "FIND(find, in_text, [start])",
     "Where the text starts, case-sensitive.", '=FIND("@", A1)', "Text"),
    ("SEARCH", "SEARCH(find, in_text, [start])",
     "Like FIND, ignoring case and allowing * and ?.",
     '=SEARCH("inv*", A1)', "Text"),
    ("REPLACE", "REPLACE(text, start, length, new)",
     "Replaces characters by position.", '=REPLACE(A1, 1, 3, "ABC")',
     "Text"),
    ("PROPER", "PROPER(text)", "Capitalises Each Word.", "=PROPER(A1)",
     "Text"),
    ("REPT", "REPT(text, times)", "Repeats the text.", '=REPT("★", A1)',
     "Text"),
    ("EXACT", "EXACT(a, b)", "TRUE when the texts match exactly, case "
     "included.", "=EXACT(A1, B1)", "Text"),
    ("TEXTJOIN", "TEXTJOIN(delimiter, skip_blank, values…)",
     "Joins values with a delimiter between them.",
     '=TEXTJOIN(", ", TRUE, A1:A5)', "Text"),
    ("VALUE", "VALUE(text)", "Turns text like \"£1,200\" or \"25%\" into a "
     "number.", "=VALUE(A1)", "Text"),
    ("TEXT", "TEXT(value, format)",
     "A number or date as text in a format: \"0.00\", \"#,##0\", \"0%\", "
     "\"dd/mm/yyyy\", \"mmm yyyy\".", '=TEXT([@Date], "d mmm yyyy")',
     "Text"),
    ("TODAY", "TODAY()", "Today's date (worked out again on every edit "
     "and run).", "=TODAY()", "Date"),
    ("NOW", "NOW()", "The date and time now.", "=NOW()", "Date"),
    ("DATE", "DATE(year, month, day)", "A date from its parts; months and "
     "days roll over (month 13 is next January).", "=DATE(2026, 10, 7)",
     "Date"),
    ("YEAR", "YEAR(date)", "The year.", "=YEAR([@Date])", "Date"),
    ("MONTH", "MONTH(date)", "The month, 1–12.", "=MONTH([@Date])", "Date"),
    ("DAY", "DAY(date)", "The day of the month.", "=DAY([@Date])", "Date"),
    ("WEEKDAY", "WEEKDAY(date, [type])",
     "Day of the week: 1 = Sunday (type 2: 1 = Monday).",
     "=WEEKDAY([@Date], 2)", "Date"),
    ("WEEKNUM", "WEEKNUM(date, [type])",
     "Week of the year (type 21 for ISO weeks).", "=WEEKNUM([@Date], 21)",
     "Date"),
    ("EDATE", "EDATE(date, months)", "The same day some months on (or "
     "back).", "=EDATE([@Start], 3)", "Date"),
    ("EOMONTH", "EOMONTH(date, months)", "The last day of the month, some "
     "months on.", "=EOMONTH([@Date], 0)", "Date"),
    ("DAYS", "DAYS(end, start)", "The days between two dates.",
     "=DAYS([@Due], TODAY())", "Date"),
    ("DATEDIF", "DATEDIF(start, end, unit)",
     "Whole years (\"Y\"), months (\"M\") or days (\"D\") between two "
     "dates; \"YM\", \"MD\", \"YD\" for what is left over.",
     '=DATEDIF([@Born], TODAY(), "Y")', "Date"),
    ("NETWORKDAYS", "NETWORKDAYS(start, end, [holidays])",
     "Working days (Monday–Friday) between two dates, both included.",
     "=NETWORKDAYS([@Start], [@End])", "Date"),
)
