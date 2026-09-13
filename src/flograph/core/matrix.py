"""Pivoting a table (X1): the Pivot node's arithmetic, and Show Table's
**Matrix** mode, which pivots inside the card instead of needing a Pivot
node wired in front of it.

The matrix keeps every conditional-formatting rule, and a rule may read the
rows *before* the pivot as well as the cells after it. That is the reason
to have it: a table of values with a checker column beside each one, there
only to feed an icon, becomes one long table with a status column, one rule
on its rows, and a pivot of the result.

How a rule reaches across the pivot: nothing downstream learns anything
new. The card, the dashboard tile and the printed page draw the matrix
with the rule engine they already have. Instead, the column a rule reads is
pivoted *alongside* the values — into hidden helper columns, one per cell,
in the same `pivot_table` call so they cannot fall out of line — and the
rule is rewritten, one per cell, to read its own cell's helper. Where a
cell is built from several rows, the helper settles which verdict wins:

* a highlight flags the cell when **any** of its rows passes;
* a map (`iconmap`, `colormap`) takes the value **listed first in the
  map** among its rows — write the worst case first and it wins;
* a note joins every row's note, each once;
* a `by` column is aggregated the way the values are.

A rule that reads nothing but the value itself (`value > 90 => bg green`,
`value scale green`) is about the cell, so it simply moves onto the cells
built from that value; a colour scale, bar or icon set is then measured
across all of them at once (`Rule.pool`), the way a matrix heatmap is read,
rather than one column at a time.

Qt-free.
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from typing import Any

from .table_format import (
    Rule, _column_list, _condition_mask, _is_glob, _is_missing,
    column_matches, hidden_columns, index_shown, rule_summary,
    rules_from_style, shown_columns)

AGGREGATIONS = ("sum", "mean", "median", "min", "max", "count",
                "distinct count", "std", "first")
ORDERS = ("as they appear", "sorted")
HEADERS = ("value first", "values only", "pivot first")
TOTALS = ("off", "rows + columns", "rows only", "columns only")

#: display names the Pivot node offers for pandas aggfuncs under other names
_AGG_FUNCS = {"distinct count": "nunique"}

#: modes measured against the spread of values — pooled across a matrix
_MEASURED = ("color_scale", "data_bar", "icons")
#: rules that shape the table rather than paint a cell
_LAYOUT = ("column_width", "align", "header_label", "wrap", "sort",
           "row_height")
#: what a highlight's helper holds for a cell one of its rows passed
_YES = "yes"


def column_list(value: Any) -> list[str]:
    """A `columns` param's value as a list of names."""
    return _column_list(value)


# ------------------------------------------------------------- the pivot

def flat_names(columns) -> list[str]:
    """The Pivot node's column names: a top level carrying one label (the
    value's name, when one value is pivoted) is dropped, and whatever
    levels are left are joined with "_"."""
    cols = columns
    while cols.nlevels > 1 and cols.get_level_values(0).nunique() == 1:
        cols = cols.droplevel(0)
    if cols.nlevels > 1:
        return ["_".join(str(part) for part in col) for col in cols]
    return [str(c) for c in cols]


def _unique_names(names) -> list[str]:
    """`names` with later duplicates suffixed ` (2)`, ` (3)` — a pivot must
    hand downstream real columns, and bare pivot values collide as soon as
    two value columns share them."""
    taken: set[str] = set()
    out: list[str] = []
    for name in names:
        candidate, n = name, 2
        while candidate in taken:
            candidate, n = f"{name} ({n})", n + 1
        taken.add(candidate)
        out.append(candidate)
    return out


def _missing_key(value):
    """A dict key for a pivot/index value that survives NaN: NaN never
    equals itself, so lookups across two groupbys would miss."""
    return "\x00missing" if _is_missing(value) else value


