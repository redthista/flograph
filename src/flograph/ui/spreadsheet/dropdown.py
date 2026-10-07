"""Dropdown lists — Excel's data validation "List", for a Table column.

A column can carry a list of values (`ColumnSpec.choices`). Its current
cell then shows a ▾; click it (or press Alt+Down) and the list opens to
pick from. Typing still works as in any cell. A *strict* list turns
anything not on it red, like any other value that doesn't fit its column;
a loose one is only a suggestion.

The list opens as a menu window, not as a combo box inside the cell: on a
canvas card a combo's popup would be embedded in the scene (see
canvas/popup_lift.py), and an editor that closes as its own popup takes
focus loses the pick.
"""
from __future__ import annotations

from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox,
                               QHBoxLayout, QLabel, QPlainTextEdit,
                               QPushButton, QVBoxLayout)

from .menus import exec_menu, heading, new_menu, real_window


def open_choice_list(view, index) -> None:
    model = view.sheet_model()
    if model is None or not index.isValid():
        return
    choices, strict = model.column_choices(index.column())
    if not choices:
        return
    current = model.cell_source(index.row(), index.column()).strip()
    menu = new_menu(view.viewport())
    heading(menu, model.sheet.columns[index.column()].name)
    for value in choices:
        action = menu.addAction(value)
        action.setCheckable(True)
        action.setChecked(value.casefold() == current.casefold())
        action.triggered.connect(
            lambda _=False, v=value: model.setData(index, v, Qt.EditRole))
    menu.addSeparator()
    clear = menu.addAction("(blank)")
    clear.setToolTip("Empty the cell.")
    clear.triggered.connect(
        lambda: model.setData(index, "", Qt.EditRole))
    rect = view.visualRect(index)
    exec_menu(menu, view.viewport(), QPoint(rect.left(), rect.bottom() + 1))


class DropdownListDialog(QDialog):
    """Edit one column's list: one value per line."""

    def __init__(self, view, col: int, parent=None) -> None:
        super().__init__(parent)
        model = view.sheet_model()
        name = model.sheet.columns[col].name
        choices, strict = model.column_choices(col)
        self.setWindowTitle(f"Dropdown List — {name}")
        self._view, self._col = view, col

        layout = QVBoxLayout(self)
        intro = QLabel(
            f"The values a cell in <b>{name}</b> can be picked from — one "
            "per line. The current cell of the column shows a ▾ to open the "
            "list (Alt+Down from the keyboard); typing still works as "
            "usual.")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        self.edit = QPlainTextEdit("\n".join(choices))
        self.edit.setPlaceholderText("Open\nIn progress\nDone")
        layout.addWidget(self.edit, 1)

        fill = QPushButton("Fill From Column")
        fill.setToolTip("Put every distinct value already in this column "
                        "into the list, in the order they first appear.")
        fill.clicked.connect(self._fill_from_column)
        row = QHBoxLayout()
        row.addWidget(fill)
        row.addStretch(1)
        layout.addLayout(row)

        self.strict = QCheckBox("Only allow values on the list")
        self.strict.setToolTip(
            "Anything else turns red and its tooltip says why — as a number "
            "in a number column would. Off, the list is a suggestion.")
        self.strict.setChecked(strict)
        layout.addWidget(self.strict)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok
                                   | QDialogButtonBox.Cancel)
        remove = buttons.addButton("Remove List",
                                   QDialogButtonBox.DestructiveRole)
        remove.setToolTip("Take the list off this column. Its values stay.")
        remove.clicked.connect(self._remove)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.resize(380, 360)

    def values(self) -> list[str]:
        seen, out = set(), []
        for line in self.edit.toPlainText().splitlines():
            value = line.strip()
            if value and value.casefold() not in seen:
                seen.add(value.casefold())
                out.append(value)
        return out

    def _fill_from_column(self) -> None:
        model = self._view.sheet_model()
        existing = self.values()
        seen = {v.casefold() for v in existing}
        for row in range(model.rowCount()):
            value = model.value_text(row, self._col).strip()
            if value and value.casefold() not in seen:
                seen.add(value.casefold())
                existing.append(value)
        self.edit.setPlainText("\n".join(existing))

    def _remove(self) -> None:
        self.edit.setPlainText("")
        self.strict.setChecked(False)
        self.accept()


def edit_dropdown_list(view, col: int) -> None:
    model = view.sheet_model()
    if model is None or model.read_only or not 0 <= col < model.columnCount():
        return
    dialog = DropdownListDialog(view, col, real_window(view))
    if dialog.exec():
        model.set_column_choices(col, dialog.values(),
                                 dialog.strict.isChecked())
