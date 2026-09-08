"""A colour swatch button, shared by the shape panel and the "color" param
editor.

Two places needed the same three behaviours — show the colour, open the
picker, and offer "no colour" as a real choice — so they read the same
widget rather than each growing their own idea of what an empty value
looks like.
"""
from __future__ import annotations

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QColorDialog, QHBoxLayout, QPushButton, QWidget

from .. import theme

#: what the picker opens on when there is no colour yet
DEFAULT_PICK = "#e5e7eb"


class ColourRow(QWidget):
    """A colour swatch, plus a clear button when the colour is optional
    (fill, text colour, an accent — an empty value means 'none' or 'theme
    default')."""

    def __init__(self, on_pick, on_clear=None, *, start: str = DEFAULT_PICK,
                 clear_tip: str = "Clear") -> None:
        super().__init__()
        self._value = ""
        self._start = start
        self._on_pick = on_pick
        self._on_clear = on_clear
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(3)
        self._swatch = QPushButton()
        self._swatch.setFixedHeight(20)
        self._swatch.clicked.connect(self._pick)
        row.addWidget(self._swatch, 1)
        self._clear = None
        if on_clear is not None:
            self._clear = QPushButton("✕")
            self._clear.setFixedSize(20, 20)
            self._clear.setToolTip(clear_tip)
            self._clear.clicked.connect(lambda: on_clear())
            row.addWidget(self._clear)

    def value(self) -> str:
        return self._value

    def set_colour(self, value: str, *, none_label: str) -> None:
        self._value = value
        border = QColor(theme.NODE_BORDER).name()
        if value:
            self._swatch.setText("")
            self._swatch.setStyleSheet(
                f"background: {value}; border: 1px solid {border};")
        else:
            self._swatch.setText(none_label)
            self._swatch.setStyleSheet(
                f"color: palette(mid); border: 1px solid {border};")
        if self._clear is not None:
            self._clear.setEnabled(bool(value))

    def _pick(self) -> None:
        start = QColor(self._value) if self._value else QColor(self._start)
        colour = QColorDialog.getColor(start, self, "Pick a colour")
        if colour.isValid():
            self._on_pick(colour.name())