def pivot(table, index, columns, values=None, agg="sum",
          order="as they appear", headers="value first", separator="_",
          fill=None, totals="off", total_label="Total"):
    """`table` pivoted: a row per `index` group, a column per value of
    `columns`, each cell `agg` of the rows behind it. Shared by the Pivot
    node and Matrix mode, so the two cannot come to disagree.

    pandas sorts both axes unless told not to, and `sort=False` is exactly
    "first seen wins" — for the rows, for the pivot values, and, with more
    than one value column, within each of them. `dropna=False` keeps a
    pivot value whose cells are all empty as a blank column rather than
    dropping it, the way Power Query keeps every pivoted value; `fill`
    writes a value into those blanks.

    `headers` decides what the new columns are called: with one value
    column they are always the bare pivot values, with several "value
    first" (`revenue_Jan`) and "pivot first" (`Jan_revenue`) carry the
    value name on either side of `separator`, while "values only" drops
    it and dedupes collisions with ` (2)`, ` (3)`.

    `totals` adds a `total_label` row and/or column aggregated from the
    underlying rows with the same `agg` — a mean total is the mean of the
    rows, not of the displayed cells.
    """
    import pandas as pd

    index, columns = list(index), list(columns)
    agg = agg if agg in AGGREGATIONS else "sum"
    func = _AGG_FUNCS.get(agg, agg)
    order = order if order in ORDERS else ORDERS[0]
    headers = headers if headers in HEADERS else HEADERS[0]
    separator = "_" if separator is None else str(separator)
    totals = totals if totals in TOTALS else TOTALS[0]
    total_label = str(total_label).strip() or "Total"
    if values is None:
        # pandas' own answer to values=None: every column the pivot does
        # not consume — resolved here so the totals below aggregate the
        # same columns the cells were built from.
        taken = set(index) | set(columns)
        values = [c for c in table.columns if c not in taken]
        if not values:
            raise ValueError("no columns left to pivot — list the Value "
                             "columns explicitly")
    values = list(values)
    multi = len(values) > 1
    by_sort = order == "sorted"

    pivoted = table.pivot_table(index=index, columns=columns, values=values,
                                aggfunc=func, sort=by_sort, dropna=False)
    tuples = [t if isinstance(t, tuple) else (t,) for t in pivoted.columns]
    raw: list[tuple] = []     # (name, value column, pivot key) per column
    for tup in tuples:
        # `tup[0]` is the value's own label only when several are pivoted;
        # with one, the whole tuple after it is the pivot's values.
        ivo = tup[0] if multi else values[0]
        disp = str(ivo)
        parts = [str(p) for p in tup[1:]] if len(tup) > 1 else [str(tup[0])]
        across = separator.join(parts)
        if not multi or headers == "values only":
            name = across
        elif headers == "pivot first":
            name = f"{across}{separator}{disp}" if across else disp
        else:
            name = f"{disp}{separator}{across}" if across else disp
        key = tuple(_missing_key(p) for p in tup[1:]) if len(tup) > 1 \
            else (_missing_key(tup[0]),)
        if len(columns) == 1 and isinstance(key, tuple):
            key = key[0]
        raw.append((name, ivo, key))
    names = _unique_names([name for name, _, _ in raw])
    pivoted.columns = names
    frame = pivoted.reset_index()

    want_rows = totals in ("rows + columns", "rows only")
    want_cols = totals in ("rows + columns", "columns only")
    total_cols: list[str] = []
    if want_rows:
        grouped = table.groupby(index, sort=by_sort,
                                dropna=False)[values].agg(func).reset_index()
        taken_names = set(frame.columns)
        rename: dict = {}
        for value in values:
            if not multi:
                base = total_label
            elif headers == "pivot first":
                base = f"{total_label}{separator}{value}"
            else:
                base = f"{value}{separator}{total_label}"
            candidate, n = base, 2
            while candidate in taken_names:
                candidate, n = f"{base} ({n})", n + 1
            taken_names.add(candidate)
            rename[value] = candidate
            total_cols.append(candidate)
        frame = frame.merge(grouped.rename(columns=rename), on=index,
                            how="left")

    if want_cols:
        per_pivot = table.groupby(columns, sort=by_sort,
                                  dropna=False)[values].agg(func)
        lookup: dict = {}
        for key, row in zip(per_pivot.index, per_pivot.itertuples(
                index=False, name=None)):
            if len(columns) == 1:
                norm = _missing_key(key)
            else:
                norm = tuple(_missing_key(p) for p in key)
            lookup[norm] = dict(zip(values, row))
        grand: dict = {}
        for value in values:
            series = table[value]
            if func == "first":
                # a Series has no "first" reduction; GroupBy.first skips
                # NaN, so the grand total is the first set value.
                pos = series.first_valid_index()
                grand[value] = series.loc[pos] if pos is not None else None
            else:
                grand[value] = series.agg(func)
        col_of = dict(zip(names, raw))
        row = {name: lookup.get(key, {}).get(value)
               for name, (_label, value, key) in col_of.items()}
        for value, total in zip(values, total_cols):
            row[total] = grand[value]
        total_row = {c: (total_label if pos == 0 else "")
                     for pos, c in enumerate(index)}
        for name in list(names) + total_cols:
            total_row[name] = row.get(name)
        frame = pd.concat([frame, pd.DataFrame([total_row])],
                          ignore_index=True)

    if fill is not None:
        data = [c for c in frame.columns if c not in index]
        frame[data] = frame[data].fillna(fill)
    return frame


