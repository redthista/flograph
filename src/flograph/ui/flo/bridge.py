"""Run a Flo Assistant turn off the GUI thread, and its tools on it.

The wait for the server is the slow part and must not freeze the window,
so `Conversation.send()` runs on a plain daemon thread (a daemon, so a
server that never answers cannot hold the app open at exit). Everything it
does to the flow comes back here: `UiCall` posts the function to the GUI
thread and blocks the worker until it has run, because undo commands and
graph events are GUI-thread business.

`close()` retires the bridge — on New/Open, a profile switch or a new
chat. A worker still waiting on the server finds every later call refused
(`Retired`), so a stale turn can never write into the next flow.
"""
from __future__ import annotations

import threading
from typing import Any, Callable

from PySide6.QtCore import QObject, QThread, Qt, Signal


class Retired(RuntimeError):
    """The conversation this worker belonged to has been closed."""


class _Job:
    def __init__(self, fn: Callable[[], Any]) -> None:
        self.fn = fn
        self.done = threading.Event()
        self.result: Any = None
        self.error: BaseException | None = None


class TurnBridge(QObject):
    """One per conversation. Signals arrive on the GUI thread."""
    event = Signal(object)        # agent.Event
    finished = Signal(object)     # agent.TurnResult, or None when retired
    failed = Signal(str)          # an unexpected exception in the worker
    _post = Signal(object)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.closed = False
        self._post.connect(self._run_job, Qt.QueuedConnection)

    # -- the GUI-thread half --------------------------------------------------------

    def _run_job(self, job: _Job) -> None:
        if self.closed:
            job.error = Retired()
        else:
            try:
                job.result = job.fn()
            except BaseException as exc:      # handed back to the worker
                job.error = exc
        job.done.set()

    def close(self) -> None:
        self.closed = True

    # -- the worker half ---------------------------------------------------------------

    def on_ui(self, fn: Callable[[], Any]) -> Any:
        """Run `fn` on the GUI thread and return what it returned."""
        if QThread.currentThread() is self.thread():
            return fn()
        if self.closed:
            raise Retired()
        job = _Job(fn)
        self._post.emit(job)
        while not job.done.wait(0.25):
            if self.closed:
                raise Retired()
        if job.error is not None:
            raise job.error
        return job.result

    def start(self, work: Callable[[], Any]) -> threading.Thread:
        def run() -> None:
            try:
                result = work()
            except Retired:
                result = None
            except Exception as exc:  # noqa: BLE001 — shown in the chat
                if not self.closed:
                    self.failed.emit(f"{type(exc).__name__}: {exc}")
                return
            if not self.closed:
                self.finished.emit(result)

        thread = threading.Thread(target=run, name="flo-turn", daemon=True)
        thread.start()
        return thread
