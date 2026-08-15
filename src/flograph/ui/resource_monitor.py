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
from flograph.engine.pressure import (COMFORT_FREE, FREE_RELIEF, LOW_FREE,
                                      PRESSURE_RELIEF, SYSTEM_PRESSURE,
                                      machine_is_tight)
from flograph.engine.runstats import ProcessSampler

from . import theme

REFRESH_MS = 2000
BAR_W, BAR_H = 108, 9
_LABEL_STYLE = "color: #9ca3af; font-size: 8pt; padding: 0 4px;"
_WARN_LABEL_STYLE = "color: #eab308; font-size: 8pt; padding: 0 4px;"

# When to say the project is the reason the machine is filling up. Both have
# to hold: a machine at 90% is not this flow's fault if the flow is holding
# 200 MB, and a flow holding 12 GB on a 128 GB box is not a problem yet.
# Nothing is ever evicted on the strength of this -- the cache invariant is
# "a node is clean iff its outputs are cached", so dropping an entry behind
# the user's back marks the node dirty and it silently re-runs later. Saying
# so and leaving the choice with them is the honest half of that trade.
# "Is the machine short of memory" lives in the engine (engine.pressure) —
# the scheduler acts on the same reading, and one definition acting in two
# places beats two definitions drifting apart. Re-exported here because this
# is where the thresholds are read from and tested.
CACHE_SHARE = 0.10       # fraction of system memory held as cached outputs
# How far back below the line the *share* has to fall before the warning
# clears. Memory in use wanders by a percentage point or two from moment to
# moment, so a bare threshold flickers the bar and re-announces itself every
# couple of seconds while hovering. Warn late, stop warning later.
CACHE_RELIEF = 0.02
# The same amber as the stale-pin and unsaved-edit markers on the canvas —
# one colour meaning "worth a look, nothing is broken" across the app.
WARN_COLOR = "#eab308"


def format_bytes(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if abs(n) < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"


def memory_pressure(cache: int, used: int, total: int,
                    already_warning: bool = False,
                    available: Optional[int] = None) -> bool:
    """Is this project the reason the machine is running out?

    Both halves matter. A machine that is tight is not this flow's doing if
    the flow holds 200 MB, and a flow holding 12 GB of a 128 GB box has not
    caused a problem yet. Warning on either alone would cry wolf.

    `available` is what the OS says can still be allocated, which is the only
    figure that means the same thing on Windows, macOS and Linux — `used`
    means three different things across them (Linux already excludes
    reclaimable page cache; Windows defines used as total minus available).
    Derived from `total - used` when a caller has not measured it, which is
    the same thing on the platform this app is mostly used to build for.

    `already_warning` relaxes every line, so a reading that wanders across
    the threshold — which is what memory in use does — does not toggle the
    bar and re-announce itself every couple of seconds.
    """
    if total <= 0:
        return False
    if available is None:
        available = max(0, total - used)
    cache_line = CACHE_SHARE - (CACHE_RELIEF if already_warning else 0.0)
    return (machine_is_tight(used, total, available, already_warning)
            and cache / total >= cache_line)


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
        self.warning = False

    def set_values(self, cache: int, process: int, used: int, total: int) -> None:
        self.cache_bytes = max(0, cache)
        self.process_bytes = max(0, process)
        self.used_bytes = max(0, used)
        self.total_bytes = max(1, total)
        self.update()

    def set_warning(self, warning: bool) -> None:
        """Amber the cached-outputs segment — the part the user can act on —
        rather than the whole bar, which would read as "the machine is full"
        when the point is "and this project is why"."""
        if warning != self.warning:
            self.warning = warning
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
        cache_color = WARN_COLOR if self.warning else theme.MEM_CACHE
        for value, color in ((used, theme.MEM_OTHER),
                             (process, theme.MEM_APP),
                             (cache, cache_color)):
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
    # Emitted once when the project becomes the reason memory is tight, not
    # on every refresh — a status bar line that reappears every two seconds
    # is nagging, and nagging gets ignored.
    pressure_changed = Signal(str)

    def __init__(self, engine: ExecutionEngine, parent=None) -> None:
        super().__init__(parent)
        self._engine = engine
        self._node_id: Optional[str] = None
        self._sampler = ProcessSampler()
        self._warned = False

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
        under_pressure = memory_pressure(cache, vm.used, vm.total,
                                         already_warning=self._warned,
                                         available=vm.available)
        self.bar.set_values(cache, process, vm.used, vm.total)
        self.bar.set_warning(under_pressure)
        self._mem_label.setText(
            f"{format_bytes(vm.used)} / {format_bytes(vm.total)}")
        self._mem_label.setStyleSheet(
            _WARN_LABEL_STYLE if under_pressure else _LABEL_STYLE)

        cached_nodes = sum(
            1 for nid in self._engine.graph.nodes if self._engine.cache.has(nid))
        tip = (f"Cached outputs\t{format_bytes(cache)}  ({cached_nodes} nodes)\n"
               f"flograph process\t{format_bytes(process)}\n"
               f"System\t\t{format_bytes(vm.used)} / {format_bytes(vm.total)}"
               f"  ({vm.percent:.0f}%)")
        if under_pressure:
            tip += "\n\n" + self._pressure_detail(cache, vm.total)
        self.setToolTip(tip + "\n\nClick for full statistics")

        if under_pressure != self._warned:
            self._warned = under_pressure
            # Both directions. The run line carries this while a run is on,
            # so it needs to be told when to stop carrying it — an empty
            # string is "nothing to say" rather than a message to show.
            self.pressure_changed.emit(
                self._pressure_summary(cache, vm.total) if under_pressure else "")

        self._run_label.setText(self._run_text())
        self._node_label.setText(self._node_text())

    def _heaviest(self, limit: int = 3) -> list[tuple[str, str]]:
        """(label, size) for the nodes holding the most, largest first."""
        graph = self._engine.graph
        out = []
        for node_id, size in self._engine.cache.heaviest(limit):
            node = graph.nodes.get(node_id)
            out.append((node.label if node else node_id, format_bytes(size)))
        return out

    def _pressure_summary(self, cache: int, total: int) -> str:
        """One line for the status bar — what is held, and what to do.

        Led by the advice that needs no knowledge of this app: whoever is
        looking at this may have been handed the tool rather than built it,
        and "freeze the node" means nothing to them. Closing something else
        always helps; reading fewer rows is the next lever and lives on the
        step that reads the data, where it is a deliberate choice.
        """
        heaviest = self._heaviest(1)
        worst = (f", the largest being {heaviest[0][0]} at {heaviest[0][1]}"
                 if heaviest else "")
        return (f"Memory is running low — this flow is holding "
                f"{format_bytes(cache)} of {format_bytes(total)}{worst}. "
                f"Close other applications, lower Max rows where the data is "
                f"read, or Reset Caches to release what is held.")

    def _pressure_detail(self, cache: int, total: int) -> str:
        # tab-aligned to match the three rows above it in the tooltip
        lines = ["Memory is running low. Holding the most:"]
        lines += [f"  {label}\t{size}" for label, size in self._heaviest(3)]
        lines.append("Close other applications, lower Max rows where the data "
                     "is read, or Reset Caches to release.")
        return "\n".join(lines)

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
