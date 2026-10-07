"""Format Cells (Ctrl+1) for a Table column — Excel's Number tab.

A list of categories on the left, the options that category has on the
right, and a sample drawn from the column itself (its first number or date)
reading exactly as the grid will show it. A sentence under the sample says
what the category is for. OK applies the format to every selected column as
one undo step; the values themselves never change.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog,
                               QDialogButtonBox, QFormLayout, QFrame,
                               QHBoxLayout, QLabel, QListWidget,
                               QListWidgetItem, QSpinBox, QStackedWidget,
                               QVBoxLayout, QWidget)

from flograph.core.sheet.numfmt import (DATE_PATTERNS, NEGATIVES, clean,
                                        format_value_as)

from .menus import real_window

CATEGORIES = (
    ("general", "General",
     "No format: numbers show as they are, with as many places as they "
     "have."),
    ("number", "Number",
     "A fixed number of decimal places, with or without thousands "
     "separators, and a choice of how negatives look."),
    ("currency", "Currency",
     "Money: a currency symbol, thousands separators and fixed decimals. "
     "Typing £1,200 into the column stores 1200."),
    ("percent", "Percent",
     "The value times 100 with a % sign: 0.25 reads 25%. Typing 25% "
     "stores 0.25."),
    ("scientific", "Scientific",
     "Very large or small numbers as a mantissa and a power of ten: "
     "1.23E+6."),
    ("date", "Date",
     "How a date column's dates are written. The dates themselves are "
     "unchanged."),
)
SYMBOLS = ("£", "$", "€", "¥", "₹", "kr", "CHF", "A$")
_NEGATIVE_LABELS = {"minus": "-1,234.10", "red": "-1,234.10 (red)",
                    "parens": "(1,234.10)", "red_parens": "(1,234.10) (red)"}


class FormatCellsDialog(QDialog):
    def __init__(self, view, cols: list[int], parent=None) -> None:
        super().__init__(parent)
        model = view.sheet_model()
        names = ", ".join(model.sheet.columns[c].name for c in cols[:3])
        if len(cols) > 3:
            names += f" and {len(cols) - 3} more"
        self.setWindowTitle(f"Format Cells — {names}")
        self._sample_value = self._sample(model, cols[0])
        start = clean(model.column_format(cols[0]))

        layout = QVBoxLayout(self)
        body = QHBoxLayout()
        self.categories = QListWidget()
        self.categories.setFixedWidth(130)
        for key, label, _help in CATEGORIES:
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, key)
            self.categories.addItem(item)
        body.addWidget(self.categories)

        right = QVBoxLayout()
        sample_box = QFrame()
        sample_box.setFrameShape(QFrame.StyledPanel)
        sample_row = QHBoxLayout(sample_box)
        sample_row.addWidget(QLabel("Sample:"))
        self.sample = QLabel()
        self.sample.setStyleSheet("font-size: 12pt; font-weight: 600;")
        sample_row.addWidget(self.sample, 1)
        right.addWidget(sample_box)

        self.options = QStackedWidget()
        self._pages: dict[str, QWidget] = {}
        for key, _label, _help in CATEGORIES:
            page = QWidget()
            QFormLayout(page)
            self._pages[key] = page
            self.options.addWidget(page)
        self._build_options()
        right.addWidget(self.options, 1)
        self.help = QLabel()
        self.help.setWordWrap(True)
        self.help.setStyleSheet("color: #9ca3af;")
        right.addWidget(self.help)
        body.addLayout(right, 1)
        layout.addLayout(body, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok
                                   | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.categories.currentRowChanged.connect(self._category_changed)
        self._load(start)
        self.resize(520, 360)

    @staticmethod
    def _sample(model, col):
        for row in range(model.rowCount()):
            value = model.computed_value(row, col)
            if value not in (None, "") and not isinstance(value, bool):
                return value
        return 1234.5678

    # ------------------------------------------------------------- pages

    def _decimals(self) -> QSpinBox:
        box = QSpinBox()
        box.setRange(0, 10)
        box.valueChanged.connect(self._refresh)
        return box

    def _negatives(self) -> QComboBox:
        box = QComboBox()
        for key in NEGATIVES:
            box.addItem(_NEGATIVE_LABELS[key], key)
        box.currentIndexChanged.connect(self._refresh)
        return box

    def _build_options(self) -> None:
        number = self._pages["number"].layout()
        self.num_decimals = self._decimals()
        self.num_thousands = QCheckBox("Use thousands separator (1,000)")
        self.num_thousands.toggled.connect(self._refresh)
        self.num_negative = self._negatives()
        number.addRow("Decimal places", self.num_decimals)
        number.addRow("", self.num_thousands)
        number.addRow("Negative numbers", self.num_negative)

        currency = self._pages["currency"].layout()
        self.cur_symbol = QComboBox()
        self.cur_symbol.setEditable(True)
        self.cur_symbol.addItems(SYMBOLS)
        self.cur_symbol.currentTextChanged.connect(self._refresh)
        self.cur_decimals = self._decimals()
        self.cur_negative = self._negatives()
        currency.addRow("Symbol", self.cur_symbol)
        currency.addRow("Decimal places", self.cur_decimals)
        currency.addRow("Negative numbers", self.cur_negative)

        percent = self._pages["percent"].layout()
        self.pct_decimals = self._decimals()
        percent.addRow("Decimal places", self.pct_decimals)

        scientific = self._pages["scientific"].layout()
        self.sci_decimals = self._decimals()
        scientific.addRow("Decimal places", self.sci_decimals)

        date = self._pages["date"].layout()
        self.date_pattern = QListWidget()
        for label, pattern in DATE_PATTERNS:
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, pattern)
            self.date_pattern.addItem(item)
        self.date_pattern.currentRowChanged.connect(self._refresh)
        date.addRow(self.date_pattern)

    def _load(self, fmt: Optional[dict]) -> None:
        from .actions import currency_format
        kind = fmt["kind"] if fmt else "general"
        keys = [key for key, _l, _h in CATEGORIES]
        self.num_decimals.setValue(2)
        self.num_thousands.setChecked(True)
        self.cur_decimals.setValue(2)
        self.cur_symbol.setCurrentText(currency_format()["symbol"])
        self.pct_decimals.setValue(0)
        self.sci_decimals.setValue(2)
        self.date_pattern.setCurrentRow(0)
        if kind == "number":
            self.num_decimals.setValue(fmt["decimals"])
            self.num_thousands.setChecked(fmt["thousands"])
            self.num_negative.setCurrentIndex(NEGATIVES.index(fmt["negative"]))
        elif kind == "currency":
            self.cur_symbol.setCurrentText(fmt["symbol"])
            self.cur_decimals.setValue(fmt["decimals"])
            self.cur_negative.setCurrentIndex(NEGATIVES.index(fmt["negative"]))
        elif kind == "percent":
            self.pct_decimals.setValue(fmt["decimals"])
        elif kind == "scientific":
            self.sci_decimals.setValue(fmt["decimals"])
        elif kind == "date":
            patterns = [p for _l, p in DATE_PATTERNS]
            if fmt["pattern"] in patterns:
                self.date_pattern.setCurrentRow(patterns.index(fmt["pattern"]))
        self.categories.setCurrentRow(keys.index(kind))
        self._category_changed(keys.index(kind))

    def _category_changed(self, row: int) -> None:
        if row < 0:
            return
        key, _label, text = CATEGORIES[row]
        self.options.setCurrentWidget(self._pages[key])
        self.help.setText(text)
        self._refresh()

    # ------------------------------------------------------------ result

    def chosen(self) -> Optional[dict]:
        item = self.categories.currentItem()
        key = item.data(Qt.UserRole) if item else "general"
        if key == "number":
            return {"kind": "number", "decimals": self.num_decimals.value(),
                    "thousands": self.num_thousands.isChecked(),
                    "negative": self.num_negative.currentData()}
        if key == "currency":
            return {"kind": "currency",
                    "symbol": self.cur_symbol.currentText().strip() or "$",
                    "decimals": self.cur_decimals.value(), "thousands": True,
                    "negative": self.cur_negative.currentData()}
        if key == "percent":
            return {"kind": "percent", "decimals": self.pct_decimals.value()}
        if key == "scientific":
            return {"kind": "scientific",
                    "decimals": self.sci_decimals.value()}
        if key == "date":
            item = self.date_pattern.currentItem()
            return {"kind": "date",
                    "pattern": item.data(Qt.UserRole) if item else
                    "%Y-%m-%d"}
        return None

    def _refresh(self, *_args) -> None:
        fmt = self.chosen()
        value = self._sample_value
        if fmt and fmt["kind"] == "date" and not isinstance(value, str):
            value = "2026-10-07"
        shown = format_value_as(value, fmt) if fmt else None
        text, red = shown if shown else (str(value), False)
        self.sample.setText(text)
        self.sample.setStyleSheet(
            "font-size: 12pt; font-weight: 600;"
            + (f" color: {QColor('#f87171').name()};" if red else ""))


def edit_number_format(view, cols: list[int]) -> None:
    model = view.sheet_model()
    if model is None or not cols:
        return
    dialog = FormatCellsDialog(view, cols, real_window(view))
    if dialog.exec():
        model.set_column_format(cols, dialog.chosen())
