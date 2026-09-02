"""Find/replace strip for the code editor (Ctrl+F, Ctrl+H).

A slim row that appears under the editor rather than a modal dialog, so the
code stays visible and the match highlights stay meaningful while typing.
Every match is highlighted as you type; Enter/F3 walks them, wrapping at
either end. Replace fields only appear when asked for, so plain find stays
one line tall.

The bar owns no state the editor needs — closing it clears the highlights
and leaves the document untouched — so a host can create one per editor and
otherwise forget about it.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QTextCursor, QTextDocument
from PySide6.QtWidgets import (
    QGridLayout, QLabel, QLineEdit, QToolButton, QWidget,
)

from .code_editor import CodeEditor

# a runaway regex-free scan is cheap, but a pathological document with tens of
# thousands of hits would spend real time building extra selections
MAX_HIGHLIGHTS = 2000


class FindBar(QWidget):
    """Incremental find, and optional replace, over one CodeEditor."""

    def __init__(self, editor: CodeEditor, parent=None) -> None:
        super().__init__(parent)
        self._editor = editor

        self._find_edit = QLineEdit()
        self._find_edit.setPlaceholderText("Find")
        self._find_edit.setClearButtonEnabled(True)
        self._find_edit.textChanged.connect(self._on_find_text_changed)

        self._replace_edit = QLineEdit()
        self._replace_edit.setPlaceholderText("Replace with")
        self._replace_edit.returnPressed.connect(self.replace_current)

        self._case_btn = QToolButton()
        self._case_btn.setText("Aa")
        self._case_btn.setCheckable(True)
        self._case_btn.setToolTip("Match case")
        self._case_btn.toggled.connect(lambda _c: self._refresh())

        self._words_btn = QToolButton()
        self._words_btn.setText("W")
        self._words_btn.setCheckable(True)
        self._words_btn.setToolTip("Whole words only")
        self._words_btn.toggled.connect(lambda _c: self._refresh())

        prev_btn = QToolButton()
        prev_btn.setText("▲")
        prev_btn.setToolTip("Previous match (Shift+F3)")
        prev_btn.clicked.connect(lambda: self.find_next(backwards=True))

        next_btn = QToolButton()
        next_btn.setText("▼")
        next_btn.setToolTip("Next match (F3)")
        next_btn.clicked.connect(lambda: self.find_next())

        self._count = QLabel("")
        self._count.setStyleSheet("color: palette(mid);")
        self._count.setToolTip("Current match of the total in this file")

        close_btn = QToolButton()
        close_btn.setText("✕")
        close_btn.setToolTip("Close (Esc)")
        close_btn.clicked.connect(self.close_bar)

        self._replace_btn = QToolButton()
        self._replace_btn.setText("Replace")
        self._replace_btn.clicked.connect(self.replace_current)

        self._replace_all_btn = QToolButton()
        self._replace_all_btn.setText("All")
        self._replace_all_btn.setToolTip("Replace every match in this file")
        self._replace_all_btn.clicked.connect(self.replace_all)

        grid = QGridLayout(self)
        grid.setContentsMargins(0, 2, 0, 0)
        grid.setSpacing(3)
        grid.addWidget(self._find_edit, 0, 0)
        grid.addWidget(self._case_btn, 0, 1)
        grid.addWidget(self._words_btn, 0, 2)
        grid.addWidget(prev_btn, 0, 3)
        grid.addWidget(next_btn, 0, 4)
        grid.addWidget(self._count, 0, 5)
        grid.addWidget(close_btn, 0, 6)
        grid.addWidget(self._replace_edit, 1, 0)
        grid.addWidget(self._replace_btn, 1, 1, 1, 2)
        grid.addWidget(self._replace_all_btn, 1, 3, 1, 2)
        grid.setColumnStretch(0, 1)

        self._replace_widgets = (self._replace_edit, self._replace_btn,
                                 self._replace_all_btn)
        self.hide()

    # ------------------------------------------------------------- lifecycle

    def open_bar(self, replace: bool = False) -> None:
        """Show the bar, seeding the find box from the editor's selection —
        select a name, hit Ctrl+F, and it is already searching for it."""
        for widget in self._replace_widgets:
            widget.setVisible(replace)
        selection = self._editor.textCursor().selectedText()
        # selectedText() uses U+2029 for newlines; a multi-line selection is
        # someone reaching for find *within* it, not a search for the block
        if selection and " " not in selection:
            self._find_edit.setText(selection)
        self.show()
        self._find_edit.setFocus()
        self._find_edit.selectAll()
        self._refresh()

    def close_bar(self) -> None:
        self.hide()
        self._editor.set_search_highlights([])
        self._editor.setFocus()

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key_Escape:
            self.close_bar()
            return
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            self.find_next(backwards=bool(event.modifiers() & Qt.ShiftModifier))
            return
        super().keyPressEvent(event)

    # ---------------------------------------------------------------- search

    def _flags(self) -> QTextDocument.FindFlag:
        flags = QTextDocument.FindFlag(0)
        if self._case_btn.isChecked():
            flags |= QTextDocument.FindCaseSensitively
        if self._words_btn.isChecked():
            flags |= QTextDocument.FindWholeWords
        return flags

    def _on_find_text_changed(self, _text: str) -> None:
        # incremental: search from the *start* of the current match, so typing
        # another character extends the hit under the cursor rather than
        # skipping past it to the next one
        cursor = self._editor.textCursor()
        cursor.setPosition(cursor.selectionStart())
        self._jump(cursor)

    def find_next(self, backwards: bool = False) -> bool:
        """Move to the next (or previous) match, wrapping around the end.
        Returns False when the needle isn't in the document at all."""
        return self._jump(self._editor.textCursor(), backwards)

    def _jump(self, start: QTextCursor, backwards: bool = False) -> bool:
        needle = self._find_edit.text()
        if not needle:
            self._refresh()
            return False
        doc = self._editor.document()
        flags = self._flags()
        if backwards:
            flags |= QTextDocument.FindBackward
        found = doc.find(needle, start, flags)
        if found.isNull():
            # wrap: restart from the far end of the document
            restart = QTextCursor(doc)
            if backwards:
                restart.movePosition(QTextCursor.End)
            found = doc.find(needle, restart, flags)
        if not found.isNull():
            self._editor.setTextCursor(found)
        self._refresh()
        return not found.isNull()

    def _all_matches(self, limit: int = MAX_HIGHLIGHTS) -> list[QTextCursor]:
        needle = self._find_edit.text()
        if not needle:
            return []
        doc = self._editor.document()
        flags = self._flags()
        hits: list[QTextCursor] = []
        cursor = QTextCursor(doc)
        while limit <= 0 or len(hits) < limit:
            cursor = doc.find(needle, cursor, flags)
            if cursor.isNull():
                break
            hits.append(QTextCursor(cursor))
        return hits

    def _refresh(self) -> None:
        """Re-scan and repaint the highlights, and update the "n of m" count."""
        hits = self._all_matches()
        current_pos = self._editor.textCursor().selectionStart()
        current_end = self._editor.textCursor().selectionEnd()
        index = -1
        for i, hit in enumerate(hits):
            if hit.selectionStart() == current_pos \
                    and hit.selectionEnd() == current_end:
                index = i
                break
        self._editor.set_search_highlights(
            [(hit, i == index) for i, hit in enumerate(hits)])

        if not self._find_edit.text():
            self._count.setText("")
        elif not hits:
            self._count.setText("no matches")
        elif index < 0:
            self._count.setText(f"{len(hits)} matches")
        else:
            self._count.setText(f"{index + 1} of {len(hits)}")
        self._find_edit.setStyleSheet(
            "" if hits or not self._find_edit.text() else "color: #ef4444;")

    # --------------------------------------------------------------- replace

    def replace_current(self) -> None:
        """Replace the selection when it is itself a match, then advance —
        so repeated clicks walk the file. When the cursor isn't sitting on a
        match yet, this just finds the first one."""
        needle = self._find_edit.text()
        if not needle:
            return
        cursor = self._editor.textCursor()
        selected = cursor.selectedText()
        matches = (selected == needle if self._case_btn.isChecked()
                   else selected.lower() == needle.lower())
        if matches:
            cursor.insertText(self._replace_edit.text())
            self._editor.setTextCursor(cursor)
        self.find_next()

    def replace_all(self) -> None:
        """Every match in one undo step — Ctrl+Z should not have to walk back
        through a hundred individual replacements."""
        needle = self._find_edit.text()
        if not needle:
            return
        replacement = self._replace_edit.text()
        # uncapped, unlike the highlight scan: "All" has to mean all
        hits = self._all_matches(limit=0)
        if not hits:
            self._refresh()
            return
        editing = self._editor.textCursor()
        editing.beginEditBlock()
        # back to front: replacing shifts every position after the hit, and
        # working backwards leaves the not-yet-used ones untouched
        for hit in reversed(hits):
            hit.insertText(replacement)
        editing.endEditBlock()
        self._count.setText(f"replaced {len(hits)}")
        self._editor.set_search_highlights([])
