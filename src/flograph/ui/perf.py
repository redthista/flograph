"""Notice when the GUI thread stops answering, and say what held it.

A timer asks to be woken every `TICK_MS`. When the GUI thread is busy the
wake-up arrives late, and how late is exactly how long the window was
frozen. The watchdog keeps the worst stall, a count of the ones worth
noticing, and — from `core.perf` — the labelled block that was running, so
"the app hung" becomes "Show Table card took 1.8 s".
"""
from __future__ import annotations

import time
from typing import Optional

from PySide6.QtCore import QObject, QTimer, Signal

from flograph.core import perf

TICK_MS = 100
# Below this a stall is a frame or two — not something anyone notices.
NOTICE_S = 0.2


class StallWatchdog(QObject):
    # seconds frozen, label of the slowest timed block in it ("" if none)
    stalled = Signal(float, str)

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        self.longest = 0.0
        self.longest_label = ""
        self.count = 0
        self._last = time.perf_counter()
        self._timer = QTimer(self)
        self._timer.setInterval(TICK_MS)
        self._timer.timeout.connect(self._tick)

    def start(self) -> None:
        self._last = time.perf_counter()
        perf.take_slowest()
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()

    def reset(self) -> None:
        self.longest = 0.0
        self.longest_label = ""
        self.count = 0
        self._last = time.perf_counter()

    def _tick(self) -> None:
        now = time.perf_counter()
        late = now - self._last - TICK_MS / 1000
        self._last = now
        slowest = perf.take_slowest()
        if late < NOTICE_S:
            return
        label = slowest[0] if slowest else ""
        self.count += 1
        if late > self.longest:
            self.longest = late
            self.longest_label = label
        self.stalled.emit(late, label)