# ----------------------------------------- how several rows become one

def _any_row(series):
    """A highlight's helper: the cell passes if any of its rows did."""
    return _YES if bool(series.fillna(False).astype(bool).any()) else None


def _first_listed(mapping: dict):
    """A map's helper: the value listed first in the map, among the
    cell's rows — so the case written first wins a cell built from a
    breach and an ok."""
    order = [str(k).strip() for k in (mapping or {})]

    def combine(series):
        present = [str(v).strip() for v in series if not _is_missing(v)]
        for key in order:
            if key in present:
                return key
        return present[0] if present else None
    return combine


def _test_label(column: str, rule) -> str:
    """What a highlight's carried column is called: its test, so the
    column says what it holds rather than borrowing the name of the column
    it tested ("status = breach", not a second "status")."""
    if rule.op in ("empty", "notempty"):
        return f"{column} {'is empty' if rule.op == 'empty' else 'is set'}"
    shown = (" and ".join(str(v) for v in rule.value)
             if isinstance(rule.value, (list, tuple)) else str(rule.value))
    return f"{column} {rule.op} {shown}"


def _joined(series):
    """A note's helper: every row's note, each once, one to a line."""
    notes = []
    for v in series:
        if _is_missing(v) or not str(v).strip():
            continue
        if str(v).strip() not in notes:
            notes.append(str(v).strip())
    return "\n".join(notes) if notes else None


# ------------------------------------------------------------ the matrix

@dataclass
class Matrix:
    frame: Any                  # the pivoted table, helper columns included
    style: dict                 # the style, rewritten onto the matrix
    notes: list = field(default_factory=list)   # for the node's log


def default_values(table, rows, columns, read=()) -> list[str]:
    """Every numeric column that is not a row, a column, or read by a rule:
    the Pivot node's "empty = all remaining numeric", less the checker
    columns a rule reads rather than shows."""
    from pandas.api.types import is_numeric_dtype
    taken = set(rows) | set(columns) | set(read)
    return [str(c) for c in table.columns
            if str(c) not in taken and is_numeric_dtype(table[c])]


def _matching(patterns, names) -> list[str]:
    return [n for n in names if patterns and column_matches(patterns, n)]


