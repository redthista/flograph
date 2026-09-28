"""Laying a report preview out in the background.

A report page re-renders as it is written, and with a big table on it the
render was most of a second of rich-text layout on the UI thread — every
pause in typing froze the editor, and the keys typed meanwhile arrived in a
burst afterwards. The embeds still resolve on the UI thread (a chart waits
on Chromium, a web card prints); only `render.finish_body` and the
pagination after it come here, which is the part that grows with the data.

**A thread of its own for every layout, kept until its document is gone.**
A laid-out document holds on to the fonts of the thread that laid it out —
Qt keeps font engines, and the FreeType faces under them, per thread — and
when that thread ends they are freed, whoever is still drawing with them.
A pooled thread retiring after a quiet half-minute took the preview on
screen down with it. So each job's thread lays out its one document, then
parks (blocked, costing nothing) until that document is destroyed, and only
then ends. No two layouts share a thread's fonts, and no document outlives
the thread whose fonts it uses.

The threads are daemons: a process quitting with a preview still on screen
leaves them parked rather than tearing their fonts down under a document
that is itself about to be torn down.
"""
from __future__ import annotations

import threading
from typing import Callable, Optional

from PySide6.QtCore import QCoreApplication, QObject, Qt, Signal, Slot

#: jobs whose thread is still alive — parked or working. Pinned here so a
#: job cannot be collected (on whichever thread Python's collector happens
#: to run) while its thread still needs it.
_LIVE: "dict[int, LayoutJob]" = {}
_DISPATCHER: "Optional[_Dispatcher]" = None


class _Dispatcher(QObject):
    """Made once, on the UI thread, so a queued slot on it runs there — a
    lambda or a bare function connected to a worker's signal would run on
    the worker instead."""
    delivered = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self.delivered.connect(self._deliver, Qt.QueuedConnection)

    @Slot(object)
    def _deliver(self, job: "LayoutJob") -> None:
        on_done, job.on_done = job.on_done, None
        if on_done is not None:
            on_done(job)


def _dispatcher() -> _Dispatcher:
    global _DISPATCHER
    if _DISPATCHER is None:
        _DISPATCHER = _Dispatcher()
    return _DISPATCHER


class LayoutJob:
    """Finish a staged report, and paginate it or write it out as HTML.

    `work(staged)` runs on the job's own thread and returns what the page
    wants handed back — it must leave any QObject it made owned by the UI
    thread (`adopt`). `on_done(job)` runs on the UI thread afterwards, with
    `result` set, or `error` if `work` raised.

    The thread then waits. Whoever takes the result says what it has to
    outlive — `keep_for(document)` — or that it has nothing to outlive —
    `release()`.
    """

    def __init__(self, generation: int, staged, work: Callable,
                 on_done: Callable) -> None:
        self.generation = generation
        self.staged = staged
        self.work = work
        self.on_done = on_done
        self.result = None
        self.error: Optional[BaseException] = None
        self._release = threading.Event()
        self._thread = threading.Thread(
            target=self._run, name="flograph-report-layout", daemon=True)

    def start(self) -> None:
        _dispatcher()                   # made here, on the UI thread
        _LIVE[id(self)] = self
        self._thread.start()

    def _run(self) -> None:
        from PySide6.QtCore import QEventLoop

        # Never run, only made: making one gives this thread the event
        # dispatcher a plain Python thread lacks, and without it every
        # timer the layout starts is a console warning.
        loop = QEventLoop()
        try:
            self.result = self.work(self.staged)
        except BaseException as exc:    # never let it take the thread down
            self.error = exc
        # the resolver holds the flow's outputs; nothing needs them now
        self.staged = None
        try:
            _dispatcher().delivered.emit(self)
        except RuntimeError:
            # The app closed while this worked, and the dispatcher with it:
            # there is no one to hand the result to, or to draw it.
            self.result = None
            self._release.set()
        self._release.wait()
        del loop                        # on the thread that made it
        _LIVE.pop(id(self), None)

    def release(self, *_args) -> None:
        """Let the thread end. Safe from any thread, and more than once."""
        self.result = None
        self._release.set()

    def keep_for(self, document) -> None:
        """Keep the thread — and its fonts — until `document` is destroyed.
        Destroyed, not merely replaced: the QTextDocument part is gone by
        the time QObject announces it, so nothing is left to draw with
        them."""
        if document is None:
            self.release()
            return
        document.destroyed.connect(self.release)


def adopt(document) -> None:
    """Hand a document made on this thread to the UI thread, which is the
    one that will show it, paint it and eventually delete it."""
    app = QCoreApplication.instance()
    if document is not None and app is not None:
        document.moveToThread(app.thread())


def wait_idle(timeout: float = 30.0) -> bool:
    """Block until no layout is still working — parked ones do not count.
    For tests."""
    import time
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not any(job.on_done is not None and job.result is None
                   and job.error is None for job in list(_LIVE.values())):
            return True
        time.sleep(0.005)
    return False
