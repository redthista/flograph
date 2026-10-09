"""Fill Series, Qt-free: Excel's Series dialog (Home ▸ Fill ▸ Series…).

From the first cell's value, each next cell is:

* **linear** — the one before plus the step (1, 3, 5 …);
* **growth** — the one before times the step (2, 4, 8 …);
* **date** — the date before moved on by the step in days, weekdays
  (Saturday and Sunday skipped), months or years. A month on from 31
  January is the last day of February, as EDATE has it;
* **autofill** — the fill handle's own rules (core/sheet/fill.py): Mon →
  Tue, Item 1 → Item 2, formulas shifted.

A *stop* value ends the series at the last value that does not pass it —
and when only one cell is selected, says how far to go.
"""
from __future__ import annotations

import calendar
from datetime import date, timedelta
from typing import Optional, Union

from .fill import _as_date, _decimals, _format_number, _number, fill_values

KINDS = (("linear", "Linear"), ("growth", "Growth"), ("date", "Date"),
         ("autofill", "AutoFill"))
UNITS = (("day", "Day"), ("weekday", "Weekday"), ("month", "Month"),
         ("year", "Year"))
MAX_CELLS = 100_000


def _add_months(day: date, months: int) -> date:
    month0 = day.month - 1 + months
    year, month = day.year + month0 // 12, month0 % 12 + 1
    last = calendar.monthrange(year, month)[1]
    return date(year, month, min(day.day, last))


def _add_weekdays(day: date, n: int) -> date:
    step = 1 if n >= 0 else -1
    while n:
        day += timedelta(days=step)
        if day.weekday() < 5:
            n -= step
    return day


def _date_step(day: date, unit: str, step: int, k: int,
               start: date) -> date:
    """The k-th date after `start` (the previous one is `day`)."""
    if unit == "month":
        return _add_months(start, step * k)      # from the start: no drift
    if unit == "year":
        return _add_months(start, 12 * step * k)
    if unit == "weekday":
        return _add_weekdays(day, step)
    return day + timedelta(days=step)


def check(first: str, kind: str, step: str, stop: str,
          unit: str = "day") -> Optional[str]:
    """Why these choices can't make a series, or None."""
    if kind == "autofill":
        return None if first.strip() else "The first cell is empty."
    if kind == "date":
        if _as_date(first) is None:
            return "The first cell needs a date for a date series."
        if _number(step) is None or float(step) != int(float(step)):
            return "The step is a whole number of days, months …"
        if stop.strip() and _as_date(stop) is None:
            return "The stop value needs to be a date."
        return None
    if _number(first) is None:
        return "The first cell needs a number (or pick Date or AutoFill)."
    if _number(step) is None:
        return "The step needs to be a number."
    if stop.strip() and _number(stop) is None:
        return "The stop value needs to be a number."
    if kind == "growth" and float(step) == 0:
        return "A growth step of 0 would make every value 0."
    return None


def series_values(first: str, count: Optional[int], kind: str,
                  step: str = "1", stop: str = "", unit: str = "day",
                  along: str = "row") -> Union[list[str], str]:
    """The values after `first`: `count` of them (None: as many as it
    takes to reach `stop`), cut short at `stop`. Or why not."""
    why = check(first, kind, step, stop, unit)
    if why:
        return why
    if count is None and not stop.strip() and kind != "autofill":
        return "With one cell selected, give a stop value — or select the " \
               "cells to fill."
    if count is None and kind == "autofill":
        return "AutoFill needs the cells to fill selected."
    limit = MAX_CELLS if count is None else count
    if kind == "autofill":
        return fill_values([first], limit, along=along)
    out: list[str] = []
    if kind == "date":
        start = _as_date(first)
        n = int(float(step))
        end = _as_date(stop) if stop.strip() else None
        if n == 0:
            return "A step of 0 would repeat the same date."
        day = start
        for k in range(1, limit + 1):
            day = _date_step(day, unit, n, k, start)
            if end is not None and (day > end if n > 0 else day < end):
                break
            out.append(day.isoformat())
        return out
    value = float(first)
    by = float(step)
    end = float(stop) if stop.strip() else None
    if count is None and (by == 0 if kind == "linear" else abs(by) == 1):
        return "That step never moves towards the stop value."
    decimals = max(_decimals(first), _decimals(step))
    whole = (value == int(value) and by == int(by)) if kind == "linear" \
        else (value == int(value) and by == int(by) and by != 0)
    rising = by > 0 if kind == "linear" else abs(by) >= 1
    for _ in range(limit):
        value = value + by if kind == "linear" else value * by
        if end is not None and (value > end + 1e-9 if rising
                                else value < end - 1e-9):
            break
        if abs(value) > 1e300:
            break
        out.append(_format_number(value, whole, decimals))
    return out
