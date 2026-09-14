"""Completion from a known vocabulary: a text box's keywords and the columns
arriving at its node.

The node script editor completes Python through jedi (completion.py). The
boxes in Properties aren't Python, so this offers the words their own
language has — as you type, or everything on Ctrl+Space. A column goes in
spelled the way that box needs it (backticks, quotes or bare); a column
started inside an opening backtick or quote is finished and closed.

Used by the pop-out editor and by the multiline boxes in Properties
themselves. `columns` may be a function: a box in Properties outlives the
runs that change what arrives at its node, so it asks each time it opens.
"""
from __future__ import annotations

from typing import Callable, Iterable, Optional, Union

from PySide6.QtCore import QEvent, QObject, QStringListModel, Qt, QTimer
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QCompleter, QPlainTextEdit

_QUOTES = ("`", '"', "'")

#: the list is as wide as its longest word, up to this
MAX_POPUP_WIDTH = 520

Columns = Union[Iterable[str], Callable[[], Iterable[str]]]


class WordCompleter(QObject):
    def __init__(self, editor: QPlainTextEdit, keywords: Iterable[str] = (),
                 columns: Columns = (),
                 quote: Optional[Callable[[str], str]] = None) -> None:
        super().__init__(editor)
        self._editor = editor
        self._keywords = tuple(dict.fromkeys(keywords))
        self._columns: tuple = ()
        self._columns_source = columns if callable(columns) else None
        self._quote = quote or (lambda name: name)
        self._completer = QCompleter([], editor)
        self._completer.setWidget(editor)
        self._completer.setCompletionMode(QCompleter.PopupCompletion)
        self._completer.setCaseSensitivity(Qt.CaseInsensitive)
        self._completer.setModelSorting(QCompleter.UnsortedModel)
        self._completer.activated.connect(self._insert)
        # Enter/Tab accept, the way completion.py's popup does — CodeEditor
        # takes Return and Tab itself otherwise
        self._completer.popup().installEventFilter(self)
        editor.installEventFilter(self)
        # The text changing is what refreshes the list, not a key press seen
        # by the filter above. While the list is open the keys go to the
        # popup, and QCompleter hands them on with a direct event() call
        # that no filter on the editor sees — so a list opened on one letter
        # never narrowed and never closed, and kept the keyboard after the
        # box had been left.
        editor.document().contentsChange.connect(self._on_contents_change)
        self._inserting = False
        #: where the open list was put: the start of the word it completes
        self._anchor: Optional[tuple] = None
        self._width_for: tuple = ()
        self._width = 0
        self.set_columns(() if self._columns_source else columns)

    @property
    def popup(self):
        return self._completer.popup()

    def words(self) -> list[str]:
        return list(self._columns) + [k for k in self._keywords
                                      if k not in self._columns]

    def set_columns(self, columns: Iterable[str]) -> None:
        self._columns = tuple(dict.fromkeys(str(c) for c in columns))
        self._completer.setModel(QStringListModel(self.words(), self._completer))

    def _refresh_columns(self) -> None:
        if self._columns_source is None:
            return
        try:
            fresh = tuple(dict.fromkeys(str(c) for c in self._columns_source()))
        except Exception:   # completion is a nicety; never break typing
            return
        if fresh != self._columns:
            self.set_columns(fresh)

    # ------------------------------------------------------------- events

    def eventFilter(self, obj, event) -> bool:
        if obj is self._editor and event.type() == QEvent.KeyPress:
            if event.key() == Qt.Key_Space and event.modifiers() & Qt.ControlModifier:
                self.show(force=True)
                return True
        popup = self.popup
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

    def _on_contents_change(self, _position: int, removed: int,
                            added: int) -> None:
        # a load or an undo from the model changes the text with nobody
        # typing, and a word going in from the list is not a word being typed
        if self._inserting or not self._editor.hasFocus():
            return
        # one character typed may open the list; once it is open, any change
        # (another letter, a backspace, a space) refreshes or closes it
        if (added == 1 and not removed) or self.popup.isVisible():
            # after the editor has finished with the edit, so the caret has
            # moved past it
            QTimer.singleShot(0, self, self.show)

    # ------------------------------------------------------------ showing

    def prefix(self) -> str:
        """The word being typed: letters, digits, `_` and `@`, back from the
        caret. An `@` only counts if some word starts with one (`@rows`) —
        otherwise it is Conditional Column's `@column` and the column after
        it is what's being typed."""
        cursor = self._editor.textCursor()
        before = cursor.block().text()[:cursor.positionInBlock()]
        i = len(before)
        while i > 0 and (before[i - 1].isalnum() or before[i - 1] in "_@"):
            i -= 1
        word = before[i:]
        if word.startswith("@") and not any(
                w.lower().startswith(word.lower()) for w in self.words()):
            word = word.lstrip("@")
        return word

    def show(self, force: bool = False) -> None:
        carets = getattr(self._editor, "carets", None)
        if carets is not None and carets.active:
            self.popup.hide()
            return
        if self._editor.isReadOnly():
            return
        prefix = self.prefix()
        if not prefix and not force:
            self.popup.hide()
            return
        self._refresh_columns()
        self._completer.setCompletionPrefix(prefix)
        count = self._completer.completionCount()
        if count == 0 or (count == 1 and not force
                          and self._completer.currentCompletion() == prefix):
            self.popup.hide()
            return
        self._place(prefix)
        self.popup.setCurrentIndex(self._completer.completionModel().index(0, 0))

    def _place(self, prefix: str) -> None:
        """Open the list under the start of the word — or, when it is open
        there already, leave it be.

        Following the caret moved the list on every letter, and moving an
        open popup is not free: on Wayland one cannot be moved at all, only
        closed and opened again where it should be. The prefix filter has
        already changed what the list holds."""
        cursor = self._editor.textCursor()
        cursor.setPosition(cursor.position() - len(prefix))
        rect = self._editor.cursorRect(cursor)
        anchor = (rect.left(), rect.top())
        if self.popup.isVisible() and anchor == self._anchor:
            return
        self._anchor = anchor
        rect.setWidth(self._popup_width())
        self._completer.complete(rect)

    def _popup_width(self) -> int:
        """Wide enough for the longest word the box can offer. Worked out
        once per vocabulary rather than from what the prefix left, so the
        list does not change size as the word is typed."""
        words = tuple(self.words())
        if words != self._width_for:
            metrics = self.popup.fontMetrics()
            longest = max((metrics.horizontalAdvance(w) for w in words),
                          default=0)
            self._width_for = words
            self._width = min(MAX_POPUP_WIDTH, longest + 24
                              + self.popup.verticalScrollBar().sizeHint().width())
        return self._width

    def _insert(self, word: str) -> None:
        prefix = self.prefix()
        cursor = self._editor.textCursor()
        cursor.movePosition(QTextCursor.Left, QTextCursor.KeepAnchor, len(prefix))
        block_text = cursor.block().text()
        start = cursor.selectionStart() - cursor.block().position()
        opener = block_text[start - 1:start] if start else ""
        opener = opener if opener in _QUOTES else ""
        is_column = word in self._columns and word not in self._keywords
        form = word if (opener or not is_column) else self._quote(word)
        self._inserting = True
        try:
            cursor.insertText(form)
            if opener and is_column:
                after = cursor.block().text()[cursor.positionInBlock():][:1]
                if after != opener:
                    cursor.insertText(opener)
        finally:
            self._inserting = False
        self._editor.setTextCursor(cursor)
        self.popup.hide()
