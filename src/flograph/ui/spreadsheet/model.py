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

# Resolving an enum attribute like `Qt.DisplayRole` goes through PySide6's
# metaclass and costs ~1.9us on this build. That is nothing once, and a great
# deal here: Qt asks `data()` for seven roles per visible cell per repaint, so
# the role cascade below ran ~2,300 times for one scroll of a 300-row sheet.
# Measured, the cascade alone was 11.0us of the 11.8us a `data()` call took —
# the sheet logic it guards was noise beside it. Bound to plain ints at import,
# the same cascade costs 0.07us, and a card scrolls at Qt's floor instead of
# three times over it. The same reasoning applies to the flag and brush
# constants: build them once, not per cell.
_DISPLAY = int(Qt.DisplayRole)
_EDIT = int(Qt.EditRole)
_CHECK_STATE = int(Qt.CheckStateRole)
_TOOLTIP = int(Qt.ToolTipRole)
_FOREGROUND = int(Qt.ForegroundRole)
_BACKGROUND = int(Qt.BackgroundRole)
_ALIGNMENT = int(Qt.TextAlignmentRole)

_CHECKED = Qt.Checked
_UNCHECKED = Qt.Unchecked
_ALIGN_NUMBER = int(Qt.AlignRight | Qt.AlignVCenter)
_ERROR_BRUSH = QBrush(_ERROR_TEXT)
_INVALID_BRUSH = QBrush(_INVALID_BG)

_VIEW_FLAGS = Qt.ItemIsEnabled | Qt.ItemIsSelectable
_EDIT_FLAGS = _VIEW_FLAGS | Qt.ItemIsEditable
_CHECKABLE = Qt.ItemIsUserCheckable


