"""Autocomplete for formula entry (cell editors and the formula bar).

Two suggestion modes, decided from the text before the cursor:
- inside an unclosed "[" — column names, completed to "[Name]" /
  "[@Name]" (whatever bracket/@ the user already typed is preserved);
- a trailing word of 2+ letters — function names, completed with an
  opening paren (TRUE/FALSE complete bare).

Enter/Tab accept the highlighted suggestion, Escape dismisses. The key
handling lives in an event filter on the completer's popup: Qt's popup
grab delivers keys there first, and handling them there sidesteps
QCompleter's forward-to-widget dance (which lets an editor that handles
Enter itself — a cell delegate committing, the code editor indenting —
swallow the keystroke before the completion can land).
"""
from __future__ import annotations

import re
from typing import Callable

from PySide6.QtCore import QEvent, QObject, QStringListModel, Qt
from PySide6.QtWidgets import QCompleter, QLineEdit

from flograph.core.sheet import FUNCTION_NAMES

_WORD_SUGGESTIONS = tuple(sorted([*FUNCTION_NAMES, "TRUE", "FALSE"]))
_BARE_WORDS = ("TRUE", "FALSE")   # complete without a "("
_TRAILING_WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_]*$")


class FormulaCompleter(QObject):
    def __init__(self, edit: QLineEdit,
                 columns: Callable[[], list[str]]) -> None:
        super().__init__(edit)
        self._edit = edit
        self._columns = columns
        self._mode = "function"
        self._replace_from = 0

        self._completer = QCompleter([], edit)
        self._completer.setWidget(edit)
        self._completer.setCompletionMode(QCompleter.PopupCompletion)
        self._completer.setCaseSensitivity(Qt.CaseInsensitive)
        self._completer.activated.connect(self._insert)
        # installed after QCompleter's own popup filter, so this runs first
        self._completer.popup().installEventFilter(self)

        edit.textEdited.connect(self._refresh)

    # ------------------------------------------------------------- popup keys

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

    # ------------------------------------------------------------ suggestions

    def _refresh(self) -> None:
        text = self._edit.text()
        pos = self._edit.cursorPosition()
        before = text[:pos]
        popup = self._completer.popup()
        if not text.startswith("=") or text == "=":
            popup.hide()
            return

        bracket = before.rfind("[")
        if bracket != -1 and "]" not in before[bracket:]:
            inner = before[bracket + 1:]
            prefix = inner[1:] if inner.startswith("@") else inner
            self._mode = "column"
            self._replace_from = bracket
            items = [str(name) for name in self._columns()]
        else:
            match = _TRAILING_WORD.search(before)
            prefix = match.group(0) if match else ""
            if len(prefix) < 2:   # single letters are usually A1-style refs
                popup.hide()
                return
            self._mode = "function"
            self._replace_from = pos - len(prefix)
            items = list(_WORD_SUGGESTIONS)

        self._completer.setModel(QStringListModel(items, self._completer))
        self._completer.setCompletionPrefix(prefix)
        if self._completer.completionCount() == 0:
            popup.hide()
            return
        self._completer.complete()
        popup.setCurrentIndex(self._completer.completionModel().index(0, 0))

    def _insert(self, name: str) -> None:
        text = self._edit.text()
        pos = self._edit.cursorPosition()
        if self._mode == "column":
            typed = text[self._replace_from:pos]
            at = "@" if typed.startswith("[@") else ""
            replacement = f"[{at}{name}]"
        elif name.upper() in _BARE_WORDS:
            replacement = name
        else:
            replacement = f"{name}("
        new_text = text[:self._replace_from] + replacement + text[pos:]
        self._edit.setText(new_text)
        self._edit.setCursorPosition(self._replace_from + len(replacement))
        self._completer.popup().hide()
