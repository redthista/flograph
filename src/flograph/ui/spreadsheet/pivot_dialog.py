"""Insert PivotTable… — Excel's Create PivotTable and its field list in
one small dialog: each selected column goes in Rows, Columns or Values
(or is left out), the values are summed or averaged or counted, and a
preview shows the PivotTable as it will open before anything is added.

What is added is a Show Table wired to this table — its matrix or
grouped mode is the PivotTable (see core/sheet/pivot.py).
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog,
                               QDialogButtonBox, QFormLayout, QHeaderView,
                               QLabel, QTableWidget, QTableWidgetItem,
                               QVBoxLayout)

from flograph.core.sheet.pivot import (AGGS, ROLES, PivotLayout, describe,
                                       guess, pick, preview)
from flograph.core.sheet.summary import _plain, is_number

from .menus import real_window


class PivotDialog(QDialog):
    def __init__(self, columns, parent=None) -> None:
        """``columns`` is (name, type, values) per column on offer."""
        super().__init__(parent)
        self.setWindowTitle("Insert PivotTable")
        self._columns = columns
        self._data = {name: list(values) for name, _t, values in columns}
        start = guess(columns)
        layout = QVBoxLayout(self)
        intro = QLabel(
            "Choose where each column goes. <b>Rows</b> run down the side "
            "and <b>Columns</b> across the top — one line for each "
            "different value; <b>Values</b> are the numbers totalled where "
            "they meet. The PivotTable is a Show Table wired to this table, "
            "so it keeps up as the table changes.")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        self.fields = QTableWidget(len(columns), 2)
        self.fields.setHorizontalHeaderLabels(["Column", "Goes in"])
        self.fields.verticalHeader().hide()
        self.fields.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.Stretch)
        self.fields.setSelectionMode(QTableWidget.NoSelection)
        self.fields.setEditTriggers(QTableWidget.NoEditTriggers)
        self.roles: list[QComboBox] = []
        for i, (name, _t, _v) in enumerate(columns):
            self.fields.setItem(i, 0, QTableWidgetItem(name))
            combo = QComboBox()
            combo.addItems(ROLES)
            combo.setCurrentText(
                "Rows" if name in start.rows
                else "Columns" if name in start.columns
                else "Values" if name in start.values else "Leave out")
            combo.currentTextChanged.connect(self._refresh)
            self.fields.setCellWidget(i, 1, combo)
            self.roles.append(combo)
        self.fields.setMaximumHeight(
            34 + 30 * min(len(columns), 6))
        layout.addWidget(self.fields)

        form = QFormLayout()
        self.agg = QComboBox()
        for key, label in AGGS:
            self.agg.addItem(label, key)
        self.agg.setToolTip("How the values meeting in one cell combine.")
        self.agg.currentIndexChanged.connect(self._refresh)
        form.addRow("Summarise values by", self.agg)
        self.total = QCheckBox("Grand total row")
        self.total.setChecked(True)
        self.total.toggled.connect(self._refresh)
        form.addRow("", self.total)
        layout.addLayout(form)

        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setStyleSheet("font-weight: 600;")
        layout.addWidget(self.status)

        caption = QLabel("Preview")
        caption.setStyleSheet("color: #9ca3af;")
        layout.addWidget(caption)
        self.preview = QTableWidget()
        self.preview.verticalHeader().hide()
        self.preview.setEditTriggers(QTableWidget.NoEditTriggers)
        self.preview.setSelectionMode(QTableWidget.NoSelection)
        layout.addWidget(self.preview, 1)

        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok
                                        | QDialogButtonBox.Cancel)
        self.buttons.button(QDialogButtonBox.Ok).setText("Insert PivotTable")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self._refresh()
        self.resize(520, 560)

    def layout_chosen(self) -> PivotLayout:
        out = PivotLayout(agg=self.agg.currentData(),
                          total=self.total.isChecked())
        for (name, _t, _v), combo in zip(self._columns, self.roles):
            role = combo.currentText()
            if role == "Rows":
                out.rows.append(name)
            elif role == "Columns":
                out.columns.append(name)
            elif role == "Values":
                out.values.append(name)
        return out

    def pick(self):
        return pick(self.layout_chosen())

    def _refresh(self, *_args) -> None:
        chosen = self.layout_chosen()
        self.status.setText(describe(chosen))
        ready = not isinstance(self.pick(), str)
        self.buttons.button(QDialogButtonBox.Ok).setEnabled(ready)
        headers, rows = preview(chosen, self._data)
        self.preview.clear()
        self.preview.setColumnCount(len(headers))
        self.preview.setRowCount(len(rows))
        self.preview.setHorizontalHeaderLabels([str(h) for h in headers])
        for r, row in enumerate(rows):
            for c, value in enumerate(row):
                item = QTableWidgetItem(
                    "" if value is None
                    else _plain(value) if is_number(value) else str(value))
                if is_number(value):
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                if chosen.total and r == len(rows) - 1:
                    font = item.font()
                    font.setBold(True)
                    item.setFont(font)
                self.preview.setItem(r, c, item)
        self.preview.resizeColumnsToContents()


def insert_pivot(view) -> None:
    columns = view.pivot_columns()
    if not columns:
        view.say("Select the columns for the PivotTable first.")
        return
    dialog = PivotDialog(columns, real_window(view))
    if not dialog.exec():
        return
    chosen = dialog.pick()
    if isinstance(chosen, str):
        view.say(chosen)
        return
    said = view.host.insert_pivot(chosen)
    if said:
        view.say(said)
