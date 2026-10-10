"""The Name Box and the Name Manager — Excel's defined names.

The Name Box is the address box left of the formula bar: it shows the
current cell, lists the names, goes to a name or an address typed into it,
and — type a new name and press Enter — names the selected cells.

The Name Manager (Formulas ▸ Name Manager, or Define Name for the
selection) lists every name with what it refers to and what it holds now,
and adds, changes and deletes them. Each change is one undo step.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QDialog,
                               QDialogButtonBox, QFormLayout, QHBoxLayout,
                               QHeaderView, QLabel, QLineEdit, QPushButton,
                               QTableWidget, QTableWidgetItem, QVBoxLayout)

from flograph.core.sheet import names as nm
from flograph.core.sheet.formula import cell_name

from .menus import real_window


class NameBox(QComboBox):
    """The address box that also knows the names (Excel's Name Box)."""

    entered = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setEditable(True)
        self.setInsertPolicy(QComboBox.NoInsert)
        self.setMinimumContentsLength(6)
        self.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.lineEdit().setAlignment(Qt.AlignCenter)
        self.lineEdit().returnPressed.connect(
            lambda: self.entered.emit(self.lineEdit().text()))
        self.activated.connect(lambda i: self.entered.emit(self.itemText(i)))
        self.setToolTip(
            "The selected cell. Type an address (B4, B2:D10) or a name to go "
            "there; type a new name and press Enter to name the selected "
            "cells — then use it in formulas: =SUM(Sales).")

    def set_names(self, names) -> None:
        text = self.text()
        self.blockSignals(True)
        self.clear()
        self.addItems(sorted(names, key=str.casefold))
        self.setCurrentIndex(-1)
        self.blockSignals(False)
        self.setText(text)

    # the QLabel slice the bar's callers and tests use
    def text(self) -> str:
        return self.lineEdit().text()

    def setText(self, text: str) -> None:
        self.lineEdit().setText(text)


def selection_target(view) -> str:
    rect = view._selection_rect()
    if rect is None:
        return ""
    r0, c0, r1, c1 = rect
    start = cell_name(r0, c0)
    return start if (r0, c0) == (r1, c1) else f"{start}:{cell_name(r1, c1)}"


class NameManager(QDialog):
    def __init__(self, view, new_from_selection: bool = False,
                 parent=None) -> None:
        super().__init__(parent)
        self._view = view
        self._model = view.sheet_model()
        self._editing = None              # the name being changed, or None
        self.setWindowTitle("Name Manager")
        layout = QVBoxLayout(self)
        intro = QLabel("A name stands for a cell or a range, so a formula "
                       "can say =SUM(Sales) instead of =SUM(B2:B40). Names "
                       "move with their cells when rows or columns are "
                       "inserted or deleted.")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Name", "Refers to", "Value"])
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.verticalHeader().hide()
        self.table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.Stretch)
        self.table.itemSelectionChanged.connect(self._picked)
        layout.addWidget(self.table)

        form = QFormLayout()
        self.name = QLineEdit()
        self.name.setPlaceholderText("e.g. Sales")
        self.target = QLineEdit()
        self.target.setPlaceholderText("e.g. B2:B40")
        form.addRow("Name", self.name)
        form.addRow("Refers to", self.target)
        layout.addLayout(form)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        row = QHBoxLayout()
        self.save_btn = QPushButton("Add")
        self.save_btn.clicked.connect(self._save)
        self.new_btn = QPushButton("New")
        self.new_btn.setToolTip("Start a new name for the selected cells.")
        self.new_btn.clicked.connect(self._new)
        self.delete_btn = QPushButton("Delete")
        self.delete_btn.clicked.connect(self._delete)
        for button in (self.save_btn, self.new_btn, self.delete_btn):
            row.addWidget(button)
        row.addStretch(1)
        layout.addLayout(row)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)

        self.name.textChanged.connect(self._check)
        self.target.textChanged.connect(self._check)
        self._fill()
        self._new()
        if not new_from_selection and self.table.rowCount():
            self.table.selectRow(0)
        self.name.setFocus()
        self.resize(520, 420)

    # ------------------------------------------------------------- list

    def _fill(self) -> None:
        names = self._model.names
        self.table.setRowCount(len(names))
        for i, (name, target) in enumerate(sorted(
                names.items(), key=lambda kv: kv[0].casefold())):
            self.table.setItem(i, 0, QTableWidgetItem(name))
            self.table.setItem(i, 1, QTableWidgetItem(nm.plain(target)))
            self.table.setItem(i, 2, QTableWidgetItem(
                self._model.name_value_text(name)))
        self.table.resizeColumnsToContents()

    def _picked(self) -> None:
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return
        name = self.table.item(rows[0].row(), 0).text()
        self._editing = name
        self.name.setText(name)
        self.target.setText(nm.plain(self._model.names.get(name, "")))
        self.save_btn.setText("Change")
        self.delete_btn.setEnabled(True)
        self._check()

    def _new(self) -> None:
        self._editing = None
        self.table.clearSelection()
        self.name.clear()
        self.target.setText(selection_target(self._view))
        self.save_btn.setText("Add")
        self.delete_btn.setEnabled(False)
        self._check()

    def _problem(self):
        from flograph.core.sheet import FUNCTION_NAMES
        taken = [n for n in self._model.names if n != self._editing]
        why = nm.check_name(self.name.text(), taken, FUNCTION_NAMES)
        if why:
            return why, None
        target = nm.parse_target(self.target.text())
        if target.startswith("!"):
            return target[1:], None
        return None, target

    def _check(self, *_args) -> None:
        why, target = self._problem()
        self.save_btn.setEnabled(why is None)
        if why:
            self.status.setStyleSheet("color: #f87171;")
            self.status.setText(why if self.name.text() else
                                "Type a name, then the cells it stands for.")
        else:
            self.status.setStyleSheet("color: #9ca3af;")
            self.status.setText(f"{self.name.text().strip()} will stand for "
                                f"{nm.plain(target)}.")

    def _save(self) -> None:
        why, target = self._problem()
        if why:
            return
        name = self.name.text().strip()
        self._model.define_name(name, target, replacing=self._editing)
        self._fill()
        for i in range(self.table.rowCount()):
            if self.table.item(i, 0).text() == name:
                self.table.selectRow(i)

    def _delete(self) -> None:
        if self._editing:
            self._model.delete_name(self._editing)
            self._fill()
            self._new()


def name_manager(view, new: bool = False) -> None:
    model = view.sheet_model()
    if model is None or model.read_only:
        return
    NameManager(view, new_from_selection=new, parent=real_window(view)).exec()
