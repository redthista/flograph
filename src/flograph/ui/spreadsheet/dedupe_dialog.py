"""Remove Duplicates… — Excel's dialog: tick the columns that make a row
the same as another, see how many rows would go, then remove them (one
undo step) or just select them to look at first.

Rows are compared by what their cells show, ignoring case and spaces
around a value; the first row of each set stays. Rows a filter hides are
left alone.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QHBoxLayout,
                               QLabel, QListWidget, QListWidgetItem,
                               QPushButton, QVBoxLayout)

from flograph.core.sheet.dedupe import duplicate_rows

from .menus import real_window


class DedupeDialog(QDialog):
    def __init__(self, view, cols: list[int], parent=None) -> None:
        super().__init__(parent)
        self._view = view
        model = self._model = view.sheet_model()
        self.setWindowTitle("Remove Duplicates")
        self.choice = None          # "remove" or "select" once closed
        layout = QVBoxLayout(self)
        intro = QLabel("Tick the columns to compare. A row whose ticked "
                       "cells all match an earlier row is a duplicate; the "
                       "first row of each set stays.")
        intro.setWordWrap(True)
        layout.addWidget(intro)
        if view.filtered:
            hidden = QLabel("A filter is on: only the rows shown are "
                            "compared and removed; hidden rows stay.")
            hidden.setWordWrap(True)
            hidden.setStyleSheet("color: #fbbf24;")
            layout.addWidget(hidden)

        row = QHBoxLayout()
        every = QPushButton("Select All")
        none = QPushButton("Unselect All")
        every.clicked.connect(lambda: self._tick_all(True))
        none.clicked.connect(lambda: self._tick_all(False))
        row.addWidget(every)
        row.addWidget(none)
        row.addStretch(1)
        layout.addLayout(row)

        self.columns = QListWidget()
        ticked = set(cols) if len(cols) > 1 else set(range(model.columnCount()))
        for c, name in enumerate(model.sheet.column_names()):
            item = QListWidgetItem(name)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if c in ticked else Qt.Unchecked)
            self.columns.addItem(item)
        self.columns.itemChanged.connect(self._refresh)
        layout.addWidget(self.columns)

        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setStyleSheet("font-weight: 600;")
        layout.addWidget(self.status)

        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok
                                        | QDialogButtonBox.Cancel)
        self.buttons.button(QDialogButtonBox.Ok).setText("Remove Duplicates")
        self.select_btn = self.buttons.addButton(
            "Select Them", QDialogButtonBox.ActionRole)
        self.select_btn.setToolTip("Select the duplicate rows to look at "
                                   "before removing anything.")
        self.select_btn.clicked.connect(self._select)
        self.buttons.accepted.connect(self._remove)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self._refresh()
        self.resize(380, 420)

    def chosen_columns(self) -> list[int]:
        return [i for i in range(self.columns.count())
                if self.columns.item(i).checkState() == Qt.Checked]

    def duplicates(self) -> list[int]:
        return self._view.duplicate_rows(self.chosen_columns())

    def _tick_all(self, on: bool) -> None:
        for i in range(self.columns.count()):
            self.columns.item(i).setCheckState(Qt.Checked if on
                                               else Qt.Unchecked)

    def _refresh(self, *_args) -> None:
        ok = self.buttons.button(QDialogButtonBox.Ok)
        if not self.chosen_columns():
            self.status.setText("Tick at least one column.")
            ok.setEnabled(False)
            self.select_btn.setEnabled(False)
            return
        dupes = self.duplicates()
        shown = [r for r in range(self._model.rowCount())
                 if not self._view.row_filtered(r)]
        ok.setEnabled(bool(dupes))
        self.select_btn.setEnabled(bool(dupes))
        if not dupes:
            self.status.setText("No duplicates — every row is different "
                                "on these columns.")
            return
        names = ", ".join(str(r + 1) for r in dupes[:6]) + (
            "…" if len(dupes) > 6 else "")
        rows = "row" if len(dupes) == 1 else "rows"
        self.status.setText(
            f"{len(dupes)} duplicate {rows} (row {names}) will be removed; "
            f"{len(shown) - len(dupes)} will remain.")

    def _remove(self) -> None:
        self.choice = "remove"
        self.accept()

    def _select(self) -> None:
        self.choice = "select"
        self.accept()


def remove_duplicates(view) -> None:
    model = view.sheet_model()
    if model is None or model.read_only or model.rowCount() < 2:
        return
    dialog = DedupeDialog(view, view.target_columns(), real_window(view))
    if dialog.exec():
        cols = dialog.chosen_columns()
        if dialog.choice == "select":
            view.select_duplicates(cols)
        else:
            view.drop_duplicates(cols)
