"""Editable Qt model over a core Sheet, shared by the canvas card and the
pop-out editor.

The model owns a Sheet plus its cached evaluation; every user mutation
re-evaluates the whole sheet (milliseconds at this node's scale) and emits
one ``sheet_edited(dict)`` with the new persisted form — the host decides
what committing means (the card pushes an undo command per edit, the
dialog records local undo steps).
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, Signal
from PySide6.QtGui import QBrush, QColor

from flograph.core.sheet import (COLUMN_TYPES, FormulaError, Sheet,
                                 evaluate_sheet, format_value, is_formula,
                                 normalize_date, parse_sheet,
                                 rename_column_in_formulas, sheet_to_dict,
                                 translate, validate_cell)

_ERROR_TEXT = QColor("#f87171")
_INVALID_BG = QColor(239, 68, 68, 45)


class SheetModel(QAbstractTableModel):
    """Display shows computed values; Edit round-trips raw cell sources."""

    sheet_edited = Signal(dict)   # the new sheet dict, after a user mutation

    def __init__(self, sheet=None, parent=None) -> None:
        super().__init__(parent)
        self._sheet = parse_sheet(sheet) if sheet is not None else parse_sheet(None)
        self._result = evaluate_sheet(self._sheet)
        self._syncing = False
        self._read_only = False

    @property
    def read_only(self) -> bool:
        return self._read_only

    def set_read_only(self, flag: bool) -> None:
        """Linked mode: the grid displays upstream data and refuses edits."""
        if self._read_only != bool(flag):
            self._read_only = bool(flag)
            if self._sheet.n_rows and self._sheet.n_cols:
                self.dataChanged.emit(
                    self.index(0, 0),
                    self.index(self._sheet.n_rows - 1, self._sheet.n_cols - 1))

    # ------------------------------------------------------------- access

    @property
    def sheet(self) -> Sheet:
        return self._sheet

    def sheet_dict(self) -> dict:
        return sheet_to_dict(self._sheet)

    def column_type(self, col: int) -> str:
        if 0 <= col < self._sheet.n_cols:
            return self._sheet.columns[col].type
        return "auto"

    def cell_source(self, row: int, col: int) -> str:
        if 0 <= row < self._sheet.n_rows and 0 <= col < self._sheet.n_cols:
            return self._sheet.cell(row, col)
        return ""

    def cell_error(self, row: int, col: int) -> Optional[str]:
        return self._result.errors.get((row, col))

    def value_text(self, row: int, col: int) -> str:
        """Computed display text (what a copy to Excel should carry)."""
        if 0 <= row < self._sheet.n_rows and 0 <= col < self._sheet.n_cols:
            return format_value(self._result.values[row][col])
        return ""

    def set_sheet(self, sheet) -> None:
        """Sync in externally-changed data (param change, undo/redo)."""
        parsed = parse_sheet(sheet)
        if sheet_to_dict(parsed) == sheet_to_dict(self._sheet):
            return
        self._syncing = True
        try:
            self.beginResetModel()
            self._sheet = parsed
            self._result = evaluate_sheet(self._sheet)
            self.endResetModel()
        finally:
            self._syncing = False

    # ------------------------------------------------------ Qt model API

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else self._sheet.n_rows

    def columnCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else self._sheet.n_cols

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal:
            if role == Qt.DisplayRole and section < self._sheet.n_cols:
                return self._sheet.columns[section].name
            if role == Qt.ToolTipRole and section < self._sheet.n_cols:
                from flograph.core.sheet import col_letters
                col = self._sheet.columns[section]
                return (f"{col.name} — column {col_letters(section)}, "
                        f"type: {col.type} — reference as [@{col.name}]")
        elif role == Qt.DisplayRole:
            return section + 1   # the same 1-based numbers formulas use
        return None

    def flags(self, index):
        if self._read_only:
            return Qt.ItemIsEnabled | Qt.ItemIsSelectable
        flags = (Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsEditable)
        if (self.column_type(index.column()) == "bool"
                and not is_formula(self.cell_source(index.row(),
                                                    index.column()))):
            flags |= Qt.ItemIsUserCheckable
        return flags

    def data(self, index, role=Qt.DisplayRole):
        row, col = index.row(), index.column()
        if not (0 <= row < self._sheet.n_rows and 0 <= col < self._sheet.n_cols):
            return None
        source = self._sheet.cell(row, col)
        value = self._result.values[row][col]
        col_type = self.column_type(col)
        bool_check = col_type == "bool" and not is_formula(source)

        if role == Qt.DisplayRole:
            if bool_check:
                return ""   # the checkbox is the display
            return format_value(value)
        if role == Qt.EditRole:
            return source
        if role == Qt.CheckStateRole and bool_check:
            if source.strip().upper() == "TRUE":
                return Qt.Checked
            if source.strip() == "":
                return None
            return Qt.Unchecked
        if role == Qt.ToolTipRole:
            error = self._result.errors.get((row, col))
            if error:
                return error
            invalid = validate_cell(source, col_type)
            if invalid:
                return invalid
            if is_formula(source):
                return source
            return None
        if role == Qt.ForegroundRole and isinstance(value, FormulaError):
            return QBrush(_ERROR_TEXT)
        if role == Qt.BackgroundRole:
            if validate_cell(source, col_type):
                return QBrush(_INVALID_BG)
            return None
        if role == Qt.TextAlignmentRole:
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                return int(Qt.AlignRight | Qt.AlignVCenter)
            return None
        return None

    def setData(self, index, value, role=Qt.EditRole) -> bool:
        row, col = index.row(), index.column()
        if self._read_only:
            return False
        if not (0 <= row < self._sheet.n_rows and 0 <= col < self._sheet.n_cols):
            return False
        if role == Qt.CheckStateRole:
            checked = Qt.CheckState(value) == Qt.Checked
            return self._set_cell_text(row, col, "TRUE" if checked else "FALSE")
        if role == Qt.EditRole:
            return self._set_cell_text(row, col, "" if value is None else str(value))
        return False

    def _set_cell_text(self, row: int, col: int, text: str) -> bool:
        if self._sheet.cell(row, col) == text:
            return True
        self._sheet.set_cell(row, col, text)
        self._after_mutation()
        return True

    # -------------------------------------------------------- cell edits

    def set_cells(self, origin: tuple[int, int], block: list[list[str]]) -> None:
        """Write a rectangular block of raw sources at origin, growing the
        grid as needed. One mutation -> one undo step for the host."""
        if self._read_only:
            return
        if not block:
            return
        row0, col0 = origin
        self._structural(lambda sheet: self._paste_into(sheet, row0, col0, block))

    @staticmethod
    def _paste_into(sheet: Sheet, row0: int, col0: int,
                    block: list[list[str]]) -> None:
        sheet.ensure_size(row0 + len(block),
                          col0 + max(len(r) for r in block))
        for dr, row in enumerate(block):
            for dc, text in enumerate(row):
                sheet.set_cell(row0 + dr, col0 + dc, text)

    def clear_cells(self, cells) -> None:
        if self._read_only:
            return
        cells = [(r, c) for r, c in cells
                 if 0 <= r < self._sheet.n_rows and 0 <= c < self._sheet.n_cols]
        if not any(self._sheet.cell(r, c) for r, c in cells):
            return
        for r, c in cells:
            self._sheet.set_cell(r, c, "")
        self._after_mutation()

    def fill_down(self, row0: int, row1: int, cols) -> None:
        """Fill each selected column down from its top row, shifting
        relative formula references per row like Excel's Ctrl+D."""
        if self._read_only:
            return
        if row1 <= row0:
            return
        changed = False
        for col in cols:
            top = self._sheet.cell(row0, col)
            for row in range(row0 + 1, row1 + 1):
                text = translate(top, row - row0, 0)
                if self._sheet.cell(row, col) != text:
                    self._sheet.set_cell(row, col, text)
                    changed = True
        if changed:
            self._after_mutation()

    # ---------------------------------------------------- structural ops

    def insert_rows_at(self, at: int, count: int = 1) -> None:
        if self._read_only:
            return
        self.beginInsertRows(QModelIndex(), at, at + count - 1)
        self._sheet.insert_rows(at, count)
        self.endInsertRows()
        self._after_mutation(reset=False)

    def insert_columns_at(self, at: int, count: int = 1) -> None:
        if self._read_only:
            return
        self.beginInsertColumns(QModelIndex(), at, at + count - 1)
        for _ in range(count):
            self._sheet.insert_column(at)
        self.endInsertColumns()
        self._after_mutation(reset=False)

    def remove_rows_at(self, indices) -> None:
        if self._read_only:
            return
        indices = [i for i in indices if 0 <= i < self._sheet.n_rows]
        if not indices or len(set(indices)) >= self._sheet.n_rows:
            return   # never remove the last row
        self._structural(lambda sheet: sheet.remove_rows(indices))

    def remove_columns_at(self, indices) -> None:
        if self._read_only:
            return
        indices = [i for i in indices if 0 <= i < self._sheet.n_cols]
        if not indices or len(set(indices)) >= self._sheet.n_cols:
            return   # never remove the last column
        self._structural(lambda sheet: sheet.remove_columns(indices))

    def rename_column(self, col: int, name: str) -> None:
        if self._read_only:
            return
        name = str(name).strip()
        old = self._sheet.columns[col].name if 0 <= col < self._sheet.n_cols else ""
        if not name or not 0 <= col < self._sheet.n_cols or old == name:
            return
        self._sheet.rename_column(col, name)
        # formulas follow the column: [@old] / [old] refs rewrite to the
        # new name everywhere in the sheet
        for row in self._sheet.rows:
            for c in range(len(row)):
                if is_formula(row[c]):
                    row[c] = rename_column_in_formulas(row[c], old, name)
        self.headerDataChanged.emit(Qt.Horizontal, col, col)
        self._after_mutation(reset=False)

    def set_column_type(self, col: int, col_type: str) -> None:
        if self._read_only:
            return
        if (col_type not in COLUMN_TYPES
                or not 0 <= col < self._sheet.n_cols
                or self._sheet.columns[col].type == col_type):
            return

        def mutate(sheet: Sheet) -> None:
            sheet.set_column_type(col, col_type)
            if col_type == "date":
                # convert what we can read ("23/07/2026", "Jul 5, 2026", …)
                # to ISO; anything unreadable stays put and flags red
                for row in sheet.rows:
                    text = row[col]
                    if not text or is_formula(text):
                        continue
                    normalized = normalize_date(text)
                    if normalized is not None and normalized != text:
                        row[col] = normalized

        self._structural(mutate)

    def set_column_widths(self, widths: dict) -> None:
        """Persist editor column widths (px) into the sheet. Width changes
        don't affect cell values, so no recalculation happens."""
        if self._read_only:
            return
        changed = False
        for col, width in widths.items():
            width = int(width)
            if (0 <= col < self._sheet.n_cols and width > 0
                    and self._sheet.columns[col].width != width):
                self._sheet.columns[col].width = width
                changed = True
        if changed and not self._syncing:
            self.sheet_edited.emit(self.sheet_dict())

    def sort_by(self, col: int, ascending: bool = True) -> None:
        if self._read_only:
            return
        self._structural(lambda sheet: sheet.sort_by(col, ascending))

    def promote_row_to_header(self, row: int) -> None:
        """Use a row's values as the column names and remove the row —
        for pasted data that arrived with its headers in row 1. Blank
        cells keep the current column name; the last remaining row is
        cleared instead of removed."""
        if self._read_only:
            return
        if not 0 <= row < self._sheet.n_rows:
            return
        names = [format_value(value).strip()
                 for value in self._result.values[row]]

        def mutate(sheet: Sheet) -> None:
            for col, name in enumerate(names):
                if name:
                    sheet.rename_column(col, name)
            if sheet.n_rows > 1:
                sheet.remove_rows([row])
            else:
                for col in range(sheet.n_cols):
                    sheet.set_cell(row, col, "")

        self._structural(mutate)

    # ----------------------------------------------------------- plumbing

    def _structural(self, mutate) -> None:
        before = sheet_to_dict(self._sheet)
        self.beginResetModel()
        mutate(self._sheet)
        self._result = evaluate_sheet(self._sheet)
        self.endResetModel()
        if sheet_to_dict(self._sheet) != before and not self._syncing:
            self.sheet_edited.emit(self.sheet_dict())

    def _after_mutation(self, reset: bool = False) -> None:
        self._result = evaluate_sheet(self._sheet)
        if reset:
            self.beginResetModel()
            self.endResetModel()
        elif self._sheet.n_rows and self._sheet.n_cols:
            # a single edit can ripple through formulas anywhere
            self.dataChanged.emit(
                self.index(0, 0),
                self.index(self._sheet.n_rows - 1, self._sheet.n_cols - 1))
        if not self._syncing:
            self.sheet_edited.emit(self.sheet_dict())
