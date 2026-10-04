"""A colour picker for the colours in a report page's CSS: double-click
one, or right-click it for **Pick Colour…**, and the colour dialog opens
on it; the colour picked replaces it, written the way it was written
(core/css_colour.py) — one undo step in the editor and on the page.

An event filter, like SpellingMenu, because the CSS box is a plain
QPlainTextEdit with a highlighter and lint tips already hung off it.
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, QObject
from PySide6.QtGui import QColor, QIcon, QPixmap, QTextCursor
from PySide6.QtWidgets import QColorDialog

from flograph.core.css_colour import colour_at, write_like


class CssColourPicker(QObject):
    def __init__(self, editor, step=None) -> None:
        """`step(edit)` runs the rewrite — a page passes one that makes it
        an undo step of its own; by default it simply runs."""
        super().__init__(editor)
        self._editor = editor
        self._step = step or (lambda edit: edit())
        # a right-click or double-click lands on the viewport; the menu key
        # arrives at the editor itself
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
                return False          # an ordinary double-click: a word
            self.pick(found)
            return True
        point = event.pos()
        if obj is self._editor:
            point = self._editor.viewport().mapFrom(self._editor, point)
        menu = self.menu_for(point)
        menu.exec(event.globalPos())
        menu.deleteLater()
        return True

    def colour_under(self, point):
        """The colour token at `point` (viewport coordinates), or None."""
        cursor = self._editor.cursorForPosition(point)
        return colour_at(self._editor.toPlainText(), cursor.position())

    def menu_for(self, point):
        """The editor's standard menu, with Pick Colour… on top when
        `point` is on a colour. Apart from opening it, so a test can read
        it without a menu appearing."""
        menu = self._editor.createStandardContextMenu()
        found = self.colour_under(point)
        if found is not None:
            first = menu.actions()[0] if menu.actions() else None
            action = menu.addAction(_swatch(found.rgba), "Pick Colour…")
            action.triggered.connect(lambda: self.pick(found))
            if first is not None:
                menu.removeAction(action)
                menu.insertAction(first, action)
                menu.insertSeparator(first)
        return menu

    def pick(self, found) -> bool:
        """Ask for a colour starting at `found` and write it in its place.
        False when the dialog was cancelled or the colour is unchanged."""
        picked = self._ask(QColor(*found.rgba))
        if picked is None or not picked.isValid():
            return False
        rgba = (picked.red(), picked.green(), picked.blue(), picked.alpha())
        if rgba == tuple(found.rgba):
            return False
        cursor = QTextCursor(self._editor.document())
        cursor.setPosition(found.start)
        cursor.setPosition(found.end, QTextCursor.KeepAnchor)
        if cursor.selectedText() != found.text:
            return False                  # the text moved under the dialog
        self._step(lambda: cursor.insertText(write_like(found.text, rgba)))
        self._editor.setTextCursor(cursor)
        return True

    def _ask(self, start: QColor):
        colour = QColorDialog.getColor(start, self._editor.window(),
                                       "Pick a colour",
                                       QColorDialog.ShowAlphaChannel)
        return colour if colour.isValid() else None


def _swatch(rgba) -> QIcon:
    pixmap = QPixmap(14, 14)
    pixmap.fill(QColor(*rgba))
    return QIcon(pixmap)
