"""What the fill handle writes: Excel's AutoFill rules, Qt-free.

Given the cells a drag starts from (the *seed*, in the order the drag runs)
and how many cells it covers beyond them, `fill_values` says what goes in
each. Per seed, in Excel's order:

* **formulas** repeat the seed's pattern with their references shifted by
  how far each copy landed from its source — =A1 dragged down is =A2, =A3;
* **numbers**: two or more continue their step (1, 3 → 5, 7); a lone
  number is copied, unless `series` is asked for (Excel's Ctrl+drag), when
  it counts on by 1;
* **dates** go on a day at a time from a lone date, or by the seed's step;
* **text ending in a number** counts on ("Item 1" → "Item 2"), keeping the
  digits' padding ("Q01" → "Q02");
* **day and month names** continue round the week or year, in the seed's
  spelling (Mon → Tue, January → February, FRI → SAT);
* anything else **repeats** the seed's pattern.

Filling against the grid's direction (up or left) is the same rules with the
seed handed over reversed and `backwards=True`, so 3, 4 dragged up gives 2,
1 and a formula's references shift up.
"""
from __future__ import annotations

import math
import re
from datetime import date, datetime, timedelta
from typing import Optional

from .formula import translate
from .schema import is_formula, normalize_date

_DAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday",
         "sunday")
_MONTHS = ("january", "february", "march", "april", "may", "june", "july",
           "august", "september", "october", "november", "december")
_TRAILING_NUMBER = re.compile(r"^(.*?)(\d+)$")


def _number(text: str) -> Optional[float]:
    text = text.strip()
    if not text:
        return None
    try:
        value = float(text)
    except ValueError:
        return None
    return value if math.isfinite(value) else None


def _format_number(value: float, as_int: bool, decimals: int) -> str:
    if as_int:
        return str(int(round(value)))
    text = f"{value:.{decimals}f}" if decimals else repr(value)
    return text.rstrip("0").rstrip(".") if "." in text else text


def _decimals(text: str) -> int:
    text = text.strip()
    return len(text.split(".", 1)[1]) if "." in text else 0


def _as_date(text: str) -> Optional[date]:
    if not text.strip() or _number(text) is not None:
        return None
    iso = normalize_date(text)
    if iso is None or len(iso) != 10:   # times are left alone
        return None
    return datetime.strptime(iso, "%Y-%m-%d").date()


def _named(text: str):
    """(list, index, style) when `text` names a day or month — in full or as
    its first three letters — else None. Style keeps the seed's case."""
    word = text.strip()
    low = word.casefold()
    for names in (_DAYS, _MONTHS):
        for i, name in enumerate(names):
            if low == name:
                return names, i, "full", word
            if low == name[:3]:
                return names, i, "short", word
    return None


def _spell(names, index: int, style: str, like: str) -> str:
    name = names[index % len(names)]
    if style == "short":
        name = name[:3]
    if like.isupper():
        return name.upper()
    if like.islower():
        return name
    return name.capitalize()


def _steps(values: list[float]) -> Optional[float]:
    """The common step of a seed, or the average one when it wobbles
    (Excel fits a line; the average step is that line's slope for an evenly
    spaced seed, which is what a dragged seed always is)."""
    if len(values) < 2:
        return None
    return (values[-1] - values[0]) / (len(values) - 1)


def fill_values(seed: list[str], count: int, *, along: str = "row",
                backwards: bool = False, series: bool = False) -> list[str]:
    """The `count` cells a fill writes after `seed`.

    `along` is "row" when the fill runs down/up a column (formulas shift
    rows) and "col" when it runs across a row (they shift columns)."""
    seed = ["" if s is None else str(s) for s in seed]
    if count <= 0 or not seed:
        return []
    n = len(seed)
    sign = -1 if backwards else 1

    def shift(text: str, distance: int) -> str:
        d = distance * sign
        return translate(text, d, 0) if along == "row" else translate(
            text, 0, d)

    # formulas anywhere in the seed: the pattern repeats, each copy shifted
    # by its distance from the cell it copies (plain values ride along)
    if any(is_formula(s) for s in seed):
        out = []
        for k in range(count):
            src = k % n
            out.append(shift(seed[src], n + k - src))
        return out

    numbers = [_number(s) for s in seed]
    if all(v is not None for v in numbers):
        if n == 1 and not series:
            return [seed[0]] * count
        step = _steps(numbers) if n > 1 else 1.0
        as_int = (all(float(v).is_integer() for v in numbers)
                  and float(step).is_integer())
        decimals = max(_decimals(s) for s in seed)
        return [_format_number(numbers[-1] + step * (k + 1), as_int,
                               decimals) for k in range(count)]

    dates = [_as_date(s) for s in seed]
    if all(d is not None for d in dates):
        days = ((dates[-1] - dates[0]).days / (n - 1)) if n > 1 else 1
        days = int(round(days)) or 1
        return [(dates[-1] + timedelta(days=days * (k + 1))).isoformat()
                for k in range(count)]

    named = [_named(s) for s in seed]
    if all(v is not None for v in named) and len({v[0] for v in named}) == 1:
        names = named[0][0]
        indexes = [v[1] for v in named]
        step = 1
        if n > 1:
            step = (indexes[1] - indexes[0]) % len(names) or 1
        style, like = named[-1][2], named[-1][3]
        return [_spell(names, indexes[-1] + step * (k + 1), style, like)
                for k in range(count)]

    matches = [_TRAILING_NUMBER.match(s.strip()) for s in seed]
    if all(matches) and len({m.group(1) for m in matches}) == 1:
        prefix = matches[0].group(1)
        values = [int(m.group(2)) for m in matches]
        width = len(matches[-1].group(2))
        padded = matches[-1].group(2).startswith("0") and width > 1
        step = int(round(_steps(values))) if n > 1 else 1
        step = step or 1
        out = []
        for k in range(count):
            value = values[-1] + step * (k + 1)
            digits = str(abs(value)).zfill(width) if padded else str(
                abs(value))
            out.append(f"{prefix}{'-' if value < 0 else ''}{digits}")
        return out

    return [seed[k % n] for k in range(count)]
