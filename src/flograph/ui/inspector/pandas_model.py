"""Lazy Qt table model over a pandas DataFrame.

Holds the DataFrame by reference and pages rows in via fetchMore, so a
million-row frame costs nothing to open. Cells are formatted lazily in
data()."""
from __future__ import annotations

import math
from typing import Any, Optional

import numpy as np
import pandas as pd
from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtGui import QColor, QFont

from ..table_delegate import BAR_ROLE, DECOR_ROLE, HEIGHT_ROLE, ICON_ROLE

PAGE_SIZE = 500

# Values are read out of the frame this many rows at a time and kept: one
# `iat` costs ~7us, Qt asks data() for about ten roles of every visible cell
# on every paint, and a formatted table asks for them all — so reading a
# cell straight from the frame each time was most of what a formatted table
# cost to paint and scroll. A block rather than a whole column, so a
# million-row frame pays only for the rows looked at.
_BLOCK = 1024
# How many cells' combined styles are kept before the cache starts over. A
# screenful is a few hundred; this is a table scrolled end to end, many times.
_STYLE_CACHE_LIMIT = 200_000
_UNSET = object()
FLOAT_PRECISION = 6

# Above this row count a conditional-format style is not evaluated: the
# per-cell pass is Python-level, and nobody heatmaps a million rows. Matches
# the ceiling table_sort puts on its text-date sniff.
CF_MAX_ROWS = 200_000

_NAN_COLOR = QColor("#6b7280")

# Bound once at import, and compared as ints. Resolving `Qt.DisplayRole`
# through PySide6's enum metaclass costs ~1.9us on this build, and Qt asks
# data() for seven roles per visible cell on every repaint — which made the
# role cascade, rather than pandas or the painting, the bulk of what a table
# card cost to scroll. See ui/spreadsheet/model.py for the measurement.
_DISPLAY = int(Qt.DisplayRole)
_EDIT = int(Qt.EditRole)
_FOREGROUND = int(Qt.ForegroundRole)
_BACKGROUND = int(Qt.BackgroundRole)
_FONT = int(Qt.FontRole)
_ALIGNMENT = int(Qt.TextAlignmentRole)
_TOOLTIP = int(Qt.ToolTipRole)
_HEIGHT = HEIGHT_ROLE
_HORIZONTAL = Qt.Horizontal
_ALIGN_NUMBER = int(Qt.AlignRight | Qt.AlignVCenter)
#: What an `align` rule asks for, as a Qt flag.
_ALIGN_RULE = {
    "left": int(Qt.AlignLeft | Qt.AlignVCenter),
    "right": int(Qt.AlignRight | Qt.AlignVCenter),
    "center": int(Qt.AlignHCenter | Qt.AlignVCenter),
}

# the roles that need the cell's value at all; anything else can answer
# without touching the frame
_VALUE_ROLES = frozenset({_DISPLAY, _EDIT, _FOREGROUND, _FONT, _ALIGNMENT})
# ...plus the format roles, used only when a style is actually wired in
_VALUE_ROLES_FMT = _VALUE_ROLES | {_BACKGROUND, BAR_ROLE, ICON_ROLE,
                                   DECOR_ROLE, _TOOLTIP}


def _bold() -> QFont:
    font = QFont()
    font.setBold(True)
    return font


_BOLD_FONT = _bold()


def _italic() -> QFont:
    font = QFont()
    font.setItalic(True)
    return font


_MISSING_FONT = _italic()


def _is_missing(value: Any) -> bool:
    try:
        return value is None or (isinstance(value, float) and math.isnan(value)) \
            or value is pd.NaT
    except Exception:
        return False


