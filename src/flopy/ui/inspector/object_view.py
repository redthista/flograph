"""Fallback inspector view: pretty-printed repr, capped."""
from __future__ import annotations

import pprint
from typing import Any

from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QPlainTextEdit

MAX_CHARS = 50_000


class ObjectView(QPlainTextEdit):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setReadOnly(True)
        font = QFontDatabase.systemFont(QFontDatabase.FixedFont)
        font.setPointSizeF(9.0)
        self.setFont(font)

    def set_value(self, value: Any) -> None:
        try:
            text = pprint.pformat(value, width=100)
        except Exception:
            text = repr(value)
        if len(text) > MAX_CHARS:
            text = text[:MAX_CHARS] + f"\n… truncated ({len(text):,} chars total)"
        self.setPlainText(text)
