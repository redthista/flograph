"""Find and Replace for a Table grid (Ctrl+F / Ctrl+H).

Looks in what a cell shows *and* in its formula, so "SUM" finds the cells
that use SUM and "1,234" finds the cell that shows it. Replace works on the
cells' contents (formulas included, as Excel does when it looks in
formulas), and Replace All is one undoable change. One window per grid; it
stays open beside the grid while you work.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QDialog, QGridLayout, QHBoxLayout,
                               QLabel, QLineEdit, QPushButton, QVBoxLayout)

from .menus import real_window


class FindDialog(QDialog):
    def __init__(self, view, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Find and Replace")
        self.setModal(False)
        self._view = view

        layout = QVBoxLayout(self)
        grid = QGridLayout()
        grid.addWidget(QLabel("Find:"), 0, 0)
        self.find_edit = QLineEdit()
        self.find_edit.setPlaceholderText("Text, a number, or part of a "
                                          "formula")
        self.find_edit.returnPressed.connect(self.find_next)
        grid.addWidget(self.find_edit, 0, 1)
        self.replace_label = QLabel("Replace with:")
        grid.addWidget(self.replace_label, 1, 0)
        self.replace_edit = QLineEdit()
        self.replace_edit.returnPressed.connect(self.replace_one)
        grid.addWidget(self.replace_edit, 1, 1)
        layout.addLayout(grid)

        options = QHBoxLayout()
        self.match_case = QCheckBox("Match case")
        self.whole_cell = QCheckBox("Whole cell")
        self.whole_cell.setToolTip("Only cells that hold exactly this, not "
                                   "cells that merely contain it.")
        self.in_selection = QCheckBox("Selection only")
        self.in_selection.setToolTip("Replace All changes only the selected "
                                     "cells.")
        for box in (self.match_case, self.whole_cell, self.in_selection):
            options.addWidget(box)
        options.addStretch(1)
        layout.addLayout(options)

        buttons = QHBoxLayout()
        previous = QPushButton("Previous")
        previous.setToolTip("Go to the match before this cell (Shift+Enter)")
        previous.clicked.connect(lambda: self.find_next(backwards=True))
        self.next_button = QPushButton("Find Next")
        self.next_button.setToolTip("Go to the next match (Enter)")
        self.next_button.clicked.connect(self.find_next)
        self.replace_button = QPushButton("Replace")
        self.replace_button.setToolTip(
            "Replace in the current cell, then go to the next match")
        self.replace_button.clicked.connect(self.replace_one)
        self.replace_all_button = QPushButton("Replace All")
        self.replace_all_button.setToolTip(
            "Replace every match at once — one change, one Undo")
        self.replace_all_button.clicked.connect(self.replace_all)
        for button in (previous, self.next_button, self.replace_button,
                       self.replace_all_button):
            button.setAutoDefault(False)
            buttons.addWidget(button)
        layout.addLayout(buttons)

        self.status = QLabel(" ")
        self.status.setStyleSheet("color: #9ca3af;")
        layout.addWidget(self.status)

    def set_replace_mode(self, on: bool) -> None:
        for widget in (self.replace_label, self.replace_edit,
                       self.replace_button, self.replace_all_button,
                       self.in_selection):
            widget.setVisible(on)
        self.setWindowTitle("Find and Replace" if on else "Find")
        self.adjustSize()

    def _options(self) -> dict:
        return {"match_case": self.match_case.isChecked(),
                "whole_cell": self.whole_cell.isChecked()}

    def find_next(self, backwards: bool = False) -> bool:
        text = self.find_edit.text()
        if not text:
            return False
        found = self._view.find_next(text, backwards=backwards,
                                     **self._options())
        self.status.setText(" " if found else f"Nothing matches “{text}”.")
        return found

    def replace_one(self) -> None:
        view, model = self._view, self._view.sheet_model()
        text = self.find_edit.text()
        current = view.currentIndex()
        if model is None or not text:
            return
        if current.isValid():
            changed = model.replace_all(
                text, self.replace_edit.text(),
                cells=[(current.row(), current.column())], **self._options())
            if changed:
                self.status.setText("Replaced 1 cell.")
        self.find_next()

    def replace_all(self) -> None:
        view, model = self._view, self._view.sheet_model()
        text = self.find_edit.text()
        if model is None or not text:
            return
        cells = None
        if self.in_selection.isChecked():
            rect = view._selection_rect()
            if rect is not None:
                r0, c0, r1, c1 = rect
                cells = [(r, c) for r in range(r0, r1 + 1)
                         for c in range(c0, c1 + 1)]
        count = model.replace_all(text, self.replace_edit.text(),
                                  cells=cells, **self._options())
        self.status.setText(
            f"Replaced {count} cell{'s' if count != 1 else ''}."
            if count else f"Nothing matches “{text}”.")

    def keyPressEvent(self, event) -> None:
        if (event.key() in (Qt.Key_Return, Qt.Key_Enter)
                and event.modifiers() & Qt.ShiftModifier):
            self.find_next(backwards=True)
            return
        super().keyPressEvent(event)


def open_find(view, replace: bool = False) -> FindDialog:
    dialog = getattr(view, "_find_dialog", None)
    import shiboken6
    if dialog is None or not shiboken6.isValid(dialog):
        dialog = FindDialog(view, real_window(view))
        view._find_dialog = dialog
    dialog.set_replace_mode(replace and view.editable)
    model = view.sheet_model()
    current = view.currentIndex()
    if model is not None and current.isValid() and not dialog.find_edit.text():
        dialog.find_edit.setText(model.value_text(current.row(),
                                                  current.column()))
    dialog.show()
    dialog.raise_()
    dialog.activateWindow()
    dialog.find_edit.setFocus()
    dialog.find_edit.selectAll()
    return dialog
