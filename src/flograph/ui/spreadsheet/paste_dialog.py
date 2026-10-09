"""Paste Special… — Excel's dialog for pasting with choices.

*Paste* picks formulas-and-values or values only; *Operation* adds,
subtracts, multiplies or divides the copied numbers into the numbers
already in the cells (raise every price 10%: copy 1.1, select the prices,
Multiply); *Skip blanks* keeps what is under the copy's empty cells and
*Transpose* turns the copied rows into columns. A sentence says what the
choices will do and a preview shows the first cells as they will be, the
changed ones picked out. Paste writes it all as one undo step.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (QAbstractItemView, QButtonGroup, QCheckBox,
                               QDialog, QDialogButtonBox, QFrame, QGridLayout,
                               QGroupBox, QHBoxLayout, QHeaderView, QLabel,
                               QRadioButton, QTableWidget, QTableWidgetItem,
                               QVBoxLayout)

from flograph.core.sheet.paste import describe, special_block

from .menus import real_window

_OPS = (("none", "None", "Paste over what is there."),
        ("add", "Add", "Add each copied number to the number in the cell — "
                       "dates move on by that many days."),
        ("subtract", "Subtract", "Take each copied number away from the "
                                 "number in the cell."),
        ("multiply", "Multiply", "Multiply the number in the cell by the "
                                 "copied number — copy 1.1 and Multiply to "
                                 "raise prices by 10%. Empty cells stay "
                                 "empty."),
        ("divide", "Divide", "Divide the number in the cell by the copied "
                             "number."))
_PREVIEW_ROWS, _PREVIEW_COLS = 5, 5
_CHANGED = QColor(167, 139, 250, 60)


class PasteSpecialDialog(QDialog):
    def __init__(self, view, parent=None) -> None:
        super().__init__(parent)
        self._view = view
        self._model = model = view.sheet_model()
        self._values, self._sources, self._origin = view.clipboard_cells()
        rect = view._selection_rect()
        self._at = (rect[0], rect[1]) if rect else (0, 0)
        self._fill_to = ((rect[2] - rect[0] + 1, rect[3] - rect[1] + 1)
                         if rect else None)
        self.setWindowTitle("Paste Special")

        layout = QVBoxLayout(self)
        self.where = QLabel()
        self.where.setWordWrap(True)
        layout.addWidget(self.where)

        choices = QHBoxLayout()
        what_box = QGroupBox("Paste")
        what = QVBoxLayout(what_box)
        self.all = QRadioButton("Formulas and values")
        self.all.setToolTip("Formulas come along and adjust to where they "
                            "land, as plain Paste does.")
        self.values = QRadioButton("Values only")
        self.values.setToolTip("What the copied cells showed — the numbers "
                               "stay put when the cells they came from "
                               "change.")
        what.addWidget(self.all)
        what.addWidget(self.values)
        self.formats = QRadioButton("Formats only")
        self.formats.setToolTip("Only the copied cells' look — bold, "
                                "colours, alignment. The values stay.")
        what.addWidget(self.formats)
        self.from_outside = QLabel("Copied from outside the app, so there "
                                   "are only values.")
        self.from_outside.setWordWrap(True)
        self.from_outside.setStyleSheet("color: #9ca3af;")
        what.addWidget(self.from_outside)
        what.addStretch(1)
        if self._sources is None:
            self.values.setChecked(True)
            self.all.setEnabled(False)
            self.formats.setEnabled(False)
        else:
            self.all.setChecked(True)
            self.from_outside.hide()
        choices.addWidget(what_box, 1)

        op_box = QGroupBox("Operation")
        grid = QGridLayout(op_box)
        self.ops = QButtonGroup(self)
        self._op_buttons = {}
        for i, (key, label, tip) in enumerate(_OPS):
            button = QRadioButton(label)
            button.setToolTip(tip)
            self.ops.addButton(button, i)
            self._op_buttons[key] = button
            grid.addWidget(button, i % 3, i // 3)
        self._op_buttons["none"].setChecked(True)
        choices.addWidget(op_box, 1)
        layout.addLayout(choices)

        self.op_help = QLabel()
        self.op_help.setWordWrap(True)
        self.op_help.setStyleSheet("color: #9ca3af;")
        layout.addWidget(self.op_help)

        ticks = QHBoxLayout()
        self.skip = QCheckBox("Skip blanks")
        self.skip.setToolTip("Where a copied cell is empty, keep what is "
                             "already in the cell under it.")
        self.transpose = QCheckBox("Transpose")
        self.transpose.setToolTip("Turn the copied rows into columns and "
                                  "the columns into rows.")
        ticks.addWidget(self.skip)
        ticks.addWidget(self.transpose)
        ticks.addStretch(1)
        layout.addLayout(ticks)

        result = QFrame()
        result.setFrameShape(QFrame.StyledPanel)
        rlay = QVBoxLayout(result)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        self.summary.setStyleSheet("font-weight: 600;")
        rlay.addWidget(self.summary)
        self.preview = QTableWidget()
        self.preview.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.preview.setSelectionMode(QAbstractItemView.NoSelection)
        self.preview.setFocusPolicy(Qt.NoFocus)
        self.preview.horizontalHeader().setSectionResizeMode(
            QHeaderView.Stretch)
        self.preview.verticalHeader().setSectionResizeMode(
            QHeaderView.Fixed)
        self.preview.verticalHeader().setDefaultSectionSize(22)
        rlay.addWidget(self.preview)
        self.preview_note = QLabel()
        self.preview_note.setWordWrap(True)
        self.preview_note.setStyleSheet("color: #9ca3af;")
        rlay.addWidget(self.preview_note)
        layout.addWidget(result)

        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok
                                        | QDialogButtonBox.Cancel)
        self.buttons.button(QDialogButtonBox.Ok).setText("Paste")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

        for box in (self.all, self.values, self.formats, self.skip,
                    self.transpose):
            box.toggled.connect(self._refresh)
        self.ops.idToggled.connect(self._refresh)
        self._refresh()
        self.resize(520, 0)

    # -------------------------------------------------------------- state

    def chosen(self) -> dict:
        op = next(key for key, button in self._op_buttons.items()
                  if button.isChecked())
        what = ("all" if self.all.isChecked() else
                "formats" if self.formats.isChecked() else "values")
        return {"what": what,
                "op": op, "skip_blanks": self.skip.isChecked(),
                "transpose": self.transpose.isChecked()}

    def block(self) -> list:
        model = self._model
        choice = self.chosen()
        if choice["what"] == "formats":
            # only the look changes: every value stays as it is
            shape = special_block(
                values=self._values, at=self._at, fill_to=self._fill_to,
                target=lambda r, c: ("", None),
                transpose=choice["transpose"])
            return [[None] * len(row) for row in shape]
        return special_block(
            values=self._values, sources=self._sources, origin=self._origin,
            at=self._at, fill_to=self._fill_to,
            target=lambda r, c: (model.cell_source(r, c),
                                 model.computed_value(r, c)),
            **self.chosen())

    def _refresh(self, *_args) -> None:
        choice = self.chosen()
        self.op_help.setText(next(tip for key, _l, tip in _OPS
                                  if key == choice["op"]))
        self.all.setEnabled(self._sources is not None
                            and choice["op"] == "none")
        self.formats.setEnabled(self._sources is not None
                                and choice["op"] == "none")
        for button in self._op_buttons.values():
            button.setEnabled(choice["what"] != "formats")
        self.summary.setText(describe(
            choice["what"], choice["op"], choice["skip_blanks"],
            choice["transpose"], self._sources is not None))
        block = self.block()
        rows = len(block)
        cols = max((len(r) for r in block), default=0)
        row0, col0 = self._at
        self.where.setText(
            f"Pasting {_count(rows, 'row')} × {_count(cols, 'column')} "
            f"starting at {self._column_name(col0)}, row {row0 + 1}"
            + (" — the table grows to fit." if self._grows(rows, cols)
               else "."))
        self._fill_preview(block)
        QTimer.singleShot(0, self, self._fit)

    def _column_name(self, col: int) -> str:
        columns = self._model.sheet.columns
        return columns[col].name if col < len(columns) else "a new column"

    def _grows(self, rows: int, cols: int) -> bool:
        return (self._at[0] + rows > self._model.rowCount()
                or self._at[1] + cols > self._model.columnCount())

    def _fill_preview(self, block) -> None:
        model = self._model
        row0, col0 = self._at
        shown_rows = min(len(block), _PREVIEW_ROWS)
        shown_cols = min(max((len(r) for r in block), default=0),
                         _PREVIEW_COLS)
        table = self.preview
        table.clear()
        table.setRowCount(shown_rows)
        table.setColumnCount(shown_cols)
        table.setHorizontalHeaderLabels(
            [self._column_name(col0 + j) for j in range(shown_cols)])
        table.setVerticalHeaderLabels(
            [str(row0 + i + 1) for i in range(shown_rows)])
        bold = QFont(table.font())
        bold.setBold(True)
        changed = 0
        for i in range(shown_rows):
            for j in range(shown_cols):
                new = block[i][j] if j < len(block[i]) else None
                old = model.cell_source(row0 + i, col0 + j)
                item = QTableWidgetItem(old if new is None else new)
                if new is None or new == old:
                    item.setForeground(QColor("#8b909c"))
                else:
                    item.setBackground(_CHANGED)
                    item.setFont(bold)
                    changed += 1
                    if old:
                        item.setToolTip(f"Was: {old}")
                table.setItem(i, j, item)
        extra = []
        if len(block) > shown_rows:
            extra.append(_count(len(block) - shown_rows, "more row"))
        widest = max((len(r) for r in block), default=0)
        if widest > shown_cols:
            extra.append(_count(widest - shown_cols, "more column"))
        note = ("Highlighted cells change; grey ones stay as they are."
                if changed else "Nothing in the cells shown would change.")
        if extra:
            note += f" Not shown: {' and '.join(extra)}."
        self.preview_note.setText(note)
        height = (table.horizontalHeader().height()
                  + 22 * shown_rows + 2 * table.frameWidth() + 2)
        table.setFixedHeight(height)

    def _fit(self) -> None:
        """As tall as the content: the preview changes size with the
        choices, and wrapped text needs its full height."""
        layout = self.layout()
        layout.activate()
        height = (layout.totalHeightForWidth(self.width())
                  if layout.hasHeightForWidth()
                  else layout.totalSizeHint().height())
        self.setMinimumHeight(height)
        self.resize(self.width(), height)


def _count(n: int, noun: str) -> str:
    return f"{n} {noun}{'' if n == 1 else 's'}"


def paste_special(view) -> None:
    model = view.sheet_model()
    if model is None or model.read_only or view.clipboard_cells() is None:
        return
    dialog = PasteSpecialDialog(view, real_window(view))
    if dialog.exec():
        view.paste_special(**dialog.chosen())
