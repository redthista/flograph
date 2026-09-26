"""Total rows and grouped tables — what Show Table adds *around* its rows.

Qt-free, and pandas is imported inside the functions that need it, as
everywhere in core. The card (`ui/inspector/pandas_model`), the dashboard
tile (the same model) and the printed page (`core/table_html`) all ask this
module the same two questions — which rows go where, and how each extra row
is drawn — so a report cannot come to disagree with the dashboard it came
off.

**What a total row is.** A row the table does not have, laid out among the
rows it does: a grand total at the top and/or bottom, and — in a grouped
table — a header row per group (carrying its subtotals, if asked) and/or a
subtotal row under each. They are a *view*: sorting moves the data rows and
never these, a heatmap is measured over the data rows only (a total is
always the largest value, and would flatten every scale it joined), and the
table leaving the node is the one that arrived unless **Totals in output**
says otherwise (`with_totals`).

**How a column is totalled** is decided per column, by rules, the last one
naming a column winning — the same bargain every other rule strikes::

    total sum                     # every number column, summed
    total sum top "Grand total"   # …placed at the top, and called that
    price     total average       # one column differently
    region    total "All regions" # a column that says something instead
    id        total none          # and one left blank

A **grouped** table gathers rows that share a value into a group with a
header row you can fold away. Groups come in the order they first appear
in the (sorted) table — so sorting by a number puts the group holding the
biggest row first — and nest, outermost first::

    group region, product
    group closed                  # start folded (open / closed / first)
    subtotal below                # above (the header) / below / both / none

The rows themselves are laid out as one array of integers (`Layout.entries`)
— a data row as its position in the frame, an extra row as ``-(i + 1)`` for
``specials[i]`` — so a million-row table costs one int64 array, and folding
a group is rebuilding that array, not the frame.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Optional

# ------------------------------------------------------------ aggregations

#: Every way a column can be totalled, in the order a menu lists them.
AGGREGATIONS = ("sum", "average", "median", "min", "max", "range", "count",
                "rows", "distinct", "std", "variance", "first", "last",
                "mode")

#: What each one means, for a tooltip or the handbook.
AGGREGATION_HELP = {
    "sum": "added up",
    "average": "the mean",
    "median": "the middle value",
    "min": "the smallest",
    "max": "the largest",
    "range": "largest minus smallest",
    "count": "how many cells have a value",
    "rows": "how many rows, blanks included",
    "distinct": "how many different values",
    "std": "standard deviation",
    "variance": "variance",
    "first": "the first value set",
    "last": "the last value set",
    "mode": "the commonest value",
}

#: Other spellings people type. `mean`/`avg` are what a spreadsheet calls it.
_AGG_ALIASES = {"mean": "average", "avg": "average", "total": "sum",
                "n": "count", "unique": "distinct", "nunique": "distinct",
                "stdev": "std", "sd": "std", "var": "variance",
                "size": "rows", "commonest": "mode", "minimum": "min",
                "maximum": "max"}

#: The aggregations whose answer is in the column's own units — a summed
#: money column is money, so the column's `format $,.0f` applies to it. A
#: count of the same column is not money, and must not print as `$12`.
UNIT_AGGS = frozenset({"sum", "average", "median", "min", "max", "range",
                       "first", "last", "mode", "std"})

#: The aggregations that only mean anything over numbers. Asked of a text
#: column they give a blank rather than pandas' idea of a sum of strings,
#: which is every string glued together.
_NUMBER_AGGS = frozenset({"sum", "average", "median", "range", "std",
                          "variance"})

#: The pandas groupby reduction for each, where there is one.
_PANDAS = {"sum": "sum", "average": "mean", "median": "median", "min": "min",
           "max": "max", "count": "count", "rows": "size",
           "distinct": "nunique", "std": "std", "variance": "var",
           "first": "first", "last": "last"}

#: Where the grand total goes.
TOTAL_PLACES = ("bottom", "top", "both", "none")
_PLACE_WORDS = {"bottom": "bottom", "below": "bottom", "end": "bottom",
                "top": "top", "above": "top", "start": "top",
                "both": "both", "none": "none", "off": "none",
                "hidden": "none"}

#: Where a group's subtotals go: on its header row, on a row of their own
#: under the group, both, or nowhere.
SUBTOTAL_PLACES = ("above", "below", "both", "none")
_SUBTOTAL_WORDS = {"above": "above", "top": "above", "header": "above",
                   "below": "below", "bottom": "below", "footer": "below",
                   "under": "below", "both": "both", "none": "none",
                   "off": "none"}

#: How groups start: all open, all folded, or the outer level open.
GROUP_OPENS = ("open", "closed", "first")
_OPEN_WORDS = {"open": "open", "expanded": "open", "closed": "closed",
               "collapsed": "closed", "folded": "closed", "first": "first",
               "outer": "first"}

#: The kinds of row a rule can be aimed at with `on …`, and the words for
#: them. `subtotal` means every row that carries a group's subtotal — the
#: header row and the row under it — because that is what the numbers are.
ROW_KINDS = ("data", "total", "group", "subtotal")
ON_WORDS = {
    "total": ("total",), "grand": ("total",),
    "subtotal": ("group", "subtotal"), "subtotals": ("group", "subtotal"),
    "group": ("group",), "groups": ("group",), "header": ("group",),
    "headers": ("group",),
    "totals": ("total", "group", "subtotal"),
    "all": ROW_KINDS, "every": ROW_KINDS, "everything": ROW_KINDS,
    "data": ("data",), "rows": ("data",),
}

#: The words that may lead a `=> style` line to paint a kind of row whole.
STYLE_WORDS = {"total": ("total",), "totals": ("total", "group", "subtotal"),
               "subtotal": ("group", "subtotal"),
               "subtotals": ("group", "subtotal"),
               "group": ("group",), "groups": ("group",)}


def canonical_agg(word: Any) -> Optional[str]:
    """`word` as one of AGGREGATIONS, or None if it is not one."""
    w = str(word or "").strip().lower()
    w = _AGG_ALIASES.get(w, w)
    return w if w in AGGREGATIONS else None


def place_word(word: Any) -> Optional[str]:
    return _PLACE_WORDS.get(str(word or "").strip().lower())


def subtotal_word(word: Any) -> Optional[str]:
    return _SUBTOTAL_WORDS.get(str(word or "").strip().lower())


def open_word(word: Any) -> Optional[str]:
    return _OPEN_WORDS.get(str(word or "").strip().lower())


def _kind_of(series) -> str:
    """"number", "bool", "date" or "text" — what an aggregation may ask."""
    from pandas.api.types import (is_bool_dtype, is_datetime64_any_dtype,
                                  is_numeric_dtype, is_timedelta64_dtype)
    dtype = series.dtype
    if is_bool_dtype(dtype):
        return "bool"
    if is_numeric_dtype(dtype):
        return "number"
    if is_datetime64_any_dtype(dtype) or is_timedelta64_dtype(dtype):
        return "date"
    return "text"


def _allowed(kind: str, how: str) -> bool:
    if how not in _NUMBER_AGGS:
        return True
    if kind == "number":
        return True
    if kind == "bool":
        return how in ("sum", "average")      # how many true, what share
    if kind == "date":
        return how in ("average", "median", "range")
    return False


def _scalar(value: Any) -> Any:
    """A numpy scalar as its Python value; NaN and NaT as None."""
    try:
        if value is None:
            return None
        if hasattr(value, "item") and not hasattr(value, "tz"):
            value = value.item()
        if isinstance(value, float) and math.isnan(value):
            return None
        import pandas as pd
        if value is pd.NaT or (not isinstance(value, (list, tuple, dict))
                               and pd.isna(value)):
            return None
    except (TypeError, ValueError):
        pass
    return value


def aggregate(series, how: str) -> Any:
    """`series` reduced by `how` — one of AGGREGATIONS — or None where the
    question has no answer (a sum of text, the mean of nothing).

    Blanks are skipped, as a spreadsheet skips them, except by `rows`,
    which is the one that exists to count them."""
    how = canonical_agg(how)
    if how is None:
        return None
    if how == "rows":
        return int(len(series))
    kind = _kind_of(series)
    if not _allowed(kind, how):
        return None
    values = series.dropna()
    if how == "count":
        return int(len(values))
    if how == "distinct":
        return int(values.nunique())
    if not len(values):
        return None
    try:
        if kind == "bool" and how in ("sum", "average"):
            values = values.astype(int)
        if how == "first":
            return _scalar(values.iloc[0])
        if how == "last":
            return _scalar(values.iloc[-1])
        if how == "mode":
            return _scalar(values.value_counts(sort=True).index[0])
        if how == "range":
            return _scalar(values.max() - values.min())
        return _scalar(getattr(values, _PANDAS[how])())
    except Exception:
        return None


def column_of(frame, name):
    """The column called `name` (as text) — a frame's labels need not be
    strings, and every name this module holds is one."""
    names = [str(c) for c in frame.columns]
    return frame.iloc[:, names.index(str(name))]


def _grouped(frame, keys, column, how) -> dict:
    """{group key: `how` of `column`} over one grouping, in one pass.

    `keys` are integer code arrays, so a group key is a tuple of ints and
    a NaN group value (a code of its own) groups like any other."""
    import pandas as pd

    series = column_of(frame, column) if column is not None else None
    grouper = [pd.Series(k, index=frame.index) for k in keys]
    out: dict = {}
    if how == "rows":
        sizes = frame.groupby(grouper, sort=False).size()
        return {_key(k): int(v) for k, v in sizes.items()}
    kind = _kind_of(series)
    if not _allowed(kind, how):
        return {}
    if kind == "bool" and how in ("sum", "average"):
        series = series.astype("Int64")
    grouped = series.groupby(grouper, sort=False)
    try:
        if how == "range":
            result = grouped.max() - grouped.min()
        elif how == "mode":
            result = grouped.agg(
                lambda s: (s.dropna().value_counts(sort=True).index[0]
                           if s.notna().any() else None))
        else:
            result = grouped.agg(_PANDAS[how])
    except Exception:
        # one group that cannot be reduced (mixed types in an object
        # column) and the column is reduced a group at a time instead
        for key, part in grouped:
            out[_key(key)] = aggregate(part, how)
        return out
    for key, value in result.items():
        out[_key(key)] = (int(value) if how in ("count", "distinct")
                          else _scalar(value))
    return out


def _key(key) -> tuple:
    return tuple(int(k) for k in key) if isinstance(key, tuple) \
        else (int(key),)


# ------------------------------------------------------------------ plan

@dataclass
class Plan:
    """What a table's rules ask for around its rows."""
    #: column -> ("agg", how) | ("text", words). A column absent is blank.
    per_column: dict = field(default_factory=dict)
    place: str = "bottom"
    label: str = "Total"
    group_by: list = field(default_factory=list)
    group_open: str = "open"
    subtotal_place: str = "above"
    #: what a subtotal row says after its group: "North Total"
    subtotal_label: str = "Total"
    #: a total asked for with no column able to take it (`total sum` on a
    #: table of text): said in the log rather than drawn as an empty row
    notes: list = field(default_factory=list)

    @property
    def has_total(self) -> bool:
        return bool(self.per_column) and self.place != "none"

    @property
    def grouped(self) -> bool:
        return bool(self.group_by)

    @property
    def active(self) -> bool:
        return self.has_total or self.grouped

    def how(self, column) -> Optional[tuple]:
        return self.per_column.get(str(column))