def build_matrix(table, rows, columns, values=(), agg="sum",
                 order="as they appear", style=None) -> Matrix:
    """`table` as a matrix, with `style`'s rules carried onto its cells.

    Raises ValueError, naming the setting to fix, when the rows or columns
    are missing — the card shows it the way any node shows a failure.
    """
    import pandas as pd

    rows, columns, values = list(rows), list(columns), list(values or ())
    if not rows:
        raise ValueError("Matrix: pick the Rows — the column whose values "
                         "run down the side")
    if not columns:
        raise ValueError("Matrix: pick the Columns — the column whose values "
                         "run across the top")
    names = [str(c) for c in table.columns]
    absent = [c for c in rows + columns + values if c not in names]
    if absent:
        raise ValueError("Matrix: not in the table: " + ", ".join(absent))
    agg = agg if agg in AGGREGATIONS else "sum"
    order = order if order in ORDERS else ORDERS[0]

    rules = rules_from_style(style)
    read = {r.source for r in rules if r.source and r.source not in rows}
    if not values:
        values = default_values(table, rows, columns, read)
    if not values:
        raise ValueError("Matrix: no numeric column is left to fill the "
                         "cells — pick the Values")

    notes: list[str] = []
    work = table.copy(deep=False)
    aggfunc: dict = {v: agg for v in values}
    #: rule index -> how it is rewritten once the pivot has been made:
    #: ("keep",) | ("move", value) | ("carry", value, helper, label)
    #: | ("row_carry", helper, label) | ("row_cells", value) | ("drop",)
    plans: list[tuple] = []

    def helper(values_series, combine, _label) -> str:
        """Stage a column to pivot beside the values, combined per cell by
        `combine`; `_label` is only for reading the call."""
        key = f"\x00carry{len(aggfunc)}"
        work[key] = values_series
        aggfunc[key] = combine
        return key

    for rule in rules:
        hits = _matching(rule.columns, values)

        if rule.mode == "highlight" and rule.scope == "row":
            tested = rule.source or next(
                (c for c in names if rule.columns
                 and column_matches(rule.columns, c)), None)
            if tested is None or tested in rows or tested not in names:
                plans.append(("keep",))
            elif tested in values:
                plans.append(("row_cells", tested))
            else:
                mask = _condition_mask(table[tested], rule.op, rule.value)
                label = _test_label(tested, rule)
                plans.append(("row_carry",
                              helper(mask, _any_row, label), label))
            continue

        if rule.mode in _LAYOUT:
            if not hits:
                plans.append(("keep",))
            elif rule.mode in ("sort", "header_label"):
                notes.append(f"“{rule_summary(rule)}” was left out: a matrix "
                             f"has a column per value of "
                             f"{', '.join(columns)}, so it can't be "
                             f"{'sorted by' if rule.mode == 'sort' else 'relabelled as'}"
                             f" one of them")
                plans.append(("drop",))
            else:
                plans.append(("move", hits[0]))
            continue

        if not hits:
            drawn = [c for c in rule.columns if c in names]
            if drawn and all(c not in rows for c in drawn):
                notes.append(f"“{rule_summary(rule)}” was left out: "
                             f"{', '.join(drawn)} is not in the matrix — a "
                             f"rule can read it through the value it goes "
                             f"with instead")
                plans.append(("drop",))
            else:
                plans.append(("keep",))
            continue

        value = hits[0]
        source = rule.source
        if not source or source == value or source in rows:
            plans.append(("move", value))
            continue
        if source not in names:
            plans.append(("move", value))      # reported as a missing column
            continue
        if rule.mode == "highlight":
            mask = _condition_mask(table[source], rule.op, rule.value)
            label = _test_label(source, rule)
            plans.append(("carry", value, helper(mask, _any_row, label),
                          label))
        elif rule.mode in ("icon_map", "color_map"):
            plans.append(("carry", value,
                          helper(table[source], _first_listed(rule.mapping),
                                 source), source))
        elif rule.mode == "tooltip":
            plans.append(("carry", value,
                          helper(table[source], _joined, source), source))
        elif rule.mode in _MEASURED:
            plans.append(("carry", value, helper(table[source], agg, source),
                          source))
        else:
            notes.append(f"“{rule_summary(rule)}” was left out: its colours "
                         f"are chosen per column, so they would not agree "
                         f"across a matrix")
            plans.append(("drop",))

    helpers = [k for k in aggfunc if k not in values]
    pivoted = work.pivot_table(index=rows, columns=columns,
                               values=values + helpers, aggfunc=aggfunc,
                               sort=order == "sorted")

    value_keys = [c for c in pivoted.columns if c[0] in values]
    cell_names = flat_names(pd.MultiIndex.from_tuples(value_keys))
    name_of = dict(zip(value_keys, cell_names))
    cells = {v: [name_of[k] for k in value_keys if k[0] == v] for v in values}
    frame = pivoted[value_keys].copy()
    frame.columns = cell_names
    taken = set(cell_names) | set(rows)

    def unique(name: str) -> str:
        out, n = name, 2
        while out in taken:
            out, n = f"{name} ({n})", n + 1
        taken.add(out)
        return out

    #: helper key -> {cell name: helper column name}
    helper_cells: dict = {}
    #: helper key -> the one row-flag column name
    helper_rows: dict = {}
    hidden_helpers: list[str] = []
    for plan in plans:
        if plan[0] == "carry":
            _kind, value, key, label = plan
            placed = {}
            for vk in value_keys:
                if vk[0] != value:
                    continue
                hk = (key, *vk[1:])
                if hk in pivoted.columns:
                    column = unique(f"{label} · {name_of[vk]}")
                    frame[column] = pivoted[hk]
                    placed[name_of[vk]] = column
                    hidden_helpers.append(column)
            helper_cells[key] = placed
        elif plan[0] == "row_carry":
            _kind, key, label = plan
            parts = [c for c in pivoted.columns if c[0] == key]
            flag = (pivoted[parts].notna().any(axis=1) if parts
                    else pd.Series(False, index=pivoted.index))
            column = unique(f"{label} · row")
            frame[column] = flag.map(lambda hit: _YES if hit else None)
            helper_rows[key] = column
            hidden_helpers.append(column)

    new_rules: list[Rule] = []
    for rule, plan in zip(rules, plans):
        kind = plan[0]
        if kind == "keep":
            new_rules.append(rule)
        elif kind == "move":
            moved = cells[plan[1]]
            new_rules.append(dataclasses.replace(
                rule, columns=list(moved),
                pool=list(moved) if rule.mode in _MEASURED else []))
        elif kind == "carry":
            _kind, value, key, _label = plan
            placed = helper_cells.get(key, {})
            pooled = list(placed.values()) if rule.mode in _MEASURED else []
            for cell, column in placed.items():
                changes = {"columns": [cell], "source": column, "pool": pooled}
                if rule.mode == "highlight":
                    changes.update(op="notempty", value=None)
                new_rules.append(dataclasses.replace(rule, **changes))
        elif kind == "row_carry":
            new_rules.append(dataclasses.replace(
                rule, columns=[], source=helper_rows[plan[1]],
                op="notempty", value=None))
        elif kind == "row_cells":
            value = plan[1]
            hit = pd.Series(False, index=frame.index)
            for cell in cells[value]:
                try:
                    hit |= _condition_mask(frame[cell], rule.op,
                                           rule.value).fillna(False)
                except Exception:
                    continue
            column = unique(f"{value} · row")
            frame[column] = hit.map(lambda passed: _YES if passed else None)
            hidden_helpers.append(column)
            new_rules.append(dataclasses.replace(
                rule, columns=[], source=column, op="notempty", value=None))

    frame = frame.reset_index()
    present = {str(c) for c in frame.columns}

    def spread(listed) -> list[str]:
        """A value's name stands for every cell built from it; a column the
        matrix no longer has (the pivot column, a status it read) is let
        go quietly — there is nothing left of it to show or hide."""
        out: list[str] = []
        for name in listed:
            if name in cells:
                out.extend(cells[name])
            elif name in present or _is_glob(name):
                out.append(name)
        return out

    payload = {
        "rules": [r.to_dict() for r in new_rules],
        "show": spread(shown_columns(style)),
        "hide": list(dict.fromkeys(spread(hidden_columns(style))
                                   + hidden_helpers)),
        "errors": list((style or {}).get("errors") or [])
        if isinstance(style, dict) else [],
    }
    if not index_shown(style):
        payload["index"] = False
    return Matrix(frame=frame, style=payload, notes=notes)
