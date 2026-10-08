"""Data validation for a Table column — Excel's Data ▸ Data Validation.

A column may carry one rule (``ColumnSpec.validation``), a small dict:

``kind``
    ``"any"`` (no limit on the value — a rule only for *required* or a
    hint), ``"whole"``, ``"number"``, ``"date"`` or ``"length"`` (of the
    text).
``op``
    ``between``, ``not_between``, ``eq``, ``ne``, ``gt``, ``lt``, ``ge``,
    ``le``.
``a`` / ``b``
    The bounds as typed: numbers, or for a date an ISO date, ``today``,
    ``today+7`` or ``today-30``. ``b`` is only read by the two *between*
    operators.
``required``
    A row with anything in it must fill this cell.
``hint``
    A note shown when a cell of the column is selected (Excel's input
    message).
``error``
    The text a broken rule shows instead of the generated one.
``stop``
    Turn a typed value away rather than flag it (Excel's *Stop* alert).
    Paste and fill are never turned away, as in Excel; what they bring in
    is flagged.

The rule only checks literal cells — a formula's result is conditional
formatting's business — and never changes a value or what flows on.
Qt-free: the grid, the dialog and the tests all ask this module.
"""
from __future__ import annotations

import datetime as _dt
import re
from typing import Optional

KINDS = (
    ("any", "Any value"),
    ("whole", "Whole number"),
    ("number", "Decimal number"),
    ("date", "Date"),
    ("length", "Text length"),
)
OPS = (
    ("between", "between"),
    ("not_between", "not between"),
    ("eq", "equal to"),
    ("ne", "not equal to"),
    ("gt", "greater than"),
    ("lt", "less than"),
    ("ge", "greater than or equal to"),
    ("le", "less than or equal to"),
)
_KIND_KEYS = {k for k, _ in KINDS}
_OP_KEYS = {k for k, _ in OPS}
_OP_WORDS = dict(OPS)
# for dates, the comparisons read as time
_DATE_WORDS = {"gt": "after", "lt": "before", "ge": "on or after",
               "le": "on or before", "eq": "on", "ne": "not on"}
_TODAY = re.compile(r"^today\s*(?:([+-])\s*(\d+))?$", re.IGNORECASE)


def two_bounds(op: str) -> bool:
    return op in ("between", "not_between")


def clean(raw) -> Optional[dict]:
    """A stored rule made safe, or None when it asks for nothing."""
    if not isinstance(raw, dict):
        return None
    kind = raw.get("kind") if raw.get("kind") in _KIND_KEYS else "any"
    op = raw.get("op") if raw.get("op") in _OP_KEYS else "between"
    rule = {"kind": kind}
    if kind != "any":
        rule["op"] = op
        rule["a"] = str(raw.get("a", "")).strip()
        if two_bounds(op):
            rule["b"] = str(raw.get("b", "")).strip()
    for key in ("required", "stop"):
        if raw.get(key):
            rule[key] = True
    for key in ("hint", "error"):
        text = str(raw.get(key) or "").strip()
        if text:
            rule[key] = text
    if kind == "any" and not (rule.get("required") or rule.get("hint")):
        return None
    return rule


# ---------------------------------------------------------------- values

def _date(text: str, today: Optional[_dt.date] = None) -> Optional[_dt.date]:
    match = _TODAY.match(text.strip())
    if match:
        base = today or _dt.date.today()
        sign, days = match.groups()
        if days:
            base += _dt.timedelta(days=int(days) * (1 if sign == "+" else -1))
        return base
    from .schema import normalize_date
    iso = normalize_date(text)
    if iso is None:
        return None
    try:
        return _dt.date.fromisoformat(iso[:10])
    except ValueError:
        return None


def _number(text: str) -> Optional[float]:
    try:
        value = float(text)
    except (TypeError, ValueError):
        return None
    return value if value == value and abs(value) != float("inf") else None


def _bound(kind: str, text: str, today=None):
    if kind == "date":
        return _date(text, today)
    if kind == "length":
        value = _number(text)
        return int(value) if value is not None and value >= 0 else None
    return _number(text)


