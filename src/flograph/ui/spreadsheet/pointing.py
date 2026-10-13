"""Click a cell while typing a formula to type its reference — Excel's
Point mode. What counts as a place a reference can go, and the text put
in, are core/sheet/pointref.py's; this is the gesture.

The awkward part is focus. Qt hands focus to the grid on a click *before*
any event filter sees the click, and the delegate closes an editor that
loses focus — so by the time the click arrived the edit was already
over. So the delegate asks :meth:`RefPointer.hold` first: while the
formula is at a point a reference can go, the editor's focus-out is held
back; the click that follows on a cell types the reference and gives the
editor its focus back. If no such click follows (the click was on a
header, or past the last cell), the held edit is finished on the next
turn of the event loop exactly as Qt would have finished it.

Like the fill handle, it listens on the grid's own viewport and each
frozen pane's, never on the application.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QEvent, QObject, Qt, QTimer
from PySide6.QtWidgets import QAbstractItemDelegate, QApplication

from flograph.core.sheet.pointref import point_span, put, range_text


def _alive(widget) -> bool:
    import shiboken6
    return widget is not None and shiboken6.isValid(widget)


class RefPointer(QObject):
    """Point mode on one SpreadsheetView (and its frozen panes)."""

    def __init__(self, view) -> None:
        super().__init__(view)
        self._view = view
        self._watched: list = []
        self._editor = None          # the editor the last reference went in
        self._span: Optional[tuple[int, int]] = None   # where it sits
        self._text = ""              # the editor's text just after it went in
        self._anchor: Optional[tuple[int, int]] = None
        self._table = None           # the view or pane a drag is on
        self._held = None            # an editor whose focus-out is held
        self.watch(view.viewport())

    def watch(self, viewport) -> None:
        """Take clicks on `viewport` too — a frozen pane's."""
        if viewport in self._watched:
            return
        self._watched.append(viewport)
        viewport.installEventFilter(self)
        viewport.destroyed.connect(
            lambda _=None, v=viewport: self._watched.remove(v)
            if v in self._watched else None)

    # ------------------------------------------------------------ state

    def _target(self, editor) -> Optional[tuple[int, int]]:
        """Where a click would put a reference in `editor`, or None."""
        if not _alive(editor) or not editor.isVisible() \
                or not hasattr(editor, "cursorPosition"):
            return None
        text = editor.text()
        cursor = editor.cursorPosition()
        start = editor.selectionStart()
        if (editor is self._editor and self._span is not None
                and text == self._text and start < 0
                and cursor == self._span[1]):
            return self._span        # a second click replaces the first
        if start >= 0:
            return point_span(text, start, editor.selectionEnd())
        return point_span(text, cursor)

    def _open_editor(self):
        from .delegates import CellEdit, SheetDelegate
        editor = SheetDelegate.last_editor
        if (isinstance(editor, CellEdit) and _alive(editor)
                and editor.isVisible() and editor.grid is self._view):
            return editor
        return None

    @property
    def pointed(self) -> Optional[tuple[int, int, int, int]]:
        """The cells the reference just typed covers, for the overlay."""
        if self._anchor is None or self._editor is None:
            return None
        return self._box

    def reset(self, *_args) -> None:
        """Forget the last reference — the edit ended, or moved on."""
        had = self._anchor is not None
        self._editor = None
        self._span = None
        self._text = ""
        self._anchor = None
        self._box = None
        self._table = None
        if had:
            self._repaint()

    def _repaint(self) -> None:
        fill = getattr(self._view, "_fill", None)
        if fill is not None:
            fill.refresh()

    # ------------------------------------------------------------ focus

    def hold(self, editor) -> bool:
        """Called by the delegate as `editor` loses focus to a click: keep
        the edit open if the click may be pointing at a cell."""
        if QApplication.focusWidget() is not self._view:
            return False
        if self._target(editor) is None:
            return False
        self._held = editor
        QTimer.singleShot(0, self, self._let_go)
        return True

    def _let_go(self) -> None:
        """No cell took the held click: end the edit the way the focus-out
        would have — commit what was typed, close the editor."""
        editor, self._held = self._held, None
        if not _alive(editor) or editor.hasFocus() or not editor.isVisible():
            return
        table = editor.parentWidget().parentWidget() \
            if editor.parentWidget() is not None else None
        delegate = table.itemDelegate() if table is not None else None
        if delegate is None:
            return
        delegate.commitData.emit(editor)
        delegate.closeEditor.emit(editor, QAbstractItemDelegate.NoHint)

    # ----------------------------------------------------------- events

    def eventFilter(self, watched, event) -> bool:
        kind = event.type()
        if kind in (QEvent.MouseButtonPress, QEvent.MouseButtonDblClick):
            return self._press(watched, event)
        if kind == QEvent.MouseMove and self._table is not None:
            if event.buttons() & Qt.LeftButton:
                self._drag(event)
            return True
        if kind == QEvent.MouseButtonRelease and self._table is not None:
            self._table = None
            return True
        return False

    def _press(self, watched, event) -> bool:
        if event.button() != Qt.LeftButton:
            return False
        editor = self._open_editor()
        if editor is None or not (editor is self._held or editor.hasFocus()):
            return False
        span = self._target(editor)
        table = watched.parentWidget()
        index = table.indexAt(event.position().toPoint()) \
            if span is not None and table is not None else None
        if index is None or not index.isValid():
            return False
        cell = (index.row(), index.column())
        extend = (bool(event.modifiers() & Qt.ShiftModifier)
                  and editor is self._editor and self._anchor is not None
                  and span == self._span)
        if not extend:
            self._anchor = cell
        self._held = None
        self._table = table
        self._write(editor, span, self._anchor, cell)
        editor.setFocus(Qt.MouseFocusReason)
        event.accept()
        return True

    def _drag(self, event) -> None:
        editor = self._editor
        if not _alive(editor) or self._span is None or self._anchor is None:
            return
        index = self._table.indexAt(event.position().toPoint())
        if not index.isValid():
            return
        cell = (index.row(), index.column())
        if self._box != _box(self._anchor, cell):
            self._write(editor, self._span, self._anchor, cell)

    def _write(self, editor, span, a, b) -> None:
        text, self._span = put(editor.text(), span, range_text(a, b))
        if editor is not self._editor:
            editor.textChanged.connect(self._edited)
            editor.destroyed.connect(self.reset)
        self._editor = editor
        self._text = text
        self._box = _box(a, b)
        editor.setText(text)        # quietly: no function list pops up
        editor.setCursorPosition(self._span[1])
        self._repaint()

    def _edited(self) -> None:
        """Typed over: the outline goes, the next click adds rather than
        replaces."""
        editor = self._editor
        if _alive(editor) and editor.text() != self._text:
            self._span = None
            if self._anchor is not None:
                self._anchor = None
                self._repaint()

    _box: Optional[tuple[int, int, int, int]] = None


def _box(a, b) -> tuple[int, int, int, int]:
    return (min(a[0], b[0]), min(a[1], b[1]),
            max(a[0], b[0]), max(a[1], b[1]))
