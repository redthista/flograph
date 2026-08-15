"""Comment frames: translucent labeled regions that move their contained
nodes with them."""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, QVariantAnimation, Signal
from PySide6.QtGui import (QBrush, QColor, QFont, QFontMetrics, QPainter,
                           QPainterPath, QPen)
from PySide6.QtWidgets import QGraphicsItem, QGraphicsObject, QInputDialog

from flograph.core import Frame
from flograph.core.node import NodeStatus

from .. import theme
from .grid import EDGE_MARGIN, grid_step, snap, snap_point, snapping_active
from .node_item import (COMPACT_MIN_H, COMPACT_NAME_FONT_SIZE, COMPACT_NAME_GAP,
                        COMPACT_NAME_H, COMPACT_NAME_MAX_W, COMPACT_PORT_TOP,
                        COMPACT_STATUS_GAP, COMPACT_STATUS_H, COMPACT_W,
                        LED_RADIUS, PORT_EDGE_GAP, ROW_H, PortItem,
                        paint_status_led)
from .stacking import COLLAPSED_FRAME_Z, FRAME_Z, z_for

TITLE_H = 24.0
HANDLE = 14.0
RUN_BTN = 18.0
#: The chevron that folds the frame down, and folds it back out. Sits at the
#: left of the title bar when expanded and in the box's top-left corner when
#: collapsed — the same disclosure triangle a node uses for its ports.
TOGGLE_W = 11.0
TOGGLE_H = 10.0
#: The grid of contained-node indicators drawn inside the collapsed box.
#: Nine at a time: enough to read a typical frame at a glance, few enough
#: that each light is still big enough to have a colour.
MATRIX_COLS = 3
MATRIX_CELLS = MATRIX_COLS * MATRIX_COLS
#: Margin between the box's edge and the grid. Narrower than a compact
#: node's COMPACT_MARK_INSET, which is sized for a single centred mark.
MATRIX_INSET = 8.0


