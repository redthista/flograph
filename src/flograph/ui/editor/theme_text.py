"""The Theme Customiser's text mode in a CodeEditor: TOML in colour, with
every `"#rrggbb"` shown on a swatch of itself (as the report CSS tab does),
and a colour dialog on double-click or right-click ▸ Pick Colour… that
rewrites the colour in place — live, as the dialog's colour moves.
"""
from __future__ import annotations

import re

from PySide6.QtCore import QEvent, QObject
from PySide6.QtGui import (
    QColor, QIcon, QPixmap, QSyntaxHighlighter, QTextCursor,
)
from PySide6.QtWidgets import QColorDialog, QDialog

from .highlighter import COLORS

HEX = re.compile(r"#[0-9a-fA-F]{6}\b")
_SECTION = re.compile(r"^\s*\[[\w.-]+\]")
_KEY = re.compile(r"^(\s*)([\w.-]+)(\s*=)")
_STRING = re.compile(r'"(?:[^"\\]|\\.)*"')
_NUMBER = re.compile(r"(?<![\w#.])-?\d+(?:\.\d+)?(?![\w.])")
_BOOL = re.compile(r"\b(?:true|false)\b")
_COMMENT = re.compile(r"(?:^|\s)(#.*)$")


class ThemeTextHighlighter(QSyntaxHighlighter):
    def highlightBlock(self, text: str) -> None:
        if _SECTION.match(text):
            self.setFormat(0, len(text), COLORS["keyword"])
            return
        key = _KEY.match(text)
        if key:
            start = len(key.group(1))
            self.setFormat(start, len(key.group(2)), COLORS["builtin"])
        for match in _NUMBER.finditer(text):
            self.setFormat(match.start(), match.end() - match.start(),
                           COLORS["number"])
        for match in _BOOL.finditer(text):
            self.setFormat(match.start(), match.end() - match.start(),
                           COLORS["keyword"])
        for match in _STRING.finditer(text):
            self.setFormat(match.start(), match.end() - match.start(),
                           COLORS["string"])
            for colour in HEX.finditer(match.group(0)):
                self._swatch(match.start() + colour.start(), colour.group(0))
        comment = _COMMENT.search(text)
        if comment and not _inside_string(text, comment.start(1)):
            self.setFormat(comment.start(1), len(text) - comment.start(1),
                           COLORS["comment"])

    def _swatch(self, start: int, value: str) -> None:
        fmt = self.format(start)
        colour = QColor(value)
        fmt.setBackground(colour)
        fmt.setForeground(QColor("#000000" if colour.lightness() > 140
                                 else "#ffffff"))
        self.setFormat(start, 7, fmt)


def swatch_selections(editor) -> list:
    """The colour swatches of the line the caret is on, as extra selections.

    The editor paints a band behind the current line, and an extra selection
    is drawn over the highlighter's own background — so without this the
    line with the caret on it would be the one line whose colours vanish."""
    from PySide6.QtWidgets import QTextEdit
    block = editor.textCursor().block()
    out = []
    for match in HEX.finditer(block.text()):
        # only inside quotes, as the highlighter does
        if not _inside_string(block.text(), match.start()):
            continue
        colour = QColor(match.group(0))
        extra = QTextEdit.ExtraSelection()
        extra.format.setBackground(colour)
        extra.format.setForeground(QColor(
            "#000000" if colour.lightness() > 140 else "#ffffff"))
        cursor = QTextCursor(block)
        cursor.setPosition(block.position() + match.start())
        cursor.setPosition(block.position() + match.end(),
                           QTextCursor.KeepAnchor)
        extra.cursor = cursor
        out.append(extra)
    return out


def _inside_string(text: str, index: int) -> bool:
    return any(m.start() < index < m.end() for m in _STRING.finditer(text))


def _icon(value: str) -> QIcon:
    pix = QPixmap(14, 14)
    pix.fill(QColor(value))
    return QIcon(pix)


class HexColourPicker(QObject):
    """Double-click a `#rrggbb` in the editor, or right-click it for **Pick
    Colour…**. The colour is written back as the dialog moves, so the theme
    preview follows it; cancelling puts it back."""

    def __init__(self, editor) -> None:
        super().__init__(editor)
        self._editor = editor
        editor.installEventFilter(self)
        editor.viewport().installEventFilter(self)

    def eventFilter(self, obj, event) -> bool:
        kind = event.type()
        if kind not in (QEvent.ContextMenu, QEvent.MouseButtonDblClick):
            return False
        if obj is not self._editor and obj is not self._editor.viewport():
            return False
        if kind == QEvent.MouseButtonDblClick:
            if obj is not self._editor.viewport():
                return False
            found = self.colour_under(event.position().toPoint())
            if found is None:
                return False
            self.pick(*found)
            return True
        point = event.pos()
        if obj is self._editor:
            point = self._editor.viewport().mapFrom(self._editor, point)
        menu = self.menu_for(point)
        menu.exec(event.globalPos())
        menu.deleteLater()
        return True

    def colour_under(self, point):
        """(position of its '#', colour text) of the colour at `point`
        (viewport coordinates), or None."""
        cursor = self._editor.cursorForPosition(point)
        block = cursor.block()
        column = cursor.position() - block.position()
        for match in HEX.finditer(block.text()):
            if match.start() <= column <= match.end():
                return block.position() + match.start(), match.group(0)
        return None

    def menu_for(self, point):
        menu = self._editor.createStandardContextMenu()
        found = self.colour_under(point)
        if found is not None:
            first = menu.actions()[0] if menu.actions() else None
            action = menu.addAction(_icon(found[1]), "Pick Colour…")
            action.triggered.connect(lambda: self.pick(*found))
            if first is not None:
                menu.removeAction(action)
                menu.insertAction(first, action)
                menu.insertSeparator(first)
        return menu

    def _write(self, position: int, value: str, first: bool) -> None:
        cursor = QTextCursor(self._editor.document())
        cursor.setPosition(position)
        cursor.setPosition(position + 7, QTextCursor.KeepAnchor)
        if first:
            cursor.beginEditBlock()
        else:
            cursor.joinPreviousEditBlock()
        cursor.insertText(value)
        cursor.endEditBlock()

    def pick(self, position: int, value: str) -> bool:
        """Ask for a colour starting at `value`; write it at `position` as
        it changes. False if cancelled (the old colour is put back)."""
        state = {"first": True}

        def moved(colour: QColor) -> None:
            if colour.isValid():
                self._write(position, colour.name().lower(), state["first"])
                state["first"] = False

        dialog = QColorDialog(QColor(value), self._editor.window())
        dialog.setWindowTitle("Pick Colour")
        dialog.currentColorChanged.connect(moved)
        accepted = dialog.exec() == QDialog.Accepted
        if not accepted and not state["first"]:
            self._editor.undo()
        return accepted and not state["first"]
