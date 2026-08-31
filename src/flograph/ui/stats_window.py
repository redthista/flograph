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
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog,
                               QHBoxLayout, QHeaderView, QLabel, QScrollArea,
                               QTableWidget, QTableWidgetItem, QTabWidget,
                               QVBoxLayout, QWidget)

from flograph.engine.runstats import (NodePair, NodeRun, RunComparison,
                                      RunRecord)

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


# In a comparison a rise is a regression and a fall is a win, whichever
# quantity moved — time, memory, output size all read the same way.
_WORSE = theme.WIRE_INVALID       # red
_BETTER = theme.WIRE_VALID        # green


def _delta_seconds(delta: float) -> str:
    if abs(delta) < 5e-4:
        return "—"
    return ("+" if delta > 0 else "−") + format_seconds(abs(delta))


def _delta_bytes(delta: float) -> str:
    if abs(delta) < 1:
        return "—"
    return ("+" if delta > 0 else "−") + format_bytes(abs(delta))


def _delta_color(delta: float) -> Optional[QColor]:
    if abs(delta) < 1e-9:
        return None
    return _WORSE if delta > 0 else _BETTER


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
        self._comparison: Optional[RunComparison] = None
        self.setMinimumHeight(ROW_H)
        # hover feedback needs moves between presses
        self.setMouseTracking(True)

    def set_record(self, record: Optional[RunRecord]) -> None:
        self._record = record
        self._comparison = None
        rows = len(record.nodes) if record else 0
        self.setMinimumHeight(max(ROW_H, rows * ROW_H + 8))
        self.update()

    def set_comparison(self, comparison: Optional[RunComparison]) -> None:
        """Draw two runs, one duration bar pair per node, instead of one run.

        The axis stops being wall-clock — the two runs did not start
        together and their start offsets are not comparable — and becomes a
        plain duration scale the pairs share, so a bar that grew is a step
        that got slower.
        """
        self._comparison = comparison
        self._record = None
        rows = len(comparison.pairs) if comparison else 0
        self.setMinimumHeight(max(ROW_H, rows * ROW_H + 8))
        self.update()

    def _rows(self) -> list:
        """The things drawn one per line — NodeRuns, or NodePairs when
        comparing. Both carry `node_id` and `label`."""
        if self._comparison is not None:
            return self._comparison.pairs
        if self._record is not None:
            return list(self._record.nodes)
        return []

    def _row_geometry(self) -> Optional[tuple[float, float]]:
        """(top_pad, row_h) as painted, or None with nothing to show.

        Rows share whatever height there is rather than stacking at the top
        of an empty panel, but only up to a point — three nodes should not
        get bars a centimetre thick just because the window is tall. Hit
        testing shares this so a click lands where the eye says it does.
        """
        rows = self._rows()
        if not rows:
            return None
        row_h = min(ROW_MAX, max(ROW_H, (self.height() - 8) / len(rows)))
        top_pad = max(4.0, (self.height() - len(rows) * row_h) / 2)
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
        rows = self._rows()
        row = int((pos.y() - top_pad) // row_h)
        if not 0 <= row < len(rows) or pos.x() > GUTTER - 8:
            return None
        return rows[row].node_id

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
        if self._comparison is not None:
            self._paint_comparison(painter)
            painter.end()
            return
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

    def _paint_comparison(self, painter: QPainter) -> None:
        """One row per node, two stacked duration bars — the selected run on
        top, the baseline below — on a shared duration scale, with the time
        delta in the right margin. A node missing from one run draws only
        the bar it has, so a gap on the top line is "this step is gone" and
        a gap on the bottom is "this step is new"."""
        comparison = self._comparison
        pairs = comparison.pairs
        if not pairs:
            painter.setPen(QPen(theme.NODE_SUBTEXT))
            painter.drawText(self.rect(), Qt.AlignCenter, "Nothing ran in either run")
            return

        span = comparison.axis_span
        track_x = GUTTER
        track_w = max(40, self.width() - GUTTER - 88)
        top_pad, row_h = self._row_geometry()

        font = painter.font()
        small = QFont(font)
        small.setPointSizeF(max(6.5, font.pointSizeF() - 1.5))
        painter.setFont(small)
        metrics = painter.fontMetrics()

        sub_h = min(6.0, (row_h - 8) / 2)
        for row, pair in enumerate(pairs):
            y = top_pad + row * row_h
            label = metrics.elidedText(pair.label, Qt.ElideRight, GUTTER - 12)
            painter.setPen(QPen(theme.NODE_TEXT))
            painter.drawText(QRectF(0, y, GUTTER - 8, row_h),
                             Qt.AlignRight | Qt.AlignVCenter, label)

            painter.setPen(Qt.NoPen)
            painter.setBrush(theme.GRID_COARSE)
            painter.drawRoundedRect(
                QRectF(track_x, y + (row_h - sub_h * 2 - 2) / 2,
                       track_w, sub_h * 2 + 2), 2, 2)

            gap = (row_h - sub_h * 2 - 2) / 2
            for i, side in enumerate((pair.after, pair.before)):
                if side is None:
                    continue
                top = y + gap + i * (sub_h + 2)
                w = max(2.0, track_w * (side.wall_time / span))
                colour = QColor(_outcome_color(side.outcome))
                if i == 1:            # the baseline reads as the fainter one
                    colour.setAlpha(120)
                painter.setBrush(colour)
                painter.drawRoundedRect(
                    QRectF(track_x, top, min(w, track_w), sub_h), 1, 1)

            delta = pair.time_delta
            colour = _delta_color(delta) or theme.NODE_SUBTEXT
            painter.setPen(QPen(colour))
            painter.drawText(
                QRectF(track_x + track_w + 6, y, 80, row_h),
                Qt.AlignLeft | Qt.AlignVCenter, _delta_seconds(delta))


class RunTab(QWidget):
    """The last run (or an earlier one from this session), in two views —
    or two runs read against each other when Compare is on."""

    COLUMNS = ("Node", "Result", "Time", "Share", "Peak RAM", "Output", "Produced")
    #: what the table shows in compare mode — the selected run's own figure
    #: next to how far it moved from the baseline
    COMPARE_COLUMNS = ("Node", "Change", "Time", "Δ Time",
                       "Peak RAM", "Δ RAM", "Output", "Δ Output")

    def __init__(self, engine, reveal: Optional[Callable[[str], None]] = None,
                 parent=None) -> None:
        super().__init__(parent)
        self._engine = engine
        self._reveal = reveal
        self._comparing = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 10)
        layout.setSpacing(6)

        picker_row = QHBoxLayout()
        picker_row.addWidget(QLabel("Run:"))
        self.picker = QComboBox()
        self.picker.setMinimumWidth(220)
        self.picker.currentIndexChanged.connect(lambda _: self._show_selected())
        picker_row.addWidget(self.picker)
        picker_row.addSpacing(14)

        # Off by default: the tab's first job is still "read one run". The
        # baseline picker only appears once there is a comparison to make.
        self.compare_check = QCheckBox("Compare with")
        self.compare_check.toggled.connect(self._on_compare_toggled)
        picker_row.addWidget(self.compare_check)
        self.baseline_picker = QComboBox()
        self.baseline_picker.setMinimumWidth(200)
        self.baseline_picker.setVisible(False)
        self.baseline_picker.currentIndexChanged.connect(
            lambda _: self._show_selected())
        picker_row.addWidget(self.baseline_picker)
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

        self.hint = QLabel()
        self.hint.setStyleSheet(_DIM)
        self.hint.setWordWrap(True)
        table_layout.addWidget(self.hint)
        self.sub_tabs.addTab(table_page, "Table")
        self._set_hint()

        self.timeline.node_clicked.connect(self._reveal_node)
        self._records: list = []

    # ------------------------------------------------------------- contents

    def refresh(self) -> None:
        records = self._engine.history.all()
        if len(records) != len(self._records) or (
                records and self._records and records[0] is not self._records[0]):
            self._reload_picker(records)
        self._show_selected()

    @staticmethod
    def _label_for(index: int, record: RunRecord) -> str:
        when = "latest" if index == 0 else f"{index} run{'s' if index > 1 else ''} ago"
        note = "" if record.ok else "  ·  errors"
        return (f"{when}  ·  {format_seconds(record.wall_time)}"
                f"  ·  {len(record.nodes)} node"
                f"{'s' if len(record.nodes) != 1 else ''}{note}")

    def _reload_picker(self, records: list) -> None:
        self._records = records
        for picker, follow_latest, default in (
                (self.picker, True, 0), (self.baseline_picker, False, 1)):
            keep = picker.currentIndex()
            blocked = picker.blockSignals(True)
            picker.clear()
            for i, record in enumerate(records):
                picker.addItem(self._label_for(i, record))
            picker.blockSignals(blocked)
            if keep < 0:
                # first fill: the baseline defaults to the run before latest
                # so ticking Compare has something to say straight away
                picker.setCurrentIndex(min(default, max(0, len(records) - 1)))
            elif follow_latest and keep == 0:
                # a new run arrives at index 0 and the selected view follows
                # it; a deliberate look back is not yanked away
                picker.setCurrentIndex(0)
            else:
                # every other run shifts down one as the new one is prepended
                picker.setCurrentIndex(min(keep + 1, len(records) - 1))

    def _comparison(self) -> Optional[RunComparison]:
        """The comparison the pickers currently describe, or None — Compare
        off, fewer than two runs, or both pickers on the same run."""
        if not self._comparing:
            return None
        a, b = self.picker.currentIndex(), self.baseline_picker.currentIndex()
        if not (0 <= a < len(self._records) and 0 <= b < len(self._records)):
            return None
        if a == b:
            return None
        return RunComparison(self._records[a], self._records[b])

    def _on_compare_toggled(self, on: bool) -> None:
        self._comparing = on
        self.baseline_picker.setVisible(on)
        self._set_hint()
        self._set_table_columns()
        # open on Δ Time when comparing (biggest regression up top), back to
        # Time when not
        self.table.sortByColumn(3 if on else 2, Qt.DescendingOrder)
        self._show_selected()

    def _set_hint(self) -> None:
        if self._comparing:
            self.hint.setText(
                "Rows are the nodes that ran in either run, sorted by how far "
                "their time moved — the biggest change is on top. A red Δ is "
                "slower or heavier in the selected run, green is faster or "
                "lighter. “new” ran only in the selected run, “gone” only in "
                "the baseline. Click a node's name to jump to it on the canvas.")
        else:
            self.hint.setText(
                "Click a column to sort — by Time for the slowest step, by "
                "Peak RAM for the hungriest. Click a node's name to jump to it "
                "on the canvas. Peak RAM is the whole process sampled while "
                "that node ran, so it includes anything else happening at the "
                "time.")

    def _set_table_columns(self) -> None:
        columns = self.COMPARE_COLUMNS if self._comparing else self.COLUMNS
        self.table.setColumnCount(len(columns))
        self.table.setHorizontalHeaderLabels(columns)

    def _show_selected(self) -> None:
        if self._comparing:
            comparison = self._comparison()
            if comparison is None:
                self.timeline.set_comparison(None)
                self.table.setRowCount(0)
                self.summary.setText(
                    "Pick two different runs above to compare them."
                    if len(self._records) >= 2 else
                    "Only one run so far this session — nothing to compare it "
                    "with yet.")
                return
            self.timeline.set_comparison(comparison)
            self._fill_summary_compare(comparison)
            self._fill_table_compare(comparison)
            return
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

    # --------------------------------------------------------- compare mode

    def _fill_summary_compare(self, comp: RunComparison) -> None:
        after, before = comp.after, comp.before

        def line(delta: float, fmt) -> str:
            colour = _delta_color(delta)
            body = fmt(delta)
            if colour is None:
                return body
            return f"<span style='color:{colour.name()}'>{body}</span>"

        parts = [
            f"<b>{format_seconds(after.wall_time)}</b> total "
            f"({line(comp.wall_delta, _delta_seconds)})",
            f"{format_seconds(after.node_time)} in nodes "
            f"({line(comp.node_time_delta, _delta_seconds)})",
        ]
        if after.peak_growth or before.peak_growth:
            parts.append(f"peak +{format_bytes(after.peak_growth)} "
                         f"({line(comp.peak_growth_delta, _delta_bytes)})")
        text = "  ·  ".join(parts)

        moved = [p for p in comp.pairs if p.status in ("slower", "faster")]
        detail = []
        if comp.added:
            detail.append(f"{len(comp.added)} new "
                          f"({', '.join(p.label for p in comp.added[:3])})")
        if comp.removed:
            detail.append(f"{len(comp.removed)} gone "
                          f"({', '.join(p.label for p in comp.removed[:3])})")
        if moved:
            worst = max(moved, key=lambda p: p.time_delta)
            best = min(moved, key=lambda p: p.time_delta)
            if worst.time_delta > 5e-4:
                detail.append(f"slowest mover {worst.label} "
                              f"{_delta_seconds(worst.time_delta)}")
            if best.time_delta < -5e-4 and best is not worst:
                detail.append(f"biggest win {best.label} "
                              f"{_delta_seconds(best.time_delta)}")
        if detail:
            text += ("<br><span style='color:#9ca3af'>"
                     + "  ·  ".join(detail) + "</span>")

        outcome_changes = [p for p in comp.pairs if p.outcome_changed]
        if outcome_changes:
            names = ", ".join(f"{p.label} {p.before.outcome}→{p.after.outcome}"
                              for p in outcome_changes[:3])
            text += ("<br><span style='color:#ef4444'>result changed: "
                     f"{names}</span>")

        self.summary.setText(
            f"Selected vs baseline — {self.picker.currentText()} vs "
            f"{self.baseline_picker.currentText()}<br>" + text)

    def _fill_table_compare(self, comp: RunComparison) -> None:
        self.table.setSortingEnabled(False)
        pairs = comp.pairs
        self.table.setRowCount(len(pairs))
        status_label = {"added": "new", "removed": "gone",
                        "slower": "slower", "faster": "faster", "same": "—"}
        for row, pair in enumerate(pairs):
            a = pair.after
            time_now = a.wall_time if a else 0.0
            rss_now = a.rss_growth if a else 0
            out_now = a.output_bytes if a else 0
            cells = (
                SortableItem(pair.label, pair.label.lower()),
                SortableItem(status_label[pair.status], pair.status),
                SortableItem(format_seconds(time_now) if a else "—", time_now),
                SortableItem(_delta_seconds(pair.time_delta), pair.time_delta),
                SortableItem(
                    f"+{format_bytes(rss_now)}" if rss_now > 0 else "—", rss_now),
                SortableItem(_delta_bytes(pair.rss_delta), pair.rss_delta),
                SortableItem(format_bytes(out_now) if a else "—", out_now),
                SortableItem(_delta_bytes(pair.output_delta), pair.output_delta),
            )
            cells[0].setData(Qt.UserRole, pair.node_id)
            for col, cell in enumerate(cells):
                self.table.setItem(row, col, cell)
            for col, delta in ((3, pair.time_delta), (5, pair.rss_delta),
                               (7, pair.output_delta)):
                colour = _delta_color(delta)
                if colour is not None:
                    self.table.item(row, col).setForeground(colour)
            if pair.status in ("added", "removed"):
                self.table.item(row, 1).setForeground(theme.SELECTION_OUTLINE)
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
