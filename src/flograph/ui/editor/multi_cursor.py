"""Several carets in one CodeEditor.

Alt+Click adds a caret, or takes one away; Alt+Shift+Up / Down (or
Ctrl+Alt+Up / Down) adds one on the line above or below. Ctrl+D or Alt+J
selects the next place the selection appears, with a caret of its own, and
Ctrl+Shift+L or Ctrl+Alt+Shift+J selects every one. Typing, Backspace,
Delete, Enter, Tab, the arrows, Home, End and cut / copy / paste then act at
every caret at once, as one undo step. Esc, or a plain click, goes back to
one caret.

The editor's own QTextCursor stays the main caret: the find bar, completion
and scroll-to-caret all go on reading it. The extra carets are ordinary
QTextCursors on the same document, which Qt keeps in place as text is
edited around them.
"""
from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import (
    QColor, QKeyEvent, QPainter, QTextCursor, QTextDocument,
)
from PySide6.QtWidgets import QApplication, QPlainTextEdit

CARET_COLOR = QColor("#d7dae0")
EXTRA_SELECTION_BG = QColor("#264f78")
INDENT = "    "
_PARAGRAPH = "\u2029"   # what QTextCursor.selectedText() uses for a newline


def _mods(event) -> tuple[bool, bool, bool]:
    mods = event.modifiers()
    return (bool(mods & Qt.ControlModifier), bool(mods & Qt.AltModifier),
            bool(mods & Qt.ShiftModifier))


