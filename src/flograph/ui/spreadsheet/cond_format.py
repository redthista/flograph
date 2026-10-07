"""Conditional formatting for a Table grid — Show Table's rule system, with
Excel's menu in front of it.

The rules are the same language Show Table reads (core/table_format.py):
one line per rule, in the Table node's `rules` param, so the Properties
panel's box, its linting and its **Rules…** builder all work on them as
they do on a Show Table. What this module adds is the quick way in, where
the grid is: the ribbon's **Conditional Formatting** list and the right-
click menus offer Excel's presets — colour scales, data bars, icon sets,
highlight-cells-that — and each one simply *writes a rule line* for the
selected columns. Nothing here is a second formatting system; a preset is
a rule like any other, and the box shows it, can edit it and can delete it.
"""
from __future__ import annotations

from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog,
                               QDialogButtonBox, QFormLayout, QLabel,
                               QLineEdit, QVBoxLayout)

from flograph.core.table_format import parse_rule_lines, quote_column

from .menus import heading, real_window, submenu

SCALES = (("Green", "green"), ("Blue", "blue"), ("Red", "red"),
          ("Red → Yellow → Green", "red-yellow-green"),
          ("Green → Yellow → Red", "green-yellow-red"),
          ("Red → Green", "red-green"))
BARS = (("Blue", "blue"), ("Green", "green"), ("Orange", "orange"),
        ("Purple", "purple"), ("Red", "red"))
ICON_SETS = (("Traffic Lights  ● ● ●", "traffic"), ("Arrows  ▼ ▬ ▲", "arrows"),
             ("Ticks and Crosses  ✗ – ✓", "check"))
COLOURS = ("red", "amber", "green", "blue", "purple", "grey")

# (menu label, operator, help) for Highlight Cells
HIGHLIGHTS = (
    ("Greater Than…", ">", "Cells above a number."),
    ("Less Than…", "<", "Cells below a number."),
    ("Between…", "between", "Cells from one number to another, both "
                            "included — e.g. 10 20."),
    ("Equal To…", "=", "Cells that equal a value."),
    ("Not Equal To…", "!=", "Cells that don't equal a value."),
    ("Text That Contains…", "contains", "Cells whose text contains "
                                        "something (case is ignored)."),
    ("Text That Starts With…", "starts with", "Cells whose text starts "
                                              "with something."),
    ("Blank Cells", "is empty", "Empty cells."),
    ("Cells That Aren't Blank", "is not empty", "Cells with anything in "
                                                "them."),
)


# ------------------------------------------------------------ rule text

def add_rule(text: str, line: str) -> str:
    """The rules text with `line` added at the end — the bottom rule wins
    where two touch a cell, so a new rule sits on top, as in Excel."""
    text = (text or "").rstrip("\n")
    return f"{text}\n{line}" if text else line


def without_columns(text: str, names) -> str:
    """The rules text with every rule *about* these columns removed (rules
    on other columns, comments and blank lines are kept as written)."""
    from flograph.core.table_format import column_matches
    kept = []
    for raw, rule, _error in parse_rule_lines(text or ""):
        if rule is not None and rule.columns and any(
                column_matches(rule.columns, name) for name in names):
            continue
        kept.append(raw)
    return "\n".join(kept).strip("\n")


def rules_for(text: str, name: str) -> int:
    from flograph.core.table_format import column_matches
    return sum(1 for _raw, rule, _e in parse_rule_lines(text or "")
               if rule is not None and rule.columns
               and column_matches(rule.columns, name))


