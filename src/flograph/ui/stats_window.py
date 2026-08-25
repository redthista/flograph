"""Where the time and the memory went.

The status bar answers "is this heavy"; this window answers "heavy where".
Three tabs, because there are three different questions and they want
different shapes:

* **Run** — what the last run actually did, as a timeline you can read the
  shape of and a table you can sort. Sorting by time puts the bottleneck on
  the first row, which is the entire point of the tab.
* **Graph** — the project at rest: how much is cached, how much is stale,
  what the heaviest nodes are holding. Nothing to do with any one run.
* **Canvas** — why drawing is slow, if it is. Paint cost, how many items
  exist against how many are actually on screen, and whether zoom-out
  simplification is doing anything.

The window is modeless and refreshes itself while it is open, so it can be
left on a second monitor during a run. A node's name is clickable wherever
it appears — in either table and on the timeline — and clicking it selects
the node on the model canvas and brings the view to it, so reading a name
here and finding it there are one gesture. Everything the window shows is
read from structures the engine and the view maintain anyway — it starts no
work of its own beyond a repaint timer.
"""
from __future__ import annotations

from typing import Callable, Optional

import psutil
from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QDialog,
                               QHBoxLayout, QHeaderView, QLabel, QScrollArea,
                               QTableWidget, QTableWidgetItem, QTabWidget,
                               QVBoxLayout, QWidget)

from flograph.engine.runstats import NodeRun, RunRecord

from . import theme
from .resource_monitor import format_bytes, format_seconds

REFRESH_MS = 1000
ROW_H = 20
ROW_MAX = 34      # ceiling on how much a row grows into an empty panel
GUTTER = 150

_HEADING = "font-size: 10pt; font-weight: 600; padding: 6px 0 2px 0;"
_BODY = "color: #d1d5db;"
_DIM = "color: #9ca3af; font-size: 8pt;"


def _outcome_color(outcome: str) -> QColor:
    if outcome == "failed":
        return theme.WIRE_INVALID
    if outcome == "cancelled":
        return theme.NODE_SUBTEXT
    return theme.SELECTION_OUTLINE


class SortableItem(QTableWidgetItem):
    """A cell that displays one thing and sorts by another.

    Qt sorts on the display string, which puts "9 ms" after "10 s" and
    "900 KB" after "1.2 GB" — every number in here is formatted, so every
    column would sort wrongly without this.
    """

    def __init__(self, text: str, key) -> None:
        super().__init__(text)
        self.key = key
        self.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)

    def __lt__(self, other) -> bool:
        if isinstance(other, SortableItem):
            return self.key < other.key
        return super().__lt__(other)