class MultiCaret:
    def __init__(self, editor: QPlainTextEdit) -> None:
        self._editor = editor
        self.extras: list[QTextCursor] = []

    @property
    def active(self) -> bool:
        return bool(self.extras)

    def cursors(self) -> list[QTextCursor]:
        """Every caret, main first. The main one is a copy — hand it back
        with setTextCursor after moving it."""
        return [self._editor.textCursor()] + self.extras

    # -------------------------------------------------------------- adding

    def clear(self) -> None:
        if self.extras:
            self.extras = []
            self._changed()

    def toggle_at(self, cursor: QTextCursor) -> None:
        """Alt+Click: a caret where there wasn't one, none where there was."""
        pos = cursor.position()
        for extra in self.extras:
            if extra.position() == pos and not extra.hasSelection():
                self.extras.remove(extra)
                self._changed()
                return
        main = self._editor.textCursor()
        if main.position() == pos and not main.hasSelection():
            if self.extras:
                # clicking the main caret away: the newest extra takes over
                self._editor.setTextCursor(self.extras.pop())
                self._changed()
            return
        self.extras.append(main)
        self._editor.setTextCursor(cursor)
        self._changed()

    def add_vertical(self, step: int) -> None:
        """A caret on the line above (step -1) or below (+1) the outermost
        one, at the same column or the end of a shorter line."""
        everyone = self.cursors()
        edge = (min(everyone, key=QTextCursor.position) if step < 0
                else max(everyone, key=QTextCursor.position))
        block = edge.block()
        target = block.previous() if step < 0 else block.next()
        if not target.isValid():
            return
        column = min(edge.positionInBlock(), target.length() - 1)
        new = QTextCursor(target)
        new.setPosition(target.position() + column)
        self.extras.append(self._editor.textCursor())
        self._editor.setTextCursor(new)
        self._changed()

    def _needle(self) -> str:
        """The selected text, selecting the word under the caret first if
        nothing is selected. '' when there is nothing to look for."""
        main = self._editor.textCursor()
        if not main.hasSelection():
            main.select(QTextCursor.WordUnderCursor)
            self._editor.setTextCursor(main)
            self._changed()
            return ""
        text = main.selectedText()
        return "" if _PARAGRAPH in text else text

    @staticmethod
    def _find(doc: QTextDocument, needle: str, start) -> QTextCursor:
        """The next place `needle` appears from `start` (a position or a
        cursor), case-sensitively. A name only matches as a whole name:
        Qt's FindWholeWords counts `_` as a break, so `cost` would still
        land inside `cost_x`."""
        flags = QTextDocument.FindCaseSensitively
        hit = doc.find(needle, start, flags)
        if not needle.isidentifier():
            return hit

        def part_of_a_name(pos: int) -> bool:
            if pos < 0 or pos >= doc.characterCount():
                return False
            ch = doc.characterAt(pos)
            return bool(ch) and (ch.isalnum() or ch == "_")

        while not hit.isNull() and (part_of_a_name(hit.selectionStart() - 1)
                                    or part_of_a_name(hit.selectionEnd())):
            hit = doc.find(needle, hit, flags)
        return hit

    def select_next(self) -> None:
        """Ctrl+D: the first press selects the word under the caret, each
        one after adds the next place that text appears, wrapping round."""
        needle = self._needle()
        if not needle:
            return
        doc = self._editor.document()
        everyone = self.cursors()
        taken = {(c.selectionStart(), c.selectionEnd()) for c in everyone}
        last = max(everyone, key=lambda c: c.selectionEnd())
        found = self._find(doc, needle, last.selectionEnd())
        if found.isNull():
            found = self._find(doc, needle, 0)
        if found.isNull() or (found.selectionStart(),
                              found.selectionEnd()) in taken:
            return
        self.extras.append(self._editor.textCursor())
        self._editor.setTextCursor(found)
        self._changed()

    def select_all(self) -> None:
        """Ctrl+Shift+L: a caret on every place the selection appears."""
        needle = self._needle()
        if not needle:
            needle = self._editor.textCursor().selectedText()
            if not needle or _PARAGRAPH in needle:
                return
        doc = self._editor.document()
        hits = []
        hit = self._find(doc, needle, 0)
        while not hit.isNull():
            hits.append(hit)
            hit = self._find(doc, needle, hit)
        if len(hits) < 2:
            return
        start = self._editor.textCursor().selectionStart()
        current = next((h for h in hits if h.selectionStart() == start), hits[0])
        self.extras = [h for h in hits if h is not current]
        self._editor.setTextCursor(current)
        self._changed()

    # ------------------------------------------------------------- editing

    def _edit(self, action: Callable[[QTextCursor], None]) -> None:
        main = self._editor.textCursor()
        main.beginEditBlock()
        for cursor in [main] + self.extras:
            action(cursor)
        main.endEditBlock()
        self._editor.setTextCursor(main)
        self._changed()

    def _move(self, key: int, ctrl: bool, shift: bool) -> None:
        mode = QTextCursor.KeepAnchor if shift else QTextCursor.MoveAnchor

        def move(cursor: QTextCursor) -> None:
            if key in (Qt.Key_Up, Qt.Key_Down):
                block = cursor.block()
                target = block.previous() if key == Qt.Key_Up else block.next()
                if target.isValid():
                    column = min(cursor.positionInBlock(), target.length() - 1)
                    cursor.setPosition(target.position() + column, mode)
            elif key in (Qt.Key_Left, Qt.Key_Right) and not shift \
                    and not ctrl and cursor.hasSelection():
                # an arrow on a selection lands at its near edge, as with one
                cursor.setPosition(cursor.selectionStart() if key == Qt.Key_Left
                                   else cursor.selectionEnd())
            elif key == Qt.Key_Left:
                cursor.movePosition(QTextCursor.PreviousWord if ctrl
                                    else QTextCursor.Left, mode)
            elif key == Qt.Key_Right:
                cursor.movePosition(QTextCursor.NextWord if ctrl
                                    else QTextCursor.Right, mode)
            elif key == Qt.Key_Home:
                cursor.movePosition(QTextCursor.StartOfBlock, mode)
            elif key == Qt.Key_End:
                cursor.movePosition(QTextCursor.EndOfBlock, mode)

        main = self._editor.textCursor()
        for cursor in [main] + self.extras:
            move(cursor)
        self._editor.setTextCursor(main)
        self._changed()

    def _ordered(self) -> list[QTextCursor]:
        return sorted(self.cursors(), key=QTextCursor.position)

    def _copy(self, cut: bool) -> None:
        pieces = [c.selectedText().replace(_PARAGRAPH, "\n")
                  for c in self._ordered()]
        if not any(pieces):
            return
        QApplication.clipboard().setText("\n".join(pieces))
        if cut:
            self._edit(lambda c: c.removeSelectedText())

    def _paste(self) -> None:
        text = QApplication.clipboard().text()
        if not text:
            return
        order = [(c.position(), c.anchor()) for c in self._ordered()]
        lines = text.split("\n")
        # one line per caret — what a multi-caret copy put there — goes one
        # to each, in order; anything else goes whole to every caret
        spread = len(lines) == len(order)
        # positions are read before any of them move
        main = self._editor.textCursor()
        pairs = [(c, order.index((c.position(), c.anchor())))
                 for c in [main] + self.extras]
        main.beginEditBlock()
        for cursor, index in pairs:
            cursor.insertText(lines[index] if spread else text)
        main.endEditBlock()
        self._editor.setTextCursor(main)
        self._changed()

    # -------------------------------------------------------------- events

    def wants(self, event: QKeyEvent) -> bool:
        """For ShortcutOverride: keys this takes before any window shortcut
        sharing them gets the chance."""
        ctrl, alt, shift = _mods(event)
        key = event.key()
        if self._is_add_key(key, ctrl, alt, shift):
            return True
        return self.active and key == Qt.Key_Escape

    @staticmethod
    def _is_add_key(key: int, ctrl: bool, alt: bool, shift: bool) -> bool:
        return (
            (key in (Qt.Key_Up, Qt.Key_Down) and alt and (shift != ctrl))
            or (key == Qt.Key_D and ctrl and not alt and not shift)
            or (key == Qt.Key_J and alt and not ctrl and not shift)
            or (key == Qt.Key_L and ctrl and shift and not alt)
            or (key == Qt.Key_J and ctrl and alt and shift))

    def key_press(self, event: QKeyEvent) -> bool:
        """Handle `event` if it is a caret key, or any edit while there are
        several carets. True when handled."""
        ctrl, alt, shift = _mods(event)
        key = event.key()
        if key in (Qt.Key_Up, Qt.Key_Down) and alt and (shift != ctrl):
            self.add_vertical(-1 if key == Qt.Key_Up else 1)
            return True
        if (key == Qt.Key_D and ctrl and not alt and not shift) \
                or (key == Qt.Key_J and alt and not ctrl and not shift):
            self.select_next()
            return True
        if (key == Qt.Key_L and ctrl and shift and not alt) \
                or (key == Qt.Key_J and ctrl and alt and shift):
            self.select_all()
            return True
        if not self.extras:
            return False
        if key == Qt.Key_Escape:
            self.clear()
            return True
        if key == Qt.Key_Backspace:
            self._edit(lambda c: c.removeSelectedText() if c.hasSelection()
                       else c.deletePreviousChar())
            return True
        if key == Qt.Key_Delete:
            self._edit(lambda c: c.removeSelectedText() if c.hasSelection()
                       else c.deleteChar())
            return True
        if key in (Qt.Key_Return, Qt.Key_Enter) and not ctrl:
            self._edit(lambda c: c.insertText("\n"))
            return True
        if key == Qt.Key_Tab:
            self._edit(lambda c: c.insertText(INDENT))
            return True
        if key in (Qt.Key_Left, Qt.Key_Right, Qt.Key_Up, Qt.Key_Down,
                   Qt.Key_Home, Qt.Key_End):
            self._move(key, ctrl, shift)
            return True
        if ctrl and not alt and key in (Qt.Key_C, Qt.Key_X):
            self._copy(cut=key == Qt.Key_X)
            return True
        if ctrl and not alt and key == Qt.Key_V:
            self._paste()
            return True
        if ctrl and not alt and key == Qt.Key_A:
            self.extras = []
            self._changed()
            return False
        text = event.text()
        # AltGr arrives as Ctrl+Alt on some platforms, and types a character
        if text and text.isprintable() and (not ctrl or alt):
            self._edit(lambda c: c.insertText(text))
            return True
        return False

    def mouse_press(self, event) -> bool:
        """Alt+Click toggles a caret (True: handled); a plain click goes
        back to one caret and lets the editor place it."""
        if event.button() != Qt.LeftButton:
            return False
        if event.modifiers() & Qt.AltModifier:
            self.toggle_at(self._editor.cursorForPosition(
                event.position().toPoint()))
            return True
        self.clear()
        return False

    def paint(self) -> None:
        """The extra carets, drawn over the text. Qt draws only its own."""
        if not self.extras:
            return
        painter = QPainter(self._editor.viewport())
        for cursor in self.extras:
            rect = self._editor.cursorRect(cursor)
            painter.fillRect(rect.x(), rect.y(), 2, rect.height(), CARET_COLOR)
        painter.end()

    def _changed(self) -> None:
        main = self._editor.textCursor()
        seen = {(main.position(), main.anchor())}
        kept = []
        for cursor in self.extras:
            key = (cursor.position(), cursor.anchor())
            if key not in seen:
                seen.add(key)
                kept.append(cursor)
        self.extras = kept
        refresh = getattr(self._editor, "_update_extra_selections", None)
        if refresh is not None:
            refresh()
        self._editor.viewport().update()
