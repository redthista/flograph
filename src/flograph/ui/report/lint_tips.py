"""Rest the pointer on an underlined line and the lint says what is wrong
with it — the same words as the problems bar, where the mistake is."""
from __future__ import annotations

from PySide6.QtCore import QEvent, QObject
from PySide6.QtWidgets import QToolTip

from ..editor.diagnostics import worst_on_line


class LintTips(QObject):
    """Tooltips for a text editor's lint marks. `diagnostics` is called
    each time, so the tip always speaks for the latest lint."""

    def __init__(self, editor, diagnostics) -> None:
        super().__init__(editor)
        self._editor = editor
        self._diagnostics = diagnostics
        editor.viewport().installEventFilter(self)

    def eventFilter(self, watched, event) -> bool:
        if event.type() != QEvent.ToolTip:
            return False
        cursor = self._editor.cursorForPosition(event.pos())
        found = worst_on_line(self._diagnostics() or (),
                              cursor.blockNumber() + 1)
        if found is None:
            QToolTip.hideText()
            return False
        QToolTip.showText(event.globalPos(), found.message, self._editor)
        return True