class RunTimeline(QWidget):
    """One bar per node on a shared time axis.

    A table tells you a node took nine seconds; this tells you whether the
    run *was* those nine seconds or whether they were one step among twenty.
    Bars are positioned by when the node started, so gaps between them are
    visible too — a run that is mostly gap is losing its time to scheduling
    rather than to any node, and that is worth being able to see.

    Bars that line up vertically are nodes that ran at the same time, which
    needed no new drawing: one row per node against a wall-clock axis already
    says it. A staircase is a flow running one node at a time; a block is a
    flow running wide.

    A node's name in the gutter is clickable and takes the canvas to it —
    the timeline is the tab for "what was slow", and the follow-up question
    is always "where is that one".
    """

    node_clicked = Signal(str)     # node_id

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._record: Optional[RunRecord] = None
        self.setMinimumHeight(ROW_H)
        # hover feedback needs moves between presses
        self.setMouseTracking(True)

    def set_record(self, record: Optional[RunRecord]) -> None:
        self._record = record
        rows = len(record.nodes) if record else 0
        self.setMinimumHeight(max(ROW_H, rows * ROW_H + 8))
        self.update()

    def _row_geometry(self) -> Optional[tuple[float, float]]:
        """(top_pad, row_h) as painted, or None with nothing to show.

        Rows share whatever height there is rather than stacking at the top
        of an empty panel, but only up to a point — three nodes should not
        get bars a centimetre thick just because the window is tall. Hit
        testing shares this so a click lands where the eye says it does.
        """
        record = self._record
        if record is None or not record.nodes:
            return None
        row_h = min(ROW_MAX, max(ROW_H, (self.height() - 8) / len(record.nodes)))
        top_pad = max(4.0, (self.height() - len(record.nodes) * row_h) / 2)
        return top_pad, row_h

    def _node_at(self, pos: QPointF) -> Optional[str]:
        """The node whose name sits under `pos`, or None.

        Only the name gutter is clickable: the track belongs to the bars,
        which answer "when", not "which".
        """
        geo = self._row_geometry()
        if geo is None:
            return None
        top_pad, row_h = geo
        nodes = self._record.nodes
        row = int((pos.y() - top_pad) // row_h)
        if not 0 <= row < len(nodes) or pos.x() > GUTTER - 8:
            return None
        return nodes[row].node_id

    def mousePressEvent(self, event) -> None:
        node_id = self._node_at(event.position())
        if node_id is not None:
            self.node_clicked.emit(node_id)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        on_name = self._node_at(event.position()) is not None
        self.setCursor(Qt.PointingHandCursor if on_name else Qt.ArrowCursor)
        super().mouseMoveEvent(event)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        # Its own backdrop rather than the dialog's: the bars are canvas
        # colours and have to be read against a canvas, and a chart that
        # changes legibility with the surface it is dropped on is a chart
        # waiting to become invisible.
        painter.fillRect(self.rect(), theme.CANVAS_BG)
        record = self._record
        if record is None or not record.nodes:
            painter.setPen(QPen(theme.NODE_SUBTEXT))
            painter.drawText(self.rect(), Qt.AlignCenter, "No run recorded yet")
            painter.end()
            return

        # The axis is the run's wall clock, not the sum of the node times, so
        # the bars really do show what share of the wait each step was. That
        # distinction is load-bearing now that nodes overlap: their times add
        # up to more than the run took, and an axis long enough to hold the
        # sum would squeeze every bar into the left of the panel and show a
        # fast parallel run as a mostly-empty chart.
        span = max(record.wall_time, 1e-6)
        track_x = GUTTER
        track_w = max(40, self.width() - GUTTER - 70)
        # the row layout the click hit-testing sees too — see _row_geometry
        top_pad, row_h = self._row_geometry()

        font = painter.font()
        small = QFont(font)
        small.setPointSizeF(max(6.5, font.pointSizeF() - 1.5))
        painter.setFont(small)
        metrics = painter.fontMetrics()

        bar_h = min(12.0, row_h - 8)
        for row, node in enumerate(record.nodes):
            y = top_pad + row * row_h
            label = metrics.elidedText(node.label, Qt.ElideRight, GUTTER - 12)
            painter.setPen(QPen(theme.NODE_TEXT))
            painter.drawText(QRectF(0, y, GUTTER - 8, row_h),
                             Qt.AlignRight | Qt.AlignVCenter, label)

            top = y + (row_h - bar_h) / 2
            painter.setPen(Qt.NoPen)
            painter.setBrush(theme.GRID_COARSE)
            painter.drawRoundedRect(
                QRectF(track_x, top + 2, track_w, bar_h - 4), 2, 2)

            x = track_x + track_w * (node.started / span)
            # a floor of 2px: a node that took a millisecond still happened,
            # and a bar you cannot see reads as a node that did not run
            w = max(2.0, track_w * (node.wall_time / span))
            painter.setBrush(_outcome_color(node.outcome))
            painter.drawRoundedRect(QRectF(x, top, min(w, track_w), bar_h), 2, 2)

            painter.setPen(QPen(theme.NODE_SUBTEXT))
            painter.drawText(
                QRectF(track_x + track_w + 6, y, 62, row_h),
                Qt.AlignLeft | Qt.AlignVCenter, format_seconds(node.wall_time))
        painter.end()


class RunTab(QWidget):
    """The last run (or an earlier one from this session), in two views."""

    COLUMNS = ("Node", "Result", "Time", "Share", "Peak RAM", "Output", "Produced")

    def __init__(self, engine, reveal: Optional[Callable[[str], None]] = None,
                 parent=None) -> None:
        super().__init__(parent)
        self._engine = engine
        self._reveal = reveal
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 10)
        layout.setSpacing(6)

        picker_row = QHBoxLayout()
        picker_row.addWidget(QLabel("Run:"))
        self.picker = QComboBox()
        self.picker.setMinimumWidth(220)
        self.picker.currentIndexChanged.connect(lambda _: self._show_selected())
        picker_row.addWidget(self.picker)
        picker_row.addStretch(1)
        layout.addLayout(picker_row)

        self.summary = QLabel()
        self.summary.setStyleSheet(_BODY)
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)

        # Timeline and table are two readings of one run, and putting them
        # side by side made each half a view: the timeline capped at a couple
        # of hundred pixels no matter how many nodes ran, the table showing
        # five rows of twenty. As sub-tabs each gets the whole panel, and the
        # picker and summary stay above both because they describe the run
        # rather than either view of it.
        self.sub_tabs = QTabWidget()
        layout.addWidget(self.sub_tabs, 1)

        self.timeline = RunTimeline()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.timeline)
        scroll.setFrameShape(QScrollArea.NoFrame)
        self.sub_tabs.addTab(scroll, "Timeline")

        table_page = QWidget()
        table_layout = QVBoxLayout(table_page)
        table_layout.setContentsMargins(0, 6, 0, 0)
        table_layout.setSpacing(4)

        self.table = QTableWidget(0, len(self.COLUMNS))
        self.table.setHorizontalHeaderLabels(self.COLUMNS)
        self.table.setSortingEnabled(True)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.Stretch)
        # Opens on the slowest step, which is the question the tab exists to
        # answer. Set once: every later refill re-sorts on whatever indicator
        # is current, so a column the user picked is not overridden.
        self.table.sortByColumn(2, Qt.DescendingOrder)
        self.table.cellClicked.connect(self._on_cell_clicked)
        table_layout.addWidget(self.table, 1)

        hint = QLabel("Click a column to sort — by Time for the slowest step, "
                      "by Peak RAM for the hungriest. Click a node's name to "
                      "jump to it on the canvas. Peak RAM is the whole "
                      "process sampled while that node ran, so it includes "
                      "anything else happening at the time.")
        hint.setStyleSheet(_DIM)
        hint.setWordWrap(True)
        table_layout.addWidget(hint)
        self.sub_tabs.addTab(table_page, "Table")

        self.timeline.node_clicked.connect(self._reveal_node)
        self._records: list = []

    # ------------------------------------------------------------- contents

    def refresh(self) -> None:
        records = self._engine.history.all()
        if len(records) != len(self._records) or (
                records and self._records and records[0] is not self._records[0]):
            self._reload_picker(records)
        self._show_selected()

    def _reload_picker(self, records: list) -> None:
        self._records = records
        keep = self.picker.currentIndex()
        blocked = self.picker.blockSignals(True)
        self.picker.clear()
        for i, record in enumerate(records):
            when = "latest" if i == 0 else f"{i} run{'s' if i > 1 else ''} ago"
            note = "" if record.ok else "  ·  errors"
            self.picker.addItem(
                f"{when}  ·  {format_seconds(record.wall_time)}"
                f"  ·  {len(record.nodes)} node"
                f"{'s' if len(record.nodes) != 1 else ''}{note}")
        self.picker.blockSignals(blocked)
        # a new run arrives at index 0 and the view should follow it, but a
        # deliberate look back at an older one should not be yanked away
        self.picker.setCurrentIndex(0 if keep <= 0 else min(keep + 1,
                                                            len(records) - 1))

    def _show_selected(self) -> None:
        index = self.picker.currentIndex()
        record = (self._records[index]
                  if 0 <= index < len(self._records) else None)
        self.timeline.set_record(record)
        self._fill_summary(record)
        self._fill_table(record)

    def _fill_summary(self, record: Optional[RunRecord]) -> None:
        if record is None:
            self.summary.setText("Nothing has run yet in this session.")
            return
        overhead = max(0.0, record.wall_time - record.node_time)
        parts = [
            f"<b>{format_seconds(record.wall_time)}</b> total",
            f"{format_seconds(record.node_time)} in nodes",
        ]
        # A run that overlapped spent no time waiting between nodes — there
        # was always another one going — so "scheduling" is not the number to
        # show it. What it saved by overlapping is.
        if record.overlap > 0:
            parts.append(f"{format_seconds(record.overlap)} saved by running "
                         f"{record.peak_concurrency} at once")
        else:
            parts.append(f"{format_seconds(overhead)} scheduling")
        if record.peak_growth:
            parts.append(f"peak +{format_bytes(record.peak_growth)}")
        skipped = (record.skipped_clean + record.skipped_frozen
                   + record.skipped_inactive + record.skipped_manual)
        if skipped:
            detail = ", ".join(
                f"{n} {name}" for n, name in
                ((record.skipped_clean, "cached"),
                 (record.skipped_frozen, "frozen"),
                 (record.skipped_inactive, "deactivated"),
                 (record.skipped_manual, "manual")) if n)
            parts.append(f"{skipped} skipped ({detail})")
        text = "  ·  ".join(parts)
        if record.failed:
            names = ", ".join(n.label for n in record.failed[:3])
            text += (f"<br><span style='color:#ef4444'>"
                     f"{len(record.failed)} failed: {names}</span>")
        if record.cancelled:
            text += "<br><span style='color:#9ca3af'>Cancelled part way.</span>"
        self.summary.setText(text)

    def _fill_table(self, record: Optional[RunRecord]) -> None:
        # Sorting has to be off while rows are written or Qt re-sorts on every
        # insert and the cells land in other rows.
        self.table.setSortingEnabled(False)
        nodes = record.nodes if record else []
        self.table.setRowCount(len(nodes))
        for row, node in enumerate(nodes):
            share = record.share(node) if record else 0.0
            cells = (
                SortableItem(node.label, node.label.lower()),
                SortableItem(node.outcome, node.outcome),
                SortableItem(format_seconds(node.wall_time), node.wall_time),
                SortableItem(f"{share * 100:.0f}%", share),
                SortableItem(
                    f"+{format_bytes(node.rss_growth)}" if node.rss_growth > 0
                    else "—", node.rss_growth),
                SortableItem(format_bytes(node.output_bytes), node.output_bytes),
                SortableItem(node.summary or "—", node.summary),
            )
            # the id the click hands to the canvas — two nodes can share a
            # label, and a renamed one must still be findable
            cells[0].setData(Qt.UserRole, node.node_id)
            for col, cell in enumerate(cells):
                if col and cell.key == 0 and col in (4, 5):
                    cell.setForeground(theme.NODE_SUBTEXT)
                if node.outcome == "failed":
                    cell.setForeground(theme.WIRE_INVALID)
                self.table.setItem(row, col, cell)
        self.table.setSortingEnabled(True)
        self.table.resizeColumnsToContents()
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)

    def _on_cell_clicked(self, row: int, _col: int) -> None:
        item = self.table.item(row, 0)
        if item is not None:
            self._reveal_node(item.data(Qt.UserRole))

    def _reveal_node(self, node_id: Optional[str]) -> None:
        if node_id and self._reveal is not None:
            self._reveal(node_id)