class FrameItem(QGraphicsObject):
    run_requested = Signal(str)  # frame_id — the run glyph was clicked

    def __init__(self, frame: Frame) -> None:
        super().__init__()
        self.frame = frame
        self.apply_stacking()
        self.setFlags(QGraphicsItem.ItemIsMovable
                      | QGraphicsItem.ItemIsSelectable
                      | QGraphicsItem.ItemSendsGeometryChanges)
        self.setAcceptHoverEvents(True)
        # set before setPos — ItemSendsGeometryChanges makes setPos fire
        # itemChange, which reads _dragging
        self._dragging = False  # a move is in progress (snap gate)
        self.setPos(frame.rect[0], frame.rect[1])
        self._size = (frame.rect[2], frame.rect[3])
        self._resizing = False
        self._resize_edge = "corner"  # which edge/corner the drag grabbed
        self._press_scene_pos = QPointF()
        self._press_size = self._size
        self._press_pos = QPointF()
        self._grabbed: list = []  # (node_item, offset)
        self._grabbed_frames: list = []  # (frame_item, offset) — nested
        self._group_starts: dict | None = None  # multi-selection drag snapshot
        self._hover_run = False
        self._run_pressed = False
        self._toggle_pressed = False
        # Nodes this box stands in for while collapsed, in execution order.
        # Owned by the scene (see set_members); empty while expanded.
        self._members: list[str] = []
        self._pulse = 0.0
        self._pulse_anim = None

    # ------------------------------------------------------------- geometry

    def sync_from_model(self) -> None:
        x, y, w, h = self.frame.rect
        self.prepareGeometryChange()
        if (self.pos().x(), self.pos().y()) != (x, y):
            self.setPos(x, y)
        self._size = (w, h)
        # collapse arrives as a frame_changed too, and it moves the item
        # between stacking bands
        self.apply_stacking()
        self.refresh_status()
        self.update()

    def toggle_collapsed(self) -> None:
        """Fold or unfold, through the undo stack — it is saved with the
        project, so it is a graph change, not a view state the canvas can
        quietly own.

        Folding writes down what was inside at that moment; the canvas is
        the only thing that can see it, and once folded the region is not
        there to be read again. Unfolding pushes aside whatever the returning
        region would land on, in the same undo step, so one Ctrl+Z puts both
        the frame and the neighbours back.
        """
        scene = self.scene()
        if scene is None:
            return
        from ..commands import SetFrameCollapsedCommand
        if self.collapsed:
            # its own contents belong inside the region and must sit still;
            # read before the command clears the membership
            keep = set(self.frame.members)
            keep_frames = set(self.frame.member_frames)
            # planned against the region it is *about* to occupy, so what got
            # moved can be recorded by the same command that does the fold
            record, moves, frame_rects = scene.plan_expand_nudge(
                self.frame.id, self.scene_rect(), self.expanded_rect(),
                keep, keep_frames)
            scene.undo_stack.beginMacro("expand frame")
            scene.undo_stack.push(SetFrameCollapsedCommand(
                scene.graph, self.frame.id, False, nudged=record))
            scene.apply_nudge(moves, frame_rects)
            scene.undo_stack.endMacro()
            return
        nodes, frames = self.carried_items()
        # folding puts back whatever reopening it shoved aside
        moves, frame_rects = scene.unnudge_plan(self.frame.id)
        scene.undo_stack.beginMacro("collapse frame")
        scene.undo_stack.push(SetFrameCollapsedCommand(
            scene.graph, self.frame.id, True,
            members=tuple(item.node.id for item, _off in nodes),
            member_frames=tuple(item.frame.id for item, _off in frames),
            collapsed_size=(COMPACT_W, COMPACT_MIN_H)))
        scene.apply_nudge(moves, frame_rects)
        scene.undo_stack.endMacro()

    def apply_stacking(self) -> None:
        """Take the frame's place in the stacking order. Frames have their
        own band below the wires, so restacking them can never lift one
        over a node — until one collapses, at which point it stops being a
        backdrop and becomes a box in the flow (see COLLAPSED_FRAME_Z)."""
        band = COLLAPSED_FRAME_Z if self.collapsed else FRAME_Z
        self.setZValue(z_for(band, self.frame.z))

    @property
    def collapsed(self) -> bool:
        return bool(self.frame.collapsed)

    def scene_rect(self) -> QRectF:
        """The region the frame occupies, in scene coordinates.

        While collapsed this is the small box itself, not the region it will
        grow back into — a folded frame owns no canvas it isn't drawing, so
        it cannot absorb or drag whatever it happens to be parked over.
        """
        return QRectF(self.pos().x(), self.pos().y(), *self._size)

    def display_size(self) -> tuple[float, float]:
        """What the frame draws and hit-tests as. The same as its rect now
        that collapsing really shrinks it; kept as the name every geometry
        method reads through."""
        return self._size

    def display_rect(self) -> QRectF:
        return self.scene_rect()

    def expanded_rect(self) -> QRectF:
        """Where the frame would sit if opened here — its box while expanded,
        and the region it will grow back into while collapsed. Only for
        working out what an expand would land on top of."""
        width, height = self.frame.expanded_size or self._size
        return QRectF(self.pos().x(), self.pos().y(), width, height)

    def boundingRect(self) -> QRectF:
        w, h = self.display_size()
        if not self.collapsed:
            return QRectF(-1, -1, w + 2, h + 2)
        # the name floats above the square and the status LED below it, both
        # outside the body — the same overhang a compact node's bounds allow
        name = self._name_rect()
        return QRectF(-1, -1, w + 2, h + 2).united(name).united(
            self._status_rect())

    def _handle_rect(self) -> QRectF:
        w, h = self.display_size()
        return QRectF(w - HANDLE, h - HANDLE, HANDLE, HANDLE)

    def _toggle_rect(self) -> QRectF:
        """The collapse chevron. Just inside the title bar's left edge when
        expanded; tucked into the square's top-left corner when collapsed,
        where the title bar it used to live in no longer exists."""
        if self.collapsed:
            return QRectF(3, 3, TOGGLE_W, TOGGLE_H)
        return QRectF(7, TITLE_H / 2 - TOGGLE_H / 2, TOGGLE_W, TOGGLE_H)

    def _edge_at(self, pos: QPointF) -> str | None:
        """Which resize edge/corner (if any) a point grabs: "right",
        "bottom", "left", "corner" (bottom-right), or None.

        Never anything while collapsed. A resize writes the dragged size
        straight into frame.rect, so grabbing the little box's edge would
        overwrite the expanded region with 60x60 and lose it for good.
        """
        if self.collapsed:
            return None
        w, h = self._size
        near_right = w - EDGE_MARGIN <= pos.x() <= w + EDGE_MARGIN
        near_bottom = h - EDGE_MARGIN <= pos.y() <= h + EDGE_MARGIN
        near_left = -EDGE_MARGIN <= pos.x() <= EDGE_MARGIN
        within_h = -EDGE_MARGIN <= pos.y() <= h + EDGE_MARGIN
        within_w = -EDGE_MARGIN <= pos.x() <= w + EDGE_MARGIN
        if self._handle_rect().contains(pos) or (near_right and near_bottom):
            return "corner"
        if near_right and within_h:
            return "right"
        if near_bottom and within_w:
            return "bottom"
        if near_left and within_h:
            return "left"
        return None

    def _run_button_rect(self) -> QRectF:
        """The play glyph in the title bar. Empty while collapsed — 60px of
        square has no room for a title, a chevron and a play button, so the
        square keeps the chevron and running moves to the context menu."""
        if self.collapsed:
            return QRectF()
        w, _h = self._size
        return QRectF(w - RUN_BTN - 4.0, (TITLE_H - RUN_BTN) / 2, RUN_BTN, RUN_BTN)

    # ------------------------------------------------- collapsed box chrome

    def _name_font(self) -> QFont:
        font = QFont()
        font.setPointSizeF(COMPACT_NAME_FONT_SIZE)
        return font

    def _name_layout(self) -> list[str]:
        """The title split into lines that fit COMPACT_NAME_MAX_W, so a long
        frame name reads above the square instead of being cut in half."""
        text = self.frame.title or "Frame"
        metrics = QFontMetrics(self._name_font())
        if metrics.horizontalAdvance(text) <= COMPACT_NAME_MAX_W:
            return [text]
        lines: list[str] = []
        current = ""
        for word in text.split():
            candidate = f"{current} {word}".strip()
            if current and metrics.horizontalAdvance(candidate) > COMPACT_NAME_MAX_W:
                lines.append(current)
                current = word
            else:
                current = candidate
            if len(lines) == 2:     # two lines is the budget; elide the rest
                break
        if current and len(lines) < 2:
            lines.append(current)
        elif current:
            lines[-1] = metrics.elidedText(f"{lines[-1]} {current}",
                                           Qt.ElideRight,
                                           int(COMPACT_NAME_MAX_W))
        return lines or [text]

    def _name_rect(self) -> QRectF:
        """Local-coordinate rect of the title above the collapsed square. It
        may overhang the box on both sides, as a compact node's name does."""
        width, _h = self.display_size()
        height = COMPACT_NAME_H * len(self._name_layout())
        return QRectF(width / 2 - COMPACT_NAME_MAX_W / 2,
                      -COMPACT_NAME_GAP - height,
                      COMPACT_NAME_MAX_W, height)

    def _status_rect(self) -> QRectF:
        """Local-coordinate strip under the collapsed square holding the
        frame's own status LED."""
        width, height = self.display_size()
        return QRectF(0, height + COMPACT_STATUS_GAP, width, COMPACT_STATUS_H)

    # ------------------------------------------------------------- painting

    def paint(self, painter: QPainter, option, widget=None) -> None:
        if self.collapsed:
            self._paint_collapsed(painter)
            return
        w, h = self._size
        body = QRectF(0, 0, w, h)
        color = QColor(self.frame.color)
        fill = QColor(color)
        fill.setAlphaF(0.18)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setBrush(QBrush(fill))
        painter.setPen(QPen(theme.SELECTION_OUTLINE if self.isSelected()
                            else color, 1.5))
        painter.drawRoundedRect(body, 6, 6)

        title_bg = QColor(color)
        title_bg.setAlphaF(0.45)
        painter.setBrush(QBrush(title_bg))
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(QRectF(0, 0, w, TITLE_H), 6, 6)

        self._paint_toggle(painter)

        painter.setPen(QPen(theme.FRAME_TITLE))
        font = painter.font()
        font.setBold(True)
        font.setPointSizeF(9.0)
        painter.setFont(font)
        # the title starts clear of the chevron now sitting at the left edge
        text_left = self._toggle_rect().right() + 6
        painter.drawText(QRectF(text_left, 0,
                                w - text_left - RUN_BTN - 10, TITLE_H),
                         Qt.AlignVCenter | Qt.AlignLeft, self.frame.title)

        btn = self._run_button_rect()
        chip = QColor(color)
        chip.setAlphaF(0.65 if self._hover_run else 0.4)
        painter.setBrush(QBrush(chip))
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(btn, 4, 4)
        painter.setBrush(QBrush(theme.FRAME_TITLE))
        tri = QPainterPath()
        cx, cy = btn.center().x(), btn.center().y()
        tri.moveTo(cx - 3, cy - 5)
        tri.lineTo(cx - 3, cy + 5)
        tri.lineTo(cx + 5, cy)
        tri.closeSubpath()
        painter.drawPath(tri)

        painter.setPen(QPen(color, 1.2))
        hr = self._handle_rect()
        for i in (4.0, 8.0, 12.0):
            painter.drawLine(QPointF(hr.right() - i, hr.bottom() - 2),
                             QPointF(hr.right() - 2, hr.bottom() - i))

    def _paint_toggle(self, painter: QPainter) -> None:
        """A disclosure triangle: pointing down when the frame is open, right
        when it is folded — the way a tree view's does, and the same glyph a
        node uses to gather its ports."""
        rect = self._toggle_rect()
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(theme.FRAME_TITLE))
        path = QPainterPath()
        if self.collapsed:
            path.moveTo(rect.left() + 1, rect.top())
            path.lineTo(rect.right() - 2, rect.center().y())
            path.lineTo(rect.left() + 1, rect.bottom())
        else:
            path.moveTo(rect.left(), rect.top() + 1)
            path.lineTo(rect.right(), rect.top() + 1)
            path.lineTo(rect.center().x(), rect.bottom() - 1)
        path.closeSubpath()
        painter.drawPath(path)
        painter.restore()

    def _paint_collapsed(self, painter: QPainter) -> None:
        """The frame folded down to a node: name above, square body carrying
        one indicator per contained node, its own status LED below.

        Built from the compact node's measurements rather than its own, so a
        collapsed frame reads as a node on the canvas instead of as a small
        frame.
        """
        width, height = self.display_size()
        body = QRectF(0, 0, width, height)
        color = QColor(self.frame.color)
        painter.setRenderHint(QPainter.Antialiasing)
        fill = QColor(color)
        fill.setAlphaF(0.45)
        painter.setBrush(QBrush(fill))
        painter.setPen(QPen(theme.SELECTION_OUTLINE if self.isSelected()
                            else color, 1.5))
        painter.drawRoundedRect(body, 6, 6)

        self._paint_toggle(painter)
        self._paint_matrix(painter, body)

        painter.setPen(QPen(theme.NODE_TEXT))
        painter.setFont(self._name_font())
        name_rect = self._name_rect()
        for i, line in enumerate(self._name_layout()):
            painter.drawText(
                QRectF(name_rect.left(), name_rect.top() + i * COMPACT_NAME_H,
                       name_rect.width(), COMPACT_NAME_H),
                Qt.AlignCenter, line)

        status = self._status_rect()
        self._paint_frame_led(painter, width / 2, status.center().y())

    # ------------------------------------------------------- members/status

    def set_members(self, node_ids) -> None:
        """Tell the box which nodes it is standing in for, in execution
        order. The scene owns this list — it is captured when the frame
        folds and cleared when it opens, rather than re-derived from the
        rect on every repaint, because the vacated region still looks like
        empty canvas and anything dropped into it must not be swallowed."""
        members = list(node_ids)
        if members != self._members:
            self._members = members
            self.refresh_status()

    def member_ids(self) -> list[str]:
        return list(self._members)

    def _member_nodes(self) -> list:
        graph = getattr(self.scene(), "graph", None)
        if graph is None:
            return []
        return [graph.nodes[nid] for nid in self._members if nid in graph.nodes]

    def status_counts(self) -> dict:
        """How many members sit in each status — the numbers behind the LED."""
        counts: dict = {}
        for node in self._member_nodes():
            counts[node.status] = counts.get(node.status, 0) + 1
        return counts

    def aggregate(self) -> tuple:
        """(status, progress, stale) for the frame as a whole.

        The worst news wins: one broken node makes the frame broken, however
        cheerful the rest are. Progress is the share of members finished —
        the frame has no fraction of its own to report, and counting what is
        done is the honest reading of "how far through are we".
        """
        nodes = self._member_nodes()
        if not nodes:
            return (NodeStatus.IDLE, 0.0, False)
        statuses = [n.status for n in nodes]
        done = sum(1 for s in statuses if s == NodeStatus.DONE)
        progress = done / len(nodes)
        if NodeStatus.ERROR in statuses:
            return (NodeStatus.ERROR, progress, False)
        if NodeStatus.RUNNING in statuses:
            return (NodeStatus.RUNNING, progress, False)
        if NodeStatus.QUEUED in statuses:
            return (NodeStatus.QUEUED, progress, False)
        if done == len(nodes):
            return (NodeStatus.DONE, progress,
                    any(n.dirty for n in nodes))
        return (NodeStatus.IDLE, progress, False)

    def refresh_status(self) -> None:
        """Re-read the members' statuses — called when any of them changes,
        and on collapse. Drives the pulse the same way a node's does: a frame
        that is running but has nothing finished yet has no fraction to draw,
        so it breathes instead."""
        status, progress, _stale = self.aggregate()
        if self.collapsed and status == NodeStatus.RUNNING and not progress:
            self._start_pulse()
        else:
            self._stop_pulse()
        self._refresh_status_tooltip()
        self.update()

    def _refresh_status_tooltip(self) -> None:
        if not self.collapsed:
            self.setToolTip("")
            return
        counts = self.status_counts()
        total = len(self._members)
        if not total:
            self.setToolTip(f"{self.frame.title} — empty")
            return
        done = counts.get(NodeStatus.DONE, 0)
        parts = [f"{done} of {total} done"]
        for status, word in ((NodeStatus.RUNNING, "running"),
                             (NodeStatus.QUEUED, "queued"),
                             (NodeStatus.ERROR, "failed"),
                             (NodeStatus.IDLE, "idle")):
            if counts.get(status):
                parts.append(f"{counts[status]} {word}")
        self.setToolTip(f"{self.frame.title} — " + " · ".join(parts))

    # ---------------------------------------------------------- the matrix

    def _matrix_start(self, total: int) -> int:
        """Index of the first member the grid shows.

        The window holds still until the run reaches the middle of it, then
        follows the frontier — so a long frame's lights sweep past rather
        than the interesting end always being off the bottom. When it has
        scrolled, the first cell becomes a "+z" count of what went by, which
        costs a slot and leaves MATRIX_CELLS - 1 for members.
        """
        if total <= MATRIX_CELLS:
            return 0
        nodes = self._member_nodes()
        frontier = 0
        for i, node in enumerate(nodes):
            if node.status != NodeStatus.IDLE:
                frontier = i
        middle = MATRIX_CELLS // 2      # 4, for a 3x3
        if frontier <= middle:
            return 0
        return min(frontier - middle, total - (MATRIX_CELLS - 1))

    def matrix_layout(self) -> tuple:
        """(start, shown) — where the window sits and which members it
        holds. Split out from painting so the arithmetic can be tested
        without a canvas."""
        ids = self._members
        start = self._matrix_start(len(ids))
        if start == 0:
            return (0, ids[:MATRIX_CELLS])
        return (start, ids[start:start + MATRIX_CELLS - 1])

    def _paint_matrix(self, painter: QPainter, body: QRectF) -> None:
        """One status light per contained node, in execution order.

        Where a compact node draws its mark, a collapsed frame draws the
        flow inside it: the same indicator, nine at a time, so a run can be
        watched through the closed lid. Cells never move within the window —
        cell i is always member start + i — because a light you cannot tie
        back to a node is decoration.
        """
        start, shown = self.matrix_layout()
        if not shown:
            return
        inner = body.adjusted(MATRIX_INSET, MATRIX_INSET,
                              -MATRIX_INSET, -MATRIX_INSET)
        step_x = inner.width() / MATRIX_COLS
        step_y = inner.height() / MATRIX_COLS
        radius = min(step_x, step_y) * 0.32
        graph = getattr(self.scene(), "graph", None)

        def centre(slot: int) -> tuple:
            row, col = divmod(slot, MATRIX_COLS)
            return (inner.left() + step_x * (col + 0.5),
                    inner.top() + step_y * (row + 0.5))

        slot = 0
        if start:
            # the leading cell counts what has already scrolled past
            cx, cy = centre(0)
            painter.setPen(QPen(theme.NODE_SUBTEXT))
            font = QFont()
            font.setPointSizeF(6.5)
            painter.setFont(font)
            painter.drawText(QRectF(cx - step_x / 2, cy - step_y / 2,
                                    step_x, step_y),
                             Qt.AlignCenter, f"+{start}")
            slot = 1

        for node_id in shown:
            node = graph.nodes.get(node_id) if graph is not None else None
            if node is None:
                slot += 1
                continue
            cx, cy = centre(slot)
            paint_status_led(painter, cx, cy,
                             status=node.status,
                             progress=node.progress,
                             pulse=self._pulse,
                             stale=node.dirty,
                             behind=QColor(self.frame.color),
                             radius=radius)
            slot += 1

    def _paint_frame_led(self, painter: QPainter, cx: float, cy: float) -> None:
        status, progress, stale = self.aggregate()
        paint_status_led(painter, cx, cy,
                         status=status,
                         progress=progress,
                         pulse=self._pulse,
                         stale=stale,
                         behind=theme.CANVAS_BG,
                         radius=LED_RADIUS)

    # ----------------------------------------------------------- the pins

    def layout_pins(self, inputs: list, outputs: list) -> None:
        """Stack the crossing wires' pins down each edge of the box.

        Inputs left, outputs right, starting at COMPACT_PORT_TOP and running
        at ROW_H — the same rhythm a compact node's pins use, so the two read
        as the same kind of thing. The spacing never compresses: a frame with
        fifteen crossing wires simply runs its pins past the bottom of the
        box and onto the canvas, which is the honest thing to do. Squeezing
        them back inside 60px would recreate exactly the overlapping-blob
        problem the stacking exists to avoid.
        """
        width, _height = self.display_size()
        gap = PortItem.RADIUS + PORT_EDGE_GAP
        for ports, x in ((inputs, -gap), (outputs, width + gap)):
            for i, pin in enumerate(ports):
                pin.setPos(x, COMPACT_PORT_TOP + ROW_H * i)

    def carried_items(self) -> tuple:
        """What a drag of this frame takes with it: ([(node_item, offset)],
        [(frame_item, offset)]).

        While collapsed this is exactly the membership written down when it
        folded — *not* whatever sits under the box. A folded frame is a 60px
        square that can be parked anywhere, and dragging it must never pick
        up the nodes it happens to be sitting on.

        While expanded, nodes by their centre and nested frames by full
        containment — the ordinary rule, over a region you can see. Blind to
        visibility either way, since a collapsed frame's own contents are
        hidden and must still travel with it.
        """
        scene = self.scene()
        if scene is None:
            return ([], [])
        if self.collapsed:
            nodes = [(item, item.pos() - self.pos())
                     for item in (scene.node_items.get(n)
                                  for n in self.frame.members)
                     if item is not None]
            frames = [(item, item.pos() - self.pos())
                      for item in (scene.frame_items.get(f)
                                   for f in self.frame.member_frames)
                      if item is not None]
            return (nodes, frames)
        rect = self.scene_rect()
        nodes = [(item, item.pos() - self.pos())
                 for item in scene.node_items.values()
                 if rect.contains(item.sceneBoundingRect().center())]
        frames = [(other, other.pos() - self.pos())
                  for other in scene.frame_items.values()
                  if other is not self and rect.contains(other.scene_rect())]
        return (nodes, frames)

    def set_pins_visible(self, visible: bool) -> None:
        """Hide the pins when the canvas flattens for zoom, matching the real
        pins — names for pins nobody can see are noise."""
        for child in self.childItems():
            if isinstance(child, PortItem):
                child.setVisible(visible)

    # --------------------------------------------------------------- pulse

    def _start_pulse(self) -> None:
        """Breathe the indicators while the frame is running but has nothing
        finished to show. Mirrors NodeItem's pulse exactly, teardown
        included — a QVariantAnimation left running past its item is the
        known crash-on-shutdown in this codebase."""
        if self._pulse_anim is not None:
            return
        anim = QVariantAnimation()
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setDuration(1200)
        anim.setLoopCount(-1)

        def tick(value: float) -> None:
            self._pulse = value * 2 if value <= 0.5 else (1 - value) * 2
            self.update()

        anim.valueChanged.connect(tick)
        anim.start()
        self._pulse_anim = anim

    def _stop_pulse(self) -> None:
        if self._pulse_anim is not None:
            self._pulse_anim.stop()
            self._pulse_anim.deleteLater()
            self._pulse_anim = None
        self._pulse = 0.0

    # ------------------------------------------------------------ behaviour

    def hoverMoveEvent(self, event) -> None:
        if self._toggle_rect().contains(event.pos()):
            self.setCursor(Qt.PointingHandCursor)
            self.setToolTip("Expand this frame" if self.collapsed
                            else "Collapse this frame to a single box")
            if self._hover_run:
                self._hover_run = False
                self.update()
            super().hoverMoveEvent(event)
            return
        hovering = self._run_button_rect().contains(event.pos())
        if hovering != self._hover_run:
            self._hover_run = hovering
            self.setToolTip("Run the nodes in this frame" if hovering else "")
            self.update()
            if not hovering:
                self._refresh_status_tooltip()
        if hovering:
            self.setCursor(Qt.PointingHandCursor)
        else:
            edge = self._edge_at(event.pos())
            if edge == "corner":
                self.setCursor(Qt.SizeFDiagCursor)
            elif edge in ("right", "left"):
                self.setCursor(Qt.SizeHorCursor)
            elif edge == "bottom":
                self.setCursor(Qt.SizeVerCursor)
            else:
                self.setCursor(Qt.ArrowCursor)
        super().hoverMoveEvent(event)

    def hoverLeaveEvent(self, event) -> None:
        if self._hover_run:
            self._hover_run = False
            self.update()
        self.unsetCursor()
        super().hoverLeaveEvent(event)

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionChange and self._dragging \
                and snapping_active(self.scene()):
            step = grid_step(self.scene())
            x, y = snap_point(value.x(), value.y(), step)
            return QPointF(x, y)
        if change == QGraphicsItem.ItemPositionHasChanged:
            # Wherever the move came from — this frame's own drag, a
            # multi-selection, a parent frame carrying it, the model syncing
            # back — the wires pinned to the box have to follow. NodeItem
            # repaths from here for exactly this reason; doing it in the
            # mouse handler instead is what left a nested collapsed frame
            # trailing its wires from where it started until you let go.
            scene = self.scene()
            if scene is not None:
                scene.frame_item_moved(self.frame.id)
        return super().itemChange(change, value)

    def mousePressEvent(self, event) -> None:
        if self._toggle_rect().contains(event.pos()):
            # same button-style deal as the run glyph below: act on release
            # so a slightly sloppy click doesn't also drag the frame
            self._toggle_pressed = True
            event.accept()
            return
        if self._run_button_rect().contains(event.pos()):
            # emit on release, button-style; without swallowing the drag
            # here a slightly sloppy click would also move the frame
            self._run_pressed = True
            event.accept()
            return
        self._press_scene_pos = event.scenePos()
        self._press_pos = self.pos()
        self._press_size = self._size
        edge = self._edge_at(event.pos())
        if edge is not None:
            self._resizing = True
            self._resize_edge = edge
            event.accept()
            return
        scene = self.scene()
        self._grabbed = []
        if (event.button() == Qt.LeftButton and self.isSelected()
                and scene is not None and len(scene._selected_movables()) > 1):
            # Part of a multi-selection: move as a uniform group so every
            # selected node/frame snaps and commits together. Skip the
            # content-grab — a node that's both inside and independently
            # selected would otherwise be moved twice.
            super().mousePressEvent(event)
            self._group_starts = scene.begin_group_drag()
            return
        # Single-frame drag: carry whatever sits inside.
        self._grabbed, self._grabbed_frames = self.carried_items()
        if event.button() == Qt.LeftButton:
            self._dragging = True  # snap the frame's position while moving
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._run_pressed or self._toggle_pressed:
            event.accept()
            return
        if self._resizing:
            delta = event.scenePos() - self._press_scene_pos
            edge = self._resize_edge
            press_w, press_h = self._press_size
            width, height = press_w, press_h
            if edge in ("right", "corner"):
                width = press_w + delta.x()
            if edge in ("bottom", "corner"):
                height = press_h + delta.y()
            if edge == "left":
                width = press_w - delta.x()
            if snapping_active(self.scene(), event.modifiers()):
                step = grid_step(self.scene())
                width = snap(width, step)
                height = snap(height, step)
            width = max(120.0, width)
            height = max(60.0, height)
            if edge == "left":
                self.setPos(self._press_pos.x() + press_w - width,
                           self.pos().y())
            self.prepareGeometryChange()
            self._size = (width, height)
            self.update()
            event.accept()
            return
        super().mouseMoveEvent(event)
        for item, offset in self._grabbed:
            item.setPos(self.pos() + offset)
        for item, offset in self._grabbed_frames:
            item.setPos(self.pos() + offset)
        # no repathing here: every setPos above lands in itemChange, which
        # does it for this frame and for each one riding along

    def mouseReleaseEvent(self, event) -> None:
        scene = self.scene()
        self._dragging = False
        if self._toggle_pressed:
            self._toggle_pressed = False
            if self._toggle_rect().contains(event.pos()):
                self.toggle_collapsed()
            event.accept()
            return
        if self._run_pressed:
            self._run_pressed = False
            if self._run_button_rect().contains(event.pos()):
                self.run_requested.emit(self.frame.id)
            event.accept()
            return
        if self._resizing:
            self._resizing = False
            self._resize_edge = None
            scene.push_frame_rect(self.frame.id, self.pos(), self._size)
            event.accept()
            return
        super().mouseReleaseEvent(event)
        if self._group_starts is not None:
            # Multi-selection drag: the scene commits the whole selection.
            scene.commit_group_move(self._group_starts)
            self._group_starts = None
            return
        if self.pos() != self._press_pos:
            moves = {}
            for item, offset in self._grabbed:
                old = self._press_pos + offset
                moves[item.node.id] = ((old.x(), old.y()),
                                       (item.pos().x(), item.pos().y()))
            nested = {item.frame.id: (item.pos().x(), item.pos().y(),
                                      *item._size)
                      for item, _offset in self._grabbed_frames}
            scene.push_frame_move(self.frame.id, self.pos(), self._size,
                                  moves, nested)
        self._grabbed = []
        self._grabbed_frames = []

    def mouseDoubleClickEvent(self, event) -> None:
        if (self._run_button_rect().contains(event.pos())
                or self._toggle_rect().contains(event.pos())):
            event.accept()
            return
        title, ok = QInputDialog.getText(None, "Frame title", "Title:",
                                         text=self.frame.title)
        if ok and title.strip():
            self.scene().push_frame_title(self.frame.id, title.strip())
        event.accept()
