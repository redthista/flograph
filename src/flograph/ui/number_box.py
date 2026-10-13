"""A number box that types like a text box.

A plain QDoubleSpinBox pads its value to every decimal it allows — six of
them in the Properties panel, so 0 reads `0.000000` — and commits on every
keystroke, each commit echoing back through that padding. Typing 0.5 meant
first clearing a zero and a run of trailing zeros out of the way.

`NumberBox` shows the shortest text for its value (`0.5`, `3`, `1e-05` is
`0.00001`) and commits once: on Enter, on leaving the box, or on an arrow
step — never mid-number.
"""
from __future__ import annotations

from PySide6.QtCore import QLocale
from PySide6.QtWidgets import QDoubleSpinBox


class NumberBox(QDoubleSpinBox):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setKeyboardTracking(False)

    def textFromValue(self, value: float) -> str:
        locale = self.locale()
        if not self.isGroupSeparatorShown():
            locale.setNumberOptions(
                locale.numberOptions() | QLocale.OmitGroupSeparator)
        text = locale.toString(value, "f", self.decimals())
        point = locale.decimalPoint()
        if point in text:
            text = text.rstrip("0").rstrip(point)
        return "0" if text in ("-0", "") else text