class SheetModel(QAbstractTableModel):
    """Display shows computed values; Edit round-trips raw cell sources."""

    sheet_edited = Signal(dict)   # the new sheet dict, after a user mutation
    freeze_changed = Signal()     # freeze panes moved (by the user or a sync)

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

    def column_choices(self, col: int) -> tuple[list[str], bool]:
        """A column's dropdown list and whether it is strict."""
        if 0 <= col < self._sheet.n_cols:
            spec = self._sheet.columns[col]
            return list(spec.choices), spec.strict
        return [], False

    def _invalid(self, row: int, col: int, source: str) -> Optional[str]:
        spec = self._sheet.columns[col]
        return validate_cell(source, spec.type, spec.choices, spec.strict)

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
        """Sync in externally-changed data (param change, undo/redo, the
        refresh at the end of a linked run).

        When the grid keeps its layout, the new values go in as a data
        change rather than a model reset. A reset drops the selection, the
        scroll position and any cell being typed into — bearable for an undo
        the user just asked for, but a linked table also gets one of these
        every time a run finishes, which on a slow flow arrives long after
        the edit that caused it and throws the user out of wherever they had
        moved on to.
        """
        parsed = parse_sheet(sheet)
        if sheet_to_dict(parsed) == sheet_to_dict(self._sheet):
            return
        froze = ((parsed.freeze_rows, parsed.freeze_cols)
                 != (self._sheet.freeze_rows, self._sheet.freeze_cols))
        in_place = self._same_layout(parsed)
        self._syncing = True
        try:
            if not in_place:
                self.beginResetModel()
            self._sheet = parsed
            self._result = evaluate_sheet(self._sheet)
            if in_place:
                self.dataChanged.emit(
                    self.index(0, 0),
                    self.index(self._sheet.n_rows - 1,
                               self._sheet.n_cols - 1))
            else:
                self.endResetModel()
        finally:
            self._syncing = False
        if froze:
            self.freeze_changed.emit()

    def _same_layout(self, other: Sheet) -> bool:
        """Can `other` replace the current sheet without a model reset?

        Only when the shape holds and every column keeps its name, type and
        stored width. Width is in there because the view applies stored
        widths on reset and nowhere else, so a change to one has to go the
        long way round; a linked refresh carries the widths through the
        merge unchanged, which is the case this fast path exists for.
        """
        if (other.n_rows != self._sheet.n_rows
                or other.n_cols != self._sheet.n_cols
                or not other.n_rows or not other.n_cols):
            return False
        return (other.freeze_rows == self._sheet.freeze_rows
                and other.freeze_cols == self._sheet.freeze_cols
                and all(new.name == old.name and new.type == old.type
                        and new.width == old.width
                        and new.choices == old.choices
                        and new.strict == old.strict
                        for new, old in zip(other.columns,
                                            self._sheet.columns)))

    # ------------------------------------------------------ Qt model API

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else self._sheet.n_rows

    def columnCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else self._sheet.n_cols

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        # the row header asks per visible row, so the same int-compare rule
        # as data() applies here
        role = int(role)
        if orientation == Qt.Horizontal:
            if role == _DISPLAY and section < self._sheet.n_cols:
                return self._sheet.columns[section].name
            if role == _TOOLTIP and section < self._sheet.n_cols:
                from flograph.core.sheet import col_letters
                col = self._sheet.columns[section]
                return (f"{col.name} — column {col_letters(section)}, "
                        f"type: {col.type} — reference as [@{col.name}]")
        elif role == _DISPLAY:
            return section + 1   # the same 1-based numbers formulas use
        return None

    def flags(self, index):
        if self._read_only:
            return _VIEW_FLAGS
        flags = _EDIT_FLAGS
        if (self.column_type(index.column()) == "bool"
                and not is_formula(self.cell_source(index.row(),
                                                    index.column()))):
            flags |= _CHECKABLE
        return flags

    def data(self, index, role=Qt.DisplayRole):
        # int() once, then integer compares: see the role constants above for
        # why this shape rather than `role == Qt.DisplayRole`
        role = int(role)
        row, col = index.row(), index.column()
        if not (0 <= row < self._sheet.n_rows and 0 <= col < self._sheet.n_cols):
            return None
        source = self._sheet.cell(row, col)
        value = self._result.values[row][col]
        col_type = self.column_type(col)
        bool_check = col_type == "bool" and not is_formula(source)

        if role == _DISPLAY:
            if bool_check:
                return ""   # the checkbox is the display
            return format_value(value)
        if role == _EDIT:
            return source
        if role == _CHECK_STATE and bool_check:
            if source.strip().upper() == "TRUE":
                return _CHECKED
            if source.strip() == "":
                return None
            return _UNCHECKED
        if role == _TOOLTIP:
            error = self._result.errors.get((row, col))
            if error:
                return error
            invalid = self._invalid(row, col, source)
            if invalid:
                return invalid
            if is_formula(source):
                return source
            return None
        if role == _FOREGROUND and isinstance(value, FormulaError):
            return _ERROR_BRUSH
        if role == _BACKGROUND:
            if self._invalid(row, col, source):
                return _INVALID_BRUSH
            return None
        if role == _ALIGNMENT:
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                return _ALIGN_NUMBER
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

    def fill_right(self, col0: int, col1: int, rows) -> None:
        """Ctrl+R: fill each selected row rightwards from its left cell,
        shifting relative references per column."""
        if self._read_only or col1 <= col0:
            return
        changed = False
        for row in rows:
            left = self._sheet.cell(row, col0)
            for col in range(col0 + 1, col1 + 1):
                text = translate(left, 0, col - col0)
                if self._sheet.cell(row, col) != text:
                    self._sheet.set_cell(row, col, text)
                    changed = True
        if changed:
            self._after_mutation()

    def fill_range(self, source: tuple, target: tuple,
                   series: bool = False) -> None:
        """The fill handle: extend `source` (r0, c0, r1, c1) to `target`,
        which grows it in one direction, by Excel's AutoFill rules
        (core/sheet/fill.py). Past the last row or column the grid grows.
        One mutation, so one undo step."""
        if self._read_only:
            return
        from flograph.core.sheet.fill import fill_values
        sr0, sc0, sr1, sc1 = source
        tr0, tc0, tr1, tc1 = target

        def mutate(sheet: Sheet) -> None:
            sheet.ensure_size(tr1 + 1, tc1 + 1)
            if tr1 > sr1 or tr0 < sr0:
                down = tr1 > sr1
                for col in range(sc0, sc1 + 1):
                    seed = [sheet.cell(r, col) for r in range(sr0, sr1 + 1)]
                    if down:
                        rows = range(sr1 + 1, tr1 + 1)
                    else:
                        seed.reverse()
                        rows = range(sr0 - 1, tr0 - 1, -1)
                    values = fill_values(seed, len(rows), along="row",
                                         backwards=not down, series=series)
                    for row, text in zip(rows, values):
                        sheet.set_cell(row, col, text)
            elif tc1 > sc1 or tc0 < sc0:
                right = tc1 > sc1
                for row in range(sr0, sr1 + 1):
                    seed = [sheet.cell(row, c) for c in range(sc0, sc1 + 1)]
                    if right:
                        cols = range(sc1 + 1, tc1 + 1)
                    else:
                        seed.reverse()
                        cols = range(sc0 - 1, tc0 - 1, -1)
                    values = fill_values(seed, len(cols), along="col",
                                         backwards=not right, series=series)
                    for col, text in zip(cols, values):
                        sheet.set_cell(row, col, text)

        grows = tr1 >= self._sheet.n_rows or tc1 >= self._sheet.n_cols
        self._structural(mutate, reset=grows)

    def replace_all(self, find: str, replace: str, *, match_case=False,
                    whole_cell=False, cells=None) -> int:
        """Replace text in cell sources (formulas included, as Excel does
        when looking in formulas). One undo step; returns how many cells
        changed. `cells` limits it to those (row, col) pairs."""
        if self._read_only or not find:
            return 0
        import re
        flags = 0 if match_case else re.IGNORECASE
        pattern = re.compile(
            ("^" + re.escape(find) + "$") if whole_cell else re.escape(find),
            flags)
        targets = (list(cells) if cells is not None else
                   [(r, c) for r in range(self._sheet.n_rows)
                    for c in range(self._sheet.n_cols)])
        changes = {}
        for r, c in targets:
            if not (0 <= r < self._sheet.n_rows and 0 <= c < self._sheet.n_cols):
                continue
            old = self._sheet.cell(r, c)
            new = pattern.sub(lambda _m: replace, old)
            if new != old:
                changes[(r, c)] = new
        if changes:
            def mutate(sheet: Sheet) -> None:
                for (r, c), text in changes.items():
                    sheet.set_cell(r, c, text)
            self._structural(mutate, reset=False)
        return len(changes)

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

    def move_rows(self, indices, to: int) -> None:
        """Move rows as a block to start at `to` (formulas keep their
        addresses, as after a sort)."""
        if self._read_only:
            return
        self._structural(lambda sheet: sheet.move_rows(indices, to))

    def move_columns(self, indices, to: int) -> None:
        if self._read_only:
            return
        self._structural(lambda sheet: sheet.move_columns(indices, to))

    def set_column_choices(self, col: int, choices, strict: bool) -> None:
        """Give a column a dropdown list (empty to remove it)."""
        if self._read_only or not 0 <= col < self._sheet.n_cols:
            return
        choices = [str(c).strip() for c in choices if str(c).strip()]
        strict = bool(strict) and bool(choices)

        def mutate(sheet: Sheet) -> None:
            sheet.columns[col].choices = choices
            sheet.columns[col].strict = strict

        self._structural(mutate)

    def set_freeze(self, rows: int, cols: int) -> None:
        """Freeze panes: this many data rows and columns stay in view."""
        if self._read_only:
            return
        rows = max(0, min(int(rows), self._sheet.n_rows - 1))
        cols = max(0, min(int(cols), self._sheet.n_cols - 1))
        if (rows, cols) == (self._sheet.freeze_rows, self._sheet.freeze_cols):
            return

        def mutate(sheet: Sheet) -> None:
            sheet.freeze_rows, sheet.freeze_cols = rows, cols

        self._structural(mutate, reset=False)
        self.freeze_changed.emit()

    @property
    def freeze(self) -> tuple[int, int]:
        return self._sheet.freeze_rows, self._sheet.freeze_cols

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

    def sort(self, column: int, order=Qt.AscendingOrder) -> None:
        """Header-click entry point (Qt calls it 'sort'). Routes through
        the same undoable structural path as the context menu."""
        self.sort_by(column, order == Qt.AscendingOrder)

    def restore_order(self, rows: list[list[str]]) -> None:
        """Put a stored row order back — the 'clear sort' step."""
        if self._read_only or not rows:
            return
        self._structural(lambda sheet: sheet.set_rows(rows))

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

    def _structural(self, mutate, reset: bool = True) -> None:
        """Apply `mutate` as one edit. `reset=False` for a change that keeps
        the grid's shape (replace, freeze), so the view keeps its place."""
        before = sheet_to_dict(self._sheet)
        if reset:
            self.beginResetModel()
        mutate(self._sheet)
        self._result = evaluate_sheet(self._sheet)
        if reset:
            self.endResetModel()
        elif self._sheet.n_rows and self._sheet.n_cols:
            self.dataChanged.emit(
                self.index(0, 0),
                self.index(self._sheet.n_rows - 1, self._sheet.n_cols - 1))
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
