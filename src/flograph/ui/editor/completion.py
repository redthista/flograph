"""jedi-powered completion and calltips.

jedi's first call can take a second — everything runs on a dedicated worker
thread, requests are debounced and tagged with ids so stale replies are
dropped, and the worker is warmed with a dummy request at startup.

A jedi call can't be interrupted, so nothing on the GUI thread may wait for
one. The worker skips a request that a newer one has overtaken before it
starts, so a burst of typing costs one call rather than a queue of them; and
an editor that goes away mid-call (the code pop-out closing) hands its thread
to `_retiring` to finish in its own time instead of blocking the window on
it — closing the pop-out used to freeze the app for as long as jedi took.
"""
from __future__ import annotations

import atexit
import sys

from PySide6.QtCore import (
    QCoreApplication, QEvent, QObject, QStringListModel, Qt, QThread, QTimer,
    Signal, Slot,
)
from PySide6.QtWidgets import QCompleter, QToolTip

from .code_editor import CodeEditor

DEBOUNCE_MS = 200
MAX_COMPLETIONS = 50
#: how long a closing editor gives its worker to stop before leaving it to
#: finish alone: long enough for an idle thread, short enough not to show
RETIRE_WAIT_MS = 50

#: (thread, worker) pairs still finishing a jedi call for an editor that has
#: gone. Held here because a QThread destroyed while running aborts the
#: process; pruned whenever another one retires, and waited for at exit.
_retiring: list = []


def _prune_retiring() -> None:
    _retiring[:] = [pair for pair in _retiring if not pair[0].isFinished()]


@atexit.register
def _wait_for_retiring() -> None:
    for thread, _worker in _retiring:
        thread.wait()
    _retiring.clear()


class JediWorker(QObject):
    completions_ready = Signal(int, object)  # request_id, [(name, suffix)]
    signatures_ready = Signal(int, str)      # request_id, text

    def __init__(self) -> None:
        super().__init__()
        #: the newest request id the editor has sent, written from the GUI
        #: thread: a queued request below it has been overtaken, and is
        #: skipped rather than run for a reply nobody will read
        self.latest = -1

    @Slot(int, str, int, int)
    def complete(self, request_id: int, source: str, line: int, col: int) -> None:
        if request_id < self.latest:
            return
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
        if request_id < self.latest:
            return
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
        #: where the open list was put — see _on_completions
        self._anchor = None

        self._thread = QThread(self)
        self._worker = JediWorker()
        self._worker.moveToThread(self._thread)
        self._request_completions.connect(self._worker.complete)
        self._request_signatures.connect(self._worker.signatures)
        self._worker.completions_ready.connect(self._on_completions)
        self._worker.signatures_ready.connect(self._on_signatures)
        self._thread.start()

        self._model = QStringListModel([], self)
        self._completer = QCompleter(self._model, editor)
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
        """Stop the worker without waiting on jedi. quit() only lands once
        an in-flight call returns, which can be seconds; the thread is then
        left in `_retiring` to finish rather than waited for here. At exit
        there is no later, so it is waited for as before."""
        thread = self._thread
        if not thread.isRunning():
            return
        self._worker.latest = sys.maxsize  # anything still queued is skipped
        thread.quit()
        if (sys.is_finalizing() or QCoreApplication.instance() is None
                or QCoreApplication.closingDown()):
            # past atexit, nothing would wait for a retired thread
            thread.wait()
            return
        if thread.wait(RETIRE_WAIT_MS):
            return
        try:
            self._worker.completions_ready.disconnect(self._on_completions)
            self._worker.signatures_ready.disconnect(self._on_signatures)
        except (RuntimeError, TypeError):
            pass
        # out of this controller's tree, which is being torn down: Qt would
        # destroy the running thread with it, and that aborts the process
        thread.setParent(None)
        _prune_retiring()
        _retiring.append((thread, self._worker))

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
            self._worker.latest = self._request_id
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
        self._worker.latest = self._request_id
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
        # into the model the list already has: QCompleter.setModel hides an
        # open list, so a new model per reply closed and reopened it per key
        names = [name for name, _ in payload]
        if self._model.stringList() != names:
            self._model.setStringList(names)
        prefix = self._current_prefix()
        self._completer.setCompletionPrefix(prefix)
        popup = self._completer.popup()
        if self._completer.completionCount() == 0:
            popup.hide()
            return
        # under the start of the name rather than the caret, so an open list
        # stays put while the name is typed — moving an open popup on
        # Wayland closes it and opens it again
        at = self._editor.textCursor()
        at.setPosition(at.position() - len(prefix))
        rect = self._editor.cursorRect(at)
        anchor = (rect.left(), rect.top())
        if not (popup.isVisible() and anchor == self._anchor):
            self._anchor = anchor
            rect.setWidth(popup.sizeHintForColumn(0)
                          + popup.verticalScrollBar().sizeHint().width())
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