class GraphTab(QWidget):
    """The project at rest — size, staleness, and what is holding memory."""

    COLUMNS = ("Node", "Memory", "Last run", "State")

    def __init__(self, engine, reveal: Optional[Callable[[str], None]] = None,
                 parent=None) -> None:
        super().__init__(parent)
        self._engine = engine
        self._reveal = reveal
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 10)
        layout.setSpacing(4)

        self.counts = QLabel()
        self.counts.setStyleSheet(_BODY)
        self.counts.setWordWrap(True)
        layout.addWidget(self.counts)

        heading = QLabel("Heaviest nodes")
        heading.setStyleSheet(_HEADING)
        layout.addWidget(heading)

        self.table = QTableWidget(0, len(self.COLUMNS))
        self.table.setHorizontalHeaderLabels(self.COLUMNS)
        self.table.setSortingEnabled(True)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.sortByColumn(1, Qt.DescendingOrder)   # "Heaviest", as billed
        self.table.cellClicked.connect(self._on_cell_clicked)
        layout.addWidget(self.table, 1)

        hint = QLabel("A node marked “shared” is re-serving the value of the "
                      "node it reads from — a Goto, a From or a Reroute. Its "
                      "size is real but it is not a second copy, and it is "
                      "counted once in the total. Click a node's name to "
                      "jump to it on the canvas.")
        hint.setStyleSheet(_DIM)
        hint.setWordWrap(True)
        layout.addWidget(hint)

    def refresh(self) -> None:
        graph, cache = self._engine.graph, self._engine.cache
        nodes = list(graph.nodes.values())
        cached = sum(1 for n in nodes if cache.has(n.id))
        dirty = sum(1 for n in nodes if n.dirty)
        frozen = sum(1 for n in nodes if n.frozen)
        manual = sum(1 for n in nodes if n.manual)
        inactive = sum(1 for n in nodes if not n.active)
        locked = sum(1 for n in nodes if n.locked)

        self.counts.setText(
            f"<b>{len(nodes)}</b> nodes  ·  {len(graph.connections)} wires  ·  "
            f"{len(graph.links)} links  ·  {len(graph.frames)} frames<br>"
            f"{cached} cached  ·  {dirty} stale  ·  {frozen} frozen  ·  "
            f"{manual} manual  ·  "
            f"{inactive} deactivated  ·  {locked} locked<br>"
            f"Cached outputs hold <b>{format_bytes(cache.total_bytes())}</b>")

        rows = []
        for node in nodes:
            entry = cache.get(node.id)
            if entry is None:
                continue
            state = []
            if entry.alias_of is not None:
                state.append("shared")
            if node.frozen:
                state.append("frozen")
            if node.manual:
                state.append("manual")
            if not node.active:
                state.append("off")
            if node.dirty:
                state.append("stale")
            rows.append((node, entry, ", ".join(state) or "cached"))
        rows.sort(key=lambda r: r[1].memory_bytes, reverse=True)

        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(rows))
        for row, (node, entry, state) in enumerate(rows):
            cells = (
                SortableItem(node.label, node.label.lower()),
                SortableItem(format_bytes(entry.memory_bytes),
                             entry.memory_bytes),
                SortableItem(format_seconds(entry.wall_time), entry.wall_time),
                SortableItem(state, state),
            )
            # the id a click hands to the canvas — see RunTab._fill_table
            cells[0].setData(Qt.UserRole, node.id)
            for col, cell in enumerate(cells):
                self.table.setItem(row, col, cell)
        self.table.setSortingEnabled(True)
        self.table.resizeColumnsToContents()
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)

    def _on_cell_clicked(self, row: int, _col: int) -> None:
        item = self.table.item(row, 0)
        if item is not None:
            self._reveal_node(item.data(Qt.UserRole))

    def _reveal_node(self, node_id: Optional[str]) -> None:
        if node_id and self._reveal is not None:
            self._reveal(node_id)


