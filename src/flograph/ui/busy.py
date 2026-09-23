"""Say the app is working before it goes quiet to do something long.

Some work still has to happen on the GUI thread — reading a project,
laying out a report for a PDF — and while it does, the window cannot paint.
Nothing can be drawn *during* it, so the one honest thing left is to say
so *before* it starts: the wait cursor goes up and the status line names
the work, both painted before the first slow line runs. Then a pause reads
as "busy", not "hung".
"""
from __future__ import annotations

from contextlib import contextmanager

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication


@contextmanager
def busy(window, text: str = ""):
    """`with busy(window, "Exporting PDF…"):` around GUI-thread work.

    The status line is repainted synchronously rather than by pumping the
    event loop: processEvents here would let a click re-enter whatever is
    about to run."""
    QGuiApplication.setOverrideCursor(Qt.WaitCursor)
    try:
        if text and hasattr(window, "show_status"):
            window.show_status(text)
            label = getattr(window, "_status_label", None)
            if label is not None:
                label.repaint()
        yield
    finally:
        QGuiApplication.restoreOverrideCursor()
