"""The **Rules** dialog behind the button on a table's conditional-formatting
box.

`RuleManager` lists every rule currently applied and lets you add one
(guided by `RuleBuilder`), edit, remove or reorder it. It edits the rules
text a line at a time, so comments and anything hand-typed it doesn't
recognise are left exactly where they are. `RuleBuilder` knows nothing about
the graph — the caller hands it the column names to offer.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
    QFormLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QPushButton, QStackedWidget, QTableWidget, QTableWidgetItem, QVBoxLayout,
    QWidget,
)

from flograph.core.table_format import (
    bar_token, fill_token, parse_rule_lines, quote_column, rule_summary,
    scale_token,
)

_SINGLE = QAbstractItemView.SelectionMode.SingleSelection
_MULTI = QAbstractItemView.SelectionMode.MultiSelection

_SCALES = [("Green (low → high)", "green"), ("Blue (low → high)", "blue"),
           ("Red (low → high)", "red"), ("Red → Green", "red-green"),
           ("Red → Yellow → Green", "red-yellow-green"),
           ("Diverging (blue ↔ red)", "diverging")]
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
_MODE_KIND = {"color_scale": 0, "data_bar": 1, "highlight": 2, "icons": 3,
              "icon_map": 4, "number_format": 5, "hide": 6}


def _combo(pairs) -> QComboBox:
    box = QComboBox()
    for label, token in pairs:
        box.addItem(label, token)
    return box


_THIS_COLUMN = "(this column)"


def _other_col_value(box: QComboBox) -> str:
    """The column name chosen in an "another column" combo, or "" for the
    default "(this column)"."""
    data = box.currentData()
    if data:
        return str(data)
    text = box.currentText().strip()
    return "" if text in ("", _THIS_COLUMN) else text


def _pick_data(combo: QComboBox, token) -> None:
    index = combo.findData(token)
    if index >= 0:
        combo.setCurrentIndex(index)


def _cols_text(names) -> str:
    return ", ".join(quote_column(str(n).strip()) for n in names if str(n).strip())


class RuleBuilder(QDialog):
    """Build (or edit) one rule; ``line()`` is the DSL it produces."""

    def __init__(self, columns, parent=None, rule=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Edit rule" if rule else "New rule")
        self.setModal(True)
        self._columns = [str(c) for c in (columns or [])]

        outer = QVBoxLayout(self)
        self._kind = QComboBox()
        self._kind.addItems(_KINDS)
        top = QFormLayout()
        top.addRow("Rule", self._kind)
        outer.addLayout(top)

        self._col_list = QListWidget()
        self._col_list.setSelectionMode(_MULTI)
        self._col_list.setMaximumHeight(120)
        for name in self._columns:
            self._col_list.addItem(QListWidgetItem(name))
        self._col_edit = QLineEdit()
        self._col_edit.setPlaceholderText(
            "column name — or several, comma separated")
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

        outer.addWidget(QLabel("Rule text:"))
        self._preview = QLabel()
        self._preview.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self._preview.setWordWrap(True)
        self._preview.setStyleSheet("font-family: monospace; padding: 6px; "
                                    "border: 1px solid palette(mid);")
        outer.addWidget(self._preview)

        self._buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self._buttons.accepted.connect(self.accept)
        self._buttons.rejected.connect(self.reject)
        outer.addWidget(self._buttons)

        self._kind.currentIndexChanged.connect(self._on_kind)
        self._kind.currentIndexChanged.connect(self._refresh)
        self._col_list.itemSelectionChanged.connect(self._refresh)
        self._col_edit.textChanged.connect(self._refresh)
        self._on_kind()
        if rule is not None:
            self._load(rule)
        self._refresh()

    # ------------------------------------------------------------- public

    def line(self) -> str:
        return self._line()

    # ------------------------------------------------------------- columns

    def _chosen_columns(self) -> list[str]:
        if self._columns:
            return [i.text() for i in self._col_list.selectedItems()]
        return [c.strip() for c in self._col_edit.text().split(",") if c.strip()]

    def _columns_text(self) -> str:
        return _cols_text(self._chosen_columns())

    def _other_col_combo(self) -> QComboBox:
        """A combo offering "(this column)" then every column name — for a
        rule that can take its deciding value from a different column."""
        box = QComboBox()
        box.setEditable(not self._columns)
        box.addItem(_THIS_COLUMN, None)
        for name in self._columns:
            box.addItem(name, name)
        box.currentIndexChanged.connect(self._refresh)
        if box.isEditable():
            box.editTextChanged.connect(self._refresh)
        return box

    def _set_other_col(self, box: QComboBox, name) -> None:
        if not name:
            box.setCurrentIndex(0)
            return
        idx = box.findData(str(name))
        if idx >= 0:
            box.setCurrentIndex(idx)
        elif box.isEditable():
            box.setCurrentText(str(name))

    def _select_columns(self, names) -> None:
        wanted = {str(n) for n in names}
        if self._columns:
            for i in range(self._col_list.count()):
                item = self._col_list.item(i)
                item.setSelected(item.text() in wanted)
        else:
            self._col_edit.setText(", ".join(str(n) for n in names))

    # ---------------------------------------------------------- type pages

    def _build_scale_page(self) -> None:
        page = QWidget()
        f = QFormLayout(page)
        self._scale = _combo(_SCALES)
        self._scale.currentIndexChanged.connect(self._refresh)
        f.addRow("Colours", self._scale)
        self._scale_by = self._other_col_combo()
        f.addRow("Colour by", self._scale_by)
        self._stack.addWidget(page)

    def _build_bar_page(self) -> None:
        page = QWidget()
        f = QFormLayout(page)
        self._bar = _combo(_BAR_COLOURS)
        self._bar.currentIndexChanged.connect(self._refresh)
        f.addRow("Bar colour", self._bar)
        self._bar_by = self._other_col_combo()
        f.addRow("Size by", self._bar_by)
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
        for w in (self._op, self._fill, self._scope):
            w.currentIndexChanged.connect(self._refresh)
        for w in (self._val1, self._val2):
            w.textChanged.connect(self._refresh)
        self._bold.toggled.connect(self._refresh)
        self._op.currentIndexChanged.connect(self._sync_highlight_inputs)
        self._hl_test = self._other_col_combo()
        f.addRow("Test column", self._hl_test)
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
        self._icon_by = self._other_col_combo()
        f.addRow("Rank by", self._icon_by)
        f.addRow(QLabel("Split at the ranking column's lower / upper third."))
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
        self._map.setMaximumHeight(150)
        self._map.horizontalHeader().setStretchLastSection(True)
        self._map.cellChanged.connect(self._refresh)
        v.addWidget(self._map)
        row = QHBoxLayout()
        add = QPushButton("＋ row")
        rm = QPushButton("－ row")
        add.clicked.connect(lambda: (self._add_map_row(), self._refresh()))
        rm.clicked.connect(self._remove_map_row)
        row.addWidget(add)
        row.addWidget(rm)
        row.addStretch(1)
        v.addLayout(row)
        self._add_map_row()
        self._add_map_row()
        self._stack.addWidget(page)

    def _add_map_row(self, value: str = "", glyph: str = "",
                     colour: str = "(none)") -> None:
        r = self._map.rowCount()
        self._map.insertRow(r)
        self._map.setItem(r, 0, QTableWidgetItem(value))
        gbox = QComboBox()
        gbox.setEditable(True)
        gbox.addItems(_GLYPHS)
        gbox.setCurrentText(glyph)
        gbox.currentTextChanged.connect(self._refresh)
        self._map.setCellWidget(r, 1, gbox)
        cbox = QComboBox()
        cbox.addItems(_MAP_COLOURS)
        cbox.setCurrentText(colour if colour in _MAP_COLOURS else "(none)")
        cbox.currentIndexChanged.connect(self._refresh)
        self._map.setCellWidget(r, 2, cbox)

    def _remove_map_row(self) -> None:
        if self._map.rowCount():
            self._map.removeRow(self._map.rowCount() - 1)
        self._refresh()

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
        single = idx == 4
        self._col_label.setText("Shown in column" if single else "Columns")
        if self._columns:
            self._col_list.setSelectionMode(_SINGLE if single else _MULTI)

    def _sync_highlight_inputs(self) -> None:
        op = self._op.currentData()
        self._val1.setVisible(op not in ("empty", "notempty"))
        two = op == "between"
        self._val2.setVisible(two)
        self._and.setVisible(two)
        self._refresh()

    def _refresh(self) -> None:
        if not hasattr(self, "_buttons"):
            return
        if hasattr(self, "_numfmt_sample"):
            self._numfmt_sample.setText(self._number_sample())
        line = self._line()
        self._preview.setText(line or "— fill in the fields above —")
        self._buttons.button(QDialogButtonBox.Ok).setEnabled(bool(line))

    def _number_sample(self) -> str:
        spec = self._numfmt.currentText().strip()
        try:
            prefix = ""
            if spec[:1] in "$€£¥":
                prefix, spec = spec[0], spec[1:]
            return prefix + format(1234.5, spec) if spec else "1234.5"
        except ValueError:
            return "(invalid format)"

    # ------------------------------------------------------------- prefill

    def _load(self, rule) -> None:
        self._kind.setCurrentIndex(_MODE_KIND.get(rule.mode, 0))
        self._on_kind()
        self._select_columns(rule.columns)
        if rule.mode == "color_scale":
            _pick_data(self._scale, scale_token(rule.low, rule.mid, rule.high))
            self._set_other_col(self._scale_by, rule.source)
        elif rule.mode == "data_bar":
            _pick_data(self._bar, bar_token(rule.color))
            self._set_other_col(self._bar_by, rule.source)
        elif rule.mode == "highlight":
            _pick_data(self._op, rule.op or "=")
            self._sync_highlight_inputs()
            value = rule.value
            if isinstance(value, (list, tuple)) and len(value) == 2:
                self._val1.setText(str(value[0]))
                self._val2.setText(str(value[1]))
            elif value is not None:
                self._val1.setText(str(value))
            _pick_data(self._fill, fill_token(rule.bg))
            self._bold.setChecked(bool(rule.bold))
            self._scope.setCurrentIndex(1 if rule.scope == "row" else 0)
            self._set_other_col(self._hl_test, rule.source)
        elif rule.mode == "icons":
            _pick_data(self._iconset, rule.icon_set or "traffic")
            self._icon_reverse.setChecked(bool(rule.reverse))
            self._set_other_col(self._icon_by, rule.source)
        elif rule.mode == "icon_map":
            self._map_source.setCurrentText(rule.source or "")
            self._map.setRowCount(0)
            for value, pair in (rule.mapping or {}).items():
                glyph = pair[0] if pair else ""
                colour = fill_token(pair[1]) if len(pair) > 1 and pair[1] else ""
                self._add_map_row(value, glyph, colour)
            if not self._map.rowCount():
                self._add_map_row()
        elif rule.mode == "number_format":
            self._numfmt.setCurrentText(rule.number_spec or "")

    # -------------------------------------------------------- line builder

    @staticmethod
    def _by(box: QComboBox) -> str:
        """The ``  by <column>`` DSL tail for an "another column" combo,
        or ``""`` when it is on "(this column)"."""
        name = _other_col_value(box)
        return f" by {quote_column(name)}" if name else ""

    def _line(self) -> str:
        kind = self._kind.currentIndex()
        cols = self._columns_text()
        if kind == 6:
            return f"hide {cols}" if cols else ""
        if not cols:
            return ""
        if kind == 0:
            return f"{cols} scale {self._scale.currentData()}{self._by(self._scale_by)}"
        if kind == 1:
            return f"{cols} bar {self._bar.currentData()}{self._by(self._bar_by)}"
        if kind == 2:
            op = self._op.currentData()
            words = {">": ">", ">=": ">=", "<": "<", "<=": "<=", "=": "=",
                     "!=": "!=", "contains": "contains", "starts": "starts with",
                     "ends": "ends with", "matches": "matches",
                     "empty": "is empty", "notempty": "is not empty"}
            test = _other_col_value(self._hl_test)
            subject = f"{cols} if {quote_column(test)}" if test else cols
            if op in ("empty", "notempty"):
                cond = f"{subject} {words[op]}"
            elif op == "between":
                v1, v2 = self._val1.text().strip(), self._val2.text().strip()
                if not v1 or not v2:
                    return ""
                cond = f"{subject} between {v1} {v2}"
            else:
                value = self._val1.text().strip()
                if not value:
                    return ""
                cond = f"{subject} {words[op]} {value}"
            fill = self._fill.currentData()
            if self._scope.currentIndex() == 1:
                return f"{cond} => row {fill}"
            tail = f"bg {fill}" + (", bold" if self._bold.isChecked() else "")
            return f"{cond} => {tail}"
        if kind == 3:
            rev = " reverse" if self._icon_reverse.isChecked() else ""
            return (f"{cols} icons {self._iconset.currentData()}{rev}"
                    f"{self._by(self._icon_by)}")
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


class RuleManager(QDialog):
    """The list of applied rules, with add / edit / remove / reorder."""

    def __init__(self, text: str, columns, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Conditional formatting rules")
        self.setModal(True)
        self.resize(520, 380)
        self._columns = list(columns or [])
        # each entry: [raw line, Rule | None, error | None]
        self._entries = [list(e) for e in parse_rule_lines(text)]

        outer = QVBoxLayout(self)
        outer.addWidget(QLabel(
            "Rules apply top to bottom — a later rule wins where two touch "
            "the same cell."))
        body = QHBoxLayout()
        self._list = QListWidget()
        self._list.currentRowChanged.connect(self._sync_buttons)
        self._list.itemDoubleClicked.connect(lambda *_: self._edit())
        body.addWidget(self._list, 1)

        side = QVBoxLayout()
        self._add_btn = QPushButton("＋  Add rule")
        self._edit_btn = QPushButton("Edit…")
        self._dup_btn = QPushButton("Duplicate")
        self._del_btn = QPushButton("Remove")
        self._up_btn = QPushButton("Move up")
        self._down_btn = QPushButton("Move down")
        self._add_btn.clicked.connect(self._add)
        self._edit_btn.clicked.connect(self._edit)
        self._dup_btn.clicked.connect(self._duplicate)
        self._del_btn.clicked.connect(self._remove)
        self._up_btn.clicked.connect(lambda: self._move(-1))
        self._down_btn.clicked.connect(lambda: self._move(1))
        for b in (self._add_btn, self._edit_btn, self._dup_btn, self._del_btn,
                  self._up_btn, self._down_btn):
            side.addWidget(b)
        side.addStretch(1)
        body.addLayout(side)
        outer.addLayout(body)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)

        self._reload()

    # ------------------------------------------------------------- result

    def result_text(self) -> str:
        return "\n".join(e[0] for e in self._entries)

    # ------------------------------------------------------------- list

    def _reload(self) -> None:
        row = self._list.currentRow()
        self._list.clear()
        for raw, rule, error in self._entries:
            if rule is not None:
                item = QListWidgetItem(rule_summary(rule))
            elif error is not None:
                item = QListWidgetItem(f"⚠  {raw.strip()}   ({error})")
                item.setForeground(Qt.red)
            else:                                   # comment / blank
                item = QListWidgetItem(raw.strip() or "(blank line)")
                item.setForeground(Qt.gray)
            self._list.addItem(item)
        self._list.setCurrentRow(min(row, self._list.count() - 1))
        self._sync_buttons()

    def _sync_buttons(self) -> None:
        row = self._list.currentRow()
        has = row >= 0
        rule = self._entries[row][1] if has else None
        self._edit_btn.setEnabled(rule is not None)
        self._dup_btn.setEnabled(rule is not None)
        self._del_btn.setEnabled(has)
        self._up_btn.setEnabled(row > 0)
        self._down_btn.setEnabled(0 <= row < len(self._entries) - 1)

    # ------------------------------------------------------------- actions

    def _add(self) -> None:
        dlg = RuleBuilder(self._columns, self)
        if dlg.exec() == QDialog.Accepted and dlg.line():
            self._entries.append(self._entry_for(dlg.line()))
            self._reload()
            self._list.setCurrentRow(len(self._entries) - 1)

    def _edit(self) -> None:
        row = self._list.currentRow()
        if row < 0 or self._entries[row][1] is None:
            return
        dlg = RuleBuilder(self._columns, self, rule=self._entries[row][1])
        if dlg.exec() == QDialog.Accepted and dlg.line():
            self._entries[row] = self._entry_for(dlg.line())
            self._reload()

    def _duplicate(self) -> None:
        row = self._list.currentRow()
        if row < 0 or self._entries[row][1] is None:
            return
        self._entries.insert(row + 1, self._entry_for(self._entries[row][0]))
        self._reload()
        self._list.setCurrentRow(row + 1)

    def _remove(self) -> None:
        row = self._list.currentRow()
        if row >= 0:
            del self._entries[row]
            self._reload()

    def _move(self, delta: int) -> None:
        row = self._list.currentRow()
        target = row + delta
        if 0 <= row < len(self._entries) and 0 <= target < len(self._entries):
            self._entries[row], self._entries[target] = (
                self._entries[target], self._entries[row])
            self._reload()
            self._list.setCurrentRow(target)

    @staticmethod
    def _entry_for(line: str) -> list:
        parsed = parse_rule_lines(line)
        return list(parsed[0]) if parsed else [line, None, None]