class FrameStrip(QWidget):
    """Recent frame times as a strip of bars, oldest at the left.

    An average hides the thing that is actually felt. Thirty frames at 4 ms
    and one at 300 ms average out to something comfortable and read as a
    stutter, and only the shape shows which of those is happening. The
    60 fps line is drawn across it as the budget everything below is under.
    """

    BUDGET_MS = 1000 / 60

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._frames: list = []
        self.setMinimumHeight(64)

    def set_frames(self, frames) -> None:
        self._frames = list(frames)
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), theme.CANVAS_BG)
        if not self._frames:
            painter.setPen(QPen(theme.NODE_SUBTEXT))
            painter.drawText(self.rect(), Qt.AlignCenter,
                             "Pan or zoom the canvas for a reading")
            painter.end()
            return

        # Scaled to the worst frame or to the budget, whichever is larger, so
        # a comfortable canvas stays visibly *under* the line instead of
        # being stretched to fill the box and looking alarming.
        ceiling = max(self.BUDGET_MS, max(self._frames) * 1000)
        height, width = self.height() - 2, self.width()
        step = max(1.0, width / len(self._frames))

        painter.setPen(Qt.NoPen)
        for i, seconds in enumerate(self._frames):
            ms = seconds * 1000
            bar = height * min(1.0, ms / ceiling)
            painter.setBrush(theme.WIRE_INVALID if ms > self.BUDGET_MS
                             else theme.MEM_CACHE)
            painter.drawRect(QRectF(i * step, height - bar + 1,
                                    max(1.0, step - 1), bar))

        y = height - height * (self.BUDGET_MS / ceiling) + 1
        painter.setPen(QPen(theme.NODE_SUBTEXT, 1, Qt.DashLine))
        painter.drawLine(0, int(y), width, int(y))
        painter.setPen(QPen(theme.NODE_SUBTEXT))
        # Below the line when it sits at the top, which is the common case:
        # a canvas comfortably inside its budget pins the line to the ceiling
        # and the caption would be drawn off the widget entirely.
        caption_y = y + 2 if y < 16 else y - 14
        painter.drawText(QRectF(4, caption_y, 120, 13),
                         Qt.AlignLeft | Qt.AlignVCenter, "60 fps budget")
        painter.end()