class PandasModel(QAbstractTableModel):
    def __init__(self, df: pd.DataFrame, parent=None, rules=None,
                 hidden=None, shown=None, grand=None) -> None:
        super().__init__(parent)
        # A spark can add a column (drawn in one the table lacks) and put
        # the columns it reads out of view. Worked out before anything else
        # here, because every projection below has to see the new column —
        # and by the same function the printed table calls, so the page and
        # the card cannot disagree about what a spark made.
        from flograph.core.table_format import spark_projection
        # the frame as handed over, before a spark adds to it — what
        # `keeps_table` compares a re-run's table against
        self._input = df
        df, rules, spark_hidden = spark_projection(df, rules)
        if spark_hidden:
            hidden = list(hidden or []) + spark_hidden
        # Total rows and groups (core/table_totals.py). Worked out from the
        # rules before anything is projected: a grouped table writes its
        # groups in a column of its own, so the grouping columns leave the
        # view — they would say the same thing on every row of a group.
        from flograph.core.table_totals import plan_from_rules
        self._all_rules = list(rules or [])
        self._plan = plan_from_rules(self._all_rules, df)
        if self._plan.grouped:
            hidden = list(hidden or []) + [
                c for c in self._plan.group_by if c not in (shown or [])]
        #: the reader's folds: group paths flipped from how groups start
        self._toggled: set = set()
        #: `Layout` when there are total rows or groups, else None — and
        #: then every row is a data row and nothing below is any different
        self._layout = None
        #: 1 when a grouped table has its group column in front, else 0
        self._lead = 1 if self._plan.grouped else 0
        #: {id(Special): {column: CellStyle}}, built a kind at a time
        self._special_styles: dict = {}
        #: the precomputed grand total a matrix carries (see styled_model)
        self._grand = grand or None
        self._df = df
        #: (column, block) -> that block's values, as `iat` would box them
        self._values: dict = {}
        # The frame as it arrived. sort() reorders a *copy* off this, so
        # ascending/descending/clear all work from a fixed base and the
        # source (and anything downstream sharing it) is never touched.
        self._source = df
        self._loaded = min(PAGE_SIZE, len(df))
        # Column projection: which source columns are shown, in order.
        # `hide` keeps a helper column in the frame (a rule may read it) but
        # out of the view; `show` is the keep-list and fixes the order. Both
        # may be globs, and both are a *view* — `self._source` is untouched,
        # so the frame leaving the node's table port is the one that
        # arrived, in its own order.
        from flograph.core.table_format import visible_columns
        names = [str(c) for c in df.columns]
        keep = visible_columns(names, shown or [], hidden or [])
        if keep == names:
            self._visible = None            # nothing projected: the fast path
        else:
            # back to positions, because a frame is allowed two columns of
            # the same name and both of them still belong in the view. Each
            # mention takes the next position holding that name, so a `hide`
            # that kept both keeps both — and a `show` that named it once
            # (the list is de-duplicated) gets the first, which is the only
            # answer a name can give when two columns answer to it.
            where: dict = {}
            for i, name in enumerate(names):
                where.setdefault(name, []).append(i)
            taken: dict = {}
            visible = []
            for c in keep:
                slots = where.get(c, ())
                if not slots:
                    continue
                n = taken.get(c, 0)
                visible.append(slots[min(n, len(slots) - 1)])
                taken[c] = n + 1
            self._visible = visible
        self._set_rules(rules)
        self._apply_default_sort()
        self._relayout()

    def _src(self, col: int) -> int:
        """A visible column index -> its position in the underlying frame;
        -1 for a grouped table's group column, which the frame lacks."""
        col -= self._lead
        if col < 0:
            return -1
        return col if self._visible is None else self._visible[col]

    # ------------------------------------------------ totals and groups

    def _relayout(self) -> None:
        """Lay the (sorted) frame out with its total rows and groups. Called
        whenever the row order or a fold changes; cheap next to a sort."""
        self._special_styles = {}
        if not self._plan.active:
            self._layout = None
            return
        from flograph.core.table_totals import build_layout
        try:
            self._layout = build_layout(self._df, self._plan, self._toggled,
                                        grand=self._grand)
        except Exception:
            # the render path: a table with no totals beats a blank card
            self._layout = None
            self._lead = 0
        self._loaded = min(max(PAGE_SIZE, self._loaded), self._row_total())

    def _row_total(self) -> int:
        return len(self._df) if self._layout is None else len(self._layout)

    def _at(self, row: int):
        """(frame position, None) for a data row, (None, Special) for a
        total or group row."""
        if self._layout is None:
            return row, None
        return self._layout.at(row)

    def special_at(self, row: int):
        """The Special at a display row, or None for a data row."""
        if self._layout is None or not 0 <= row < len(self._layout):
            return None
        return self._layout.at(row)[1]

    def is_data_row(self, row: int) -> bool:
        return self.special_at(row) is None

    def is_grouped(self) -> bool:
        return self._layout is not None and self._plan.grouped

    def plan(self):
        return self._plan

    def toggle_group(self, row: int) -> bool:
        """Fold or unfold the group whose header is at `row`. The rows come
        and go as an insert or a removal, not a reset, so the scroll
        position and the rest of the table stay where they were."""
        special = self.special_at(row)
        if special is None or special.kind != "group":
            return False
        from flograph.core.table_totals import build_layout
        key = tuple(special.key)
        toggled = set(self._toggled)
        toggled ^= {key}
        try:
            layout = build_layout(self._df, self._plan, toggled,
                                  grand=self._grand)
        except Exception:
            return False
        old, new = len(self._layout), len(layout)
        delta = new - old
        loaded = self._loaded
        if delta < 0:
            last = min(row - delta, loaded - 1)
            if last > row:
                self.beginRemoveRows(QModelIndex(), row + 1, last)
            self._commit_layout(layout, toggled,
                                max(row + 1, loaded + delta))
            if last > row:
                self.endRemoveRows()
        elif delta > 0:
            self.beginInsertRows(QModelIndex(), row + 1, row + delta)
            self._commit_layout(layout, toggled, loaded + delta)
            self.endInsertRows()
        else:
            self._commit_layout(layout, toggled, loaded)
        # the arrow on the header row, and every total row's styles
        self.dataChanged.emit(self.index(0, 0),
                              self.index(max(0, self._loaded - 1),
                                         max(0, self.columnCount() - 1)))
        return True

    def _commit_layout(self, layout, toggled, loaded) -> None:
        self._layout = layout
        self._toggled = toggled
        self._special_styles = {}
        self._loaded = max(0, min(loaded, len(layout)))

    def set_all_groups(self, folded: bool) -> None:
        """Expand All / Collapse All: every group to one state."""
        if not self.is_grouped():
            return
        from flograph.core.table_totals import build_layout, is_collapsed
        # every group key there is, whatever is folded now
        whole = build_layout(self._df, self._plan, grand=self._grand,
                             expand_all=True)
        toggled = {s.key for s in whole.specials
                   if s.kind == "group"
                   and is_collapsed(self._plan, s.level, s.key, ()) != folded}
        self.beginResetModel()
        self._toggled = toggled
        self._relayout()
        self.endResetModel()

    def carry_folds(self, other) -> None:
        """Take `other`'s folds — a re-run's new model keeping the groups
        the reader had folded, where it groups the same way."""
        try:
            if (other is not None and self.is_grouped()
                    and other.plan().group_by == self._plan.group_by
                    and other._toggled):
                self.beginResetModel()
                self._toggled = set(other._toggled)
                self._relayout()
                self.endResetModel()
        except Exception:
            pass

    def _visible_names(self) -> list:
        names = [str(c) for c in self._df.columns]
        if self._visible is None:
            return names
        return [names[i] for i in self._visible]

    def _style_of_special(self, special, name: str):
        """The CellStyle a total or group row's cell is drawn with."""
        found = self._special_styles.get(id(special))
        if found is None:
            from flograph.core.table_totals import label_column, special_styles
            kind = special.kind
            of_kind = [s for s in self._layout.specials if s.kind == kind]
            names = self._visible_names()
            where = (None if self._plan.grouped
                     else label_column(self._plan, names))

            def values_of(s):
                row = dict(s.values)
                if where is not None and where not in row:
                    row[where] = s.label
                return row
            try:
                styles = special_styles(of_kind, kind, self._all_rules,
                                        names, values_of)
            except Exception:
                styles = [{} for _ in of_kind]
            for s, style in zip(of_kind, styles):
                self._special_styles[id(s)] = style
            found = self._special_styles.get(id(special), {})
        return found.get(name)

    def _special_text(self, special, col: int) -> str:
        """What a total or group row says in a (visible) column."""
        if col == 0 and self._lead:
            indent = "    " * max(0, special.level)
            if special.kind == "group":
                arrow = "▸" if special.collapsed else "▾"
                return f"{indent}{arrow} {special.label}  ({special.count:,})"
            if special.kind == "subtotal":
                return f"{indent}   {special.label}"
            return special.label
        name = self._visible_names()[col - self._lead]
        how = self._plan.how(name)
        if name in special.values:
            from flograph.core.table_totals import cell_text
            return cell_text(special.values[name], how, self._all_rules, name)
        if special.kind == "total" and not self._lead:
            from flograph.core.table_totals import label_column
            if name == label_column(self._plan, self._visible_names()):
                return special.label
        return ""

    def _special_data(self, special, index, role: int):
        col = index.column()
        if role == _DISPLAY:
            if col >= self._lead:
                style = self._style_of_special(
                    special, self._visible_names()[col - self._lead])
                if style is not None and style.hide_value:
                    return ""
            return self._special_text(special, col)
        if role == _EDIT:
            if col >= self._lead:
                name = self._visible_names()[col - self._lead]
                if name in special.values:
                    value = special.values[name]
                    return "" if value is None else str(value)
            return self._special_text(special, col).strip()
        if role == _TOOLTIP:
            if special.kind == "group":
                verb = "unfold" if special.collapsed else "fold"
                return (f"{special.label}: {special.count:,} rows — click "
                        f"the arrow to {verb}")
            if col >= self._lead:
                name = self._visible_names()[col - self._lead]
                how = self._plan.how(name)
                if how and how[0] == "agg" and name in special.values:
                    from flograph.core.table_totals import AGGREGATION_HELP
                    return (f"{special.label} — {name}: "
                            f"{how[1]} ({AGGREGATION_HELP.get(how[1], '')})")
            return None
        if role == _HEIGHT:
            return self._row_height
        name = (self._visible_names()[col - self._lead]
                if col >= self._lead else None)
        style = self._style_of_special(
            special, name if name is not None
            else self._visible_names()[0] if self._visible_names() else "")
        if role == _ALIGNMENT:
            if col < self._lead:
                return None
            forced = self._align.get(self._src(col))
            if forced is not None:
                return forced
            value = special.values.get(name)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                return _ALIGN_NUMBER
            return None
        if style is None:
            return None
        if role == _FONT:
            return _BOLD_FONT if style.bold else None
        if role == _FOREGROUND:
            return QColor(style.fg) if style.fg else None
        if role == _BACKGROUND:
            return QColor(style.bg) if style.bg else None
        if col < self._lead:
            return None
        if role == BAR_ROLE:
            if style.bar is not None:
                return (style.bar, style.bar_color, style.bar_mode)
            return None
        if role == ICON_ROLE:
            if style.decorations:
                first = style.decorations[0]
                return (first.text, first.color)
            return None
        if role == DECOR_ROLE:
            if style.decorations or style.pill:
                return (style.decorations, style.pill, style.pill_fg)
            return None
        return None

    def _value(self, row: int, col: int):
        """`self._df.iat[row, col]`, from a block of the column read once.

        The same object `iat` gives: a numpy column's own scalars, and for
        dates, durations and extension types what their array boxes them as
        — a numpy datetime64 would print differently from the Timestamp
        `iat` returns, so those go through the pandas array too."""
        key = (col, row // _BLOCK)
        block = self._values.get(key)
        if block is None:
            start = key[1] * _BLOCK
            series = self._df.iloc[start:start + _BLOCK, col]
            dtype = series.dtype
            if isinstance(dtype, np.dtype) and dtype.kind not in "mM":
                block = series.to_numpy()
            else:
                block = list(series.array)
            self._values[key] = block
        return block[row - key[1] * _BLOCK]

    # ----------------------------------------------- conditional formatting

    def _set_rules(self, rules) -> None:
        from flograph.core.table_format import (
            LAYOUT_MODES, column_layout, row_height_of, sort_order,
            wraps_text)
        # A `height` line is table-wide like `wrap`: one default row height,
        # read once here and handed to the view.
        self._row_height = row_height_of(rules)
        # Table-wide like `wrap`, and filtered out of `self._rules` with the
        # other layout modes — so it is read here or not at all.
        self._sort = sort_order(rules)
        # Layout rules shape the column, not the cell. Reading them once
        # here keeps them out of the per-cell path entirely — and out of
        # `_cf_active`, so a table whose only rule is `width 120` pays
        # nothing per row.
        self._layout_rules = column_layout(rules, self._df.columns)
        self._wraps = wraps_text(rules)
        # by column index, so the hot paths (data / headerData) are a dict
        # lookup on a number rather than a string built per call
        self._align: dict = {}
        self._labels: dict = {}
        for i, name in enumerate(self._df.columns):
            entry = self._layout_rules.get(str(name))
            if entry is None:
                continue
            if entry.align in _ALIGN_RULE:
                self._align[i] = _ALIGN_RULE[entry.align]
            if entry.label:
                self._labels[i] = entry.label
        from flograph.core.table_format import TOTAL_MODES, on_data
        # total and group lines lay rows out rather than paint them, and a
        # rule aimed `on totals` only is drawn by _special_data — neither is
        # evaluated down a column of data
        self._rules = [r for r in (rules or [])
                       if r.mode != "hide" and r.mode not in LAYOUT_MODES
                       and r.mode not in TOTAL_MODES and on_data(r)]
        # A mark on a line of its own, or a tall spark, asks the delegate
        # for a taller cell — and Qt only asks the delegate how tall a row
        # is when the view sizes rows to their contents. Read off the rules
        # rather than the cells, so it is known before a row is drawn.
        from flograph.core.table_format import DECOR_LINES
        self._grows = any(
            (r.glyph_where in DECOR_LINES)
            or (r.mode == "sparkline" and r.tall)
            # a highlight's `height` makes the rows it picks taller, and
            # only the delegate knows which rows those are
            or bool(r.row_height)
            # a picture drawn taller than a line of text
            or bool(getattr(r, "picture_size", None))
            for r in self._rules)
        # A style is only honoured on a table small enough to walk per-cell.
        self._cf_active = bool(self._rules) and len(self._df) <= CF_MAX_ROWS
        self._value_roles = _VALUE_ROLES_FMT if self._cf_active else _VALUE_ROLES
        self._col_stats: dict = {}          # col index -> ColumnStats
        # What a rule measures across the whole table (a `by` column's
        # range, a pool, autocolour's wheel) — see evaluate_column's `memo`.
        # Row order does not change any of it, so a sort keeps it too.
        self._measured: dict = {}
        # Rules are evaluated a block of rows at a time, when a row in the
        # block is first drawn — never down the whole column: a 50,000-row
        # table showing forty rows used to style all 50,000 for every rule
        # the moment it arrived (AE3).
        # (col index, block) -> [(rule index, [CellStyle | None] per row)]
        self._col_cache: dict = {}
        # block -> {rule index: [CellStyle | None] per row}
        self._row_cache: dict = {}
        #: (row, col) -> the combined CellStyle (or None) — see _cell_style
        self._styles_at: dict = {}

    def set_rules(self, rules) -> None:
        """Swap the formatting rules and repaint — no model rebuild, so a
        sort in progress survives.

        Deliberately does *not* re-apply a `sort` rule: by now the reader
        may have clicked a header, and having the rows jump because a
        colour rule changed would be worse than the default arriving late.
        It takes effect the next time the table is built — a re-run, or
        reopening the project.
        """
        from flograph.core.table_totals import plan_from_rules
        self.beginResetModel()
        self._all_rules = list(rules or [])
        plan = plan_from_rules(self._all_rules, self._df)
        if plan.group_by == self._plan.group_by:
            # a grouping that changed would need the columns re-projected,
            # which is a new model's job; the totals can change in place
            self._plan = plan
        self._set_rules(rules)
        self._relayout()
        self.endResetModel()

    def _apply_default_sort(self) -> None:
        """Open in the order a `sort` rule asked for.

        Construction only. A header click still wins from then on, and
        clearing the sort (the third click) restores the frame's own
        order rather than this one — "no sort" is the honest reading of
        clear, and the default comes back with the next run.
        """
        if not self._sort:
            return
        from flograph.core.table_sort import sorted_frame
        ordered = sorted_frame(self._source, self._sort[0], self._sort[1])
        if ordered is self._source:
            return                     # no such column, or the sort failed
        self._df = ordered
        self._loaded = min(PAGE_SIZE, len(self._df))
        self._col_cache.clear()
        self._row_cache.clear()
        self._values.clear()
        self._styles_at.clear()

    def _is_row_rule(self, rule) -> bool:
        return rule.mode == "highlight" and rule.scope == "row"

    def _row_styles(self, block: int) -> dict:
        found = self._row_cache.get(block)
        if found is None:
            from flograph.core.table_format import evaluate_rows
            start = block * _BLOCK
            rows = self._df.iloc[start:start + _BLOCK]
            found = self._row_cache[block] = {
                i: evaluate_rows(rows, [rule])
                for i, rule in enumerate(self._rules) if self._is_row_rule(rule)}
        return found

    def _col_styles(self, col: int, block: int) -> list:
        key = (col, block)
        entry = self._col_cache.get(key)
        if entry is None:
            from flograph.core.table_format import (
                column_matches, column_stats, evaluate_column)
            name = str(self._df.columns[col])
            start = block * _BLOCK
            rows = None
            stats = None
            entry = []
            for i, rule in enumerate(self._rules):
                if self._is_row_rule(rule):
                    continue
                if rule.columns and not column_matches(rule.columns, name):
                    continue
                if stats is None:
                    # over the whole column, so a block is shaded against
                    # the table's range rather than its own
                    stats = self._col_stats.get(col) or column_stats(
                        self._source.iloc[:, col])
                    self._col_stats[col] = stats
                    rows = self._df.iloc[start:start + _BLOCK]
                try:
                    styles = evaluate_column(
                        rows.iloc[:, col], [rule], stats, frame=rows,
                        pool_frame=self._df, memo=self._measured)
                except Exception:
                    # This runs inside data(), which Qt calls from the middle
                    # of painting and measuring. An exception escaping there
                    # is not an error message: PySide crashes the process
                    # printing it. One rule that cannot be drawn is skipped,
                    # and the rest of the table still is.
                    continue
                entry.append((i, styles))
            self._col_cache[key] = entry
        return entry

    def _cell_style(self, row: int, col: int):
        """Every rule that touches this cell, applied in the order they
        appear in the box — a later line wins, whether it is a whole-row
        highlight or a single-cell one."""
        if not self._cf_active:
            return None
        # Asked for once per role per cell per paint, and the answer only
        # changes with the rules or the row order — both of which clear this.
        key = (row, col)
        found = self._styles_at.get(key, _UNSET)
        if found is not _UNSET:
            return found
        if len(self._styles_at) >= _STYLE_CACHE_LIMIT:
            self._styles_at.clear()
        self._styles_at[key] = found = self._combined_style(row, col)
        return found

    def _combined_style(self, row: int, col: int):
        parts = []                         # (rule index, CellStyle)
        block, at = divmod(row, _BLOCK)
        for i, styles in self._col_styles(col, block):
            if at < len(styles) and styles[at] is not None:
                parts.append((i, styles[at]))
        for i, styles in self._row_styles(block).items():
            if at < len(styles) and styles[at] is not None:
                parts.append((i, styles[at]))
        if not parts:
            return None
        parts.sort(key=lambda t: t[0])
        acc = None
        for _i, style in parts:
            acc = style.over(acc)
        return acc

    def dataframe(self) -> pd.DataFrame:
        """The frame behind the model, whole — not just the rows paged in.

        Copying the whole table goes through this rather than through the
        view, so asking for a million rows does not first have to fetchMore
        its way there. Hidden helper columns are dropped: a copy is of what
        you see.
        """
        if self._visible is None:
            return self._df
        return self._df.iloc[:, self._visible]

    # ------------------------------------------------------------- sorting

    def sort(self, column: int, order=Qt.AscendingOrder) -> None:
        """Reorder the view by one column.

        ``order`` of ``None`` clears the sort and restores the frame's
        original row order. Detection of numbers/dates stored as text
        lives in :func:`flograph.ui.table_sort.pandas_sort_key`; real
        dtypes sort natively.

        The column is addressed by position, not label — a frame with two
        columns of the same name (a bad join/concat result) is common
        enough, and ``sort_values(by="X")`` raises on it. Any failure in
        the key computation or the reorder leaves the rows as they were
        rather than escaping into the Qt slot that called this.
        """
        column = self._src(column) if 0 <= column < self.columnCount() else column
        if not 0 <= column < len(self._source.columns):
            return                   # the group column sorts nothing
        from ..table_sort import pandas_sort_key

        self.beginResetModel()
        try:
            if order is None:
                self._df = self._source
            else:
                ascending = order == Qt.AscendingOrder
                key = pandas_sort_key(
                    self._source.iloc[:, column]).reset_index(drop=True)
                positions = key.sort_values(
                    ascending=ascending, kind="stable",
                    na_position="last").index.to_numpy()
                self._df = self._source.take(positions)
        except Exception:
            self._df = self._source
        self._loaded = min(PAGE_SIZE, len(self._df))
        # the data rows moved; the totals stay where they are, and groups
        # keep their rows together — in the order their first row now comes
        self._relayout()
        # colours follow values: the per-cell styles were built against the
        # old order, the column stats (whole-column min/max/…) still hold
        self._col_cache.clear()
        self._row_cache.clear()
        self._values.clear()
        self._styles_at.clear()
        self.endResetModel()

    # ------------------------------------------------------------- shape

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else self._loaded

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        if parent.isValid():
            return 0
        return self._lead + (len(self._df.columns) if self._visible is None
                             else len(self._visible))

    def canFetchMore(self, parent: QModelIndex = QModelIndex()) -> bool:
        return not parent.isValid() and self._loaded < self._row_total()

    def fetchMore(self, parent: QModelIndex = QModelIndex()) -> None:
        remaining = self._row_total() - self._loaded
        count = min(PAGE_SIZE, remaining)
        if count <= 0:
            return
        self.beginInsertRows(QModelIndex(), self._loaded,
                             self._loaded + count - 1)
        self._loaded += count
        self.endInsertRows()

    # -------------------------------------------------------------- data

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
        role = int(role)
        if self._layout is not None and index.isValid():
            row, special = self._layout.at(index.row())
            if special is not None:
                return self._special_data(special, index, role)
            if index.column() < self._lead:
                return None              # a data row's group cell is empty
        else:
            row = index.row()
        if role == _HEIGHT:
            return self._height_at(index, row)
        # Bail before touching the frame: Qt asks for roles this model has
        # no opinion on, and `iat` is a real pandas lookup, not a free one.
        # `_value_roles` widens to include the format roles only when a
        # style is actually wired in, so an unformatted table pays nothing.
        if role not in self._value_roles or not index.isValid():
            return None
        col = self._src(index.column())
        value = self._value(row, col)
        style = self._cell_style(row, col) if self._cf_active else None
        if role == _DISPLAY:
            if style is not None and style.hide_value:
                # an `only` rule draws its format instead of the value. The
                # value goes from the *display* and nowhere else: EditRole
                # still answers, so copy, export and sort are untouched.
                return ""
            if _is_missing(value):
                return "NaN"
            if style is not None and style.text is not None:
                return style.text
            if isinstance(value, float):
                return f"{value:.{FLOAT_PRECISION}g}"
            return str(value)
        if role == _EDIT:
            # What a copy puts on the clipboard. DisplayRole is rounded to
            # six significant figures for reading, and pasting *that* into
            # Excel would quietly lose precision from every float in the
            # table. Missing goes out empty rather than "NaN", which is what
            # a spreadsheet reads as a blank cell.
            if _is_missing(value):
                return ""
            if isinstance(value, float):
                # float() first: numpy scalars are float subclasses whose
                # own repr is "np.float64(1234.5)", which is not a number
                # any spreadsheet will take. Python's float repr is the
                # shortest string that round-trips, so nothing is lost.
                return repr(float(value))
            return str(value)
        if role == _FOREGROUND:
            if _is_missing(value):
                return _NAN_COLOR
            if style is not None and style.fg:
                return QColor(style.fg)
            return None
        if role == _FONT:
            if _is_missing(value):
                return _MISSING_FONT
            if style is not None and style.bold:
                return _BOLD_FONT
            return None
        if role == _BACKGROUND:
            if style is not None and style.bg and not _is_missing(value):
                return QColor(style.bg)
            return None
        if role == BAR_ROLE:
            if style is not None and style.bar is not None:
                return (style.bar, style.bar_color, style.bar_mode)
            return None
        if role == ICON_ROLE:
            # the first decoration only — what a caller sizing a column
            # wants to know, and what this role meant when a cell could
            # hold exactly one icon
            if style is not None and style.decorations:
                first = style.decorations[0]
                return (first.text, first.color)
            return None
        if role == _TOOLTIP:
            # a `tooltip` rule's note. The *cut-short* tooltip is not here
            # and cannot be: it depends on how wide the column ended up,
            # which is the view's business, not a model's.
            return style.tooltip if style is not None else None
        if role == DECOR_ROLE:
            if style is not None and (style.decorations or style.pill):
                return (style.decorations, style.pill, style.pill_fg)
            return None
        if role == _ALIGNMENT:
            forced = self._align.get(col)
            if forced is not None:
                return forced
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                return _ALIGN_NUMBER
        return None

    def headerData(self, section: int, orientation: Qt.Orientation,
                   role: int = Qt.DisplayRole):
        role = int(role)
        if role == _DISPLAY:
            if orientation == _HORIZONTAL:
                col = self._src(section)
                if col < 0:
                    return " › ".join(self._plan.group_by)
                # a `label` rule renames the header on screen only; every
                # rule, sort and export still goes by the real column name
                return self._labels.get(col, str(self._df.columns[col]))
            pos, special = self._at(section)
            if special is not None:
                return special.label if special.kind == "total" else ""
            return str(self._df.index[pos])
        if role == _ALIGNMENT and orientation == _HORIZONTAL:
            # the header follows its column, or a right-aligned money
            # column would sit under a centred title
            return self._align.get(self._src(section))
        if role == _TOOLTIP and orientation == _HORIZONTAL:
            col = self._src(section)
            if col < 0:
                return ("Grouped by " + ", ".join(self._plan.group_by)
                        + " — click a group's arrow to fold it; right-click "
                          "to fold or unfold them all")
            name = str(self._df.columns[col])
            # The name in full, always: a header cut short by a `width` rule
            # or a dragged edge has nowhere else to be read (AA3). A `label`
            # leads when there is one — it is what the header shows — with
            # the real name every rule and export goes by under it.
            label = self._labels.get(col)
            head = f"{label}\n{name}" if label not in (None, name) else name
            return f"{head}\ndtype: {self._df.dtypes.iloc[col]}"
        return None

    def column_name(self, section: int) -> str:
        """The real name behind a visible column, whatever a `label` rule
        renamed it to on screen. What a copy puts on the clipboard: the
        values go out raw (EditRole), and a header that did not match them
        would be worse than useless in the spreadsheet they land in."""
        col = self._src(section)
        if col < 0:
            return " › ".join(self._plan.group_by)
        return str(self._df.columns[col])

    def wraps_text(self) -> bool:
        """Did a rule ask for wrapped text? The view acts on it — row
        heights are geometry, which is the view's business."""
        return self._wraps

    def grows_rows(self) -> bool:
        """Does a rule make some rows taller — a mark `above` or `below`
        the value, a `tall` spark, or a highlight's `height`? Like
        `wraps_text`, for the view."""
        return self._grows and self._cf_active

    def row_height(self) -> "int | None":
        """How tall a `height` line asks every row to be, or None."""
        return self._row_height

    def _height_at(self, index, row=None) -> "int | None":
        """How tall this cell's row should be: a highlight's `height` where
        one matched, else the table's `height` line, else None."""
        if not index.isValid():
            return None
        row = index.row() if row is None else row
        if self._cf_active and self._src(index.column()) >= 0:
            style = self._cell_style(row, self._src(index.column()))
            if style is not None and style.row_height:
                return style.row_height
        return self._row_height

    def column_layout(self, section: int):
        """The `ColumnLayout` for a *visible* column, or None. Read by the
        view, which owns column widths — the model has no say in geometry."""
        col = self._src(section)
        if col < 0:
            return None
        return self._layout_rules.get(str(self._df.columns[col]))

    # ----------------------------------------------------- click to filter

    def row_label(self, row: int) -> str:
        """A row's index label as text — what a row pick keeps it by."""
        pos, special = self._at(row)
        if special is not None:
            return ""
        return str(self._df.index[pos])

    def _column_texts(self, section: int):
        """A visible column as text, converted whole and kept.

        Whole, because `astype(str)` formats a column as one: a datetime
        column with a single time of day in it prints every value with a
        time, so a slice converted alone could print a picked value
        differently from the node's table — and match nothing. Kept, because
        highlighting a pick asks for the same column again on every click.
        """
        src = self._src(section)
        cache = getattr(self, "_texts_cache", None)
        if cache is None or cache[0] is not self._df:
            cache = (self._df, {})
            self._texts_cache = cache
        texts = cache[1].get(src)
        if texts is None:
            texts = self._df.iloc[:, src].astype(str).to_numpy()
            cache[1][src] = texts
        return texts

    def pick_texts(self, section: int, rows) -> list[str]:
        """The values at `rows` of a visible column, as a pick records them
        — the way core.table_picks reads the node's table."""
        if self._src(section) < 0:
            return ["" for _ in rows]
        texts = self._column_texts(section)
        out = []
        for r in rows:
            pos, special = self._at(r)
            out.append("" if special is not None else str(texts[pos]))
        return out

    def rows_matching(self, section: int, values) -> list[int]:
        """The paged-in rows whose value in a visible column is one of
        `values` (as text)."""
        wanted = set(values)
        if self._layout is None:
            texts = self._column_texts(section)[:self._loaded]
            return [r for r, text in enumerate(texts) if text in wanted]
        if self._src(section) < 0:
            return []
        texts = self._column_texts(section)
        return [r for r in range(self._loaded)
                if (e := int(self._layout.entries[r])) >= 0
                and texts[e] in wanted]

    def rows_labelled(self, labels) -> list[int]:
        """The paged-in rows whose index label is one of `labels`."""
        wanted = set(labels)
        if self._layout is None:
            index = self._df.index[:self._loaded].astype(str)
            return [r for r, label in enumerate(index) if label in wanted]
        index = self._df.index.astype(str)
        return [r for r in range(self._loaded)
                if (e := int(self._layout.entries[r])) >= 0
                and index[e] in wanted]


def keeps_table(model, table, style) -> bool:
    """Is `model` already showing `table` under `style`?

    A pick re-runs its own node, and the node passes the table through —
    as a shallow copy, so not the same object, but the same table. Building
    a new model for it would throw away the scroll position, a header sort
    and the paged-in rows on every click; a card that asks this first keeps
    them. Any doubt is a no: rebuilding is always correct, only slower."""
    try:
        if getattr(model, "style_payload", None) != style:
            return False
        table = _unbaked(table, style)
        old = getattr(model, "_input", None)
        if old is None:
            return False
        if old is table:
            return True
        return (old.shape == table.shape
                and old.columns.equals(table.columns)
                and old.index.equals(table.index)
                and old.equals(table))
    except Exception:
        return False


def _unbaked(df, style):
    """`df` without the total rows Totals in output wrote into it."""
    baked = style.get("baked") if isinstance(style, dict) else None
    if not baked:
        return df
    try:
        from flograph.core.table_totals import strip_baked
        return strip_baked(df, baked)
    except Exception:
        return df


def styled_model(df: pd.DataFrame, style: Any, parent=None) -> PandasModel:
    """A model for a table under a Show Table's `style` payload — its rules,
    its keep-list and its hide-list — shared by the card, the dashboard tile
    and the preview window so the three cannot show one table three ways.
    A bad payload gives the plain table: this is the render path, where a
    raise would blank the view."""
    from flograph.core.table_format import (
        hidden_columns, rules_from_style, shown_columns)
    try:
        rules = rules_from_style(style)
        hidden = hidden_columns(style)
        shown = shown_columns(style)
    except Exception:
        rules, hidden, shown = [], [], []
    # Totals in output wrote the total rows into the table; the card lays
    # them out itself — pinned, styled, and out of every sort and scale —
    # so it takes back the rows they were written into.
    df = _unbaked(df, style)
    grand = style.get("grand") if isinstance(style, dict) else None
    model = PandasModel(df, parent=parent, rules=rules, hidden=hidden,
                        shown=shown,
                        grand=grand if isinstance(grand, dict) else None)
    model.style_payload = style        # for keeps_table
    return model
