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
        if not index.isValid():
            return None
        value = self._df.iat[index.row(), index.column()]
        if role == Qt.DisplayRole:
            if _is_missing(value):
                return "NaN"
            if isinstance(value, float):
                return f"{value:.{FLOAT_PRECISION}g}"
            return str(value)
        if role == Qt.EditRole:
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
        if role == Qt.ForegroundRole and _is_missing(value):
            return _NAN_COLOR
        if role == Qt.FontRole and _is_missing(value):
            font = QFont()
            font.setItalic(True)
            return font
        if role == Qt.TextAlignmentRole:
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                return int(Qt.AlignRight | Qt.AlignVCenter)
        return None

    def headerData(self, section: int, orientation: Qt.Orientation,
                   role: int = Qt.DisplayRole):
        if role == Qt.DisplayRole:
            if orientation == Qt.Horizontal:
                return str(self._df.columns[section])
            return str(self._df.index[section])
        if role == Qt.ToolTipRole and orientation == Qt.Horizontal:
            return f"dtype: {self._df.dtypes.iloc[section]}"
        return None
