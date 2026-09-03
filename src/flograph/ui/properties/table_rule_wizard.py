"""The guided builder behind the **Build a rule…** button on a table's
conditional-formatting box.

It knows nothing about the graph: the caller hands it the column names it
should offer (from the table the rules will be applied to, or empty) and
takes back the DSL line(s) to append. Every field feeds a live preview of
exactly the text that will be written, so the dialog doubles as a way to
learn the syntax.
"""
from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
    QFormLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QPushButton, QStackedWidget, QTableWidget, QTableWidgetItem, QVBoxLayout,
    QWidget,
)

from flograph.core.table_format import quote_column

_SINGLE = QAbstractItemView.SelectionMode.SingleSelection
_MULTI = QAbstractItemView.SelectionMode.MultiSelection

# label shown -> DSL token
_SCALES = [
    ("Green (low → high)", "green"),
    ("Blue (low → high)", "blue"),
    ("Red (low → high)", "red"),
    ("Red → Green", "red-green"),
    ("Red → Yellow → Green", "red-yellow-green"),
    ("Diverging (blue ↔ red)", "diverging"),
]
_BAR_COLOURS = [("Blue", "blue"), ("Green", "green"),
                ("Orange", "orange"), ("Purple", "purple")]
_FILLS = [("Red", "red"), ("Amber", "amber"), ("Green", "green"),
          ("Grey", "grey"), ("Blue", "blue")]
_OPS = [("is greater than", ">"), ("is ≥", ">="), ("is less than", "<"),
        ("is ≤", "<="), ("equals", "="), ("does not equal", "!="),
        ("contains", "contains"), ("starts with", "starts"),
        ("ends with", "ends"), ("matches (regex)", "matches"),
        ("is between", "between"), ("is empty", "empty"),
        ("is not empty", "notempty")]
_ICON_SETS = [("Traffic lights  ● ● ●", "traffic"),
              ("Arrows  ▼ ▬ ▲", "arrows"),
              ("Tick / dash / cross  ✓ – ✗", "check")]
_GLYPHS = ["✓", "✗", "!", "●", "▲", "▼", "★", "?", "→", "–"]
_MAP_COLOURS = ["green", "amber", "red", "blue", "grey", "(none)"]
_NUMBER_PRESETS = ["", ",.0f", ",.2f", ".1%", "$,.0f", "$,.2f"]

_KINDS = ["Colour scale", "Data bars", "Highlight cells / rows",
          "Icon set (by this column)", "Icon from another column",
          "Number format", "Hide columns"]


def _combo(pairs) -> QComboBox:
    box = QComboBox()
    for label, token in pairs:
        box.addItem(label, token)
    return box


def _cols(text: str) -> str:
    """A comma list of column names, each quoted only if it needs it."""
    parts = [quote_column(p.strip()) for p in text.split(",") if p.strip()]
    return ", ".join(parts)


