"""Autocomplete for `${` in the Properties panel.

Type `${` in any text param and the flow's variables drop down, the way the
code editor offers names as you type. Without it a variable is only usable
by someone who already remembers what it is called, which for the person a
flow gets handed to is nobody.

Built on the same shape as `ui.spreadsheet.completion` — a QCompleter driven
manually so it can complete *mid-text*, with Enter/Tab/Escape handled in an
event filter on the popup. Qt's popup grab delivers keys there first, and
handling them there sidesteps QCompleter's forward-to-widget dance, which
would otherwise let the editor swallow Return before the completion lands.

Works over both widget shapes the panel builds: QLineEdit (string, columns,
file paths, password) and QPlainTextEdit (multiline text).
"""
from __future__ import annotations

import re
from typing import Callable, Optional

from PySide6.QtCore import QEvent, QObject, QStringListModel, Qt
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QCompleter, QLineEdit, QPlainTextEdit, QWidget

# An unclosed "${" before the cursor, and whatever has been typed since.
# The ":" is in the character class so "${env:TO" keeps completing rather
# than dropping out of the match at the colon.
OPEN_REFERENCE = re.compile(r"\$\{([A-Za-z0-9_:]*)$")


def attach(widget: QWidget, names: Callable[[], list[str]]
           ) -> Optional["VariableCompleter"]:
    """Fit a completer to whatever editor is inside `widget`.

    The panel wraps some params (file paths, password) in a host widget with
    a button beside the field, so the editor has to be found rather than
    assumed. None when there is nothing to attach to.
    """
    editor = widget
    if not isinstance(editor, (QLineEdit, QPlainTextEdit)):
        editor = (widget.findChild(QLineEdit)
                  or widget.findChild(QPlainTextEdit))
    if editor is None:
        return None
    return VariableCompleter(editor, names)


class VariableCompleter(QObject):
    def __init__(self, editor, names: Callable[[], list[str]]) -> None:
        super().__init__(editor)
        self._editor = editor
        self._names = names

        self._completer = QCompleter([], editor)
        self._completer.setWidget(editor)
        self._completer.setCompletionMode(QCompleter.PopupCompletion)
        self._completer.setCaseSensitivity(Qt.CaseInsensitive)
        self._completer.activated.connect(self._insert)
        # installed after QCompleter's own popup filter, so this runs first
        self._completer.popup().installEventFilter(self)

        # QPlainTextEdit has no textEdited, and its textChanged also fires
        # when the panel syncs a value in from the graph — so that path has
        # to check focus, or selecting a node would pop a menu at nobody.
        # QLineEdit.textEdited already means "the user typed", so it needs
        # no such test.
        self._needs_focus = isinstance(editor, QPlainTextEdit)
        if self._needs_focus:
            editor.textChanged.connect(self._refresh)
        else:
            editor.textEdited.connect(self._refresh)

    # ----------------------------------------------------------- popup keys

    def eventFilter(self, obj, event) -> bool:
        popup = self._completer.popup()
        if obj is popup and popup.isVisible() and event.type() == QEvent.KeyPress:
            if event.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Tab):
                index = popup.currentIndex()
                if not index.isValid():
                    index = self._completer.completionModel().index(0, 0)
                if index.isValid():
                    self._insert(str(index.data()))
                popup.hide()
                return True
            if event.key() == Qt.Key_Escape:
                popup.hide()
                return True
        return super().eventFilter(obj, event)

    # ---------------------------------------------------------- the editor

    def _state(self) -> tuple[str, int]:
        if isinstance(self._editor, QPlainTextEdit):
            return self._editor.toPlainText(), self._editor.textCursor().position()
        return self._editor.text(), self._editor.cursorPosition()

    def _replace(self, start: int, end: int, replacement: str) -> None:
        if isinstance(self._editor, QPlainTextEdit):
            # Through a QTextCursor rather than setPlainText: it keeps the
            # editor's own undo history intact and leaves the caret where
            # the edit ended.
            cursor = self._editor.textCursor()
            cursor.setPosition(start)
            cursor.setPosition(end, QTextCursor.KeepAnchor)
            cursor.insertText(replacement)
            return
        text = self._editor.text()
        self._editor.setText(text[:start] + replacement + text[end:])
        self._editor.setCursorPosition(start + len(replacement))

    # ---------------------------------------------------------- suggestions

    def _refresh(self) -> None:
        popup = self._completer.popup()
        if self._needs_focus and not self._editor.hasFocus():
            popup.hide()
            return
        text, pos = self._state()
        match = OPEN_REFERENCE.search(text[:pos])
        if match is None:
            popup.hide()
            return
        items = list(self._names())
        if not items:
            popup.hide()
            return
        self._completer.setModel(QStringListModel(items, self._completer))
        self._completer.setCompletionPrefix(match.group(1))
        if self._completer.completionCount() == 0:
            popup.hide()
            return
        if isinstance(self._editor, QPlainTextEdit):
            rect = self._editor.cursorRect()
            rect.setWidth(popup.sizeHintForColumn(0)
                          + popup.verticalScrollBar().sizeHint().width())
            self._completer.complete(rect)
        else:
            self._completer.complete()
        # highlight the first suggestion so a bare Enter/Tab accepts it
        popup.setCurrentIndex(self._completer.completionModel().index(0, 0))

    def _insert(self, name: str) -> None:
        text, pos = self._state()
        # Re-derived here rather than carried over from _refresh. The two are
        # in step whenever the popup is driving this, but an offset held
        # across an edit that moved the text would splice the name in at the
        # wrong place and eat whatever was in between — a silent corruption
        # of something the user typed, which is not worth risking to save a
        # regex.
        match = OPEN_REFERENCE.search(text[:pos])
        if match is None:
            self._completer.popup().hide()
            return
        # Consume a "}" the user already typed rather than adding a second:
        # completing into "${}" is the common case when someone types the
        # pair and then goes back between them.
        end = pos + 1 if text[pos:pos + 1] == "}" else pos
        self._replace(match.start(), end, f"${{{name}}}")
        self._completer.popup().hide()