class CanvasTab(QWidget):
    """Why the canvas is (or is not) slow to draw."""

    def __init__(self, window, parent=None) -> None:
        super().__init__(parent)
        self._window = window
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 10)
        layout.setSpacing(4)

        self.paint = QLabel()
        self.items = QLabel()
        self.cards = QLabel()
        self.advice = QLabel()
        for label in (self.paint, self.items, self.cards):
            label.setStyleSheet(_BODY)
            label.setWordWrap(True)
            layout.addWidget(label)

        heading = QLabel("Recent frames")
        heading.setStyleSheet(_HEADING)
        layout.addWidget(heading)
        self.strip = FrameStrip()
        layout.addWidget(self.strip)

        self.advice.setStyleSheet(_DIM)
        self.advice.setWordWrap(True)
        layout.addWidget(self.advice)
        layout.addStretch(1)

        note = QLabel(
            "Frames are only drawn when something asks for a repaint, so a "
            "still canvas records nothing and these numbers describe the last "
            "burst of drawing. Pan or zoom for a live reading.")
        note.setStyleSheet(_DIM)
        note.setWordWrap(True)
        layout.addWidget(note)

    def refresh(self) -> None:
        view = getattr(self._window, "view", None)
        scene = getattr(self._window, "scene", None)
        stats = getattr(view, "paint_stats", None)
        if view is None or scene is None or stats is None:
            self.paint.setText("No canvas.")
            return

        if stats.samples:
            self.paint.setText(
                f"Paint <b>{stats.avg_ms:.1f} ms</b> average  ·  "
                f"{stats.worst_ms:.1f} ms worst  ·  "
                f"up to {stats.fps:.0f} fps  ·  "
                f"{stats.total:,} frames drawn")
        else:
            self.paint.setText("Nothing drawn yet.")

        visible = len(view.items(view.viewport().rect()))
        zoom = getattr(view, "zoom", 1.0)
        flattening = (scene.lod_enabled and zoom < scene.lod_threshold)
        self.items.setText(
            f"{len(scene.node_items)} node cards  ·  "
            f"{len(scene.connection_items)} wires  ·  "
            f"{len(scene.frame_items)} frames  ·  "
            f"<b>{visible}</b> items in view<br>"
            f"Zoom {zoom * 100:.0f}%  ·  simplification "
            f"{'on' if scene.lod_enabled else 'disabled'}"
            f"{' and active' if flattening else ''} "
            f"(below {scene.lod_threshold * 100:.0f}%)")

        self.cards.setText(self._card_text(scene))
        self.strip.set_frames(stats.recent())
        self.advice.setText(self._advice(stats, scene, flattening))

    @staticmethod
    def _card_text(scene) -> str:
        """What kind of cards are on the canvas, heaviest kinds called out.

        Node count alone does not predict paint cost — twenty plain script
        nodes are nothing and three webview cards are a lot. These are the
        kinds that carry a live widget, and switching their previews off is
        the lever the canvas actually responds to.
        """
        from .canvas.node_item import card_kind

        heavy_kinds = ("webview", "figure", "table_viewer", "grid", "report")
        heavy = previews = 0
        for item in scene.node_items.values():
            if card_kind(item.node) in heavy_kinds:
                heavy += 1
                if item.node.canvas_preview_enabled:
                    previews += 1
        if not heavy:
            return "No chart, table or web cards — nothing expensive to draw."
        return (f"{heavy} chart/table/web card{'s' if heavy != 1 else ''}, "
                f"<b>{previews}</b> with the canvas preview switched on")

    @staticmethod
    def _advice(stats, scene, flattening: bool) -> str:
        if not stats.samples or stats.avg_ms < 16:
            return "Drawing comfortably."
        parts = ["Drawing is costing more than one 60 fps frame."]
        if not scene.lod_enabled:
            parts.append("Turning on “Simplify nodes when zoomed out” in "
                         "Settings > Canvas is the biggest single win.")
        elif not flattening:
            parts.append("Simplification is on but not active at this zoom — "
                         "raising its threshold makes it start sooner.")
        else:
            parts.append("Simplification is already active; switching off "
                         "per-node previews on the heavy viz cards, or "
                         "collapsing what you are not working on into a "
                         "frame, is the next lever.")
        return " ".join(parts)


