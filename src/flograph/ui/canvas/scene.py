"""NodeGraphScene: a *view* of core.Graph.

One-way data flow: item interactions never mutate the graph directly — they
push QUndoCommands; command.redo() mutates the graph; graph events come back
here and update the items. Undo/redo, project load, and palette insertion all
travel the same path.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QPointF, QRectF, QTimer, Signal
from PySide6.QtGui import QUndoStack
from PySide6.QtWidgets import QGraphicsScene

from flograph.core import (
    Connection, Frame, Graph, NodeInstance, NodeRegistry, PortSpec, can_connect,
)
from flograph.core.node import NodeStatus
from flograph.core.ports import is_flow

from ..commands import (
    AddNodeCommand, ConnectCommand, DisconnectCommand, MoveNodesCommand,
    RemoveSelectionCommand, SetCompactViewCommand, SetLabelCommand,
    SetNodeColorCommand, SetNodeMarkCommand, UpdateFrameCommand,
)
from .base_view import SCENE_MARGIN
from .connection_item import ConnectionItem, PendingConnectionItem
from .frame_item import FrameItem
from .node_item import (
    DEFAULT_LOD_THRESHOLD, NodeItem, PortItem, compact_on,
)
from .stacking import LAYER_LABELS

#: The half-extent of the world-sized span used whenever the scroll bars are
#: hidden. Large enough that a drag pan never reaches an edge, so the canvas
#: feels infinite — which is the point of it when there are no bars to give
#: the span a visible meaning.
SCENE_EXTENT = 1_000_000.0
_WORLD_RECT = QRectF(-SCENE_EXTENT, -SCENE_EXTENT,
                     2 * SCENE_EXTENT, 2 * SCENE_EXTENT)

REROUTE_TYPE = "flograph.util.reroute"
#: Breathing room left inside a frame that had to stretch to hold a nested
#: one reopening (see _grow_enclosing) — flush against the parent's edge
#: reads as overflowing it.
_ENCLOSE_PAD = 16.0
#: The floor a frame cannot be taken below by undoing a stretch, matching
#: what a resize drag allows (see FrameItem.mouseMoveEvent).
_MIN_FRAME_W = 120.0
_MIN_FRAME_H = 60.0
#: Clearance left between a reopened frame and whatever it pushed out of the
#: way. Landing exactly on the edge is arithmetically correct and looks like
#: a collision — the node appears stuck to the frame rather than beside it.
NUDGE_GAP = 20.0


class ContentFittedSceneRect:
    """Keeps `sceneRect` fitted to the content plus a margin, on a debounce —
    but only while the scroll bars are shown.

    The scroll bars map the whole span onto their length, so a world-sized
    rect makes them hair-triggered: one pixel of bar is thousands of canvas
    pixels, and the smallest drag sends everything past like a bullet.
    Fitted to the flow, a bar pixel moves at canvas speed — and the span
    grows (after a beat) as the flow does.

    With the bars hidden there is nothing to keep honest, and a fitted span
    only gets in the way: the view cannot scroll outside its `sceneRect`, so
    fitting it walls a drag pan in at the edge of the flow. So the span goes
    back to world-sized and the canvas feels infinite again. The scroll-bar
    setting drives the switch — see `set_rect_fitted`, called from
    `ZoomPanGraphicsView._apply_scrollbar_policy`.
    """

    def _install_rect_fit(self) -> None:
        self._rect_fitted = False
        self._rect_timer = QTimer(self)
        self._rect_timer.setSingleShot(True)
        self._rect_timer.setInterval(250)
        self._rect_timer.timeout.connect(self._fit_scene_rect)
        self.changed.connect(self._queue_rect_fit)
        self.setSceneRect(_WORLD_RECT)

    def set_rect_fitted(self, fitted: bool) -> None:
        """Fit the span to the flow (so the scroll bars stay proportional) or
        let it be world-sized (so a pan is never walled in). Driven by the
        scroll-bar setting: bars on → fitted, bars off → world."""
        fitted = bool(fitted)
        if fitted == self._rect_fitted:
            return
        self._rect_fitted = fitted
        if fitted:
            self._fit_scene_rect()
        else:
            self._rect_timer.stop()
            self.setSceneRect(_WORLD_RECT)

    def _queue_rect_fit(self, *_regions) -> None:
        if self._rect_fitted and not self._rect_timer.isActive():
            self._rect_timer.start()

    def flush_rect_fit(self) -> None:
        """Refit right now instead of after the debounce. Navigation that
        centres on a point must do this first: the view cannot scroll
        outside the span, so a jump to a node the stale span doesn't cover
        would land short of centre. A no-op while the span is world-sized —
        it already covers everywhere."""
        if not self._rect_fitted:
            return
        if self._rect_timer.isActive():
            self._rect_timer.stop()
        self._fit_scene_rect()

    def _fit_scene_rect(self) -> None:
        target = self.itemsBoundingRect().adjusted(
            -SCENE_MARGIN, -SCENE_MARGIN, SCENE_MARGIN, SCENE_MARGIN)
        # wherever the views are right now stays reachable: Esc-restore,
        # a minimap click into empty margin, a jump to the far side — none
        # may be clamped back by the refit that follows them
        for view in self.views():
            visible = view.mapToScene(view.viewport().rect()).boundingRect()
            target = target.united(visible)
        if target != self.sceneRect():
            # setSceneRect itself emits changed for the redrawn regions;
            # the equality check above is what stops that re-queueing us
            # forever, so nothing here may be blocked — the views still
            # need sceneRectChanged to retune their scroll ranges
            self.setSceneRect(target)


def plan_nudge(box: QRectF, region: QRectF, units: list,
               gap: float = NUDGE_GAP) -> dict:
    """How far each unit moves when a folded frame reopens into `region`.

    `box` is the little square as it stands; `region` is what it is about to
    become, growing down and right from that same top-left corner. `units` is
    [(key, QRectF)], where a unit is one movable thing: a lone node, or a
    frame taken *together with everything inside it*. Frames move whole —
    pushing their contents out from under them instead would empty the frame,
    which is the thing an expanding neighbour must never do.

    Two questions, answered separately: **which** things move, and **how far**.

    Which: draw a line straight down from the square's bottom-right corner.
    Everything at or beyond it goes right, along with anything standing under
    the square itself. Everything below the square that still falls in the
    column the frame is about to occupy goes down. Everything else — to the
    left, or above — is not in the frame's way and is never touched. So most
    things go right, and only what is genuinely underneath goes down.

    Nothing that **starts** to the left of the square is ever moved, not even
    if it reaches across and overlaps it. A frame is only ever going to grow
    right and down, so its left-hand neighbour cannot be in its way; and a
    wide frame whose right-hand edge happens to overlap the little box would
    otherwise be flung the whole width of the region to "clear" it, which is
    a violent answer to a collision the expand did not create.

    How far: the least that clears the region **plus `gap`**, and nothing at
    all if the region is already clear. The clearance is not cosmetic
    padding — landing a node exactly on the frame's edge is arithmetically
    right and reads as a collision, the node looking stuck to the frame
    rather than standing beside it. That last part matters more than it sounds. A frame that
    folds and reopens with nothing else changed must land exactly where it
    was, because the space it is growing back into is the space it vacated.
    Shifting by the width gained regardless looks the same on screen but
    ratchets: fold and unfold a frame three times and the canvas to the right
    of it has walked 1200px away, and folding again cannot pull it back
    because on each fold there was nothing recorded to put back.

    Within a group the shift is **uniform** — everything that moves, moves by
    the same amount — and that is what keeps a layout intact across an expand:
    same spacing, same alignment, same relative order, and the gaps either
    side of the frame exactly as they were. Shoving each unit just far enough
    to clear the one before it compounds instead: the second thing along is
    pushed past the first, the third past the second, and a tidy row comes
    back fanned out with the far end flung twice as far as it should be.

    The classification is exhaustive over things that are actually in the way,
    which is the property worth holding on to. Anything overlapping the region
    either sits under the square or reaches past the line (so it goes right),
    or is clear below it in the column (so it goes down); nothing in the way
    falls through. Each mover then clears the region by construction, since
    the shift is the largest any of them needed — and clears it by `gap` at
    the very least.

    Pure geometry, no scene: the awkward part of this is the arithmetic, and
    it is worth being able to test it without a canvas.
    """
    right: list = []
    down: list = []
    for key, rect in units:
        under = rect.intersects(box) and rect.left() >= box.left()
        if rect.left() >= box.right() or under:
            right.append((key, rect))
        elif rect.top() >= box.bottom() and rect.right() > box.left():
            down.append((key, rect))
    dx = max([region.right() + gap - rect.left()
              for _key, rect in right if rect.intersects(region)] or [0.0])
    dy = max([region.bottom() + gap - rect.top()
              for _key, rect in down if rect.intersects(region)] or [0.0])
    delta: dict = {}
    if dx > 0:
        delta.update({key: (dx, 0.0) for key, _rect in right})
    if dy > 0:
        delta.update({key: (0.0, dy) for key, _rect in down})
    return delta


class NodeGraphScene(QGraphicsScene, ContentFittedSceneRect):
    node_double_clicked = Signal(str)   # node_id
    node_window_requested = Signal(str)  # node_id — Ctrl+double-click
    node_rename_requested = Signal(str)  # node_id — header was double-clicked
    wire_dropped = Signal(object, QPointF)  # fixed PortItem, scene pos
    button_fired = Signal(str)          # node_id — an Action Button was clicked
    slicer_changed = Signal(str)        # node_id — a Slicer's selection changed
    control_changed = Signal(str)       # node_id — an input control was moved
    frame_run_requested = Signal(str)   # frame_id — a frame's run glyph was clicked
    tables_kept = Signal(list)          # node_ids — Tables that kept their
                                        # contents as their input was cut
    canvas_drag_changed = Signal(bool)  # a wire or selection drag started / ended

    def __init__(self, graph: Graph, undo_stack: QUndoStack,
                 registry: Optional[NodeRegistry] = None, parent=None) -> None:
        super().__init__(parent)
        self.graph = graph
        self.undo_stack = undo_stack
        self.registry = registry
        # The engine's OutputCache, injected by the main window once the
        # engine exists. Only used to freeze what a linked Table is showing
        # before its wire is cut (see _push_orphan_snapshots); None simply
        # means no snapshot, which is what a scene without an engine wants.
        self.output_cache = None
        # Nodes with a re-run queued but not yet started, injected by the
        # main window from the engine (see set_requested_nodes). Cards fade
        # their output previews from it, so a scene without an engine simply
        # never fades anything.
        self.requested_nodes: frozenset = frozenset()
        self.node_items: dict[str, NodeItem] = {}
        self.connection_items: dict[str, ConnectionItem] = {}
        # Goto/From links that have asked to be drawn, keyed by link id. Not
        # a wire and not in graph.connections — see canvas.link_line.
        self.link_line_items: dict[str, "LinkLineItem"] = {}
        self.frame_items: dict[str, FrameItem] = {}
        # --- collapsed frames (see _refresh_collapsed_frames) --------------
        # Which nodes each collapsed frame is standing in for. Mirrors
        # Frame.members, which the frame wrote down when it folded — never
        # derived from geometry here, so undo gives back exactly the
        # membership it took and a folded box parked over other nodes cannot
        # adopt them.
        self._hidden: dict[str, list[str]] = {}
        self._hidden_frames: dict[str, list[str]] = {}
        # One pin per crossing wire end, keyed (conn_id, "src"|"dst").
        self._frame_pins: dict[tuple, "FramePortItem"] = {}
        # Set while a bulk load replaces the graph node by node; the rebuild
        # would otherwise run once per add and be quadratic in graph size.
        self._suspend_collapse_refresh = False
        # Asked before a collapsed frame takes its hidden contents with it.
        # The main window supplies a message box; left None (tests, headless)
        # the delete simply goes ahead.
        self.confirm_collapsed_delete = None
        self._zoom = 1.0  # last zoom pushed by the view, see set_lod

        # Zoom-out node simplification preference; the main window is the
        # sole writer (see MainWindow.set_lod_enabled/set_lod_threshold).
        self.lod_enabled = True
        self.lod_threshold = DEFAULT_LOD_THRESHOLD

        # Snap-to-grid view preference; the main window is the sole writer.
        from .grid import DEFAULT_STEP
        self.snap_enabled = True
        self.grid_step = DEFAULT_STEP
        # Whether the background grid is drawn — independent of snapping, same
        # sole writer (MainWindow.set_grid_visible).
        self.grid_visible = True

        # Canvas-wide "float the port names beside the pins" preference; the
        # main window is the sole writer (MainWindow.set_port_labels_enabled).
        # A node that has been toggled on its own ignores this — see
        # node_item.port_labels_on.
        self.port_labels_enabled = False

        # Transient: the reveal key is held down, so every port shows its
        # name regardless of the setting above or any per-node override.
        # Not a preference and never saved — see NodeGraphView's key handling.
        # It reveals the flow pins too: the moment you want to know what
        # connects to what is the moment you want to see all of it.
        self.revealing_port_labels = False

        # Canvas-wide "show the flow pins" preference — the pins an order
        # edge is drawn between (core.ports). Off by default, unlike every
        # other pin, because most canvases never draw one; the main window is
        # the sole writer. See node_item.flow_pins_on.
        self.flow_pins_enabled = False

        # Transient: an order edge is being dragged right now, so every flow
        # pin shows itself for the duration — you cannot aim at a pin that
        # is not on screen. Set by begin_wire_drag, cleared by _cleanup_drag.
        self.drawing_order_edge = False

        # Canvas-wide "draw plain nodes as squares" preference; the main
        # window is the sole writer (MainWindow.set_compact_nodes). Card
        # kinds are unaffected — see NodeItem.apply_compact.
        self.compact_nodes = True

        self._install_rect_fit()

        self._pending: Optional[PendingConnectionItem] = None
        self._drag_detach: Optional[Connection] = None
        self._tinted_port: Optional[PortItem] = None
        # nesting depth of node/frame group drags (begin_group_drag /
        # commit_group_move), so the view can edge-scroll for them too
        self._group_drags = 0
        # what a node dragged from the library is currently hovering over,
        # as graphics items — see drop_target_at / set_drop_hint
        self._drop_hint_conn: Optional[ConnectionItem] = None
        self._drop_hint_node: Optional[NodeItem] = None

        events = graph.events
        events.node_added.connect(self._on_node_added)
        events.node_removed.connect(self._on_node_removed)
        events.connected.connect(self._on_connected)
        events.disconnected.connect(self._on_disconnected)
        events.node_moved.connect(self._on_node_moved)
        events.code_changed.connect(self._on_code_changed)
        events.param_changed.connect(self._on_param_changed)
        events.status_changed.connect(self._on_status_changed)
        events.progress_changed.connect(self._on_progress_changed)
        events.dirty_changed.connect(self._on_dirty_changed)
        events.label_changed.connect(self._on_label_changed)
        events.description_changed.connect(self._on_description_changed)
        events.active_changed.connect(self._on_active_changed)
        events.locked_changed.connect(self._on_locked_changed)
        events.frozen_changed.connect(self._on_frozen_changed)
        events.manual_changed.connect(self._on_manual_changed)
        events.preview_enabled_changed.connect(self._on_preview_enabled_changed)
        events.port_labels_changed.connect(self._on_port_labels_changed)
        events.flow_pins_changed.connect(self._on_flow_pins_changed)
        events.ports_collapsed_changed.connect(
            self._on_ports_collapsed_changed)
        events.color_changed.connect(self._on_color_changed)
        events.mark_changed.connect(self._on_mark_changed)
        events.compact_view_changed.connect(self._on_compact_view_changed)
        events.links_changed.connect(self._refresh_link_cards)
        events.links_changed.connect(self._refresh_port_connections)
        events.links_changed.connect(self._refresh_link_lines)
        events.temp_edit_changed.connect(self._on_temp_edit_changed)
        events.frame_added.connect(self._on_frame_added)
        events.frame_removed.connect(self._on_frame_removed)
        events.frame_changed.connect(self._on_frame_changed)
        events.restacked.connect(self._on_restacked)

        # mirror pre-existing graph content (e.g. a loaded project)
        for node in graph.nodes.values():
            self._on_node_added(node)
        for conn in graph.connections.values():
            self._on_connected(conn)
        for frame in graph.frames.values():
            self._on_frame_added(frame)
        self._refresh_link_cards()
        self._refresh_link_lines()
        # frames were mirrored above, before any link line existed — fold
        # again now that they do, so a collapsed frame built straight over an
        # existing graph gets its link pins too
        self._refresh_collapsed_frames()
        # Goto/From pairs have no wire to trace, so selecting one end glows
        # the other -- the only on-canvas evidence that a link exists, short
        # of asking for the line itself (see _refresh_link_lines)
        self.selectionChanged.connect(self._highlight_link_partners)

    # ------------------------------------------------------- event mirrors

    def _on_node_added(self, node: NodeInstance) -> None:
        item = NodeItem(node)
        item.set_lod(self._flat_state())
        item.apply_compact(compact_on(node, self))
        item.apply_stacking()
        self.addItem(item)
        self.node_items[node.id] = item
        # After addItem, not before: whether the flow pins show is a question
        # about the *canvas*, and an item still outside the scene has no way
        # to ask it — it would answer "hidden" and stay that way.
        item._apply_port_visibility()
        item.refresh_link_card()  # its text needs the scene's graph to resolve
        # undoing a delete puts a collapsed frame's contents back; they have
        # to go straight back under the lid rather than appear on top of it
        self._refresh_collapsed_frames()
        # a node created inside a held frame is held from the start
        self.refresh_frame_holds()

    def _on_restacked(self, kind: str, page_id) -> None:
        """One kind's stacking order changed. Every item of that kind re-reads
        its own z rather than the event naming the movers: a restack
        renumbers the whole kind, so a partial update would leave stale
        z-values behind on the items that merely shifted along."""
        items = (self.node_items if kind == "node"
                 else self.frame_items if kind == "frame" else {})
        for item in items.values():
            item.apply_stacking()

    def _on_node_removed(self, node_id: str) -> None:
        item = self.node_items.pop(node_id, None)
        if item is not None:
            # before removeItem: a QMovie still delivering frames into a
            # deleted item is a crash, not a leak
            item.dispose_mark_image()
            # then free what the card was displaying: the item won't be
            # collected on its own (its own reference cycles pin it), so the
            # webview's renderer, the table model's frame and the figure
            # canvas would otherwise outlive the node
            item.teardown()
            self.removeItem(item)
        self._refresh_collapsed_frames()

    def _on_connected(self, conn: Connection) -> None:
        src = self.node_items[conn.src_node].port_item(conn.src_port, "output")
        dst = self.node_items[conn.dst_node].port_item(conn.dst_port, "input")
        item = ConnectionItem(conn, src, dst)
        self.addItem(item)
        self.connection_items[conn.id] = item
        dst.refresh_connected()  # input pin becomes filled
        if item.is_order:
            # both ends: an order edge is what keeps an otherwise hidden flow
            # pin on screen, at the source as much as the destination
            self._refresh_order_pins(conn)
        dst_node_item = self.node_items.get(conn.dst_node)
        if dst_node_item is not None and dst_node_item.table:
            dst_node_item.refresh_table_link()
        # a wire made through a collapsed frame's pin needs a pin of its own
        self._refresh_collapsed_frames()

    def _on_disconnected(self, conn: Connection) -> None:
        item = self.connection_items.pop(conn.id, None)
        if item is not None:
            self.removeItem(item)
        if is_flow(conn.dst_port):
            self._refresh_order_pins(conn)   # they may go back into hiding
        dst_item = self.node_items.get(conn.dst_node)
        if dst_item is not None:
            port = dst_item.port_item(conn.dst_port, "input")
            if port is not None:
                # not necessarily hollow now: a Goto/From link can still be
                # feeding this port after the drawn wire goes
                port.refresh_connected()
            if dst_item.table:
                dst_item.refresh_table_link()
        self._refresh_collapsed_frames()   # the orphaned pin must go

    def _on_node_moved(self, node_id: str, pos: tuple[float, float]) -> None:
        item = self.node_items.get(node_id)
        if item is not None and (item.pos().x(), item.pos().y()) != pos:
            item.setPos(*pos)
        # it may have just been dragged into — or out of — a frame that is
        # disabled or held back, which is the whole point of the flag living
        # on the frame rather than on the nodes
        self.refresh_frame_holds()

    def _on_code_changed(self, node_id: str) -> None:
        item = self.node_items.get(node_id)
        if item is None:
            return
        item.rebuild_ports()
        # reattach surviving wires to the freshly built port items — through
        # reattach(), so the drawn anchors follow when they were the real
        # pins and not a collapsed frame's stand-in
        for ci in self.connection_items.values():
            if ci.conn.src_node == node_id:
                src = item.port_item(ci.conn.src_port, "output")
            else:
                src = None
            if ci.conn.dst_node == node_id:
                dst = item.port_item(ci.conn.dst_port, "input")
            else:
                dst = None
            if src is not None or dst is not None:
                ci.reattach(
                    src if src is not None else ci.src_port,
                    dst if dst is not None else ci.dst_port)
        # a frame pin caches the spec it was built from, which has just been
        # replaced — drop them so the rebuild makes fresh ones rather than
        # leaving one pointing at a port that no longer exists
        self._drop_frame_pins_for(node_id)
        self._refresh_collapsed_frames()

    def _on_param_changed(self, node_id: str, name: str, value) -> None:
        item = self.node_items.get(node_id)
        if item is not None:
            item.on_params_changed(name)
        if item is not None and item.link_card:
            # a Goto's name is shown on every From reading it, not just here
            self._refresh_link_cards()
            # and the card just changed width, which is where a drawn line
            # starts — so this is also how the show_lines toggle takes effect
            self._refresh_link_lines()

    def _refresh_link_cards(self) -> None:
        for item in self.node_items.values():
            item.refresh_link_card()

    def _refresh_link_lines(self) -> None:
        """Draw the links whose ends asked for it, and only those.

        Rebuilt against the whole link set rather than patched, for the same
        reason the links themselves are (see core.links): a link is derived
        state, and there is no event that means "this one link changed" —
        adding a node, deleting one, repointing a From or ticking the toggle
        all arrive as different events with the same answer. The set is tiny
        (links a user has opted into drawing), so recomputing it is cheaper
        than being clever about it.
        """
        from flograph.core.links import link_label
        from .link_line import LinkLineItem, wants_lines
        wanted: dict[str, tuple] = {}
        for link_id, link in self.graph.links.items():
            src = self.node_items.get(link.src_node)
            dst = self.node_items.get(link.dst_node)
            if src is None or dst is None:
                continue
            # either end may ask: a From draws its own line back without
            # lighting up every other From reading the same Goto
            if wants_lines(src.node) or wants_lines(dst.node):
                wanted[link_id] = (src, dst)
        for link_id in list(self.link_line_items):
            item = self.link_line_items[link_id]
            if link_id not in wanted or wanted[link_id] != (item.src_item,
                                                            item.dst_item):
                self.removeItem(self.link_line_items.pop(link_id))
        for link_id, (src, dst) in wanted.items():
            existing = self.link_line_items.get(link_id)
            if existing is None:
                existing = LinkLineItem(link_id, src, dst,
                                        link_label(src.node))
                self.addItem(existing)
                self.link_line_items[link_id] = existing
            else:
                existing.setToolTip(f"Link: {link_label(src.node)}")
            existing.update_path()
        # a line that crosses a collapsed boundary terminates on a pin, and
        # the lines only exist as of this method, so re-derive after them
        self._refresh_collapsed_frames()

    # ------------------------------------------------------ collapsed frames

    def enclosing_frames(self, frame_id: str) -> set:
        """The visible frames this one sits inside.

        Containment by geometry, the same rule that decides what a frame
        carries when you drag it — so what the canvas shows you is what this
        agrees with, and a frame you have merely parked on top of another is
        not mistaken for one nested in it.
        """
        item = self.frame_items.get(frame_id)
        if item is None:
            return set()
        rect = item.scene_rect()
        return {other_id for other_id, other in self.frame_items.items()
                if other is not item and other.isVisible()
                and other.scene_rect().contains(rect)}

    def _nudge_units(self, frame_id: str, keep: set,
                     keep_frames: set) -> list:
        """The movable things around an expanding frame, as (key, rect, nodes,
        frames).

        A frame and its contents are **one** unit. Pushing its nodes out
        individually would empty it — which is exactly the complaint that a
        frame expanding over a neighbour "stole its nodes": the neighbour sat
        still while the things inside it were shoved out from under it.

        Nodes already spoken for by some frame are therefore not offered
        separately; only genuinely loose ones are.

        A frame the expanding one lives *inside* is the exception, and it has
        to be: it is not in the way, it is the room. Pushing a parent aside to
        make space for its own child sends the parent and its other contents
        off to the right while the child, held still by `keep`, stays exactly
        where it was — the frame visibly tears itself apart. So an enclosing
        frame is transparent here. It is not offered as a unit and it lays no
        claim to its contents, which are offered singly instead, so the
        expanding frame's siblings shuffle along *within* their shared parent
        while the parent itself holds its ground and grows (see
        `_grow_enclosing`).
        """
        item = self.frame_items.get(frame_id)
        enclosing = self.enclosing_frames(frame_id)
        spoken_for: set = set(keep)
        units: list = []
        for other_id, other in self.frame_items.items():
            if other is item or not other.isVisible():
                continue
            if other_id in keep_frames:
                continue        # nested inside the one expanding; it belongs
            if other_id in enclosing:
                continue        # the room, not the furniture — see above
            # `keep` is subtracted, not just skipped later: frames overlap,
            # and membership is geometric, so a neighbour can quite legally
            # claim a node that belongs to the frame being expanded. Letting
            # it travel with the neighbour drags the expanding frame's own
            # contents out from under it — the ones under the overlap moved
            # and the ones clear of it did not, which is as baffling as it
            # sounds. Its contents sit still, whoever else lays claim.
            members = [nid for nid in self._frame_members(other)
                       if nid in self.node_items and nid not in keep]
            spoken_for.update(members)
            rect = other.scene_rect()
            if not other.collapsed:
                # a node can hang over its frame's edge, and the whole unit
                # has to clear the region, so the overhang counts
                for nid in members:
                    rect = rect.united(
                        self.node_items[nid].sceneBoundingRect())
            # a folded frame's members are hidden and occupy no canvas, so
            # the unit is the little box and nothing else. Unioning their
            # stored positions in would stretch the unit across everywhere
            # they used to be, and a 60px box would push things about as
            # though it were still the size of the flow inside it.
            units.append((("frame", other_id), rect, members, [other_id]))
        for node_id, node_item in self.node_items.items():
            if node_id in spoken_for or not node_item.isVisible():
                continue
            units.append((("node", node_id), node_item.sceneBoundingRect(),
                          [node_id], []))
        return units

    def _already_held(self) -> tuple:
        """(node_ids, frame_ids) that some folded frame already stands for.

        The rule this exists to enforce: **a node belongs to one frame
        directly**. If a folded frame wrote it down, it is that frame's, and
        anything else reaches it only by containing that frame.

        Geometric membership has to be blind to visibility — a folded frame's
        own contents are hidden and must still travel with it — but blind
        also means a frame drawn anywhere near where those hidden nodes were
        left standing will happily claim them as well. Two frames then both
        record the same node, whichever one you open shows it while the other
        still believes it is holding it, and which of them owns it is decided
        by dictionary order. That is the "losing nodes" of nested frames.
        """
        held_nodes: set = set()
        held_frames: set = set()
        for frame in self.graph.frames.values():
            if not frame.collapsed:
                continue
            held_nodes.update(frame.members)
            held_frames.update(frame.member_frames)
        return (held_nodes, held_frames)

    def _frame_members(self, item) -> list:
        """Who a frame holds directly: what it wrote down if folded, whatever
        sits inside it if not. Not transitive — see frame_contents."""
        if item.collapsed:
            return list(item.frame.members)
        held, _frames = self._already_held()
        rect = item.scene_rect()
        return [nid for nid, node_item in self.node_items.items()
                if nid not in held
                and rect.contains(node_item.sceneBoundingRect().center())]

    def _frame_member_frames(self, item) -> list:
        """The frames a frame holds directly. A frame already folded away
        inside another is that one's to carry, for the same reason."""
        _nodes, held = self._already_held()
        if item.collapsed:
            return list(item.frame.member_frames)
        rect = item.scene_rect()
        return [fid for fid, other in self.frame_items.items()
                if other is not item and fid not in held
                and rect.contains(other.scene_rect())]

    def frame_contents(self, item) -> tuple:
        """(node_ids, frame_ids) — everything this frame holds, including
        everything its nested frames hold.

        Transitive, and that is the whole point. Direct membership uses two
        different rules — a node counts by its centre, a frame by its whole
        rectangle — and at the edges they disagree: a frame can sit wholly
        inside this one while a node *it* holds hangs out past the edge. Take
        the frame without its contents and two things break, both reported.
        Dragging the box leaves those nodes behind, so the flow comes back
        scattered relative to its own frame. And a wire reaching one of them
        gets pinned to the nested frame, which is itself hidden — a visible
        wire drawn to a box that is not on the canvas, trailing off across
        the scene to nothing.

        If you carry the frame, you carry what is in it, wherever it reaches.
        """
        # dict rather than set throughout: the member list is the order the
        # indicators light up in on the folded box, so it has to be stable
        nodes: dict = {nid: None for nid in self._frame_members(item)}
        frames: list = []
        seen: set = {item.frame.id}
        queue: list = list(self._frame_member_frames(item))
        while queue:
            frame_id = queue.pop(0)
            if frame_id in seen or frame_id not in self.frame_items:
                continue        # a frame cannot contain itself, but a stale
            seen.add(frame_id)  # member list could still say so
            frames.append(frame_id)
            nested = self.frame_items[frame_id]
            nodes.update({nid: None for nid in self._frame_members(nested)})
            queue.extend(self._frame_member_frames(nested))
        return (list(nodes), frames)

    def frame_direct_members(self, frame_id: str) -> tuple:
        """(node_ids, frame_ids) this frame holds *directly* — one level, not
        transitive. Folded frames report what they wrote down; open ones report
        what sits inside them right now. The Navigator builds its tree from
        this, one frame at a time.
        """
        item = self.frame_items.get(frame_id)
        if item is None:
            return ([], [])
        return (list(self._frame_members(item)),
                list(self._frame_member_frames(item)))

    def canvas_outline(self) -> tuple:
        """(top_node_ids, top_frame_ids, {frame_id: (node_ids, frame_ids)}).

        The whole containment tree in one call: what sits on the bare canvas,
        and the direct membership of every frame. A node or frame that several
        open frames overlap is attributed to the smallest — the same frame the
        eye reads it as being in.
        """
        direct: dict = {fid: self.frame_direct_members(fid)
                        for fid in self.frame_items}

        def area(fid: str) -> float:
            item = self.frame_items.get(fid)
            if item is None:
                return float("inf")
            r = item.scene_rect()
            return r.width() * r.height()

        node_owner: dict = {}
        frame_owner: dict = {}
        for fid, (nids, subs) in direct.items():
            for nid in nids:
                cur = node_owner.get(nid)
                if cur is None or area(fid) < area(cur):
                    node_owner[nid] = fid
            for sub in subs:
                cur = frame_owner.get(sub)
                if cur is None or area(fid) < area(cur):
                    frame_owner[sub] = fid

        tree: dict = {}
        for fid, (nids, subs) in direct.items():
            tree[fid] = ([nid for nid in nids if node_owner.get(nid) == fid],
                         [sub for sub in subs if frame_owner.get(sub) == fid])
        top_nodes = [nid for nid in self.node_items if nid not in node_owner]
        top_frames = [fid for fid in self.frame_items if fid not in frame_owner]
        return (top_nodes, top_frames, tree)

    def flagged_frame_members(self) -> dict:
        """`{frame_id: node_ids}` for the frames carrying a run flag.

        What the engine asks for when it builds a plan (see
        ExecutionEngine.frame_membership). Only flagged frames are walked:
        on a canvas where nobody has disabled or held anything — which is
        most of them — this is a scan of two booleans per frame and no
        containment work at all.
        """
        out: dict = {}
        for frame_id, frame in self.graph.frames.items():
            if frame.active and not frame.manual:
                continue
            item = self.frame_items.get(frame_id)
            if item is None:        # mirrored before the canvas caught up
                ids = list(frame.members)
            else:
                ids, _frames = self.frame_contents(item)
            out[frame_id] = [nid for nid in ids if nid in self.graph.nodes]
        return out

    def refresh_frame_holds(self) -> None:
        """Show which nodes the frames' flags currently reach — the play
        triangle on a held node, the fade on a disabled one.

        Display only. The run itself resolves this again at the moment a
        plan is built, so a badge that has not caught up yet is a cosmetic
        lag rather than a node that runs when it should not.
        """
        held: set = set()
        off: set = set()
        for frame_id, node_ids in self.flagged_frame_members().items():
            frame = self.graph.frames[frame_id]
            if frame.manual:
                held.update(node_ids)
            if not frame.active:
                off.update(node_ids)
        for node_id, item in self.node_items.items():
            item.set_frame_flags(node_id in held, node_id in off)

    def _grow_enclosing(self, frame_id: str, region: QRectF,
                        landings: list) -> tuple:
        """(record, frame_rects) letting the frames around this one hold it.

        A frame reopening inside another can easily come back bigger than the
        room it is in. The parent is not in the way — it *is* the way — so it
        stretches to fit rather than being shoved aside, which is what makes
        an expand-in-place read as opening out rather than bursting.

        It has to cover `landings` — where the displaced things ended up — and
        not just the region, because the same expand that needs the extra room
        has just pushed the parent's own contents to the right. Growing for
        the region alone leaves a node that was comfortably inside its frame
        sitting just past the edge of it, evicted by a sibling opening up.

        Only ever outwards, and only as far as it must. The region shares its
        top-left corner with the folded square, which is already inside the
        parent, and everything moves right or down, so the union can only add
        width on the right and height at the bottom.
        """
        record: list = []
        frame_rects: dict = {}
        for other_id in self.enclosing_frames(frame_id):
            x, y, w, h = self.graph.frames[other_id].rect
            rect = QRectF(x, y, w, h)
            grown = QRectF(rect).united(region)
            for before, after in landings:
                # only what this frame was already holding: a neighbour shunted
                # along outside it is not its business to grow around
                if rect.contains(before.center()):
                    grown = grown.united(after)
            if grown != rect:
                grown = grown.adjusted(0, 0, _ENCLOSE_PAD, _ENCLOSE_PAD)
            if (grown.width(), grown.height()) == (w, h):
                continue
            frame_rects[other_id] = (x, y, grown.width(), grown.height())
            record.append(("grow", other_id, grown.width() - w,
                           grown.height() - h, grown.width(), grown.height()))
        return (tuple(record), frame_rects)

    def plan_expand_nudge(self, frame_id: str, box: QRectF, region: QRectF,
                          keep: set, keep_frames: set) -> tuple:
        """(record, moves, frame_rects) for reopening a frame into `region`.

        Worked out *before* the frame is expanded, so the record of what got
        shoved aside can be written down as part of the same fold — folding
        again then takes it back off. What the record needs is how far each
        thing went; where it landed is written down too, but only as history
        (see unnudge_plan, which applies the inverse shift wherever the thing
        has since got to).
        """
        units = self._nudge_units(frame_id, keep, keep_frames)
        plan = plan_nudge(box, region,
                          [(key, rect) for key, rect, _n, _f in units])
        contents = {key: (nodes, frames) for key, _r, nodes, frames in units}
        rects = {key: rect for key, rect, _n, _f in units}
        record: list = []
        moves: dict = {}
        frame_rects: dict = {}
        landings: list = []
        for key, (dx, dy) in plan.items():
            landings.append((rects[key], rects[key].translated(dx, dy)))
            nodes, frames = contents[key]
            for node_id in nodes:
                node = self.graph.nodes.get(node_id)
                if node is None:
                    continue
                landed = (node.pos[0] + dx, node.pos[1] + dy)
                moves[node_id] = (node.pos, landed)
                record.append(("node", node_id, dx, dy, *landed))
            for other_id in frames:
                rect = self.graph.frames[other_id].rect
                landed = (rect[0] + dx, rect[1] + dy)
                frame_rects[other_id] = (*landed, rect[2], rect[3])
                record.append(("frame", other_id, dx, dy, *landed))
        grow_record, grown = self._grow_enclosing(frame_id, region, landings)
        frame_rects.update(grown)
        return (tuple(record) + grow_record, moves, frame_rects)

    def unnudge_plan(self, frame_id: str) -> tuple:
        """(moves, frame_rects) putting back what expanding this frame moved.

        The **inverse shift**, applied wherever the thing is now — not a
        restoration of the position it was left at. Anything the user has
        moved in the meantime keeps their move; it simply loses the
        displacement we imposed on top of it.

        This started out as "only what is still where the expand left it",
        on the reasoning that an arrangement the user chose is theirs and not
        ours to reclaim. That is true, and this respects it — subtracting the
        shift preserves their move exactly, as an offset from where the thing
        would have been. What it gets wrong is *consistency*: displace two
        frames, move one of them, fold again, and one comes home while the
        other stays behind, which reads as the fold simply forgetting. A
        systematic shift has to be reversible as a whole or not at all.

        The cost, stated plainly: a thing moved somewhere deliberate since
        the expand still slides back by the shift when the frame folds. That
        is the same amount everything else moves, it is one Ctrl+Z, and it
        beats a canvas that half-restores.
        """
        frame = self.graph.frames.get(frame_id)
        moves: dict = {}
        frame_rects: dict = {}
        for kind, item_id, dx, dy, _landed_x, _landed_y in (
                frame.nudged if frame else ()):
            if kind == "node":
                node = self.graph.nodes.get(item_id)
                if node is None:
                    continue        # deleted since; nothing to put back
                moves[item_id] = (node.pos, (node.pos[0] - dx,
                                             node.pos[1] - dy))
            elif kind == "grow":
                # a frame that stretched to hold this one: the displacement
                # was a size rather than a position, and comes off the same
                # way. Floored rather than trusted — the user may have
                # shrunk it themselves in between, and a frame cannot come
                # back inside out.
                other = self.graph.frames.get(item_id)
                if other is None:
                    continue
                frame_rects[item_id] = (other.rect[0], other.rect[1],
                                        max(_MIN_FRAME_W, other.rect[2] - dx),
                                        max(_MIN_FRAME_H, other.rect[3] - dy))
            else:
                other = self.graph.frames.get(item_id)
                if other is None:
                    continue
                frame_rects[item_id] = (other.rect[0] - dx,
                                        other.rect[1] - dy,
                                        other.rect[2], other.rect[3])
                for nid in self._frame_members(self.frame_items[item_id]):
                    node = self.graph.nodes.get(nid)
                    if node is not None and nid not in moves:
                        moves[nid] = (node.pos, (node.pos[0] - dx,
                                                 node.pos[1] - dy))
        return (moves, frame_rects)

    def placement_plan(self, placements: dict) -> tuple:
        """(moves, frame_rects) for putting these items at these positions.

        Keyed by the item, which may be a node or a frame. A frame takes what
        it holds along with it, exactly as dragging it does — moving a frame
        off its own contents is never what anyone meant, and for a collapsed
        one it would strand nodes nobody can see.

        A node that is both selected in its own right and inside a selected
        frame is placed where it was asked to go, not where its frame would
        have carried it. The explicit instruction wins.
        """
        moves: dict = {}
        frame_rects: dict = {}
        carried_nodes: dict = {}
        carried_frames: dict = {}
        for item, (x, y) in placements.items():
            old = (item.pos().x(), item.pos().y())
            if (x, y) == old:
                continue
            frame = getattr(item, "frame", None)
            if frame is None:
                moves[item.node.id] = (old, (x, y))
                continue
            frame_rects[frame.id] = (x, y, *item.display_size())
            dx, dy = x - old[0], y - old[1]
            nodes, frames = item.carried_items()
            for node_item, _offset in nodes:
                node = self.graph.nodes.get(node_item.node.id)
                if node is not None:
                    carried_nodes[node.id] = (node.pos, (node.pos[0] + dx,
                                                         node.pos[1] + dy))
            for other, _offset in frames:
                rect = self.graph.frames[other.frame.id].rect
                carried_frames[other.frame.id] = (rect[0] + dx, rect[1] + dy,
                                                  rect[2], rect[3])
        # folded in afterwards, never during: an item placed explicitly must
        # win over one merely carried, whichever order they came in
        for node_id, move in carried_nodes.items():
            moves.setdefault(node_id, move)
        for frame_id, rect in carried_frames.items():
            frame_rects.setdefault(frame_id, rect)
        return (moves, frame_rects)

    def apply_nudge(self, moves: dict, frame_rects: dict) -> None:
        """Push a planned displacement onto the stack, inside whatever macro
        the caller has open."""
        if moves:
            self.push_move_command(moves)
        for other_id, rect in frame_rects.items():
            self.undo_stack.push(UpdateFrameCommand(
                self.graph, other_id, rect=rect))

    def _buried_frames(self) -> set:
        """Collapsed frames that are themselves folded away inside another."""
        return {fid for ids in self._hidden_frames.values() for fid in ids}

    def _burier_of(self) -> dict:
        """frame_id -> the collapsed frame that has folded it away."""
        return {fid: owner for owner, ids in self._hidden_frames.items()
                for fid in ids}

    def _owner_of(self, node_id: str) -> Optional[str]:
        """The collapsed frame that stands in for this node on the canvas.

        The **outermost** one, found by climbing: whichever frame claims the
        node, then whatever has folded *that* away, until we reach one nobody
        has buried. That frame is the box actually on screen, and it is the
        only correct place to pin the node's wires — pinning them to a buried
        frame draws them to something invisible, which is a wire trailing off
        across the canvas to nowhere.

        Climbing rather than "the first unburied frame that claims it",
        because the two membership rules disagree at the edges (see
        frame_contents) and an outer frame's own list can miss a node that a
        frame it carries holds. Following the chain gets the right answer
        even then, and also for projects saved before this was fixed.

        Before that it returned whichever frame came first in the dictionary,
        which made it a coin toss decided by the order the frames happened to
        be created in — the same nesting drew correctly or not at all
        depending on which frame you had drawn first.
        """
        burier = self._burier_of()
        for frame_id, members in self._hidden.items():
            if node_id not in members:
                continue
            seen = {frame_id}
            while frame_id in burier:
                frame_id = burier[frame_id]
                if frame_id in seen:
                    break       # a cycle in stale membership; stop climbing
                seen.add(frame_id)
            return frame_id
        return None

    def wire_anchor(self, conn, side: str):
        """The item a wire's `side` end should be drawn from.

        The frame pin standing in for it when that end is folded away,
        otherwise the port's own pin. One rule, so every path that draws or
        drags a wire agrees on where its ends are — including the drag
        preview, which would otherwise spring from a hidden pin's stale
        position.
        """
        pin = self._frame_pins.get((conn.id, side))
        if pin is not None:
            return pin
        node_id, port = ((conn.src_node, conn.src_port) if side == "src"
                         else (conn.dst_node, conn.dst_port))
        item = self.node_items.get(node_id)
        if item is None:
            return None
        table = item.output_ports if side == "src" else item.input_ports
        return table.get(port)

    def _refresh_collapsed_frames(self) -> None:
        """Re-derive everything collapse implies, from scratch.

        Rebuilt whole against current state rather than patched, for the same
        reason the link lines are (see _refresh_link_lines): folding, adding
        a wire through a pin, deleting a node inside and undoing any of it
        all arrive as different events with the same answer. Patching would
        mean each of those carrying its own correction, and the one a
        collapse-time snapshot cannot know about — a wire made *through* a
        pin, after the fold — is exactly the one that would leak.
        """
        if self._suspend_collapse_refresh:
            return
        collapsed = [f for f in self.graph.frames.values() if f.collapsed]
        if not collapsed and not self._hidden and not self._frame_pins:
            return      # the overwhelmingly common canvas: nothing to do

        # 1. membership — read straight off the model, never recomputed here.
        #    The frame wrote down what it owned when it folded, so this is a
        #    pure function of the graph: undo restores exactly the membership
        #    it took away, and a folded frame parked over other nodes cannot
        #    quietly adopt them.
        self._hidden = {
            frame.id: [nid for nid in frame.members if nid in self.node_items]
            for frame in collapsed}
        self._hidden_frames = {
            frame.id: [fid for fid in frame.member_frames
                       if fid in self.frame_items]
            for frame in collapsed}

        hidden_nodes = {nid for ids in self._hidden.values() for nid in ids}
        hidden_frames = {fid for ids in self._hidden_frames.values()
                         for fid in ids}

        # 2. visibility.
        for node_id, item in self.node_items.items():
            item.setVisible(node_id not in hidden_nodes)
        for frame_id, item in self.frame_items.items():
            item.setVisible(frame_id not in hidden_frames)
            item.set_members(self._hidden.get(frame_id, [])
                             if item.collapsed else [])

        # 3. the pins, reconciled by (conn_id, side) so a pin that survives a
        #    rebuild keeps its hover state and stays valid mid-drag.
        wanted: dict[tuple, tuple] = {}
        for conn in self.graph.connections.values():
            src_owner = self._owner_of(conn.src_node)
            dst_owner = self._owner_of(conn.dst_node)
            if src_owner is not None and src_owner == dst_owner:
                continue            # wholly inside one frame: an internal wire
            if src_owner is not None:
                wanted[(conn.id, "src")] = (src_owner, conn, "src", False)
            if dst_owner is not None:
                wanted[(conn.id, "dst")] = (dst_owner, conn, "dst", False)
        wanted.update(self._wanted_link_pins())

        self._drop_frame_pins(
            key for key, pin in self._frame_pins.items()
            if key not in wanted
            or wanted[key][0] != pin.frame_item.frame.id)
        for key, (frame_id, conn, side, is_link) in wanted.items():
            if key in self._frame_pins:
                continue
            pin = self._build_frame_pin(frame_id, conn, side, is_link)
            if pin is not None:
                self._frame_pins[key] = pin

        # 4. lay the surviving pins out, and point the wires at them.
        self._layout_frame_pins()
        self._reanchor_wires(hidden_nodes)
        for pin in self._frame_pins.values():
            pin.refresh_connected()

    def _drop_frame_pins(self, keys) -> None:
        """Take these pins off the box and out of the scene.

        The scene check is not defensive padding: a pin is a *child* of its
        frame, so removing the frame takes the pin out of the scene with it,
        and a second removeItem on the detached item is a dangling pointer
        that segfaults later. Every pin teardown goes through here.
        """
        for key in list(keys):
            pin = self._frame_pins.pop(key, None)
            if pin is None:
                continue
            if pin.scene() is self:
                pin.setParentItem(None)
                self.removeItem(pin)

    def _drop_frame_pins_for(self, node_id: str) -> None:
        self._drop_frame_pins([key for key, pin in self._frame_pins.items()
                               if pin.node_id == node_id])

    def _wanted_link_pins(self) -> dict:
        """Crossing Goto/From links that are already being drawn.

        A named link the user has not asked to see has no line on the canvas,
        so giving it a pin would invent a connection where the whole point of
        the link was to not draw one. Only the opted-in ones cross visibly.
        """
        from .link_line import wants_lines
        wanted: dict[tuple, tuple] = {}
        for link_id, link in self.graph.links.items():
            if link_id not in self.link_line_items:
                continue
            src = self.node_items.get(link.src_node)
            dst = self.node_items.get(link.dst_node)
            if src is None or dst is None:
                continue
            if not (wants_lines(src.node) or wants_lines(dst.node)):
                continue
            src_owner = self._owner_of(link.src_node)
            dst_owner = self._owner_of(link.dst_node)
            if src_owner is not None and src_owner == dst_owner:
                continue
            if src_owner is not None:
                wanted[(link_id, "src")] = (src_owner, link, "src", True)
            if dst_owner is not None:
                wanted[(link_id, "dst")] = (dst_owner, link, "dst", True)
        return wanted

    def _build_frame_pin(self, frame_id: str, conn, side: str, is_link: bool):
        from .frame_port import FramePortItem
        frame_item = self.frame_items.get(frame_id)
        if frame_item is None:
            return None
        node_id = conn.src_node if side == "src" else conn.dst_node
        port_name = conn.src_port if side == "src" else conn.dst_port
        node = self.graph.nodes.get(node_id)
        item = self.node_items.get(node_id)
        if node is None or item is None:
            return None
        port = item.port_item(port_name,
                              "output" if side == "src" else "input")
        if port is None:
            return None
        pin = FramePortItem(frame_item, node, port.spec,
                            getattr(conn, "id", ""), side, link=is_link)
        return pin

    def _layout_frame_pins(self) -> None:
        """Group the pins by their frame and stack them down its edges.

        Ordered by the wire's hidden end — the node's position, then the port
        — so the pins mirror how the flow was laid out inside, and stay put
        across rebuilds instead of shuffling whenever a wire is added.
        """
        by_frame: dict[str, list] = {}
        for pin in self._frame_pins.values():
            by_frame.setdefault(pin.frame_item.frame.id, []).append(pin)
        for frame_id, item in self.frame_items.items():
            pins = by_frame.get(frame_id, [])

            def order(pin):
                node_item = self.node_items.get(pin.node_id)
                pos = node_item.pos() if node_item is not None else None
                return (pos.y() if pos else 0.0, pos.x() if pos else 0.0,
                        pin.spec.name, pin.conn_id)

            inputs = sorted((p for p in pins if p.side == "dst"), key=order)
            outputs = sorted((p for p in pins if p.side == "src"), key=order)
            item.layout_pins(inputs, outputs)

    def _reanchor_wires(self, hidden_nodes: set) -> None:
        """Point every wire and link line at wherever its ends now live, and
        hide the ones that run entirely inside a collapsed frame."""
        for conn_id, ci in self.connection_items.items():
            conn = ci.conn
            src_pin = self._frame_pins.get((conn_id, "src"))
            dst_pin = self._frame_pins.get((conn_id, "dst"))
            internal = (conn.src_node in hidden_nodes
                        and conn.dst_node in hidden_nodes
                        and src_pin is None and dst_pin is None)
            ci.setVisible(not internal)
            ci.set_anchors(src_pin, dst_pin)
        for link_id, line in self.link_line_items.items():
            src_pin = self._frame_pins.get((link_id, "src"))
            dst_pin = self._frame_pins.get((link_id, "dst"))
            link = self.graph.links.get(link_id)
            internal = (link is not None
                        and link.src_node in hidden_nodes
                        and link.dst_node in hidden_nodes
                        and src_pin is None and dst_pin is None)
            line.setVisible(not internal)
            line.set_anchors(src_pin, dst_pin)

    def frame_item_moved(self, frame_id: Optional[str] = None) -> None:
        """A collapsed frame moved, so the wires pinned to it must follow.
        node_item_moved cannot cover this: the wires' other ends are hidden
        nodes that did not themselves move relative to the box.

        `None` means every collapsed frame, for the drags that move several
        at once and cannot say which.
        """
        for pin in self._frame_pins.values():
            if frame_id is not None and pin.frame_item.frame.id != frame_id:
                continue
            ci = self.connection_items.get(pin.conn_id)
            if ci is not None:
                ci.update_path()
            line = self.link_line_items.get(pin.conn_id)
            if line is not None:
                line.update_path()

    def _refresh_port_connections(self) -> None:
        """A derived Goto/From link feeds a port no drawn wire reaches, so
        every input pin is re-read when the link set moves. Rare enough to
        be blunt about — the alternative is working out which Froms changed,
        for an answer that is one dictionary lookup per pin."""
        for item in self.node_items.values():
            item.refresh_port_connections()
        # frame pins are in no node's port dict, so they are not covered by
        # the loop above — an input pin fed only by a link would draw hollow
        for pin in self._frame_pins.values():
            pin.refresh_connected()

    def _highlight_link_partners(self) -> None:
        selected = {item.node.id for item in self.selected_node_items()}
        partners: set[str] = set()
        for link in self.graph.links.values():
            if link.src_node in selected:
                partners.add(link.dst_node)
            if link.dst_node in selected:
                partners.add(link.src_node)
        for node_id, item in self.node_items.items():
            item.set_link_highlight(node_id in partners)

    def _on_status_changed(self, node_id: str, status: NodeStatus, message: str) -> None:
        item = self.node_items.get(node_id)
        if item is not None:
            item.on_status_changed()  # also refreshes the tooltip
        self._notify_owning_frame(node_id)

    def _notify_owning_frame(self, node_id: str) -> None:
        """A hidden node still shows through its frame's matrix and drives
        that frame's own LED, so the box has to hear about it even though
        the node item itself is invisible."""
        frame_id = self._owner_of(node_id)
        if frame_id is None:
            return
        item = self.frame_items.get(frame_id)
        if item is not None:
            item.refresh_status()

    def set_requested_nodes(self, node_ids) -> None:
        """Which nodes have a re-run queued. Only the cards whose answer
        changes are touched — on a large flow a queued run covers most of
        the graph, and every card repainting for it is the wrong cost to pay
        for a fade."""
        new = frozenset(node_ids)
        changed = new ^ self.requested_nodes
        self.requested_nodes = new
        for node_id in changed:
            item = self.node_items.get(node_id)
            if item is not None:
                item.refresh_updating()

    def _on_progress_changed(self, node_id: str, fraction: float) -> None:
        item = self.node_items.get(node_id)
        if item is not None:
            # No dearer than the pulse animation this replaces, which already
            # repaints the whole item continuously while a node runs — and the
            # RunContext has thinned these out long before they arrive here.
            item.on_progress_changed()
        self._notify_owning_frame(node_id)

    def _on_dirty_changed(self, node_id: str, dirty: bool) -> None:
        item = self.node_items.get(node_id)
        if item is not None:
            item.update()

    def _on_label_changed(self, node_id: str) -> None:
        item = self.node_items.get(node_id)
        if item is not None:
            item.prepareGeometryChange()  # compact nodes resize their bounding rect for the label
            item.invalidate_label()
            item.update()

    def _on_description_changed(self, node_id: str) -> None:
        item = self.node_items.get(node_id)
        if item is not None:
            item._refresh_tooltip()

    def _on_active_changed(self, node_id: str, active: bool) -> None:
        item = self.node_items.get(node_id)
        if item is not None:
            item.set_active(active)

    def _on_locked_changed(self, node_id: str, locked: bool) -> None:
        item = self.node_items.get(node_id)
        if item is not None:
            item.set_locked(locked)

    def _on_frozen_changed(self, node_id: str, frozen: bool) -> None:
        item = self.node_items.get(node_id)
        if item is not None:
            item.set_frozen(frozen)

    def _on_manual_changed(self, node_id: str, manual: bool) -> None:
        item = self.node_items.get(node_id)
        if item is not None:
            item.set_manual(manual)

    def refresh_stale_pins(self, stale: set) -> None:
        """Amber the frozen nodes in `stale`, plain-grey the rest. Called
        after a run, when the answer can have changed."""
        for node_id, item in self.node_items.items():
            if item.node.frozen:
                item.set_frozen(True, node_id in stale)

    def _on_preview_enabled_changed(self, node_id: str, enabled: bool) -> None:
        item = self.node_items.get(node_id)
        if item is not None:
            item.set_preview_enabled(enabled)

    def _on_ports_collapsed_changed(self, node_id: str) -> None:
        item = self.node_items.get(node_id)
        if item is not None:
            item._refresh_ports_collapsed()

    def _on_port_labels_changed(self, node_id: str) -> None:
        self._repaint_ports(self.node_items.get(node_id))

    def _on_flow_pins_changed(self, node_id: str) -> None:
        item = self.node_items.get(node_id)
        if item is not None:
            item._apply_port_visibility()

    def set_flow_pins_enabled(self, enabled: bool) -> None:
        """Canvas-wide preference: show every node's flow pins, or leave them
        to the nodes that have an order edge on them. Nodes carrying their own
        override are unmoved by this, which is the point of the override."""
        if enabled == self.flow_pins_enabled:
            return
        self.flow_pins_enabled = enabled
        self._refresh_flow_pins()

    def set_drawing_order_edge(self, drawing: bool) -> None:
        """Reveal every flow pin for the length of an order-edge drag. A
        look, not a setting — nothing is written down, and it goes back the
        moment the drag ends."""
        if drawing == self.drawing_order_edge:
            return
        self.drawing_order_edge = drawing
        self._refresh_flow_pins()

    def _refresh_flow_pins(self) -> None:
        for item in self.node_items.values():
            item._apply_port_visibility()

    def _refresh_order_pins(self, conn: Connection) -> None:
        """Re-read both ends of an order edge that has just appeared or gone.
        Their pins are drawn whenever a wire lands on them, so the answer
        changes with the wire."""
        for node_id in (conn.src_node, conn.dst_node):
            item = self.node_items.get(node_id)
            if item is not None:
                item.refresh_port_connections()

    def set_port_labels_enabled(self, enabled: bool) -> None:
        """Canvas-wide preference. Repaints every node, because a pill
        appearing changes each port's bounding rect — Qt would otherwise
        leave the old one smeared on the canvas until something else
        happened to redraw that region."""
        if enabled == self.port_labels_enabled:
            return
        self.port_labels_enabled = enabled
        for item in self.node_items.values():
            self._repaint_ports(item)

    def set_revealing_port_labels(self, revealing: bool) -> None:
        """Show every port's name while the reveal key is held, then put them
        all back. Repaints the pins for the same reason
        set_port_labels_enabled does: a pill appearing changes each pin's
        bounding rect, and Qt's index has to be told."""
        if revealing == self.revealing_port_labels:
            return
        self.revealing_port_labels = revealing
        for item in self.node_items.values():
            self._repaint_ports(item)
            item._apply_port_visibility()   # the flow pins come up too
        for pin in self._frame_pins.values():
            pin.prepareGeometryChange()   # the pill changes its bounds
            pin.update()

    def set_compact_nodes(self, enabled: bool) -> None:
        """Canvas-wide preference. Every plain node changes width, so its
        pins move and every wire on them has to be re-routed; apply_compact
        does that per item. Nodes carrying their own override are unmoved by
        this, which is the point of the override."""
        if enabled == self.compact_nodes:
            return
        self.compact_nodes = enabled
        for item in self.node_items.values():
            item.refresh_compact()

    def _on_compact_view_changed(self, node_id: str) -> None:
        item = self.node_items.get(node_id)
        if item is not None:
            item.refresh_compact()

    def _repaint_ports(self, item) -> None:
        if item is None:
            return
        for port in (*item.input_ports.values(), *item.output_ports.values()):
            # prepareGeometryChange, not update: the label pill lives outside
            # the pin's usual 20x20 box, so the item's bounding rect really
            # does change and Qt's index has to be told
            port.prepareGeometryChange()
            port.update()
        # The label-visibility flag has already flipped by the time we get
        # here, so boundingRect (and the update above) only ever sees the
        # post-flip extent — a pill that just *vanished* sits outside it and
        # smears until something else repaints that strip. Every caller is a
        # one-shot user toggle (a canvas preference, a per-node override, the
        # held reveal key), never a per-frame path, so damage the whole
        # scene; Qt coalesces the repeats into one repaint.
        self.update()

    def _on_color_changed(self, node_id: str) -> None:
        item = self.node_items.get(node_id)
        if item is not None:
            item.update()

    def _on_mark_changed(self, node_id: str) -> None:
        item = self.node_items.get(node_id)
        if item is not None:
            item.refresh_mark_image()

    def _on_temp_edit_changed(self, node_id: str, has_temp_edit: bool) -> None:
        item = self.node_items.get(node_id)
        if item is not None:
            item.update()

    def _on_frame_added(self, frame: Frame) -> None:
        item = FrameItem(frame)
        item.run_requested.connect(self.frame_run_requested.emit)
        self.addItem(item)
        self.frame_items[frame.id] = item
        item.apply_stacking()
        # A project loads nodes, then connections, then frames, so a frame
        # arriving already collapsed (from a file, a paste, or undo) finds
        # everything it needs to fold around right here.
        self._refresh_collapsed_frames()
        self.refresh_frame_holds()

    def _on_frame_removed(self, frame_id: str) -> None:
        item = self.frame_items.pop(frame_id, None)
        if item is None:
            return
        item._stop_pulse()
        # Drop this frame's pins here, unconditionally, while the frame is
        # still in the scene — not inside the rebuild. The rebuild can be
        # suspended (a project load tears every frame down with it off), and
        # a pin left in _frame_pins after its parent frame has gone is a
        # dangling pointer the next rebuild would try to remove a second
        # time. That crashed the app on File > New with a frame collapsed.
        self._drop_frame_pins([key for key, pin in self._frame_pins.items()
                               if pin.frame_item is item])
        # The membership entry is left for the rebuild to prune, which is
        # what makes it show the contents again — clearing it here would
        # leave nothing to reconcile and the nodes would stay hidden.
        self._refresh_collapsed_frames()
        self.removeItem(item)
        self.refresh_frame_holds()   # whatever it held is free again

    def _on_frame_changed(self, frame: Frame) -> None:
        item = self.frame_items.get(frame.id)
        if item is not None:
            item.sync_from_model()
        # The captured membership is *not* dropped here: the rebuild prunes
        # frames that are no longer collapsed itself, and it has to see the
        # stale entry to know there is anything to undo. Clearing it first
        # leaves nothing to reconcile and the contents stay hidden.
        self._refresh_collapsed_frames()
        # The frame may have *moved*, and the wires pinned to it have their
        # other end on a hidden node that did not move relative to it, so
        # nothing else repaths them. Only a mouse drag used to do this, which
        # left every other way a frame can move — a nudge, an undo, a paste,
        # a project load — drawing its wires from where the box used to be.
        self.frame_item_moved(frame.id)
        # its flags may have changed, and so may the region they apply to
        self.refresh_frame_holds()

    # ------------------------------------------------------------- helpers

    def is_port_connected(self, node_id: str, spec: PortSpec) -> bool:
        if is_flow(spec.name) and spec.direction.value == "input":
            # The flow port takes any number of order edges and is kept out
            # of the by-input index because it receives no value, so the
            # lookup below would always answer "no".
            return bool(self.graph.order_sources(node_id))
        if spec.direction.value == "input":
            return self.graph.input_connection(node_id, spec.name) is not None
        # out_connections is indexed; scanning every wire in the graph here
        # made this quadratic in graph size for the output case alone
        return any(c.src_port == spec.name
                   for c in self.graph.out_connections(node_id))

    def selected_node_items(self) -> list[NodeItem]:
        return [i for i in self.selectedItems() if isinstance(i, NodeItem)]

    def selected_frame_items(self) -> list[FrameItem]:
        return [i for i in self.selectedItems() if isinstance(i, FrameItem)]

    def node_item_moved(self, node_id: str) -> None:
        for ci in self.connection_items.values():
            if node_id in (ci.conn.src_node, ci.conn.dst_node):
                ci.update_path()
        for line in self.link_line_items.values():
            if node_id in (line.src_item.node.id, line.dst_item.node.id):
                line.update_path()

    def _flat_state(self) -> bool:
        return self.lod_enabled and self._zoom < self.lod_threshold

    def _apply_lod(self) -> None:
        flat = self._flat_state()
        for item in self.node_items.values():
            item.set_lod(flat)
        # a collapsed frame's pins are the only ones left at that zoom, so
        # they have to flatten with everything else
        for item in self.frame_items.values():
            item.set_pins_visible(not flat)

    def set_lod(self, zoom: float) -> None:
        """Called by the view whenever its scale changes: push the decision
        (zoom vs. lod_threshold, gated by lod_enabled) to every node, so
        ports/embedded widgets hide and painting flattens — see
        node_item.NodeItem.set_lod."""
        self._zoom = zoom
        self._apply_lod()

    def refresh_lod_settings(self) -> None:
        """Re-applies the flat/full-detail decision using the last-known
        zoom — call after lod_enabled/lod_threshold change (e.g. from the
        Settings dialog) so the effect is immediate rather than waiting for
        the next zoom change."""
        self._apply_lod()

    def refresh_render_ratios(self) -> None:
        """Re-target figure cards' render resolution — called by the view
        once its zoom settles, so embedded figures stay crisp at any zoom."""
        for item in self.node_items.values():
            item.refresh_render_ratio()

    def push_move_command(self, moves: dict) -> None:
        self.undo_stack.push(MoveNodesCommand(self.graph, moves))

    # "a rubber band takes a frame only when it takes the whole frame" used
    # to live here as a setSelectionArea override. It never ran: the function
    # is not virtual in Qt, so the rubber band's call from QGraphicsView goes
    # straight to C++ and the Python override was only ever reached by Python
    # callers — which is to say by its own tests. The rule now lives in
    # ZoomPanGraphicsView (see _drop_grazed_frames), where the drag is, and
    # is one of the choices under Settings > Canvas > Drag-select.

    # ------------------------------------------------------- group drag/move

    def _selected_movables(self) -> list:
        """Selected items that participate in a drag: nodes and frames."""
        return [i for i in self.selectedItems()
                if isinstance(i, (NodeItem, FrameItem))]

    def _bump_group_drags(self, delta: int) -> None:
        """Raise or lower the drag-nesting count, emitting canvas_drag_changed
        only on the 0<->1 crossings so the view starts and stops edge-scrolling
        once per gesture. Shared by begin_group_drag / commit_group_move (a full
        selection move) and begin_edge_scroll / end_edge_scroll (a lone frame,
        which commits its own move but still wants the border glide)."""
        was = self._group_drags > 0
        self._group_drags = max(0, self._group_drags + delta)
        now = self._group_drags > 0
        if now != was:
            self.canvas_drag_changed.emit(now)

    def begin_edge_scroll(self) -> None:
        """Edge-scroll for a drag that isn't a group move — a single frame
        carrying its contents. It commits its own move on release, so it wants
        the border glide without the selection snapshot begin_group_drag takes.
        Pair with end_edge_scroll."""
        self._bump_group_drags(1)

    def end_edge_scroll(self) -> None:
        self._bump_group_drags(-1)

    def cancel_active_drags(self) -> None:
        """Drop every in-progress wire / group / frame drag without a commit.

        A drag that ends by something other than a mouse release — Open
        replacing the graph out from under it, a node deleted mid-move —
        otherwise leaves _group_drags pinned above zero and _dragging set on
        an item, and the view goes on edge-scrolling for a drag that is over,
        including during an ordinary middle-drag pan (the grab cursor sticks
        too). Called when the graph is replaced."""
        self.cancel_wire_drag()
        if self._group_drags:
            self._group_drags = 0
            self.canvas_drag_changed.emit(False)
        for item in self.node_items.values():
            item._dragging = False
            item._group_starts = None
        for item in self.frame_items.values():
            item._dragging = False
            item._group_starts = None
            item._edge_scrolling = False

    def begin_group_drag(self) -> dict:
        """Arm every selected node/frame for a group drag: flag each as
        dragging so its own itemChange snaps (Qt moves the whole selection by
        one delta, but only the pressed item was flagged before), and snapshot
        their start positions for the release commit."""
        starts: dict = {"nodes": {}, "frames": {}, "carried": {}}
        self._bump_group_drags(1)
        for item in self._selected_movables():
            item._dragging = True
            if isinstance(item, FrameItem):
                starts["frames"][item.frame.id] = (
                    item.pos().x(), item.pos().y(), *item._size)
                # A collapsed frame's contents cannot themselves be selected
                # (Qt refuses to select an invisible item), so the skip-the-
                # content-grab rule above would leave them behind. They can
                # never be double-moved, by exactly that construction.
                for node_id in self._hidden.get(item.frame.id, ()):
                    node_item = self.node_items.get(node_id)
                    if node_item is not None:
                        starts["carried"][node_id] = (
                            node_item.pos().x(), node_item.pos().y())
            else:
                starts["nodes"][item.node.id] = (item.pos().x(), item.pos().y())
        return starts

    def commit_group_move(self, starts: dict) -> None:
        """Clear the drag flags and push one undo macro for whatever actually
        moved — node positions and frame rects together, so a mixed-selection
        drag sticks (and undoes) as a single step."""
        # end the edge-scroll before anything else: a click that never moved
        # still ends the drag, and the early return below must not skip it
        self._bump_group_drags(-1)
        node_moves: dict = {}
        for node_id, old in starts.get("nodes", {}).items():
            item = self.node_items.get(node_id)
            if item is None:
                continue
            item._dragging = False
            new = (item.pos().x(), item.pos().y())
            if new != old:
                node_moves[node_id] = (old, new)
        frame_moves: dict = {}
        deltas: dict = {}
        for frame_id, old in starts.get("frames", {}).items():
            item = self.frame_items.get(frame_id)
            if item is None:
                continue
            item._dragging = False
            new = (item.pos().x(), item.pos().y(), *item._size)
            if new[:2] != old[:2]:
                frame_moves[frame_id] = new
                deltas[frame_id] = (new[0] - old[0], new[1] - old[1])
        # Qt moved the selection for us, but a collapsed frame's hidden
        # contents were never in it — shift them by their own frame's delta.
        for frame_id, (dx, dy) in deltas.items():
            for node_id in self._hidden.get(frame_id, ()):
                old = starts.get("carried", {}).get(node_id)
                item = self.node_items.get(node_id)
                if old is None or item is None or node_id in node_moves:
                    continue
                new = (old[0] + dx, old[1] + dy)
                item.setPos(*new)
                node_moves[node_id] = (old, new)
        if not (node_moves or frame_moves):
            return
        self.undo_stack.beginMacro("move selection")
        if node_moves:
            self.push_move_command(node_moves)
        for frame_id, rect in frame_moves.items():
            self.undo_stack.push(UpdateFrameCommand(
                self.graph, frame_id, rect=rect))
        self.undo_stack.endMacro()

    def delete_selection(self) -> None:
        node_ids = [i.node.id for i in self.selected_node_items()]
        conn_ids = [i.conn.id for i in self.selectedItems()
                    if isinstance(i, ConnectionItem)]
        frame_ids = [i.frame.id for i in self.selectedItems()
                     if isinstance(i, FrameItem)]
        self.delete_items(node_ids, conn_ids, frame_ids)

    def delete_items(self, node_ids: list, conn_ids: list,
                     frame_ids: list, *, confirm: bool = True) -> None:
        """Remove nodes, wires and frames in one undo step.

        A *collapsed* frame takes its contents with it. Expanded, deleting a
        frame has never touched the nodes inside and still doesn't — but
        collapsed, the box is the only thing on the canvas and its contents
        cannot be seen or selected, so removing it alone would silently
        strand nodes nobody can reach.

        `confirm=False` skips the are-you-sure. For a caller that is not
        really deleting anything — updating a component tears its contents
        down only to build them straight back — asking would be a question
        about something that isn't happening.
        """
        from ..commands import RemoveFrameCommand
        if not (node_ids or conn_ids or frame_ids):
            return
        collapsed = [fid for fid in frame_ids
                     if fid in self.graph.frames
                     and self.graph.frames[fid].collapsed]
        members: list = []
        nested: list = []
        for frame_id in collapsed:
            members.extend(self._hidden.get(frame_id, ()))
            nested.extend(self._hidden_frames.get(frame_id, ()))
        if confirm and members and self.confirm_collapsed_delete is not None:
            titles = [self.graph.frames[f].title for f in collapsed]
            if not self.confirm_collapsed_delete(titles, len(members)):
                return
        all_nodes = list(dict.fromkeys([*node_ids, *members]))
        all_frames = list(dict.fromkeys([*frame_ids, *nested]))

        self.undo_stack.beginMacro("delete selection")
        if all_nodes or conn_ids:
            # first: it reads the wires that are about to go
            self._push_orphan_snapshots(conn_ids=conn_ids, node_ids=all_nodes)
        # Frames before nodes, because undo runs a macro backwards. The other
        # way round, undo re-adds a collapsed frame while none of its members
        # exist yet, it folds around nothing, and the nodes then come back
        # visible on top of the box.
        for frame_id in all_frames:
            self.undo_stack.push(RemoveFrameCommand(self.graph, frame_id))
        if all_nodes or conn_ids:
            self.undo_stack.push(
                RemoveSelectionCommand(self.graph, all_nodes, conn_ids))
        self.undo_stack.endMacro()

    # -------------------------------------------------------------- layering

    def restack_selection(self, action: str) -> bool:
        """Bring the selection to the front / forward / backward / to the
        back. Nodes and frames restack within their own kind — a frame can't
        be lifted over a node, so raising a mixed selection means raising
        each of them among its own peers, in one undo step.

        Returns whether anything actually moved, so a caller can leave the
        keystroke to another handler when it didn't.
        """
        from flograph.core.layers import restack

        from ..commands import RestackCommand
        moves = []
        for kind, ids in (("node", {i.node.id for i in self.selected_node_items()}),
                          ("frame", {i.frame.id for i in self.selectedItems()
                                     if isinstance(i, FrameItem)})):
            if not ids:
                continue
            current = self.graph.stacking_order(kind)
            new = restack(current, ids, action)
            if new != current:
                moves.append((kind, new))
        if not moves:
            return False
        label = LAYER_LABELS[action]
        self.undo_stack.beginMacro(label)
        for kind, order in moves:
            self.undo_stack.push(
                RestackCommand(self.graph, kind, order, text=label))
        self.undo_stack.endMacro()
        return True

    def _push_orphan_snapshots(self, *, conn_ids=(), node_ids=()) -> None:
        """Freeze what a linked Table is *showing* into its own sheet before
        the wire feeding it is cut, so disconnecting an input keeps the
        contents instead of collapsing the grid back to the user's own
        columns. Pushed inside the caller's macro, so one Ctrl+Z takes the
        wire and the snapshot back together.

        Must run before the removal command, while the connection is still
        there to follow upstream.
        """
        if self.output_cache is None:
            return
        from flograph.engine.introspect import orphaned_table_sheets

        from ..commands import SetParamCommand
        kept = []
        for node_id, data in orphaned_table_sheets(
                self.graph, self.output_cache,
                conn_ids=conn_ids, node_ids=node_ids):
            self.undo_stack.push(SetParamCommand(
                self.graph, node_id, "data", data, merge=False))
            kept.append(node_id)
        if kept:
            # rewriting someone's sheet behind their back deserves saying so
            self.tables_kept.emit(kept)

    # ---------------------------------------------------------- frame edits

    def push_frame_rect(self, frame_id: str, pos, size) -> None:
        self.undo_stack.push(UpdateFrameCommand(
            self.graph, frame_id,
            rect=(pos.x(), pos.y(), size[0], size[1])))

    def push_frame_move(self, frame_id: str, pos, size, node_moves: dict,
                        nested: Optional[dict] = None) -> None:
        self.undo_stack.beginMacro("move frame")
        self.push_frame_rect(frame_id, pos, size)
        if node_moves:
            self.push_move_command(node_moves)
        # frames nested inside travel with it, in the same step: a nested
        # frame left behind is merely odd while both are open, and outright
        # corruption once the outer one has been folded over it
        for nested_id, rect in (nested or {}).items():
            self.undo_stack.push(UpdateFrameCommand(
                self.graph, nested_id, rect=rect))
        self.undo_stack.endMacro()

    def push_frame_title(self, frame_id: str, title: str) -> None:
        self.undo_stack.push(UpdateFrameCommand(self.graph, frame_id, title=title))

    def push_frame_color(self, frame_id: str, color: str) -> None:
        self.undo_stack.push(UpdateFrameCommand(self.graph, frame_id, color=color))

    def push_node_color(self, node_id: str, color: Optional[str]) -> None:
        self.undo_stack.push(SetNodeColorCommand(self.graph, node_id, color))

    def push_node_mark(self, node_id: str, mark: str, mark_text: str,
                       mark_image: str = "") -> None:
        self.undo_stack.push(SetNodeMarkCommand(
            self.graph, node_id, mark, mark_text, mark_image))

    def push_compact_view(self, node_id: str,
                          compact: Optional[bool]) -> None:
        self.undo_stack.push(
            SetCompactViewCommand(self.graph, node_id, compact))

    # -------------------------------------------------------------- reroute

    def insert_reroute(self, conn: Connection, scene_pos: QPointF) -> None:
        """Split a wire with a reroute dot at the given position."""
        if self.registry is None:
            return
        node = self.registry.instantiate(
            REROUTE_TYPE, pos=(scene_pos.x() - 14, scene_pos.y() - 12))
        self.undo_stack.beginMacro("insert reroute")
        self.undo_stack.push(AddNodeCommand(self.graph, node))
        self.undo_stack.push(DisconnectCommand(self.graph, conn.id))
        self.undo_stack.push(ConnectCommand(
            self.graph, conn.src_node, conn.src_port, node.id, "value"))
        self.undo_stack.push(ConnectCommand(
            self.graph, node.id, "value", conn.dst_node, conn.dst_port))
        self.undo_stack.endMacro()

    # ------------------------------------------------- node drop targeting

    @staticmethod
    def _owning_node_item(item) -> Optional[NodeItem]:
        """The NodeItem an item belongs to: pins and embedded widgets are
        its children, and a drop on any of them is a drop on the node."""
        while item is not None:
            if isinstance(item, NodeItem):
                return item
            item = item.parentItem()
        return None

    def drop_target_at(self, type_id: str,
                       scene_pos: QPointF) -> Optional[tuple]:
        """What dropping a node of `type_id` at `scene_pos` would do.

        ("wire", ConnectionItem) splices the new node into that wire;
        ("node", NodeItem) replaces that node with it; None is an ordinary
        add. A target only ever comes back when the drop would fully
        succeed — the highlight the view shows from this answer must never
        promise something the command cannot deliver.

        Nodes stack above wires, so walking items() front to back answers
        "the thing you see under the cursor" first. A locked node is
        transparent here (it refuses replacement) and so is anything hidden
        inside a collapsed frame.
        """
        spec = self.registry.maybe_get(type_id) if self.registry else None
        if spec is None:
            return None
        for raw in self.items(scene_pos):
            node_item = self._owning_node_item(raw)
            if node_item is not None:
                if not node_item.isVisible() or node_item.node.locked:
                    continue
                return ("node", node_item)
            if not isinstance(raw, ConnectionItem):
                continue
            if raw.is_order or not raw.isVisible():
                continue
            conn = raw.conn
            src = self.graph.nodes.get(conn.src_node)
            dst = self.graph.nodes.get(conn.dst_node)
            if src is None or dst is None:
                continue
            out_spec = src.spec.output(conn.src_port)
            in_spec = dst.spec.input(conn.dst_port)
            if out_spec is None or in_spec is None:
                continue
            # both ends must land somewhere on the new node, or the splice
            # would cut the flow it was meant to join
            if not any(can_connect(out_spec.type, p.type) for p in spec.inputs):
                continue
            if not any(can_connect(p.type, in_spec.type) for p in spec.outputs):
                continue
            return ("wire", raw)
        return None

    def set_drop_hint(self, target: Optional[tuple]) -> None:
        """Show the drop affordance for `target` from drop_target_at, and
        take down whatever it showed before. None clears."""
        conn_item = target[1] if target and target[0] == "wire" else None
        node_item = target[1] if target and target[0] == "node" else None
        if conn_item is self._drop_hint_conn and node_item is self._drop_hint_node:
            return
        if self._drop_hint_conn is not None and self._drop_hint_conn is not conn_item:
            self._drop_hint_conn.set_drop_hint(False)
            self._drop_hint_conn = None
        if self._drop_hint_node is not None and self._drop_hint_node is not node_item:
            self._drop_hint_node.set_drop_hint(False)
            self._drop_hint_node = None
        if conn_item is not None:
            conn_item.set_drop_hint(True)
            self._drop_hint_conn = conn_item
        if node_item is not None:
            node_item.set_drop_hint(True)
            self._drop_hint_node = node_item

    def clear_drop_hint(self) -> None:
        self.set_drop_hint(None)

    # ----------------------------------------------------- splice / replace

    def splice_into_wire(self, type_id: str, conn_id: str,
                         scene_pos: QPointF) -> bool:
        """Drop-splice: insert a new node of `type_id` into wire `conn_id`,
        between its source and destination, at `scene_pos`.

        All-or-nothing by design: both ends must find a compatible port on
        the new node, or nothing happens and the caller falls back to a
        plain add — half a splice would silently cut the flow it was meant
        to join. Returns whether the splice happened.
        """
        if self.registry is None:
            return False
        conn = self.graph.connections.get(conn_id)
        if conn is None:
            return False
        spec = self.registry.maybe_get(type_id)
        src = self.graph.nodes.get(conn.src_node)
        dst = self.graph.nodes.get(conn.dst_node)
        if spec is None or src is None or dst is None:
            return False
        out_spec = src.spec.output(conn.src_port)
        in_spec = dst.spec.input(conn.dst_port)
        if out_spec is None or in_spec is None:
            return False
        port_in = next((p for p in spec.inputs
                        if can_connect(out_spec.type, p.type)), None)
        port_out = next((p for p in spec.outputs
                        if can_connect(p.type, in_spec.type)), None)
        if port_in is None or port_out is None:
            return False
        node = self.registry.instantiate(
            type_id, pos=(scene_pos.x(), scene_pos.y()))
        self.undo_stack.beginMacro(f"splice in {spec.label}")
        self.undo_stack.push(AddNodeCommand(self.graph, node))
        # free the destination's input before the new wire claims it, so no
        # connection of the flow's is displaced by its own splice
        self.undo_stack.push(DisconnectCommand(self.graph, conn.id))
        self.undo_stack.push(ConnectCommand(
            self.graph, conn.src_node, conn.src_port, node.id, port_in.name))
        self.undo_stack.push(ConnectCommand(
            self.graph, node.id, port_out.name, conn.dst_node, conn.dst_port))
        self.undo_stack.endMacro()
        return True

    def replace_node_with(self, type_id: str, node_id: str) -> bool:
        """Drop-replace: swap the node `node_id` for a new one of `type_id`
        at the same position, carrying across every wire whose end finds a
        home on the new node.

        Matching prefers the port of the same name, then any compatible
        unclaimed one. Wires that cannot be remapped are cut rather than
        forced; order edges always survive, since every node has the flow
        ports they run between. A locked node refuses. Returns whether the
        replacement happened.
        """
        old = self.graph.nodes.get(node_id)
        if old is None or old.locked:
            return False
        if self.registry is None:
            return False
        spec = self.registry.maybe_get(type_id)
        if spec is None:
            return False

        def source_out_type(conn):
            src = self.graph.nodes.get(conn.src_node)
            port = src.spec.output(conn.src_port) if src else None
            return port.type if port else None

        def dest_in_type(conn):
            dst = self.graph.nodes.get(conn.dst_node)
            port = dst.spec.input(conn.dst_port) if dst else None
            return port.type if port else None

        incoming = [c for c in self.graph.connections.values()
                    if c.dst_node == node_id]
        outgoing = [c for c in self.graph.connections.values()
                    if c.src_node == node_id]

        # Where each surviving wire reattaches, as connect() arguments with
        # the new node standing where the old one did. Order edges need no
        # matching at all — their ports are the implicit flow pair every
        # node carries, whatever else the script declares.
        remap: list[tuple[str, str, str, str]] = []
        dropped_ids: list[str] = []

        def match(conns, spec_ports, wire_port, forward: bool) -> dict:
            """Reattach each wire to a port of the new node.

            Two passes, so a fallback can never steal the port another wire
            is named for: exact name matches are reserved across every wire
            first, then whatever is left takes the first compatible port in
            declaration order. Inputs claim exclusively (one wire per input
            is the graph's own law); outputs share when they must — they fan
            out freely, so two old outputs may feed one new one rather than
            see their consumers cut. Returns {conn_id: PortSpec}, and
            appends the hopeless wires to dropped_ids.
            """
            free = list(spec_ports)
            chosen_by_id: dict[str, object] = {}
            unmatched: list = []
            for conn in conns:
                ptype = source_out_type(conn) if forward else dest_in_type(conn)
                port = next(
                    (p for p in free
                     if p.name == wire_port(conn) and ptype is not None
                     and (can_connect(ptype, p.type) if forward
                          else can_connect(p.type, ptype))),
                    None)
                if port is not None:
                    chosen_by_id[conn.id] = port
                    free.remove(port)
                else:
                    unmatched.append(conn)
            for conn in unmatched:
                ptype = source_out_type(conn) if forward else dest_in_type(conn)
                compat = [p for p in free
                          if ptype is not None and (
                              can_connect(ptype, p.type) if forward
                              else can_connect(p.type, ptype))]
                if compat:
                    port = compat[0]
                    free.remove(port)
                elif not forward:
                    # an input would silently displace, so nothing shared is
                    # on offer there; an output already taken still beats a cut
                    port = next(
                        (p for p in spec_ports
                         if ptype is not None and can_connect(p.type, ptype)),
                        None)
                else:
                    port = None
                if port is None:
                    dropped_ids.append(conn.id)
                else:
                    chosen_by_id[conn.id] = port
            return chosen_by_id

        data_in = [c for c in incoming if not is_flow(c.dst_port)]
        data_out = [c for c in outgoing if not is_flow(c.src_port)]
        in_choice = match(data_in, spec.inputs,
                          lambda c: c.dst_port, forward=True)
        out_choice = match(data_out, spec.outputs,
                           lambda c: c.src_port, forward=False)

        # order edges first, then the remapped data wires — both as plain
        # connect() arguments with the new node standing where the old was
        # order edges first, then the remapped data wires — both as plain
        # connect() arguments with the new node standing where the old was
        node = self.registry.instantiate(type_id, pos=old.pos)
        new_id = node.id
        for conn in incoming:
            if is_flow(conn.dst_port):
                remap.append((conn.src_node, conn.src_port,
                              new_id, conn.dst_port))
        for conn in outgoing:
            if is_flow(conn.src_port):
                remap.append((new_id, conn.src_port,
                              conn.dst_node, conn.dst_port))
        for conn in data_in:
            if conn.id in in_choice:
                remap.append((conn.src_node, conn.src_port,
                              new_id, in_choice[conn.id].name))
        for conn in data_out:
            if conn.id in out_choice:
                remap.append((new_id, out_choice[conn.id].name,
                              conn.dst_node, conn.dst_port))

        kept_ids = [c.id for c in (*incoming, *outgoing)
                    if c.id not in set(dropped_ids)]
        self.undo_stack.beginMacro(f"replace {old.label}")
        # before anything moves: freezing what a linked Table shows needs
        # the wires still in place to walk upstream through them
        self._push_orphan_snapshots(conn_ids=dropped_ids)
        self.undo_stack.push(AddNodeCommand(self.graph, node))
        if old.label_override is not None:
            # constructed after the add, so undo sees the fresh node's own
            # (empty) override as the state to go back to
            self.undo_stack.push(SetLabelCommand(
                self.graph, node.id, old.label_override))
        for conn_id in kept_ids:
            self.undo_stack.push(DisconnectCommand(self.graph, conn_id))
        # removes the old node plus exactly the wires still on it — the
        # dropped ones, since the kept ones went above
        self.undo_stack.push(RemoveSelectionCommand(self.graph, [node_id]))
        for src_node, src_port, dst_node, dst_port in remap:
            self.undo_stack.push(ConnectCommand(
                self.graph, src_node, src_port, dst_node, dst_port))
        self.undo_stack.endMacro()
        return True

    # ------------------------------------------------------------ wire drag

    @property
    def wire_drag_active(self) -> bool:
        """A wire is being dragged right now — the view edge-scrolls while
        this holds, so the far port can be reached without letting go."""
        return self._pending is not None

    @property
    def group_drag_active(self) -> bool:
        """A node/frame selection is being dragged (see begin_group_drag)."""
        return self._group_drags > 0

    @property
    def canvas_drag_active(self) -> bool:
        """Anything the view should edge-scroll for."""
        return self.wire_drag_active or self.group_drag_active

    def begin_wire_drag(self, port: PortItem) -> None:
        self.cancel_wire_drag()
        fixed = port
        self._drag_detach = None
        if port.spec.direction.value == "input":
            existing = self.graph.input_connection(port.node_id, port.spec.name)
            if existing is not None:
                # grab the wire: drag continues from its source output —
                # or from the frame pin standing in for it, when that source
                # is folded away inside a collapsed frame. Reaching straight
                # for the hidden node's own pin would start the drag from a
                # point in the vacated region, nowhere near the wire.
                self._drag_detach = existing
                fixed = self.wire_anchor(existing, "src") or (
                    self.node_items[existing.src_node]
                    .output_ports[existing.src_port])
                item = self.connection_items.get(existing.id)
                if item is not None:
                    item.hide()
        if port.is_flow:
            # bring every other node's flow pins up, so there is something
            # to aim at
            self.set_drawing_order_edge(True)
        self._pending = PendingConnectionItem(fixed)
        self.addItem(self._pending)
        self._pending.update_drag(port.scenePos(), None)
        self.canvas_drag_changed.emit(True)

    def update_wire_drag(self, scene_pos: QPointF) -> None:
        if self._pending is None:
            return
        target = self._port_at(scene_pos)
        valid = None
        if target is not None and target is not self._pending.fixed_port:
            valid = self._wire_valid(self._pending.fixed_port, target)
        self._tint(target if target is not None else None,
                   valid if target is not None else None)
        self._pending.update_drag(scene_pos, valid)

    def finish_wire_drag(self, scene_pos: QPointF) -> None:
        if self._pending is None:
            return
        fixed = self._pending.fixed_port
        target = self._port_at(scene_pos)
        detach = self._drag_detach
        self._cleanup_drag()

        if target is not None and self._wire_valid(fixed, target):
            src, dst = self._normalize(fixed, target)
            same_as_detached = (
                detach is not None
                and (detach.src_node, detach.src_port) == (src.node_id, src.spec.name)
                and (detach.dst_node, detach.dst_port) == (dst.node_id, dst.spec.name)
            )
            if same_as_detached:
                return  # dropped back where it was
            if detach is not None:
                self.undo_stack.beginMacro("move wire")
                self._push_orphan_snapshots(conn_ids=[detach.id])
                self.undo_stack.push(DisconnectCommand(self.graph, detach.id))
                self.undo_stack.push(ConnectCommand(
                    self.graph, src.node_id, src.spec.name,
                    dst.node_id, dst.spec.name))
                self.undo_stack.endMacro()
            else:
                self.undo_stack.push(ConnectCommand(
                    self.graph, src.node_id, src.spec.name,
                    dst.node_id, dst.spec.name))
        elif target is None and detach is not None:
            # dragged an existing wire off into empty space
            self.undo_stack.beginMacro("disconnect")
            self._push_orphan_snapshots(conn_ids=[detach.id])
            self.undo_stack.push(DisconnectCommand(self.graph, detach.id))
            self.undo_stack.endMacro()
        elif target is None:
            # dropped a fresh wire on the canvas: offer compatible nodes
            self.wire_dropped.emit(fixed, scene_pos)

    def cancel_wire_drag(self) -> None:
        self._cleanup_drag()

    def _cleanup_drag(self) -> None:
        had_pending = self._pending is not None
        self.set_drawing_order_edge(False)
        if self._pending is not None:
            self.removeItem(self._pending)
            self._pending = None
        if self._drag_detach is not None:
            item = self.connection_items.get(self._drag_detach.id)
            if item is not None:
                item.show()
            self._drag_detach = None
        if had_pending:
            # only on a real end: cancel_wire_drag also runs at the top of
            # begin_wire_drag, when nothing is under way to end
            self.canvas_drag_changed.emit(False)
        self._tint(None, None)

    def _tint(self, port: Optional[PortItem], valid: Optional[bool]) -> None:
        if self._tinted_port is not None and self._tinted_port is not port:
            self._tinted_port.set_drag_tint(None)
            self._tinted_port = None
        if port is not None:
            port.set_drag_tint(valid)
            self._tinted_port = port

    def _port_at(self, scene_pos: QPointF) -> Optional[PortItem]:
        for item in self.items(scene_pos):
            if isinstance(item, PortItem):
                return item
        return None

    @staticmethod
    def _normalize(a: PortItem, b: PortItem) -> tuple[PortItem, PortItem]:
        """(output, input) regardless of drag direction."""
        return (a, b) if a.spec.direction.value == "output" else (b, a)

    def _wire_valid(self, a: PortItem, b: PortItem) -> bool:
        if a.spec.direction == b.spec.direction:
            return False
        src, dst = self._normalize(a, b)
        if src.node_id == dst.node_id:
            return False
        if not can_connect(src.spec.type, dst.spec.type):
            return False
        # ignore the wire being dragged when checking cycles: it is already
        # disconnected conceptually, and re-plugging it can't add a cycle it
        # didn't already have unless endpoints changed (checked normally).
        return not self.graph.would_cycle(src.node_id, dst.node_id)