#: The rule modes this module reads. None of them paints a data cell.
TOTAL_MODES = frozenset({"total", "subtotal", "group", "total_style"})


def plan_from_rules(rules, frame) -> Plan:
    """The Plan `rules` describe for `frame`.

    Later lines win, column by column: `total sum` then `price total
    average` averages price and sums the rest; the other way round sums
    everything, because the blanket line came last."""
    from .table_format import expand_columns

    plan = Plan()
    if frame is None or not hasattr(frame, "columns") or not any(
            getattr(r, "mode", None) in TOTAL_MODES for r in rules or ()):
        return plan
    names = [str(c) for c in frame.columns]
    known = set(names)
    grouped_by: list = []
    for rule in rules or ():
        mode = getattr(rule, "mode", None)
        if mode == "group":
            if rule.columns:
                grouped_by = [c for c in expand_columns(rule.columns, names)
                              if c in known]
            if rule.total_place:
                plan.group_open = rule.total_place
        elif mode == "subtotal":
            if rule.total_place:
                plan.subtotal_place = rule.total_place
            if rule.label:
                plan.subtotal_label = rule.label
        elif mode == "total":
            if rule.total_place:
                plan.place = rule.total_place
            if rule.label:
                plan.label = rule.label
            if rule.columns:
                targets = [c for c in expand_columns(rule.columns, names)
                           if c in known]
            elif rule.total_agg or rule.total_text is not None:
                targets = [c for c in names
                           if _kind_of(column_of(frame, c)) == "number"]
                if not targets:
                    plan.notes.append(
                        f"“total {rule.total_agg}” found no number column "
                        f"to total — name the columns: "
                        f"“column total {rule.total_agg}”")
            else:
                targets = []
            for column in targets:
                if rule.total_text is not None:
                    plan.per_column[column] = ("text", rule.total_text)
                elif rule.total_agg == "none":
                    plan.per_column.pop(column, None)
                elif rule.total_agg:
                    plan.per_column[column] = ("agg", rule.total_agg)
    plan.group_by = grouped_by
    # a grouping column is written in the group's header; totalling it too
    # would put a number where its name goes
    for column in grouped_by:
        plan.per_column.pop(column, None)
    return plan


