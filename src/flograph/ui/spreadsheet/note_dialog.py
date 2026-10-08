"""New Note… / Edit Note… — a note on one cell, Excel's comment box.

A note is for whoever reads the table next: why a figure is what it is,
who to ask, what is still to check. A red corner marks the cell and the
note shows when the pointer rests on it. It never changes the value or
what the node sends on. Ctrl+Enter saves, as it does in the grid.
"""
from __future__ import annotations

from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QLabel,
                               QPlainTextEdit, QVBoxLayout)

from .menus import real_window


class NoteDialog(QDialog):
    def __init__(self, view, row: int, col: int, parent=None) -> None:
        super().__init__(parent)
        model = view.sheet_model()
        self._had = bool(model.note(row, col))
        self._deleted = False
        name = model.sheet.columns[col].name
        self.setWindowTitle(("Edit Note" if self._had else "New Note")
                            + f" — {name}, row {row + 1}")
        layout = QVBoxLayout(self)
        intro = QLabel("A note for whoever reads the table next. A red "
                       "corner marks the cell; rest the pointer on it to "
                       "read the note. It never changes the value or what "
                       "flows on.")
        intro.setWordWrap(True)
        intro.setStyleSheet("color: #9ca3af;")
        layout.addWidget(intro)
        self.text = QPlainTextEdit()
        self.text.setPlainText(model.note(row, col))
        self.text.setPlaceholderText("e.g. Price agreed with the supplier "
                                     "on 3 Oct — check again in January.")
        self.text.setTabChangesFocus(True)
        layout.addWidget(self.text)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Save
                                        | QDialogButtonBox.Cancel)
        self.buttons.button(QDialogButtonBox.Save).setToolTip(
            "Save the note (Ctrl+Enter).")
        if self._had:
            delete = self.buttons.addButton("Delete Note",
                                            QDialogButtonBox.DestructiveRole)
            delete.setToolTip("Take the note off this cell.")
            delete.clicked.connect(self._delete)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        for keys in ("Ctrl+Return", "Ctrl+Enter"):
            QShortcut(QKeySequence(keys), self, self.accept)
        self.text.setFocus()
        cursor = self.text.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        self.text.setTextCursor(cursor)
        self.resize(380, 220)

    def _delete(self) -> None:
        self._deleted = True
        self.accept()

    def chosen(self) -> str:
        return "" if self._deleted else self.text.toPlainText().strip()


def edit_note(view, row: int, col: int) -> None:
    model = view.sheet_model()
    if model is None or model.read_only:
        return
    dialog = NoteDialog(view, row, col, real_window(view))
    if dialog.exec():
        model.set_note(row, col, dialog.chosen())