class StatsWindow(QDialog):
    """Modeless statistics window — run cost, project weight, canvas health."""

    #: a clicked node name in the Run or Graph tab; the owner connects this
    #: to whatever brings the model canvas to the node
    reveal_requested = Signal(str)

    def __init__(self, window, parent=None) -> None:
        super().__init__(parent or window)
        self.setWindowTitle("Statistics")
        self.setModal(False)
        self.resize(760, 560)

        self._window = window
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)

        self.tabs = QTabWidget()
        self.run_tab = RunTab(window.engine, self.reveal_requested.emit)
        self.graph_tab = GraphTab(window.engine, self.reveal_requested.emit)
        self.canvas_tab = CanvasTab(window)
        self.tabs.addTab(self.run_tab, "Run")
        self.tabs.addTab(self.graph_tab, "Graph")
        self.tabs.addTab(self.canvas_tab, "Canvas")
        layout.addWidget(self.tabs)

        self._timer = QTimer(self)
        self._timer.setInterval(REFRESH_MS)
        self._timer.timeout.connect(self._refresh_visible)
        self.refresh()

    # Only the tab on top is rebuilt on the timer. The other two would be
    # rebuilding tables nobody is looking at, and the Run table in particular
    # throws away the user's chosen sort every time it is refilled.
    def _refresh_visible(self) -> None:
        current = self.tabs.currentWidget()
        if current is not None and hasattr(current, "refresh"):
            current.refresh()

    def refresh(self) -> None:
        for tab in (self.run_tab, self.graph_tab, self.canvas_tab):
            tab.refresh()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.refresh()
        self._timer.start()

    def hideEvent(self, event) -> None:
        self._timer.stop()
        super().hideEvent(event)
