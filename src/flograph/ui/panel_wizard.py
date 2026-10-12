"""Set up an Input Panel without writing its field lines by hand.

A row per field — label, shape, column, comparison, options — over the
columns of the table wired into the panel, with "Suggest from data" to
propose a field for every column worth one. The panel's own settings that
decide how it behaves (how fields filter each other, when changes apply,
the layout) sit above the rows, so one dialog sets the panel up.

The dialog edits a list of field dicts and writes them back as the very
lines a person would type (core.input_panel.dump_fields), so the Fields box
stays the source of truth and stays readable: the wizard is a way of
writing it, not a second format beside it.

Opened from three places — the Fields box's button in Properties, the
node's right-click menu, and the button on an empty panel card — all
through `open_panel_wizard`, so they can't differ in what OK does.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
    QFormLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QPlainTextEdit,
    QPushButton, QTableWidget, QVBoxLayout, QWidget,
)

from flograph.core import control_apply as ca
from flograph.core import input_panel as ip

# shape -> what the dropdown says, in the order it lists them
SHAPE_LABELS = [
    ("list", "Slicer (tick list)"),
    ("choice", "Dropdown / buttons"),
    ("multi", "Chips (pick several)"),
    ("range", "Between (two handles)"),
    ("slider", "Slider"),
    ("number", "Number box"),
    ("date_range", "Date range"),
    ("date", "Date"),
    ("text", "Search text"),
    ("toggle", "Switch"),
    ("time", "Time"),
    ("datetime", "Date & time"),
    ("colour", "Colour"),
]
COMPARISON_LABELS = {
    ">=": "at least", "<=": "at most", ">": "more than", "<": "less than",
    "==": "exactly", "contains": "contains", "startswith": "starts with",
}
APPLY_LABELS = [
    (ca.LIVE, "As soon as a field changes"),
    (ca.BUTTON, "When Apply on the panel is pressed"),
    (ca.WAIT, "When an Apply button on the page is pressed"),
]
CASCADE_LABELS = [
    (ip.EACH_OTHER, "Each other (like Power BI slicers)"),
    (ip.TOP_DOWN, "Top to bottom"),
    (ip.OFF, "Not at all"),
]
LAYOUTS = ["stacked", "row", "2 columns", "3 columns"]
NO_COLUMN = "(no column — just a value)"

_USE, _LABEL, _SHAPE, _COLUMN, _OP, _OPTS = range(6)


def _combo(pairs, current) -> QComboBox:
    combo = QComboBox()
    for value, label in pairs:
        combo.addItem(label, value)
    index = combo.findData(current)
    combo.setCurrentIndex(max(0, index))
    return combo


def _opts_text(opts: dict) -> str:
    return " ".join(f"{k}={ip._quoted(v)}" for k, v in (opts or {}).items()
                    if v not in (None, ""))


def _parse_opts(text: str) -> dict:
    import shlex
    opts: dict = {}
    try:
        words = shlex.split(text or "")
    except ValueError:
        words = (text or "").split()
    for word in words:
        key, eq, value = word.partition("=")
        if eq and key.strip():
            opts[key.strip().lower()] = value
    return opts


class PanelWizard(QDialog):
    """The setup dialog. `result_params()` is what OK hands back: the
    params to write on the panel, by name."""

    def __init__(self, params: dict, data=None, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Set Up Input Panel")
        self.resize(980, 720)
        self._data = data
        self._columns = [str(c) for c in getattr(data, "columns", [])]

        layout = QVBoxLayout(self)
        intro = QLabel(
            "Each row is one field on the panel. A field with a column "
            "filters the panel's table on it; one without is just a value "
            "the flow can read. Fields are shown in this order.")
        intro.setWordWrap(True)
        layout.addWidget(intro)
        self._source = QLabel()
        self._source.setObjectName("wizard_source")
        self._source.setWordWrap(True)
        if self._columns:
            self._source.setText(
                f"Columns from the table wired into the panel: "
                f"{len(self._columns)} — {len(data):,} rows.")
        else:
            self._source.setText(
                "No table yet — wire one into the panel's data input and "
                "run it, and its columns will be offered here (and "
                "Suggest from data will work). You can still type column "
                "names.")
        layout.addWidget(self._source)

        # the panel's own behaviour, set once for every field
        form = QFormLayout()
        self._cascade = _combo(CASCADE_LABELS,
                               ip.cascade_mode(params.get("cascade")))
        self._apply = _combo(APPLY_LABELS, params.get("apply") or ca.LIVE)
        self._layout = QComboBox()
        self._layout.addItems(LAYOUTS)
        self._layout.setCurrentText(str(params.get("layout") or "stacked"))
        self._caption = QLineEdit(str(params.get("caption") or ""))
        self._caption.setPlaceholderText("Shown above the fields")
        form.addRow("Caption", self._caption)
        form.addRow("Fields filter", self._cascade)
        form.addRow("Changes apply", self._apply)
        form.addRow("Layout", self._layout)
        layout.addLayout(form)

        self.table = QTableWidget(0, 6)
        self.table.setObjectName("wizard_fields")
        self.table.setHorizontalHeaderLabels(
            ["Use", "Label", "Shape", "Column", "Filters rows where …",
             "Options"])
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(_LABEL, QHeaderView.Stretch)
        header.setSectionResizeMode(_OPTS, QHeaderView.Stretch)
        for col in (_USE, _SHAPE, _COLUMN, _OP):
            header.setSectionResizeMode(col, QHeaderView.ResizeToContents)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.verticalHeader().setVisible(False)
        layout.addWidget(self.table, 1)

        buttons = QHBoxLayout()
        self._add = QPushButton("Add Field")
        self._remove = QPushButton("Remove")
        self._up = QPushButton("↑ Up")
        self._down = QPushButton("↓ Down")
        self._suggest = QPushButton("Suggest from Data")
        self._suggest.setEnabled(bool(self._columns))
        self._suggest.setToolTip(
            "Propose a field for every column worth one: text becomes a "
            "slicer or buttons, numbers a between, dates a date range, "
            "true/false a switch")
        self._add.clicked.connect(lambda: self.add_field(None))
        self._remove.clicked.connect(self._remove_row)
        self._up.clicked.connect(lambda: self._move(-1))
        self._down.clicked.connect(lambda: self._move(1))
        self._suggest.clicked.connect(self.suggest)
        for button in (self._add, self._remove, self._up, self._down):
            buttons.addWidget(button)
        buttons.addStretch(1)
        buttons.addWidget(self._suggest)
        layout.addLayout(buttons)

        layout.addWidget(QLabel("The Fields box will read:"))
        self.preview = QPlainTextEdit()
        self.preview.setObjectName("wizard_preview")
        self.preview.setReadOnly(True)
        self.preview.setMaximumHeight(96)
        layout.addWidget(self.preview)
        self._problems = QLabel()
        self._problems.setStyleSheet("color: #ef4444;")
        self._problems.setWordWrap(True)
        layout.addWidget(self._problems)

        box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        layout.addWidget(box)

        fields, problems = ip.parse_fields(params.get("fields"))
        for field in fields:
            self.add_field(field, refresh=False)
        if not fields and self._columns:
            # an empty panel with a table behind it: start from a proposal,
            # ticked — opening the wizard is asking for one, and a dialog
            # whose OK adds nothing until every row is ticked reads as
            # broken. The line above the rows says to untick what isn't
            # wanted.
            for field in ip.suggest_fields(self._data):
                self.add_field(field, use=True, refresh=False)
            self._source.setText(
                self._source.text() + "  A field is suggested for each "
                "column worth one — untick what you don't want, change a "
                "shape, then OK.")
        if problems:
            self._problems.setText(
                "These lines couldn't be read and will be dropped: "
                + "; ".join(problems))
        self.refresh()

    # ----------------------------------------------------------------- rows

    def add_field(self, field: Optional[dict], use: bool = True,
                  refresh: bool = True) -> int:
        field = field or {"label": f"Field {self.table.rowCount() + 1}",
                          "shape": "list", "column": "", "op": "",
                          "opts": {}}
        row = self.table.rowCount()
        self.table.insertRow(row)
        tick = QCheckBox()
        tick.setChecked(use)
        tick.toggled.connect(self.refresh)
        holder = QWidget()
        hl = QHBoxLayout(holder)
        hl.setContentsMargins(6, 0, 0, 0)
        hl.addWidget(tick)
        self.table.setCellWidget(row, _USE, holder)
        label = QLineEdit(str(field.get("label") or ""))
        label.textChanged.connect(self.refresh)
        self.table.setCellWidget(row, _LABEL, label)
        shape = _combo(SHAPE_LABELS, field["shape"])
        self.table.setCellWidget(row, _SHAPE, shape)
        column = QComboBox()
        column.setEditable(True)
        column.addItem(NO_COLUMN, "")
        for name in self._columns:
            column.addItem(name, name)
        current = str(field.get("column") or "")
        if current and column.findData(current) < 0:
            column.addItem(current, current)
        column.setCurrentIndex(max(0, column.findData(current)))
        column.currentTextChanged.connect(self.refresh)
        self.table.setCellWidget(row, _COLUMN, column)
        op = QComboBox()
        self.table.setCellWidget(row, _OP, op)
        opts = QLineEdit(_opts_text(field.get("opts")))
        opts.setPlaceholderText("e.g. step=5  required=yes  help=\"…\"")
        opts.textChanged.connect(self.refresh)
        self.table.setCellWidget(row, _OPTS, opts)
        self._fill_ops(row, field.get("op") or "")
        shape.currentIndexChanged.connect(
            lambda _i, s=shape: self._shape_changed(s))
        op.currentIndexChanged.connect(self.refresh)
        if refresh:
            self.table.selectRow(row)
            self.refresh()
        return row

    def _row_of(self, widget) -> int:
        for row in range(self.table.rowCount()):
            if self.table.cellWidget(row, _SHAPE) is widget:
                return row
        return -1

    def _shape_changed(self, combo) -> None:
        row = self._row_of(combo)
        if row >= 0:
            self._fill_ops(row, "")
            self.refresh()

    def _fill_ops(self, row: int, current: str) -> None:
        shape = self.table.cellWidget(row, _SHAPE).currentData()
        op = self.table.cellWidget(row, _OP)
        op.blockSignals(True)
        op.clear()
        choices = ip.SHAPE_COMPARISONS.get(shape)
        if choices:
            for value in choices:
                op.addItem(f"the column is {COMPARISON_LABELS[value]} it",
                           value)
            op.setCurrentIndex(max(0, op.findData(current)))
            op.setEnabled(True)
        else:
            fixed = {"list": "the column is one of the ticked",
                     "multi": "the column is one of the picked",
                     "choice": "the column is the pick",
                     "range": "the column is between the handles",
                     "date_range": "the date is in the window",
                     "toggle": "the column is true (while on)"}
            op.addItem(fixed.get(shape, "—"), "")
            op.setEnabled(False)
        op.blockSignals(False)

    def _remove_row(self) -> None:
        row = self.table.currentRow()
        if row >= 0:
            self.table.removeRow(row)
            self.refresh()

    def _move(self, step: int) -> None:
        row = self.table.currentRow()
        target = row + step
        if row < 0 or not 0 <= target < self.table.rowCount():
            return
        fields = self.fields(all_rows=True)
        fields[row], fields[target] = fields[target], fields[row]
        self._reload(fields)
        self.table.selectRow(target)

    def _reload(self, fields_with_use) -> None:
        self.table.setRowCount(0)
        for field, use in fields_with_use:
            self.add_field(field, use=use, refresh=False)
        self.refresh()

    def suggest(self) -> None:
        """Add a row for every suggested column not already used — ticked,
        because pressing the button is asking for them."""
        used = {f["column"] for f, _u in self.fields(all_rows=True)}
        for field in ip.suggest_fields(self._data):
            if field["column"] not in used:
                self.add_field(field, use=True, refresh=False)
        self.refresh()

    # ---------------------------------------------------------------- reading

    def fields(self, all_rows: bool = False):
        """The rows as field dicts — only the ticked ones, or (all_rows)
        every row paired with its tick."""
        out = []
        for row in range(self.table.rowCount()):
            tick = self.table.cellWidget(row, _USE).findChild(QCheckBox)
            # the combo is editable, so its text — not its data — is what
            # the person chose (a typed name has no item behind it)
            column_name = self.table.cellWidget(row, _COLUMN) \
                .currentText().strip()
            if column_name == NO_COLUMN:
                column_name = ""
            field = {
                "label": self.table.cellWidget(row, _LABEL).text().strip(),
                "shape": self.table.cellWidget(row, _SHAPE).currentData(),
                "column": column_name or "",
                "op": self.table.cellWidget(row, _OP).currentData() or "",
                "opts": _parse_opts(self.table.cellWidget(row, _OPTS).text()),
            }
            if all_rows:
                out.append((field, tick.isChecked()))
            elif tick.isChecked():
                out.append(field)
        return out

    def fields_text(self) -> str:
        return ip.dump_fields(self.fields())

    def refresh(self, *_args) -> None:
        text = self.fields_text()
        self.preview.setPlainText(text)
        _fields, problems = ip.parse_fields(text)
        if problems:
            self._problems.setText("; ".join(problems))
        elif not self._problems.text().startswith("These lines"):
            self._problems.setText("")

    def result_params(self) -> dict:
        return {"fields": self.fields_text(),
                "cascade": self._cascade.currentData(),
                "apply": self._apply.currentData(),
                "layout": self._layout.currentText(),
                "caption": self._caption.text()}


def open_panel_wizard(parent, graph, stack, cache, node_id: str) -> bool:
    """Open the wizard on an Input Panel and write what OK hands back, as
    one undo step. True when anything changed."""
    from .commands import SetParamCommand

    node = graph.nodes.get(node_id)
    if node is None or node.spec.control != "panel":
        return False
    data = None
    if cache is not None:
        from flograph.engine.introspect import cached_input
        data = cached_input(graph, cache, node_id, "data")
    dialog = PanelWizard(node.params, data, parent)
    if dialog.exec() != QDialog.Accepted:
        return False
    wanted = {k: v for k, v in dialog.result_params().items()
              if node.params.get(k) != v}
    if not wanted:
        return False
    stack.beginMacro("set up input panel")
    try:
        for name, value in wanted.items():
            stack.push(SetParamCommand(graph, node_id, name, value,
                                       merge=False))
    finally:
        stack.endMacro()
    return True
