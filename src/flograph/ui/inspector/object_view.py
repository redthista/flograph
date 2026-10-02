"""Fallback inspector view: pretty-printed repr, capped."""
from __future__ import annotations

import pprint
from typing import Any

from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QPlainTextEdit

MAX_CHARS = 50_000
#: a string or bytes *inside* a container longer than this shows as its
#: start and its length — a data: URI or an image's bytes is a screenful of
#: base64 that hides every other field of the dict it sits in
LONG_INSIDE = 300


class _Elided(str):
    """Prints without quotes, so the note reads as a note, not a value."""

    def __repr__(self) -> str:
        return str(self)


def _elide(value: Any, depth: int = 0) -> Any:
    """`value` with long strings/bytes nested in dicts, lists and tuples
    shortened. A top-level string is left whole: there it *is* the output."""
    if depth > 6:
        return value
    if isinstance(value, dict):
        return {k: _short(v, depth) for k, v in value.items()}
    if isinstance(value, list):
        return [_short(v, depth) for v in value]
    if isinstance(value, tuple) and not hasattr(value, "_fields"):
        return tuple(_short(v, depth) for v in value)
    return value


def _short(value: Any, depth: int) -> Any:
    if isinstance(value, str) and len(value) > LONG_INSIDE:
        return _Elided(f"{value[:80]!r}… ({len(value):,} chars)")
    if isinstance(value, (bytes, bytearray)) and len(value) > LONG_INSIDE:
        return _Elided(f"<{len(value):,} bytes>")
    return _elide(value, depth + 1)


class ObjectView(QPlainTextEdit):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setReadOnly(True)
        font = QFontDatabase.systemFont(QFontDatabase.FixedFont)
        font.setPointSizeF(9.0)
        self.setFont(font)

    def set_value(self, value: Any) -> None:
        try:
            text = pprint.pformat(_elide(value), width=100)
        except Exception:
            text = repr(value)
        if len(text) > MAX_CHARS:
            text = text[:MAX_CHARS] + f"\n… truncated ({len(text):,} chars total)"
        self.setPlainText(text)
