"""Paste Special, Qt-free: what lands in each cell, Excel's rules.

`special_block` takes what was copied — the cells' display values, and
their raw sources when they were copied inside the app — and the choices
from the Paste Special dialog, and says what to write at each target cell:

* **what**: ``"all"`` brings formulas along, their relative references
  shifted to where they land (as plain Paste does); ``"values"`` brings what
  the copied cells showed;
* **op**: ``"add"``, ``"subtract"``, ``"multiply"`` or ``"divide"`` combine
  each copied number with the number already in the target cell. Like
  Excel, a blank copied cell counts as 0 and a blank target counts as 0 when
  adding or subtracting; unlike Excel, multiplying or dividing leaves a
  blank target blank (Excel writes 0, turning "not known" into a real
  zero). Text on either side leaves the target alone, a formula target stays live as ``=(formula)+n``, and a date
  target moves by that many days under add or subtract. An operation always
  uses the copied *values*;
* **skip_blanks**: an empty copied cell leaves the target as it was;
* **transpose**: the copied rows land as columns.

A ``None`` in the result means "leave this cell alone".
"""
from __future__ import annotations

from datetime import timedelta
from typing import Callable, Optional

from .formula import translate
from .schema import is_formula
from .values import as_date, format_number

WHAT = ("all", "values", "formats")
OPS = ("none", "add", "subtract", "multiply", "divide")
_SYMBOL = {"add": "+", "subtract": "-", "multiply": "*", "divide": "/"}


def _number(text) -> Optional[float]:
    if text is None:
        return None
    if isinstance(text, bool):             # TRUE/FALSE is not a number here
        return None
    if isinstance(text, (int, float)):
        return float(text)
    raw = str(text).strip()
    if not raw:
        return 0.0
    try:
        return float(raw)
    except ValueError:
        return None


def _apply(op: str, left: float, right: float) -> Optional[float]:
    if op == "add":
        return left + right
    if op == "subtract":
        return left - right
    if op == "multiply":
        return left * right
    return None if right == 0 else left / right


def combine(op: str, target_source: str, target_value, copied: str
            ) -> Optional[str]:
    """What one target cell becomes when `copied` (a display value) is
    added to, taken from, multiplied into or divided into it; None leaves
    it alone. `target_value` is the cell's computed value."""
    amount = _number(copied)
    if amount is None:                     # copied text: target untouched
        return None
    shown = format_number(amount)
    if is_formula(target_source):
        body = target_source.strip()[1:]
        return f"=({body}){_SYMBOL[op]}{shown}"
    if not str(target_source).strip():
        if op in ("multiply", "divide"):
            return None                    # nothing to scale: stays blank
        start = 0.0
    else:
        start = _number(target_value if target_value is not None
                        else target_source)
    if start is None:
        moment = as_date(str(target_source))
        if moment is not None and op in ("add", "subtract") \
                and amount == int(amount):
            days = int(amount) if op == "add" else -int(amount)
            moved = moment + timedelta(days=days)
            return moved.strftime("%Y-%m-%d")
        return None                        # target text: untouched
    result = _apply(op, start, amount)
    if result is None:                     # dividing by zero
        return f"={format_number(start)}/0"
    return format_number(result)


def special_block(*, values: list[list[str]], at: tuple[int, int],
                  target: Callable[[int, int], tuple[str, object]],
                  sources: Optional[list[list[str]]] = None,
                  origin: Optional[tuple[int, int]] = None,
                  what: str = "all", op: str = "none",
                  skip_blanks: bool = False, transpose: bool = False,
                  fill_to: Optional[tuple[int, int]] = None
                  ) -> list[list[Optional[str]]]:
    """The block to write at `at`. `target(row, col)` gives a target
    cell's (source, computed value). `fill_to` is the (rows, cols) of the
    selection: a single copied cell fills it, as plain Paste does."""
    if not values:
        return []
    if sources is None or origin is None:
        sources, origin = None, None
    rows = len(values)
    cols = max(len(row) for row in values)

    def copied(r, c):
        row = values[r]
        value = row[c] if c < len(row) else ""
        if sources is None:
            return value, value
        src_row = sources[r] if r < len(sources) else []
        return (src_row[c] if c < len(src_row) else ""), value

    if transpose:
        out_rows, out_cols = cols, rows
    else:
        out_rows, out_cols = rows, cols
    single = rows == 1 and cols == 1
    if single and fill_to is not None:
        out_rows, out_cols = max(1, fill_to[0]), max(1, fill_to[1])

    row0, col0 = at
    block = []
    for i in range(out_rows):
        line = []
        for j in range(out_cols):
            if single:
                r, c = 0, 0
            elif transpose:
                r, c = j, i
            else:
                r, c = i, j
            source, value = copied(r, c)
            blank = not str(value).strip() and not str(source).strip()
            if skip_blanks and blank:
                line.append(None)
                continue
            if op != "none":
                line.append(combine(op, *target(row0 + i, col0 + j), value))
                continue
            if what == "all" and sources is not None:
                drow = row0 + i - (origin[0] + r)
                dcol = col0 + j - (origin[1] + c)
                line.append(translate(source, drow, dcol))
            else:
                line.append(value)
        block.append(line)
    return block


def arrange_block(block: list[list], *, transpose: bool = False,
                  fill_to: Optional[tuple[int, int]] = None) -> list[list]:
    """A copied block laid out as Paste Special lays the cells: turned
    when transposed, and one copied cell spread over the selection."""
    if not block:
        return []
    if len(block) == 1 and len(block[0]) == 1 and fill_to is not None:
        return [[block[0][0]] * max(1, fill_to[1])
                for _ in range(max(1, fill_to[0]))]
    if transpose:
        width = max(len(row) for row in block)
        return [[row[j] if j < len(row) else None for row in block]
                for j in range(width)]
    return [list(row) for row in block]


def describe(what: str, op: str, skip_blanks: bool, transpose: bool,
             from_app: bool) -> str:
    """One plain sentence saying what the choices will do."""
    if what == "formats":
        parts = ["Pastes only the copied cells' formats — bold, colours, "
                 "alignment — and leaves the values as they are"]
    elif op == "none":
        if what == "all" and from_app:
            parts = ["Pastes the copied cells with their formulas, which "
                     "adjust to where they land"]
        else:
            parts = ["Pastes what the copied cells show"]
    else:
        verb = {"add": "Adds each copied number to",
                "subtract": "Takes each copied number away from",
                "multiply": "Multiplies",
                "divide": "Divides"}[op]
        tail = {"add": "the number already there",
                "subtract": "the number already there",
                "multiply": "the number already there by each copied number",
                "divide": "the number already there by each copied number"}
        parts = [f"{verb} {tail[op]}"]
    if transpose:
        parts.append("with rows turned into columns")
    if skip_blanks:
        parts.append("leaving cells alone where the copy was empty")
    return ", ".join(parts) + "."