# ---------------------------------------------------------------- layout

@dataclass
class Special:
    """One row the table does not have: a total, a group header, or the
    subtotal row under a group."""
    kind: str                       # "total" | "group" | "subtotal"
    level: int = -1                 # group depth; -1 for the grand total
    #: the group's values, outermost first — what the reader sees
    path: tuple = ()
    #: the same path as text, which is what folding remembers a group by
    #: (it survives a re-run; a position in the frame would not)
    key: tuple = ()
    label: str = ""
    count: int = 0
    values: dict = field(default_factory=dict)
    collapsed: bool = False


@dataclass
class Layout:
    entries: Any                    # numpy int64: row position or -(i+1)
    specials: list = field(default_factory=list)
    plan: Plan = field(default_factory=Plan)

    def __len__(self) -> int:
        return len(self.entries)

    def at(self, row: int):
        """(position, None) for a data row, (None, Special) for the rest."""
        e = int(self.entries[row])
        return (e, None) if e >= 0 else (None, self.specials[-e - 1])

    def data_positions(self):
        """The frame positions on show, in the order they are shown."""
        return self.entries[self.entries >= 0]


def _starts_folded(plan: Plan, level: int) -> bool:
    if plan.group_open == "closed":
        return True
    if plan.group_open == "first":
        return level > 0
    return False


