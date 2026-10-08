"""Data Validation… — Excel's dialog for what a Table column will take.

*Allow* picks the kind of value (whole number, decimal, date, text length,
or any), *Data* how it compares (between, greater than, …) and the boxes
under them the limits. *Required* says a row with anything in it must
fill the cell. A hint shows beside the cell when it is selected, a custom
message replaces the generated one, and *When a value breaks the rule*
chooses between flagging it red (it still flows on) and turning a typed
value away. A sentence at the foot says, in words, what the rule now
means and how many cells already break it. OK applies the rule to every
selected column as one undo step.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog,
                               QDialogButtonBox, QFormLayout, QFrame,
                               QGroupBox, QHBoxLayout, QLabel, QLineEdit,
                               QRadioButton, QVBoxLayout)

from flograph.core.sheet import validation as rules
from flograph.core.sheet.schema import validate_cell

from .menus import real_window

_PLACEHOLDERS = {
    "whole": ("1", "100"), "number": ("0", "9.99"),
    "date": ("2026-01-01 or today", "today+30"),
    "length": ("1", "10"),
}
_KIND_HELP = {
    "any": "No limit on the value itself — use this for Required on its "
           "own, or just a hint.",
    "whole": "Whole numbers only (no decimals), within the limits.",
    "number": "Any number, decimals too, within the limits.",
    "date": "A date within the limits. A limit can be a date or today, "
            "today+7, today-30 — worked out afresh each time.",
    "length": "Text whose number of characters is within the limits — a "
              "code of exactly 6, a note of at most 200.",
}


class ValidationDialog(QDialog):
    def __init__(self, view, cols: list[int], parent=None) -> None:
        super().__init__(parent)
        model = view.sheet_model()
        self._model, self._cols = model, cols
        names = [model.sheet.columns[c].name for c in cols]
        shown = ", ".join(names[:3]) + (f" and {len(names) - 3} more"
                                        if len(names) > 3 else "")
        self._name = names[0] if len(names) == 1 else "Each cell"
        self.setWindowTitle(f"Data Validation — {shown}")

        layout = QVBoxLayout(self)
        intro = QLabel(
            "Choose what a cell in this column may hold. A value that "
            "breaks the rule turns red and its tooltip says why; nothing "
            "is ever changed for you.")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        criteria = QGroupBox("Rule")
        # the wrapped help and the tick box sit under the form, in a plain
        # box layout: a form row does not give a wrapped label the height
        # its second line needs, and the text was cut off
        crit = QVBoxLayout(criteria)
        form = self._form = QFormLayout()
        crit.addLayout(form)
        self.kind = QComboBox()
        for key, label in rules.KINDS:
            self.kind.addItem(label, key)
        form.addRow("Allow", self.kind)
        self.op = QComboBox()
        for key, label in rules.OPS:
            self.op.addItem(label, key)
        form.addRow("Data", self.op)
        self.a, self.b = QLineEdit(), QLineEdit()
        self.a_label, self.b_label = QLabel("Minimum"), QLabel("Maximum")
        form.addRow(self.a_label, self.a)
        form.addRow(self.b_label, self.b)
        self.kind_help = QLabel()
        self.kind_help.setWordWrap(True)
        self.kind_help.setStyleSheet("color: #9ca3af;")
        crit.addWidget(self.kind_help)
        self.required = QCheckBox("Required — can't be left blank")
        self.required.setToolTip(
            "A row with anything in it must fill this cell. Wholly empty "
            "rows are left alone.")
        crit.addWidget(self.required)
        layout.addWidget(criteria)

        messages = QGroupBox("Messages")
        mform = QFormLayout(messages)
        self.hint = QLineEdit()
        self.hint.setPlaceholderText("e.g. Units shipped, 1 to 100")
        self.hint.setToolTip("Shown beside a cell of the column when it is "
                             "selected — Excel's input message.")
        mform.addRow("Hint when selected", self.hint)
        self.error = QLineEdit()
        self.error.setPlaceholderText("Leave empty to say what the rule is")
        self.error.setToolTip("What a cell that breaks the rule says, in "
                              "place of the generated explanation.")
        mform.addRow("Error message", self.error)
        layout.addWidget(messages)

        alert = QGroupBox("When a value breaks the rule")
        arow = QVBoxLayout(alert)
        self.flag = QRadioButton("Flag it red — it is kept and still flows on")
        self.stop = QRadioButton(
            "Turn it away — a typed value must be fixed before it is kept")
        self.stop.setToolTip(
            "Excel's Stop alert. Paste and fill are never turned away (as "
            "in Excel); what they bring in is flagged instead.")
        arow.addWidget(self.flag)
        arow.addWidget(self.stop)
        layout.addWidget(alert)

        rule_box = QFrame()
        rule_box.setFrameShape(QFrame.StyledPanel)
        rrow = QVBoxLayout(rule_box)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        self.summary.setStyleSheet("font-weight: 600;")
        rrow.addWidget(self.summary)
        self.status = QLabel()
        self.status.setWordWrap(True)
        rrow.addWidget(self.status)
        layout.addWidget(rule_box)

        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok
                                        | QDialogButtonBox.Cancel)
        clear = self.buttons.addButton("Clear Rule",
                                       QDialogButtonBox.DestructiveRole)
        clear.setToolTip("Take the rule off. Values stay as they are.")
        clear.clicked.connect(self._clear)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

        self._load(model.column_validation(cols[0]))
        for box in (self.kind, self.op):
            box.currentIndexChanged.connect(self._refresh)
        for edit in (self.a, self.b, self.hint, self.error):
            edit.textChanged.connect(self._refresh)
        self.required.toggled.connect(self._refresh)
        self._refresh()
        self.resize(480, 0)

    # -------------------------------------------------------------- state

    def _load(self, rule: Optional[dict]) -> None:
        rule = rule or {"kind": "any"}
        self.kind.setCurrentIndex(max(0, self.kind.findData(rule["kind"])))
        self.op.setCurrentIndex(
            max(0, self.op.findData(rule.get("op", "between"))))
        self.a.setText(rule.get("a", ""))
        self.b.setText(rule.get("b", ""))
        self.required.setChecked(bool(rule.get("required")))
        self.hint.setText(rule.get("hint", ""))
        self.error.setText(rule.get("error", ""))
        (self.stop if rule.get("stop") else self.flag).setChecked(True)

    def _clear(self) -> None:
        self._load(None)
        self._cleared = True
        self.accept()

    def chosen(self) -> Optional[dict]:
        if getattr(self, "_cleared", False):
            return None
        return rules.clean({
            "kind": self.kind.currentData(), "op": self.op.currentData(),
            "a": self.a.text(), "b": self.b.text(),
            "required": self.required.isChecked(),
            "hint": self.hint.text(), "error": self.error.text(),
            "stop": self.stop.isChecked()})

    def _refresh(self, *_args) -> None:
        kind, op = self.kind.currentData(), self.op.currentData()
        limited = kind != "any"
        two = rules.two_bounds(op)
        self._form.setRowVisible(self.op, limited)
        self._form.setRowVisible(self.a, limited)
        self._form.setRowVisible(self.b, limited and two)
        if kind == "date":
            first, second = ("Start date", "End date") if two else ("Date",
                                                                    "")
        elif kind == "length":
            first, second = (("Minimum length", "Maximum length") if two
                             else ("Length", ""))
        else:
            first, second = ("Minimum", "Maximum") if two else ("Value", "")
        self.a_label.setText(first)
        self.b_label.setText(second)
        hold_a, hold_b = _PLACEHOLDERS.get(kind, ("", ""))
        self.a.setPlaceholderText(hold_a)
        self.b.setPlaceholderText(hold_b)
        self.kind_help.setText(_KIND_HELP[kind])
        QTimer.singleShot(0, self, self._fit)

        rule = self.chosen()
        ok = self.buttons.button(QDialogButtonBox.Ok)
        problem = rules.bound_problem(rule) if rule else None
        if problem:
            self.summary.setText(problem)
            self.summary.setStyleSheet("font-weight: 600; color: #f87171;")
            self.status.setText("")
            ok.setEnabled(False)
            return
        ok.setEnabled(True)
        self.summary.setStyleSheet("font-weight: 600;")
        self.summary.setText(rules.describe(rule, self._name))
        broken = self._broken(rule)
        self.status.setStyleSheet("color: #fbbf24;" if broken else
                                  "color: #9ca3af;")
        self.status.setText(
            f"{broken} cell{'s' if broken != 1 else ''} already break"
            f"{'' if broken != 1 else 's'} it and will turn red." if broken
            else "Every cell already keeps it." if rule else
            "No rule: the column takes anything its type allows.")

    def _fit(self) -> None:
        """Be exactly as tall as the content at this width: rows come and
        go with Allow and Data, and wrapped text needs its full height."""
        layout = self.layout()
        layout.activate()
        height = (layout.totalHeightForWidth(self.width())
                  if layout.hasHeightForWidth()
                  else layout.totalSizeHint().height())
        self.setMinimumHeight(height)
        self.resize(self.width(), height)

    def _broken(self, rule: Optional[dict]) -> int:
        """How many cells of the chosen columns break the new rule."""
        if rule is None:
            return 0
        sheet = self._model.sheet
        count = 0
        for row_i, row in enumerate(sheet.rows):
            has_data = any(t.strip() for t in row)
            for col in self._cols:
                spec = sheet.columns[col]
                text = row[col]
                if validate_cell(text, spec.type, spec.choices, spec.strict):
                    continue    # already red for its type; counted there
                if rules.check(text, rule, has_data):
                    count += 1
        return count


def edit_validation(view, cols: list[int]) -> None:
    model = view.sheet_model()
    if model is None or model.read_only or not cols:
        return
    dialog = ValidationDialog(view, cols, real_window(view))
    if dialog.exec():
        model.set_column_validation(cols, dialog.chosen())
