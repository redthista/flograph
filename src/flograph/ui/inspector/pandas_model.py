"""Lazy Qt table model over a pandas DataFrame.

Holds the DataFrame by reference and pages rows in via fetchMore, so a
million-row frame costs nothing to open. Cells are formatted lazily in
data()."""
from __future__ import annotations

import math
from typing import Any, Optional

import pandas as pd
from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtGui import QColor, QFont

from ..table_delegate import BAR_ROLE, ICON_ROLE

PAGE_SIZE = 500
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
_HORIZONTAL = Qt.Horizontal
_ALIGN_NUMBER = int(Qt.AlignRight | Qt.AlignVCenter)

# the roles that need the cell's value at all; anything else can answer
# without touching the frame
_VALUE_ROLES = frozenset({_DISPLAY, _EDIT, _FOREGROUND, _FONT, _ALIGNMENT})
# ...plus the format roles, used only when a style is actually wired in
_VALUE_ROLES_FMT = _VALUE_ROLES | {_BACKGROUND, BAR_ROLE, ICON_ROLE}


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
                 hidden=None) -> None:
        super().__init__(parent)
        self._df = df
        # The frame as it arrived. sort() reorders a *copy* off this, so
        # ascending/descending/clear all work from a fixed base and the
        # source (and anything downstream sharing it) is never touched.
        self._source = df
        self._loaded = min(PAGE_SIZE, len(df))
        # Column projection: which source columns are shown, in order. A
        # `hide` directive keeps a helper column in the frame (a rule may
        # read it) but out of the view; a `hide` entry may be a glob.
        from flograph.core.table_format import expand_columns
        hide = set(expand_columns(hidden or [], df.columns))
        self._visible = [i for i, c in enumerate(df.columns)
                         if str(c) not in hide] if hide else None
        self._set_rules(rules)

    def _src(self, col: int) -> int:
        """A visible column index -> its position in the underlying frame."""
        return col if self._visible is None else self._visible[col]

    # ----------------------------------------------- conditional formatting

    def _set_rules(self, rules) -> None:
        self._rules = [r for r in (rules or []) if r.mode != "hide"]
        # A style is only honoured on a table small enough to walk per-cell.
        self._cf_active = bool(self._rules) and len(self._df) <= CF_MAX_ROWS
        self._value_roles = _VALUE_ROLES_FMT if self._cf_active else _VALUE_ROLES
        self._col_stats: dict = {}          # col index -> ColumnStats
        # col index -> [(rule index, [CellStyle | None] down the rows)]
        self._col_cache: dict = {}
        self._row_cache = None              # {rule index: [CellStyle | None]}

    def set_rules(self, rules) -> None:
        """Swap the formatting rules and repaint — no model rebuild, so a
        sort in progress survives."""
        self.beginResetModel()
        self._set_rules(rules)
        self.endResetModel()

    def _is_row_rule(self, rule) -> bool:
        return rule.mode == "highlight" and rule.scope == "row"

    def _row_styles(self) -> dict:
        if self._row_cache is None:
            from flograph.core.table_format import evaluate_rows
            self._row_cache = {
                i: evaluate_rows(self._df, [rule])
                for i, rule in enumerate(self._rules) if self._is_row_rule(rule)}
        return self._row_cache

    def _col_styles(self, col: int) -> list:
        entry = self._col_cache.get(col)
        if entry is None:
            from flograph.core.table_format import (
                column_matches, column_stats, evaluate_column)
            name = str(self._df.columns[col])
            stats = None
            entry = []
            for i, rule in enumerate(self._rules):
                if self._is_row_rule(rule):
                    continue
                if rule.columns and not column_matches(rule.columns, name):
                    continue
                if stats is None:
                    stats = self._col_stats.get(col) or column_stats(
                        self._source.iloc[:, col])
                    self._col_stats[col] = stats
                entry.append((i, evaluate_column(self._df.iloc[:, col], [rule],
                                                 stats, frame=self._df)))
            self._col_cache[col] = entry
        return entry

    def _cell_style(self, row: int, col: int):
        """Every rule that touches this cell, applied in the order they
        appear in the box — a later line wins, whether it is a whole-row
        highlight or a single-cell one."""
        if not self._cf_active:
            return None
        parts = []                         # (rule index, CellStyle)
        for i, styles in self._col_styles(col):
            if row < len(styles) and styles[row] is not None:
                parts.append((i, styles[row]))
        for i, styles in self._row_styles().items():
            if row < len(styles) and styles[row] is not None:
                parts.append((i, styles[row]))
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
            return
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
        # colours follow values: the per-cell styles were built against the
        # old order, the column stats (whole-column min/max/…) still hold
        self._col_cache.clear()
        self._row_cache = None
        self.endResetModel()

    # ------------------------------------------------------------- shape

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else self._loaded

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        if parent.isValid():
            return 0
        return (len(self._df.columns) if self._visible is None
                else len(self._visible))

    def canFetchMore(self, parent: QModelIndex = QModelIndex()) -> bool:
        return not parent.isValid() and self._loaded < len(self._df)

    def fetchMore(self, parent: QModelIndex = QModelIndex()) -> None:
        remaining = len(self._df) - self._loaded
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
        # Bail before touching the frame: Qt asks for roles this model has
        # no opinion on, and `iat` is a real pandas lookup, not a free one.
        # `_value_roles` widens to include the format roles only when a
        # style is actually wired in, so an unformatted table pays nothing.
        if role not in self._value_roles or not index.isValid():
            return None
        col = self._src(index.column())
        value = self._df.iat[index.row(), col]
        style = self._cell_style(index.row(), col) if self._cf_active else None
        if role == _DISPLAY:
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
            if style is not None and style.icon:
                return (style.icon, style.icon_color)
            return None
        if role == _ALIGNMENT:
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                return _ALIGN_NUMBER
        return None

    def headerData(self, section: int, orientation: Qt.Orientation,
                   role: int = Qt.DisplayRole):
        role = int(role)
        if role == _DISPLAY:
            if orientation == _HORIZONTAL:
                return str(self._df.columns[self._src(section)])
            return str(self._df.index[section])
        if role == _TOOLTIP and orientation == _HORIZONTAL:
            return f"dtype: {self._df.dtypes.iloc[self._src(section)]}"
        return None
