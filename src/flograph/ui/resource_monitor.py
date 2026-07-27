"""Status bar resource monitor: how much of the machine this flow is using.

Three numbers used to sit here as three pieces of text — system memory, the
project's cached outputs, the selected node's. Text is the wrong shape for
the question actually being asked, which is not "how many bytes" but "how
heavy is this, and how much of it is me". So the memory readout is a single
layered bar: the whole machine is the track, the flograph process is a
segment inside it, and the project's cached outputs are a brighter segment
inside that. Proportion is the whole point, and proportion is what a bar
shows and a number does not.

Beside it, what the last run cost and what the selected node cost. Clicking
anywhere opens the full stats window (ui.stats_window), which is where the
per-node detail lives — the status bar's job is to be glanceable and to say
when it is worth looking closer.
"""
from __future__ import annotations

from typing import Optional

import psutil
from PySide6.QtCore import QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget

from flograph.engine import ExecutionEngine
from flograph.engine.runstats import ProcessSampler

from . import theme

REFRESH_MS = 2000
BAR_W, BAR_H = 108, 9
_LABEL_STYLE = "color: #9ca3af; font-size: 8pt; padding: 0 4px;"


def format_bytes(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if abs(n) < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"


def format_seconds(s: float) -> str:
    if s < 1:
        return f"{s * 1000:.0f} ms"
    if s < 60:
        return f"{s:.1f} s"
    return f"{int(s // 60)}m {s % 60:.0f}s"


class MemoryBar(QWidget):
    """The layered bar: cached outputs, the rest of the app, the rest of the
    machine, and what is still free.

    Segments are drawn in that order from the left, brightest first, so the
    part you control sits at the origin and grows towards the part you do
    not. Cached bytes are clamped to the process size before drawing:
    `estimate_size` measures a value's own footprint, which is not the same
    thing as its contribution to resident memory, and a bar whose inner
    segment overflows its outer one would be worse than no bar.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedSize(BAR_W, BAR_H)
        self.cache_bytes = 0
        self.process_bytes = 0
        self.used_bytes = 0
        self.total_bytes = 1

    def set_values(self, cache: int, process: int, used: int, total: int) -> None:
        self.cache_bytes = max(0, cache)
        self.process_bytes = max(0, process)
        self.used_bytes = max(0, used)
        self.total_bytes = max(1, total)
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)

        rect = QRectF(0, 0, self.width(), self.height())
        radius = self.height() / 2
        painter.setBrush(theme.GRID_COARSE)
        painter.drawRoundedRect(rect, radius, radius)

        cache = min(self.cache_bytes, self.process_bytes)
        process = max(cache, min(self.process_bytes, self.used_bytes))
        used = max(process, self.used_bytes)

        # Cumulative, and drawn longest first so each shorter one lands on
        # top of the one behind it. Every bar starts at the left edge, which
        # is what keeps the rounded cap at the origin and leaves no seam
        # where two segments meet — only the running total's right edge ever
        # shows.
        def px(value: float) -> float:
            return self.width() * value / self.total_bytes

        painter.setClipRect(rect)
        for value, color in ((used, theme.MEM_OTHER),
                             (process, theme.MEM_APP),
                             (cache, theme.MEM_CACHE)):
            width = px(value)
            if width <= 0:
                continue
            painter.setBrush(QColor(color))
            painter.drawRoundedRect(
                QRectF(0, 0, max(width, self.height()), self.height()),
                radius, radius)
        painter.end()


class ResourceMonitorWidget(QWidget):
    """Permanent status bar widget: the memory bar, the last run's cost, and
    the selected node's."""

    clicked = Signal()

    def __init__(self, engine: ExecutionEngine, parent=None) -> None:
        super().__init__(parent)
        self._engine = engine
        self._node_id: Optional[str] = None
        self._sampler = ProcessSampler()

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 8, 0)
        layout.setSpacing(4)

        self.bar = MemoryBar(self)
        self._mem_label = QLabel()
        self._run_label = QLabel()
        self._node_label = QLabel()
        for label in (self._mem_label, self._run_label, self._node_label):
            label.setStyleSheet(_LABEL_STYLE)
        layout.addWidget(self.bar)
        layout.addWidget(self._mem_label)
        layout.addWidget(self._run_label)
        layout.addWidget(self._node_label)

        self.setCursor(Qt.PointingHandCursor)
        engine.run_recorded.connect(lambda *_: self._refresh())

        self._timer = QTimer(self)
        self._timer.setInterval(REFRESH_MS)
        self._timer.timeout.connect(self._refresh)
        self._timer.start()
        self._refresh()

    def set_node(self, node_id: Optional[str]) -> None:
        self._node_id = node_id
        self._refresh()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)

    # ------------------------------------------------------------- contents

    def _refresh(self) -> None:
        vm = psutil.virtual_memory()
        cache = self._engine.cache.total_bytes()
        process = self._sampler.rss()
        self.bar.set_values(cache, process, vm.used, vm.total)
        self._mem_label.setText(
            f"{format_bytes(vm.used)} / {format_bytes(vm.total)}")

        cached_nodes = sum(
            1 for nid in self._engine.graph.nodes if self._engine.cache.has(nid))
        self.setToolTip(
            f"Cached outputs\t{format_bytes(cache)}  ({cached_nodes} nodes)\n"
            f"flograph process\t{format_bytes(process)}\n"
            f"System\t\t{format_bytes(vm.used)} / {format_bytes(vm.total)}"
            f"  ({vm.percent:.0f}%)\n\nClick for full statistics")

        self._run_label.setText(self._run_text())
        self._node_label.setText(self._node_text())

    def _run_text(self) -> str:
        record = self._engine.history.latest
        if record is None:
            return "Run: —"
        note = "" if record.ok else " (errors)"
        return f"Run: {format_seconds(record.wall_time)}{note}"

    def _node_text(self) -> str:
        if not self._node_id:
            return "Node: —"
        entry = self._engine.cache.get(self._node_id)
        if entry is None:
            return "Node: —"
        parts = [format_bytes(entry.memory_bytes)]
        if entry.wall_time:
            parts.append(format_seconds(entry.wall_time))
        if entry.alias_of is not None:
            # otherwise the same DataFrame appears to be in memory twice over
            parts.append("shared")
        return "Node: " + " · ".join(parts)