def bound_problem(rule: dict) -> Optional[str]:
    """Why a rule's bounds can't be used, for the dialog — or None."""
    kind = rule.get("kind", "any")
    if kind == "any":
        return None
    names = ["a", "b"] if two_bounds(rule.get("op", "between")) else ["a"]
    what = {"date": "a date like 2026-01-31, or today, today+7",
            "length": "a whole number of characters",
            "whole": "a number", "number": "a number"}[kind]
    for name in names:
        text = str(rule.get(name, "")).strip()
        if _bound(kind, text) is None:
            label = ("the first value" if name == "a" and len(names) == 2
                     else "the second value" if name == "b" else "the value")
            if not text:
                return f"Fill in {label}."
            return f"{label[0].upper()}{label[1:]} must be {what}."
    a = _bound(kind, rule["a"])
    if len(names) == 2 and a > _bound(kind, rule["b"]):
        return "The first value is larger than the second."
    return None


def _compare(value, op: str, a, b) -> bool:
    if op == "between":
        return a <= value <= b
    if op == "not_between":
        return not a <= value <= b
    return {"eq": value == a, "ne": value != a, "gt": value > a,
            "lt": value < a, "ge": value >= a, "le": value <= a}[op]


# ------------------------------------------------------------ the check

def check(text, rule: Optional[dict], row_has_data: bool = True,
          today: Optional[_dt.date] = None) -> Optional[str]:
    """Why a literal cell breaks the column's rule, or None when it keeps
    it. Formulas always pass; a blank only fails ``required``, and only in
    a row that holds something else (a spare empty row is not missing
    anything)."""
    rule = clean(rule)
    if rule is None:
        return None
    text = ("" if text is None else str(text)).strip()
    from .schema import is_formula
    if is_formula(text):
        return None
    if text == "":
        if rule.get("required") and row_has_data:
            return rule.get("error") or "This cell can't be left blank."
        return None
    kind = rule["kind"]
    if kind == "any":
        return None
    op = rule["op"]
    a = _bound(kind, rule.get("a", ""), today)
    b = _bound(kind, rule.get("b", ""), today) if two_bounds(op) else None
    if a is None or (two_bounds(op) and b is None):
        return None     # a half-made rule checks nothing
    if kind == "length":
        value = len(text)
    elif kind == "date":
        value = _date(text, today)
        if value is None:
            return rule.get("error") or f"{text!r} is not a date."
    else:
        value = _number(text)
        if value is None:
            return rule.get("error") or f"{text!r} is not a number."
        if kind == "whole" and value != int(value):
            return rule.get("error") or f"{text!r} is not a whole number."
    if _compare(value, op, a, b):
        return None
    return rule.get("error") or f"{text!r} breaks the rule: {describe(rule)}"


# ---------------------------------------------------------------- words

def _shown(kind: str, text: str) -> str:
    if kind == "date" and _TODAY.match(text.strip()):
        return text.strip().lower().replace(" ", "")
    return text


def describe(rule: Optional[dict], name: str = "") -> str:
    """The rule as a sentence: "a whole number between 1 and 100, not
    blank". With ``name``, a full sentence about the column."""
    rule = clean(rule)
    if rule is None:
        return f"{name} takes any value." if name else "any value"
    kind = rule["kind"]
    parts = []
    if kind != "any":
        op = rule["op"]
        a, b = _shown(kind, rule.get("a", "")), _shown(kind, rule.get("b", ""))
        noun = {"whole": "a whole number", "number": "a number",
                "date": "a date", "length": "text"}[kind]
        if kind == "length":
            words = {"between": f"between {a} and {b} characters long",
                     "not_between": f"not {a} to {b} characters long",
                     "eq": f"exactly {a} characters long",
                     "ne": f"not {a} characters long",
                     "gt": f"more than {a} characters long",
                     "lt": f"fewer than {a} characters long",
                     "ge": f"at least {a} characters long",
                     "le": f"at most {a} characters long"}[op]
        elif two_bounds(op):
            words = f"{_OP_WORDS[op]} {a} and {b}"
        elif kind == "date":
            words = f"{_DATE_WORDS[op]} {a}"
        else:
            words = f"{_OP_WORDS[op]} {a}"
        parts.append(f"{noun} {words}")
    required = bool(rule.get("required"))
    if required and parts:
        parts.append("never blank")
    if not parts:
        text = "any value, never blank" if required else "any value"
        if not name:
            return text
        return (f"{name} can't be left blank." if required
                else f"{name} takes any value.")
    text = ", ".join(parts)
    return f"{name} must be {text}." if name else text