def is_collapsed(plan: Plan, level: int, key: tuple, toggled) -> bool:
    """Is this group folded? The plan's starting state, flipped for every
    group the reader has clicked (`toggled`, a set of text paths)."""
    return _starts_folded(plan, level) != (tuple(key) in (toggled or ()))


def _total_values(frame, plan: Plan, positions=None, grand=None) -> dict:
    part = frame if positions is None else frame.take(positions)
    # a matrix's true totals, used where the total asked for is the one the
    # matrix was built with — summing a sum matrix, averaging a mean one
    known = (grand or {}).get("values") or {}
    known_agg = (grand or {}).get("agg")
    out = {}
    for column, (kind, what) in plan.per_column.items():
        if kind == "agg" and what == known_agg and column in known:
            out[column] = known[column]
        elif kind == "text":
            out[column] = what
        else:
            out[column] = aggregate(column_of(part, column), what)
    return out


def build_layout(frame, plan: Plan, toggled=None, grand=None,
                 expand_all: bool = False) -> Layout:
    """Where every row of `frame` goes, and the rows this adds.

    `frame` is taken in the order it is in — the caller has already sorted
    it — and groups come out in the order their first row appears.
    `grand` is ``{"agg": how, "values": {column: value}}``, which beats
    the computed grand total where the total asked for is `how` (a matrix
    knows the true total of the rows its cells were built from).
    `expand_all` ignores folding, for a table written out whole.
    """
    import numpy as np

    n = len(frame)
    specials: list = []

    def special(item: Special) -> int:
        specials.append(item)
        return -len(specials)

    top: list = []
    bottom: list = []
    if plan.has_total:
        values = _total_values(frame, plan, grand=grand)
        if plan.place in ("top", "both"):
            top.append(special(Special("total", label=plan.label,
                                       count=n, values=values)))
        if plan.place in ("bottom", "both"):
            bottom.append(special(Special("total", label=plan.label,
                                          count=n, values=dict(values))))
    if not plan.grouped:
        middle = np.arange(n, dtype=np.int64)
    else:
        middle = _grouped_entries(frame, plan, toggled, expand_all, special)
    entries = np.concatenate([np.asarray(top, dtype=np.int64), middle,
                              np.asarray(bottom, dtype=np.int64)])
    return Layout(entries=entries, specials=specials, plan=plan)