class RuleWizard(QDialog):
    def __init__(self, columns, on_add: Callable[[str], None],
                 parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Build a formatting rule")
        self.setModal(True)
        self._columns = [str(c) for c in (columns or [])]
        self._on_add = on_add
        self._added = 0

        outer = QVBoxLayout(self)

        self._kind = QComboBox()
        self._kind.addItems(_KINDS)
        form = QFormLayout()
        form.addRow("Rule", self._kind)
        outer.addLayout(form)

        # column chooser — a checkable list when we know the columns, a
        # plain line otherwise
        self._col_list = QListWidget()
        self._col_list.setSelectionMode(_MULTI)
        self._col_list.setMaximumHeight(120)
        for name in self._columns:
            self._col_list.addItem(QListWidgetItem(name))
        self._col_edit = QLineEdit()
        self._col_edit.setPlaceholderText("column name — or several, comma separated")
        self._col_label = QLabel("Columns")
        cform = QFormLayout()
        cform.addRow(self._col_label,
                     self._col_list if self._columns else self._col_edit)
        outer.addLayout(cform)

        self._stack = QStackedWidget()
        self._build_scale_page()
        self._build_bar_page()
        self._build_highlight_page()
        self._build_icons_page()
        self._build_iconmap_page()
        self._build_number_page()
        self._build_hide_page()
        outer.addWidget(self._stack)

        outer.addWidget(QLabel("This will add:"))
        self._preview = QLabel()
        self._preview.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self._preview.setWordWrap(True)
        self._preview.setStyleSheet(
            "font-family: monospace; padding: 6px; border: 1px solid palette(mid);")
        outer.addWidget(self._preview)

        buttons = QDialogButtonBox()
        self._add_btn = buttons.addButton("Add to rules",
                                          QDialogButtonBox.ActionRole)
        close = buttons.addButton("Close", QDialogButtonBox.AcceptRole)
        self._add_btn.clicked.connect(self._append)
        close.clicked.connect(self.accept)
        outer.addWidget(buttons)

        self._kind.currentIndexChanged.connect(self._on_kind)
        self._kind.currentIndexChanged.connect(self._refresh)
        self._col_list.itemSelectionChanged.connect(self._refresh)
        self._col_edit.textChanged.connect(self._refresh)
        self._on_kind()
        self._refresh()

    # ------------------------------------------------------------- result

    def added(self) -> int:
        return self._added

    def _append(self) -> None:
        line = self._line()
        if line:
            self._on_add(line)
            self._added += 1
            self._preview.setText(line + "\n   ✓ added — build another, or Close")

    # ------------------------------------------------------------- columns

    def _chosen_columns(self) -> list[str]:
        if self._columns:
            return [i.text() for i in self._col_list.selectedItems()]
        return [c.strip() for c in self._col_edit.text().split(",") if c.strip()]

    def _columns_text(self) -> str:
        return _cols(", ".join(self._chosen_columns()))

    # ---------------------------------------------------------- type pages

    def _build_scale_page(self) -> None:
        page = QWidget()
        f = QFormLayout(page)
        self._scale = _combo(_SCALES)
        self._scale.currentIndexChanged.connect(self._refresh)
        f.addRow("Colours", self._scale)
        self._stack.addWidget(page)

    def _build_bar_page(self) -> None:
        page = QWidget()
        f = QFormLayout(page)
        self._bar = _combo(_BAR_COLOURS)
        self._bar.currentIndexChanged.connect(self._refresh)
        f.addRow("Bar colour", self._bar)
        self._stack.addWidget(page)

    def _build_highlight_page(self) -> None:
        page = QWidget()
        f = QFormLayout(page)
        self._op = _combo(_OPS)
        self._val1 = QLineEdit()
        self._val2 = QLineEdit()
        vrow = QWidget()
        vl = QHBoxLayout(vrow)
        vl.setContentsMargins(0, 0, 0, 0)
        vl.addWidget(self._val1)
        self._and = QLabel("and")
        vl.addWidget(self._and)
        vl.addWidget(self._val2)
        self._fill = _combo(_FILLS)
        self._bold = QCheckBox("bold text")
        self._scope = QComboBox()
        self._scope.addItems(["this cell", "the whole row"])
        for w in (self._op, self._val1, self._val2, self._fill, self._scope):
            (w.currentIndexChanged if isinstance(w, QComboBox)
             else w.textChanged).connect(self._refresh)
        self._bold.toggled.connect(self._refresh)
        self._op.currentIndexChanged.connect(self._sync_highlight_inputs)
        f.addRow("When the value", self._op)
        f.addRow("", vrow)
        f.addRow("Fill", self._fill)
        f.addRow("Apply to", self._scope)
        f.addRow("", self._bold)
        self._stack.addWidget(page)

    def _build_icons_page(self) -> None:
        page = QWidget()
        f = QFormLayout(page)
        self._iconset = _combo(_ICON_SETS)
        self._icon_reverse = QCheckBox("reverse (high = red)")
        self._iconset.currentIndexChanged.connect(self._refresh)
        self._icon_reverse.toggled.connect(self._refresh)
        f.addRow("Icon set", self._iconset)
        f.addRow("", self._icon_reverse)
        f.addRow(QLabel("Split at the column's lower / upper third."))
        self._stack.addWidget(page)

    def _build_iconmap_page(self) -> None:
        page = QWidget()
        v = QVBoxLayout(page)
        f = QFormLayout()
        self._map_source = QComboBox()
        self._map_source.setEditable(not self._columns)
        self._map_source.addItems(self._columns)
        self._map_source.currentIndexChanged.connect(self._refresh)
        if self._map_source.isEditable():
            self._map_source.editTextChanged.connect(self._refresh)
        f.addRow("Icon decided by", self._map_source)
        v.addLayout(f)
        v.addWidget(QLabel("Value → icon:"))
        self._map = QTableWidget(0, 3)
        self._map.setHorizontalHeaderLabels(["value", "icon", "colour"])
        self._map.setMaximumHeight(140)
        self._map.horizontalHeader().setStretchLastSection(True)
        self._map.cellChanged.connect(self._refresh)
        v.addWidget(self._map)
        row = QHBoxLayout()
        add = QPushButton("＋ row")
        rm = QPushButton("－ row")
        add.clicked.connect(lambda: (self._add_map_row(), self._refresh()))
        rm.clicked.connect(lambda: (self._map.removeRow(self._map.rowCount() - 1)
                                    if self._map.rowCount() else None,
                                    self._refresh()))
        row.addWidget(add)
        row.addWidget(rm)
        row.addStretch(1)
        v.addLayout(row)
        for value in ("", ""):
            self._add_map_row(value)
        self._stack.addWidget(page)

    def _add_map_row(self, value: str = "") -> None:
        r = self._map.rowCount()
        self._map.insertRow(r)
        self._map.setItem(r, 0, QTableWidgetItem(value))
        glyph = QComboBox()
        glyph.setEditable(True)
        glyph.addItems(_GLYPHS)
        glyph.currentTextChanged.connect(self._refresh)
        self._map.setCellWidget(r, 1, glyph)
        colour = QComboBox()
        colour.addItems(_MAP_COLOURS)
        colour.currentIndexChanged.connect(self._refresh)
        self._map.setCellWidget(r, 2, colour)

    def _build_number_page(self) -> None:
        page = QWidget()
        f = QFormLayout(page)
        self._numfmt = QComboBox()
        self._numfmt.setEditable(True)
        self._numfmt.addItems(_NUMBER_PRESETS)
        self._numfmt.setCurrentText(",.0f")
        self._numfmt.editTextChanged.connect(self._refresh)
        self._numfmt.currentIndexChanged.connect(self._refresh)
        self._numfmt_sample = QLabel()
        f.addRow("Format", self._numfmt)
        f.addRow("1234.5 →", self._numfmt_sample)
        self._stack.addWidget(page)

    def _build_hide_page(self) -> None:
        page = QWidget()
        v = QVBoxLayout(page)
        v.addWidget(QLabel(
            "The chosen columns stay in the data (a rule can still read them) "
            "but are not shown in this table."))
        self._stack.addWidget(page)

    # ------------------------------------------------------------- reactive

    def _on_kind(self) -> None:
        idx = self._kind.currentIndex()
        self._stack.setCurrentIndex(idx)
        single = idx == 4                      # icon-from-another-column
        self._col_label.setText("Shown in column" if single else "Columns")
        if self._columns:
            self._col_list.setSelectionMode(
                _SINGLE if single
                else _MULTI)

    def _sync_highlight_inputs(self) -> None:
        op = self._op.currentData()
        self._val1.setVisible(op not in ("empty", "notempty"))
        two = op == "between"
        self._val2.setVisible(two)
        self._and.setVisible(two)
        self._refresh()

    def _refresh(self) -> None:
        # signals fire while pages are still being built
        if not hasattr(self, "_add_btn"):
            return
        if hasattr(self, "_numfmt_sample"):
            self._numfmt_sample.setText(self._number_sample())
        line = self._line()
        self._preview.setText(line or "— choose a column —")
        self._add_btn.setEnabled(bool(line))

    def _number_sample(self) -> str:
        spec = self._numfmt.currentText().strip()
        try:
            prefix = ""
            if spec[:1] in "$€£¥":
                prefix, spec = spec[0], spec[1:]
            return prefix + format(1234.5, spec) if spec else "1234.5"
        except ValueError:
            return "(invalid format)"

    # -------------------------------------------------------- line builder

    def _line(self) -> str:
        kind = self._kind.currentIndex()
        cols = self._columns_text()
        if kind == 6:                                    # hide
            return f"hide {cols}" if cols else ""
        if not cols:
            return ""
        if kind == 0:
            return f"{cols} scale {self._scale.currentData()}"
        if kind == 1:
            return f"{cols} bar {self._bar.currentData()}"
        if kind == 2:
            op = self._op.currentData()
            words = {">": ">", ">=": ">=", "<": "<", "<=": "<=", "=": "=",
                     "!=": "!=", "contains": "contains", "starts": "starts with",
                     "ends": "ends with", "matches": "matches",
                     "between": "between", "empty": "is empty",
                     "notempty": "is not empty"}[op]
            if op in ("empty", "notempty"):
                cond = f"{cols} {words}"
            elif op == "between":
                cond = f"{cols} between {self._val1.text().strip()} " \
                       f"{self._val2.text().strip()}"
            else:
                cond = f"{cols} {words} {self._val1.text().strip()}"
            fill = self._fill.currentData()
            if self._scope.currentIndex() == 1:
                return f"{cond} => row {fill}"
            tail = f"bg {fill}" + (", bold" if self._bold.isChecked() else "")
            return f"{cond} => {tail}"
        if kind == 3:
            rev = " reverse" if self._icon_reverse.isChecked() else ""
            return f"{cols} icons {self._iconset.currentData()}{rev}"
        if kind == 4:
            source = quote_column(self._map_source.currentText().strip())
            pairs = []
            for r in range(self._map.rowCount()):
                item = self._map.item(r, 0)
                value = item.text().strip() if item else ""
                glyph = self._map.cellWidget(r, 1).currentText().strip()
                colour = self._map.cellWidget(r, 2).currentText()
                if not value or not glyph:
                    continue
                pairs.append(f"{value}={glyph}"
                             + ("" if colour == "(none)" else f" {colour}"))
            if not source or not pairs:
                return ""
            return f"{cols} iconmap {source}: " + ", ".join(pairs)
        if kind == 5:
            spec = self._numfmt.currentText().strip()
            return f"{cols} format {spec}" if spec else ""
        return ""
