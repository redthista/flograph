"""Marking what a lint found (core/text_assist) in a QPlainTextEdit.

Shared by the code editor — the pop-out and the node script panel — and the
multiline boxes in Properties, so a mistake looks the same in the box as in
the window it pops out to: a wavy underline under the words of the line, red
for what the node would refuse, amber for what it may not mean.
"""
from __future__ import annotations

from typing import Iterable

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import (
    QColor, QIcon, QPainter, QPixmap, QTextCharFormat, QTextCursor,
    QTextDocument,
)
from PySide6.QtWidgets import QTextEdit

DIAGNOSTIC_COLORS = {"error": QColor("#ef4444"), "warning": QColor("#f59e0b")}


def worst_on_line(diagnostics: Iterable, line: int):
    """The error on a 1-based line if there is one, else its first warning,
    else None."""
    found = [d for d in diagnostics if d.line == line]
    return next((d for d in found if d.severity == "error"),
                found[0] if found else None)


def underline_selections(document: QTextDocument, diagnostics: Iterable) -> list:
    """An extra selection per marked line, underlining its words — not the
    indent before them or the spaces after. A blank line gets none."""
    selections = []
    for diagnostic in diagnostics:
        block = document.findBlockByNumber(diagnostic.line - 1)
        text = block.text() if block.isValid() else ""
        if not text.strip():
            continue
        mark = QTextEdit.ExtraSelection()
        mark.format.setUnderlineStyle(QTextCharFormat.WaveUnderline)
        mark.format.setUnderlineColor(DIAGNOSTIC_COLORS.get(
            diagnostic.severity, DIAGNOSTIC_COLORS["error"]))
        cursor = QTextCursor(block)
        cursor.setPosition(block.position() + len(text) - len(text.lstrip()))
        cursor.setPosition(block.position() + len(text.rstrip()),
                           QTextCursor.KeepAnchor)
        mark.cursor = cursor
        selections.append(mark)
    return selections


def summary(diagnostics: Iterable, limit: int = 8) -> str:
    """One line per problem, for a tooltip: `line 2: no operator …`."""
    found = sorted(diagnostics, key=lambda d: d.line)
    lines = [f"line {d.line}: {d.message}" for d in found[:limit]]
    if len(found) > limit:
        lines.append(f"… and {len(found) - limit} more")
    return "\n".join(lines)


def dot_icon(color: QColor, size: int = 10) -> QIcon:
    """A filled dot, beside the name of a setting whose text has problems.
    Drawn rather than typed, so no font can turn it into a box."""
    scale = 2
    pixmap = QPixmap(size * scale, size * scale)
    pixmap.setDevicePixelRatio(scale)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setPen(Qt.NoPen)
    painter.setBrush(color)
    painter.drawEllipse(QRectF(1.5, 1.5, size - 3, size - 3))
    painter.end()
    return QIcon(pixmap)