class HighlightDialog(QDialog):
    """Highlight Cells: the value to test against and how to mark the
    matches — the same choice Excel's Greater Than… box offers."""

    def __init__(self, column: str, label: str, op: str, help_text: str,
                 parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Highlight Cells — {column}")
        self._op = op
        layout = QVBoxLayout(self)
        intro = QLabel(f"<b>{label.rstrip('…')}</b> — {help_text}")
        intro.setWordWrap(True)
        layout.addWidget(intro)
        form = QFormLayout()
        self.value = QLineEdit()
        if op == "between":
            self.value.setPlaceholderText("10 20")
        form.addRow("Value", self.value)
        self.colour = QComboBox()
        for colour in COLOURS:
            self.colour.addItem(colour.capitalize(), colour)
        form.addRow("Fill", self.colour)
        self.bold = QCheckBox("Bold")
        form.addRow("", self.bold)
        self.row = QCheckBox("Colour the whole row")
        self.row.setToolTip("Fill every cell of a matching row, not only "
                            "this column's.")
        form.addRow("", self.row)
        layout.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok
                                   | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        if op in ("is empty", "is not empty"):
            self.value.setEnabled(False)

    def condition(self) -> str:
        value = self.value.text().strip()
        if self._op in ("is empty", "is not empty"):
            return self._op
        return f"{self._op} {value}" if value else ""

    def style(self) -> str:
        colour = self.colour.currentData()
        if self.row.isChecked():
            return f"row {colour}"
        return f"bg {colour}" + (", bold" if self.bold.isChecked() else "")


# ------------------------------------------------------------- the menu

def _apply(view, make_line) -> None:
    host, model = view.host, view.sheet_model()
    cols = view.target_columns()
    if model is None or not cols or not host.can_format():
        return
    text = host.rules()
    for col in cols:
        line = make_line(quote_column(model.sheet.columns[col].name))
        if line:
            text = add_rule(text, line)
    host.set_rules(text)


def _highlight(view, label: str, op: str, help_text: str) -> None:
    model = view.sheet_model()
    cols = view.target_columns()
    if model is None or not cols:
        return
    name = model.sheet.columns[cols[0]].name
    dialog = HighlightDialog(name, label, op, help_text, real_window(view))
    if not dialog.exec():
        return
    condition, style = dialog.condition(), dialog.style()
    if not condition:
        return
    _apply(view, lambda col: f"{col} {condition} => {style}")


def clear_columns(view) -> None:
    host, model = view.host, view.sheet_model()
    cols = view.target_columns()
    if model is None or not cols:
        return
    names = [model.sheet.columns[c].name for c in cols]
    host.set_rules(without_columns(host.rules(), names))


def manage_rules(view) -> None:
    """Show Table's rules manager, on this table's columns."""
    from ..properties.table_rule_wizard import RuleManager
    host, model = view.host, view.sheet_model()
    if model is None or not host.can_format():
        return
    dialog = RuleManager(host.rules(), model.sheet.column_names(),
                         real_window(view))
    if dialog.exec():
        host.set_rules(dialog.result_text())


def fill_menu(menu, view) -> None:
    """The Conditional Formatting list, for the selected columns."""
    from .icons import sheet_icon
    host = view.host
    if not host.can_format():
        action = menu.addAction("Conditional formatting needs a Table node")
        action.setEnabled(False)
        return
    heading(menu, "For the selected columns")
    sub = submenu(menu, "Colour Scale", sheet_icon("cf_scale"))
    sub.setToolTip("Shade each cell by its value — the larger, the "
                   "stronger.")
    for label, preset in SCALES:
        sub.addAction(label).triggered.connect(
            lambda _=False, p=preset: _apply(view,
                                             lambda c: f"{c} scale {p}"))
    sub = submenu(menu, "Data Bar", sheet_icon("cf_bar"))
    for label, preset in BARS:
        sub.addAction(label).triggered.connect(
            lambda _=False, p=preset: _apply(view, lambda c: f"{c} bar {p}"))
    sub = submenu(menu, "Icon Set", sheet_icon("cf_icons"))
    for label, preset in ICON_SETS:
        sub.addAction(label).triggered.connect(
            lambda _=False, p=preset: _apply(view,
                                             lambda c: f"{c} icons {p}"))
    sub = submenu(menu, "Highlight Cells", sheet_icon("cf_highlight"))
    for label, op, help_text in HIGHLIGHTS:
        action = sub.addAction(label)
        action.setToolTip(help_text)
        action.triggered.connect(
            lambda _=False, la=label, o=op, h=help_text:
            _highlight(view, la, o, h))
    menu.addSeparator()
    model = view.sheet_model()
    cols = view.target_columns()
    count = sum(rules_for(host.rules(), model.sheet.columns[c].name)
                for c in cols) if model is not None else 0
    clear = menu.addAction(sheet_icon("filter_clear"),
                           f"Clear Rules from Column ({count})")
    clear.setEnabled(count > 0)
    clear.triggered.connect(lambda: clear_columns(view))
    every = menu.addAction("Clear All Rules")
    every.setEnabled(bool(host.rules().strip()))
    every.triggered.connect(lambda: host.set_rules(""))
    menu.addSeparator()
    manage = menu.addAction(sheet_icon("cf_manage"), "Manage Rules…")
    manage.setToolTip("Every rule on this table, to add, edit, reorder and "
                      "remove — the same rule builder Show Table uses.")
    manage.triggered.connect(lambda: manage_rules(view))
