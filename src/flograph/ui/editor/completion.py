"""jedi-powered completion and calltips.

jedi's first call can take a second — everything runs on a dedicated worker
thread, requests are debounced and tagged with ids so stale replies are
dropped, and the worker is warmed with a dummy request at startup.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import (
    QEvent, QObject, QStringListModel, Qt, QThread, QTimer, Signal, Slot,
)
from PySide6.QtWidgets import QCompleter, QToolTip

from .code_editor import CodeEditor

DEBOUNCE_MS = 200
MAX_COMPLETIONS = 50


class JediWorker(QObject):
    completions_ready = Signal(int, object)  # request_id, [(name, suffix)]
    signatures_ready = Signal(int, str)      # request_id, text

    @Slot(int, str, int, int)
    def complete(self, request_id: int, source: str, line: int, col: int) -> None:
        payload: list[tuple[str, str]] = []
        try:
            import jedi
            completions = jedi.Script(source).complete(line, col)
            payload = [(c.name, c.complete or "") for c in
                       completions[:MAX_COMPLETIONS]]
        except Exception:
            pass
        try:
            self.completions_ready.emit(request_id, payload)
        except RuntimeError:
            pass  # editor torn down while jedi was busy

    @Slot(int, str, int, int)
    def signatures(self, request_id: int, source: str, line: int, col: int) -> None:
        text = ""
        try:
            import jedi
            sigs = jedi.Script(source).get_signatures(line, col)
            if sigs:
                text = sigs[0].to_string()
        except Exception:
            pass
        try:
            self.signatures_ready.emit(request_id, text)
        except RuntimeError:
            pass  # editor torn down while jedi was busy


class CompletionController(QObject):
    """Wires a CodeEditor to the jedi worker: debounced completion popup and
    an open-paren calltip."""

    _request_completions = Signal(int, str, int, int)
    _request_signatures = Signal(int, str, int, int)

    def __init__(self, editor: CodeEditor) -> None:
        super().__init__(editor)
        self._editor = editor
        self._request_id = 0
        self._suffixes: dict[str, str] = {}

        self._thread = QThread(self)
        self._worker = JediWorker()
        self._worker.moveToThread(self._thread)
        self._request_completions.connect(self._worker.complete)
        self._request_signatures.connect(self._worker.signatures)
        self._worker.completions_ready.connect(self._on_completions)
        self._worker.signatures_ready.connect(self._on_signatures)
        self._thread.start()

        self._completer = QCompleter([], editor)
        self._completer.setWidget(editor)
        self._completer.setCompletionMode(QCompleter.PopupCompletion)
        self._completer.setCaseSensitivity(Qt.CaseInsensitive)
        self._completer.activated.connect(self._insert)
        # Enter/Tab must accept the highlighted suggestion. QCompleter
        # forwards popup keys to the editor first, and CodeEditor handles
        # Return (auto-indent) and Tab (indent) itself — accepting the
        # event, which made QCompleter just hide the popup instead of
        # completing. Filtering the popup directly (installed after
        # QCompleter's own filter, so it runs first) sidesteps that.
        self._completer.popup().installEventFilter(self)

        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(DEBOUNCE_MS)
        self._debounce.timeout.connect(self._fire_request)
        editor.textChanged.connect(self._on_text_changed)

        # warm up jedi lazily, on the editor's first focus: an eager warm-up
        # keeps the worker busy for ~1s in every fresh window, and a busy
        # worker can't process quit() — teardown then destroys a running
        # QThread, which is fatal
        self._warmed = False
        editor.installEventFilter(self)

        # stop the worker thread before Qt tears down the object tree
        editor.destroyed.connect(self.shutdown)

    def eventFilter(self, obj, event) -> bool:
        if (not self._warmed and obj is self._editor
                and event.type() == QEvent.FocusIn):
            self._warmed = True
            # so the first real completion is snappy
            self._request_completions.emit(-1, "import os\nos.", 2, 3)
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

    def shutdown(self) -> None:
        if self._thread.isRunning():
            self._thread.quit()
            # no timeout: quit() is queued behind any in-flight jedi call,
            # and abandoning a running QThread aborts the process
            self._thread.wait()

    # ------------------------------------------------------------- requests

    def _cursor_location(self) -> tuple[str, int, int]:
        cursor = self._editor.textCursor()
        return (self._editor.toPlainText(),
                cursor.blockNumber() + 1, cursor.positionInBlock())

    def _current_prefix(self) -> str:
        cursor = self._editor.textCursor()
        text = cursor.block().text()[:cursor.positionInBlock()]
        i = len(text)
        while i > 0 and (text[i - 1].isalnum() or text[i - 1] == "_"):
            i -= 1
        return text[i:]

    def _on_text_changed(self) -> None:
        source, line, col = self._cursor_location()
        before = self._editor.textCursor().block().text(
            )[:self._editor.textCursor().positionInBlock()]
        if before.endswith("("):
            self._request_id += 1
            self._request_signatures.emit(self._request_id, source, line, col)
            self._completer.popup().hide()
            return
        prefix = self._current_prefix()
        if prefix or before.endswith("."):
            self._debounce.start()
        else:
            self._completer.popup().hide()

    def _fire_request(self) -> None:
        self._request_id += 1
        source, line, col = self._cursor_location()
        self._request_completions.emit(self._request_id, source, line, col)

    # -------------------------------------------------------------- replies

    def _on_completions(self, request_id: int, payload: list) -> None:
        if request_id != self._request_id or not payload:
            self._completer.popup().hide()
            return
        if not self._editor.hasFocus():
            return
        self._suffixes = dict(payload)
        self._completer.setModel(QStringListModel([name for name, _ in payload]))
        self._completer.setCompletionPrefix(self._current_prefix())
        if self._completer.completionCount() == 0:
            self._completer.popup().hide()
            return
        rect = self._editor.cursorRect()
        rect.setWidth(self._completer.popup().sizeHintForColumn(0)
                      + self._completer.popup().verticalScrollBar().sizeHint().width())
        self._completer.complete(rect)
        # highlight the first suggestion so a bare Enter/Tab accepts it
        self._completer.popup().setCurrentIndex(
            self._completer.completionModel().index(0, 0))

    def _on_signatures(self, request_id: int, text: str) -> None:
        if text and self._editor.hasFocus():
            pos = self._editor.viewport().mapToGlobal(
                self._editor.cursorRect().bottomRight())
            QToolTip.showText(pos, text, self._editor)

    def _insert(self, name: str) -> None:
        suffix = self._suffixes.get(name)
        cursor = self._editor.textCursor()
        if suffix is None:
            prefix = self._current_prefix()
            suffix = name[len(prefix):] if name.startswith(prefix) else name
        cursor.insertText(suffix)
        self._editor.setTextCursor(cursor)