def _grouped_entries(frame, plan, toggled, expand_all, special):
    import numpy as np
    import pandas as pd

    levels = list(plan.group_by)
    codes: list = []
    uniques: list = []
    for column in levels:
        c, u = pd.factorize(column_of(frame, column), use_na_sentinel=False)
        codes.append(np.asarray(c, dtype=np.int64))
        uniques.append(u)
    subtotals = plan.subtotal_place != "none" and bool(plan.per_column)
    # every level's subtotals, one groupby per level and column
    sums: list = []
    counts: list = []
    for depth in range(len(levels)):
        keys = codes[:depth + 1]
        counts.append(_grouped(frame, keys, None, "rows"))
        per: dict = {}
        if subtotals:
            for column, (kind, what) in plan.per_column.items():
                per[column] = (("text", what) if kind == "text"
                               else ("agg", _grouped(frame, keys, column,
                                                     what)))
        sums.append(per)

    out: list = []

    def text_of(value) -> str:
        v = _scalar(value)
        return "(blank)" if v is None or (isinstance(v, str)
                                          and not v.strip()) else str(v)

    def walk(pos, depth: int, key_codes: tuple, path: tuple, key: tuple):
        if depth == len(levels):
            out.append(pos)
            return
        level_codes = codes[depth][pos]
        order = np.argsort(level_codes, kind="stable")
        ordered = level_codes[order]
        starts = np.flatnonzero(np.r_[True, ordered[1:] != ordered[:-1]]) \
            if len(ordered) else np.array([], dtype=np.int64)
        ends = np.r_[starts[1:], len(ordered)]
        # a group's first row is order[start] — stable, so the smallest
        # position in it — which is the order groups are shown in
        groups = sorted(zip(starts, ends), key=lambda se: order[se[0]])
        for s, e in groups:
            members = pos[order[s:e]]
            code = int(ordered[s])
            gcodes = key_codes + (code,)
            value = _scalar(uniques[depth][code])
            gpath = path + (value,)
            gkey = key + (text_of(value),)
            values = {}
            if subtotals:
                for column, (kind, what) in sums[depth].items():
                    values[column] = what if kind == "text" \
                        else what.get(gcodes)
            folded = (not expand_all) and is_collapsed(plan, depth, gkey,
                                                       toggled)
            count = counts[depth].get(gcodes, len(members))
            header_values = values if plan.subtotal_place in (
                "above", "both") else {}
            out.append(np.asarray([special(Special(
                "group", level=depth, path=gpath, key=gkey,
                label=text_of(value), count=count, values=header_values,
                collapsed=folded))], dtype=np.int64))
            if folded:
                continue
            walk(members, depth + 1, gcodes, gpath, gkey)
            if subtotals and plan.subtotal_place in ("below", "both"):
                out.append(np.asarray([special(Special(
                    "subtotal", level=depth, path=gpath, key=gkey,
                    label=f"{text_of(value)} {plan.subtotal_label}", count=count,
                    values=values))], dtype=np.int64))

    walk(np.arange(len(frame), dtype=np.int64), 0, (), (), ())
    return (np.concatenate(out) if out
            else np.asarray([], dtype=np.int64))


