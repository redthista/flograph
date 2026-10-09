"""Fill Series… — Excel's Series dialog.

Fills the selection from its first cell, down each column or across each
row: Linear adds the step, Growth multiplies by it, Date moves on by days,
weekdays, months or years, AutoFill uses the fill handle's rules. A stop
value ends the series early — and with one cell selected says how far to
go, the table growing to fit. A line shows the values before anything
changes; one undo step.
"""
from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (QButtonGroup, QDialog, QDialogButtonBox,
                               QFormLayout, QGroupBox, QHBoxLayout, QLabel,
                               QLineEdit, QRadioButton, QVBoxLayout)

from flograph.core.sheet import series
from flograph.core.sheet.schema import is_formula

from .menus import real_window

_KIND_HELP = {
    "linear": "Each value is the one before plus the step: 1, 3, 5, 7 …",
    "growth": "Each value is the one before times the step: 2, 4, 8, 16 …",
    "date": "Each date moves on by the step — in days, weekdays (skipping "
            "Saturday and Sunday), months or years.",
    "autofill": "The fill handle's rules: Mon → Tue, Item 1 → Item 2, "
                "formulas shifted.",
}


class SeriesDialog(QDialog):
    def __init__(self, view, rect, parent=None) -> None:
        super().__init__(parent)
        self._view = view
        self._model = view.sheet_model()
        self._rect = rect
        self.setWindowTitle("Fill Series")
        layout = QVBoxLayout(self)

        row = QHBoxLayout()
        where = QGroupBox("Series in")
        where_lay = QVBoxLayout(where)
        self.columns = QRadioButton("Columns — down")
        self.rows = QRadioButton("Rows — across")
        where_lay.addWidget(self.columns)
        where_lay.addWidget(self.rows)
        r0, c0, r1, c1 = rect
        (self.rows if c1 - c0 > r1 - r0 else self.columns).setChecked(True)
        row.addWidget(where)

        kind_box = QGroupBox("Type")
        kind_lay = QVBoxLayout(kind_box)
        self.kinds = QButtonGroup(self)
        self._kind_buttons = {}
        for i, (key, label) in enumerate(series.KINDS):
            button = QRadioButton(label)
            button.setToolTip(_KIND_HELP[key])
            self.kinds.addButton(button, i)
            self._kind_buttons[key] = button
            kind_lay.addWidget(button)
        row.addWidget(kind_box)

        unit_box = self.unit_box = QGroupBox("Date unit")
        unit_lay = QVBoxLayout(unit_box)
        self.units = QButtonGroup(self)
        self._unit_buttons = {}
        for i, (key, label) in enumerate(series.UNITS):
            button = QRadioButton(label)
            self.units.addButton(button, i)
            self._unit_buttons[key] = button
            unit_lay.addWidget(button)
        self._unit_buttons["day"].setChecked(True)
        row.addWidget(unit_box)
        layout.addLayout(row)

        self.help = QLabel()
        self.help.setWordWrap(True)
        self.help.setStyleSheet("color: #9ca3af;")
        layout.addWidget(self.help)

        form = QFormLayout()
        self.step = QLineEdit("1")
        self.stop = QLineEdit()
        self.stop.setPlaceholderText("optional — where to end")
        form.addRow("Step value", self.step)
        form.addRow("Stop value", self.stop)
        layout.addLayout(form)

        self.preview = QLabel()
        self.preview.setWordWrap(True)
        self.preview.setStyleSheet("font-weight: 600;")
        layout.addWidget(self.preview)

        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok
                                        | QDialogButtonBox.Cancel)
        self.buttons.button(QDialogButtonBox.Ok).setText("Fill")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

        first = self.first_value(r0, c0)
        from flograph.core.sheet.fill import _as_date
        start = "date" if _as_date(first) is not None else (
            "linear" if series.check(first, "linear", "1", "") is None
            else "autofill")
        self._kind_buttons[start].setChecked(True)

        for box in (self.columns, self.rows):
            box.toggled.connect(self._refresh)
        self.kinds.idToggled.connect(self._refresh)
        self.units.idToggled.connect(self._refresh)
        self.step.textChanged.connect(self._refresh)
        self.stop.textChanged.connect(self._refresh)
        self._refresh()
        self.resize(460, 0)

    # -------------------------------------------------------------- state

    def first_value(self, row: int, col: int) -> str:
        model = self._model
        source = model.cell_source(row, col)
        return source if not is_formula(source) else model.value_text(row,
                                                                      col)

    def chosen(self) -> dict:
        kind = next(k for k, b in self._kind_buttons.items() if b.isChecked())
        unit = next(k for k, b in self._unit_buttons.items() if b.isChecked())
        return {"kind": kind, "unit": unit, "step": self.step.text().strip(),
                "stop": self.stop.text().strip(),
                "down": self.columns.isChecked()}

    def plan(self):
        """[(origin, values)] — each line's first cell and what follows it
        — or a sentence saying why not."""
        c = self.chosen()
        r0, c0, r1, c1 = self._rect
        single = (r0, c0) == (r1, c1)
        lines = ([(r0, col) for col in range(c0, c1 + 1)] if c["down"]
                 else [(row, c0) for row in range(r0, r1 + 1)])
        length = (r1 - r0) if c["down"] else (c1 - c0)
        out = []
        for origin in lines:
            source = self._model.cell_source(*origin)
            first = (source if c["kind"] == "autofill"
                     else self.first_value(*origin))
            if not first.strip() and len(lines) > 1:
                continue                     # an empty line stays empty
            values = series.series_values(
                first, None if single else length, c["kind"], c["step"],
                c["stop"], c["unit"], along="row" if c["down"] else "col")
            if isinstance(values, str):
                return values
            out.append((origin, values))
        if not out:
            return "The selection's first cells are empty."
        return out

    def _refresh(self, *_args) -> None:
        c = self.chosen()
        self.unit_box.setEnabled(c["kind"] == "date")
        self.step.setEnabled(c["kind"] != "autofill")
        self.stop.setEnabled(c["kind"] != "autofill")
        self.help.setText(_KIND_HELP[c["kind"]])
        ok = self.buttons.button(QDialogButtonBox.Ok)
        plan = self.plan()
        if isinstance(plan, str):
            self.preview.setStyleSheet("font-weight: 600; color: #f87171;")
            self.preview.setText(plan)
            ok.setEnabled(False)
        else:
            self.preview.setStyleSheet("font-weight: 600;")
            origin, values = plan[0]
            first = self.first_value(*origin) if c["kind"] != "autofill" \
                else self._model.cell_source(*origin)
            shown = [first] + values
            text = ", ".join(shown[:8]) + (" …" if len(shown) > 8 else "")
            more = (f" — and {len(plan) - 1} more "
                    f"{'columns' if c['down'] else 'rows'} the same way"
                    if len(plan) > 1 else "")
            self.preview.setText(f"{text}  ({len(values)} new "
                                 f"value{'s' if len(values) != 1 else ''})"
                                 + more)
            ok.setEnabled(any(values for _o, values in plan))
        QTimer.singleShot(0, self, self._fit)

    def _fit(self) -> None:
        layout = self.layout()
        layout.activate()
        height = (layout.totalHeightForWidth(self.width())
                  if layout.hasHeightForWidth()
                  else layout.totalSizeHint().height())
        self.setMinimumHeight(height)
        self.resize(self.width(), height)


def fill_series(view) -> None:
    model = view.sheet_model()
    rect = view._selection_rect()
    if model is None or model.read_only or rect is None:
        return
    dialog = SeriesDialog(view, rect, real_window(view))
    if dialog.exec():
        plan = dialog.plan()
        if not isinstance(plan, str):
            view.write_series(plan, dialog.chosen()["down"])
