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

PAGE_SIZE = 500
FLOAT_PRECISION = 6

_NAN_COLOR = QColor("#6b7280")

# Bound once at import, and compared as ints. Resolving `Qt.DisplayRole`
# through PySide6's enum metaclass costs ~1.9us on this build, and Qt asks
# data() for seven roles per visible cell on every repaint — which made the
# role cascade, rather than pandas or the painting, the bulk of what a table
# card cost to scroll. See ui/spreadsheet/model.py for the measurement.
_DISPLAY = int(Qt.DisplayRole)
_EDIT = int(Qt.EditRole)
_FOREGROUND = int(Qt.ForegroundRole)
_FONT = int(Qt.FontRole)
_ALIGNMENT = int(Qt.TextAlignmentRole)
_TOOLTIP = int(Qt.ToolTipRole)
_HORIZONTAL = Qt.Horizontal
_ALIGN_NUMBER = int(Qt.AlignRight | Qt.AlignVCenter)
# the roles that need the cell's value at all; anything else can answer
# without touching the frame
_VALUE_ROLES = frozenset({_DISPLAY, _EDIT, _FOREGROUND, _FONT, _ALIGNMENT})


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
    def __init__(self, df: pd.DataFrame, parent=None) -> None:
        super().__init__(parent)
        self._df = df
        self._loaded = min(PAGE_SIZE, len(df))

    def dataframe(self) -> pd.DataFrame:
        """The frame behind the model, whole — not just the rows paged in.

        Copying the whole table goes through this rather than through the
        view, so asking for a million rows does not first have to fetchMore
        its way there.
        """
        return self._df

    # ------------------------------------------------------------- shape

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else self._loaded

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._df.columns)

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
        if role not in _VALUE_ROLES or not index.isValid():
            return None
        value = self._df.iat[index.row(), index.column()]
        if role == _DISPLAY:
            if _is_missing(value):
                return "NaN"
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
        if role == _FOREGROUND and _is_missing(value):
            return _NAN_COLOR
        if role == _FONT and _is_missing(value):
            return _MISSING_FONT
        if role == _ALIGNMENT:
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                return _ALIGN_NUMBER
        return None

    def headerData(self, section: int, orientation: Qt.Orientation,
                   role: int = Qt.DisplayRole):
        role = int(role)
        if role == _DISPLAY:
            if orientation == _HORIZONTAL:
                return str(self._df.columns[section])
            return str(self._df.index[section])
        if role == _TOOLTIP and orientation == _HORIZONTAL:
            return f"dtype: {self._df.dtypes.iloc[section]}"
        return None