def all_group_keys(layout: Layout) -> list:
    return [s.key for s in layout.specials if s.kind == "group"]


# ----------------------------------------------------------- drawing them

def label_column(plan: Plan, columns) -> Optional[str]:
    """Where a flat table writes "Total": the first column on show that no
    total takes. None when every column carries one — the row index says
    it then, and a grouped table has a column of its own for it."""
    for column in columns:
        if str(column) not in plan.per_column:
            return str(column)
    return None


def cell_text(value: Any, how: Optional[tuple], rules, column) -> str:
    """A total's cell as text: the column's own number format where the
    aggregate is in the column's units, else a readable number."""
    if value is None:
        return ""
    if how is not None and how[0] == "text":
        return str(value)
    agg = how[1] if how else None
    if agg in UNIT_AGGS:
        spec = _number_format(rules, column)
        if spec:
            from .table_format import _format_value
            text = _format_value(value, spec)
            if text is not None:
                return text
    return plain_number(value)


def plain_number(value: Any) -> str:
    """A total written the way a person reads one: whole numbers whole,
    and never `1.23457e+06` — the data cells' six significant figures are
    fine for a reading and wrong for a sum."""
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, float):
        if math.isnan(value):
            return ""
        if value.is_integer() and abs(value) < 1e15:
            return str(int(value))
        if abs(value) >= 1:
            return f"{value:.2f}".rstrip("0").rstrip(".")
        return f"{value:.4g}"
    return str(value)


def _number_format(rules, column) -> Optional[str]:
    from .table_format import column_matches
    spec = None
    for rule in rules or ():
        if (rule.mode == "number_format" and not getattr(rule, "rows_on", None)
                and column_matches(rule.columns, str(column))):
            spec = rule.number_spec
    return spec


#: How each kind of row looks before any rule says otherwise: bold, on a
#: ground a step lighter than the grid, so a total reads as one without a
#: rule being written.
DEFAULT_LOOK = {"total": ("#3a3f4b", True), "group": ("#30343e", True),
                "subtotal": ("#2c2f37", True)}


def aimed_at(rule, kind: str) -> bool:
    """Does `rule` draw on rows of this kind?"""
    on = getattr(rule, "rows_on", None)
    if not on:
        return kind == "data"
    return kind in on


def special_styles(specials, kind: str, rules, columns, values_of,
                   label_at=None) -> list:
    """One {column: CellStyle} per special row of `kind`, in order.

    `values_of(special)` is the row as {column: value} — the totals, and
    the label where it is written. The rows are laid side by side in a
    small frame and every rule aimed at `kind` evaluated over it at once,
    which is what lets `profit < 0 => fg red, on totals` read a total
    exactly as it reads a cell, and a scale aimed at subtotals measure the
    subtotals against each other rather than against the rows."""
    import pandas as pd

    from .table_format import (CellStyle, column_matches, column_stats,
                               evaluate_column, evaluate_rows, readable_fg)

    rows = [values_of(s) for s in specials]
    names = [str(c) for c in columns]
    frame = pd.DataFrame(rows, columns=names) if rows else None
    ground, bold = DEFAULT_LOOK.get(kind, (None, True))
    base = CellStyle(bg=ground, fg=readable_fg(ground) if ground else None,
                     bold=bold)
    out = [{name: base for name in names} for _ in specials]
    if frame is None:
        return out
    for rule in rules or ():
        if not aimed_at(rule, kind) or kind == "data":
            continue
        if rule.mode == "total_style":
            style = CellStyle(bg=rule.bg, fg=rule.fg, bold=rule.bold,
                              hide_value=rule.hide_value,
                              row_height=rule.row_height)
            for row in out:
                for name in names:
                    # a new ground takes its readable ink only where no
                    # earlier rule chose one: `profit < 0 => fg red, on
                    # totals` above `total => bg blue` stays red
                    under = row[name]
                    ink = style.fg
                    if ink is None and style.bg and (
                            under is None or under.fg in (None, base.fg)):
                        ink = readable_fg(style.bg)
                    row[name] = CellStyle(
                        bg=style.bg, fg=ink, bold=style.bold,
                        hide_value=style.hide_value,
                        row_height=style.row_height).over(under)
            continue
        if rule.mode == "highlight" and rule.scope == "row":
            try:
                styles = evaluate_rows(frame, [rule])
            except Exception:
                continue
            for i, style in enumerate(styles):
                if style is not None:
                    for name in names:
                        out[i][name] = style.over(out[i][name])
            continue
        for name in names:
            if rule.columns and not column_matches(rule.columns, name):
                continue
            try:
                styles = evaluate_column(frame[name], [rule],
                                         column_stats(frame[name]),
                                         frame=frame)
            except Exception:
                continue
            for i, style in enumerate(styles):
                if style is not None:
                    out[i][name] = style.over(out[i][name])
    return out


# ---------------------------------------------------- written into a table

def with_totals(frame, plan: Plan, grand=None):
    """`frame` with its total rows written in, for **Totals in output**:
    ``(frame, positions of the rows added)``.

    Grouped, it comes out in grouped order, every group open — a folded
    group is a way of looking, not something to hand downstream. A group
    header row is written only where it carries subtotals; its grouping
    column holds the group's value, and a subtotal row's holds "North
    Total", which is what a spreadsheet's Subtotal command writes. A grand
    total's label goes in the first column that is not totalled (the first
    grouping column, grouped). Every added row is indexed by its label.
    """
    import numpy as np
    import pandas as pd

    if not plan.active:
        return frame, []
    layout = build_layout(frame, plan, grand=grand, expand_all=True)
    names = [str(c) for c in frame.columns]
    where = label_column(plan, names) if not plan.grouped else None
    rows = []
    index = []
    keep = []                                   # which specials are written
    for i, s in enumerate(layout.specials):
        if s.kind == "group" and not s.values:
            continue
        row = dict(s.values)
        if s.kind == "total":
            if plan.grouped:
                row[plan.group_by[0]] = s.label
            elif where is not None:
                row[where] = s.label
        else:
            for depth, column in enumerate(plan.group_by[:s.level + 1]):
                row[column] = s.path[depth]
            if s.kind == "subtotal":
                row[plan.group_by[s.level]] = s.label
        rows.append(row)
        index.append(s.label)
        keep.append(i)
    extra = frame.iloc[0:0]
    if rows:
        extra = pd.DataFrame(rows, columns=names, index=index)
        extra.columns = frame.columns
    slot = {sp: len(frame) + j for j, sp in enumerate(keep)}
    order = []
    added = []
    for e in layout.entries.tolist():
        if e >= 0:
            order.append(e)
        elif (-e - 1) in slot:
            added.append(len(order))
            order.append(slot[-e - 1])
    combined = pd.concat([frame, extra]) if len(extra) else frame
    out = combined.take(np.asarray(order, dtype=np.int64))
    return out, added


def strip_baked(frame, positions):
    """`frame` without the rows `with_totals` wrote into it — how the card
    gets back to the rows it lays out itself."""
    if not positions:
        return frame
    import numpy as np
    mask = np.ones(len(frame), dtype=bool)
    for p in positions:
        if 0 <= int(p) < len(frame):
            mask[int(p)] = False
    return frame.iloc[mask]
