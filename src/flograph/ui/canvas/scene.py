"""NodeGraphScene: a *view* of core.Graph.

One-way data flow: item interactions never mutate the graph directly — they
push QUndoCommands; command.redo() mutates the graph; graph events come back
here and update the items. Undo/redo, project load, and palette insertion all
travel the same path.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QPointF, QRectF, Signal
from PySide6.QtGui import QUndoStack
from PySide6.QtWidgets import QGraphicsScene

from flograph.core import (
    Connection, Frame, Graph, NodeInstance, NodeRegistry, PortSpec, can_connect,
)
from flograph.core.node import NodeStatus

from ..commands import (
    AddNodeCommand, ConnectCommand, DisconnectCommand, MoveNodesCommand,
    RemoveSelectionCommand, SetCompactViewCommand, SetNodeColorCommand,
    SetNodeMarkCommand, UpdateFrameCommand,
)
from .connection_item import ConnectionItem, PendingConnectionItem
from .frame_item import FrameItem
from .node_item import (
    DEFAULT_LOD_THRESHOLD, NodeItem, PortItem, compact_on,
)
from .stacking import LAYER_LABELS

SCENE_EXTENT = 1_000_000.0
REROUTE_TYPE = "flograph.util.reroute"


class NodeGraphScene(QGraphicsScene):
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
        # Which nodes each collapsed frame is standing in for. Captured when
        # the frame folds rather than re-derived from its rect on every
        # rebuild: the vacated region still looks like empty canvas, so a
        # node dropped into it later must not be silently swallowed.
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

        # Canvas-wide "float the port names beside the pins" preference; the
        # main window is the sole writer (MainWindow.set_port_labels_enabled).
        # A node that has been toggled on its own ignores this — see
        # node_item.port_labels_on.
        self.port_labels_enabled = False

        # Transient: the reveal key is held down, so every port shows its
        # name regardless of the setting above or any per-node override.
        # Not a preference and never saved — see NodeGraphView's key handling.
        self.revealing_port_labels = False

        # Canvas-wide "draw plain nodes as squares" preference; the main
        # window is the sole writer (MainWindow.set_compact_nodes). Card
        # kinds are unaffected — see NodeItem.apply_compact.
        self.compact_nodes = True

        self.setSceneRect(QRectF(-SCENE_EXTENT, -SCENE_EXTENT,
                                 2 * SCENE_EXTENT, 2 * SCENE_EXTENT))

        self._pending: Optional[PendingConnectionItem] = None
        self._drag_detach: Optional[Connection] = None
        self._tinted_port: Optional[PortItem] = None

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
        events.preview_enabled_changed.connect(self._on_preview_enabled_changed)
        events.port_labels_changed.connect(self._on_port_labels_changed)
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
        item.refresh_link_card()  # its text needs the scene's graph to resolve
        # undoing a delete puts a collapsed frame's contents back; they have
        # to go straight back under the lid rather than appear on top of it
        self._refresh_collapsed_frames()

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
            self.removeItem(item)
        self._refresh_collapsed_frames()

    def _on_connected(self, conn: Connection) -> None:
        src = self.node_items[conn.src_node].output_ports[conn.src_port]
        dst = self.node_items[conn.dst_node].input_ports[conn.dst_port]
        item = ConnectionItem(conn, src, dst)
        self.addItem(item)
        self.connection_items[conn.id] = item
        dst.refresh_connected()  # input pin becomes filled
        dst_node_item = self.node_items.get(conn.dst_node)
        if dst_node_item is not None and dst_node_item.table:
            dst_node_item.refresh_table_link()
        # a wire made through a collapsed frame's pin needs a pin of its own
        self._refresh_collapsed_frames()

    def _on_disconnected(self, conn: Connection) -> None:
        item = self.connection_items.pop(conn.id, None)
        if item is not None:
            self.removeItem(item)
        dst_item = self.node_items.get(conn.dst_node)
        if dst_item is not None:
            port = dst_item.input_ports.get(conn.dst_port)
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

    def _on_code_changed(self, node_id: str) -> None:
        item = self.node_items.get(node_id)
        if item is None:
            return
        item.rebuild_ports()
        # reattach surviving wires to the freshly built port items
        for ci in self.connection_items.values():
            if ci.conn.src_node == node_id:
                ci.src_port = item.output_ports[ci.conn.src_port]
            if ci.conn.dst_node == node_id:
                ci.dst_port = item.input_ports[ci.conn.dst_port]
            if node_id in (ci.conn.src_node, ci.conn.dst_node):
                ci.update_path()
        # a frame pin caches the spec it was built from, which has just been
        # replaced — drop them so the rebuild makes fresh ones rather than
        # leaving one pointing at a port that no longer exists
        self._drop_frame_pins_for(node_id)
        self._refresh_collapsed_frames()

    def _on_param_changed(self, node_id: str, name: str, value) -> None:
        item = self.node_items.get(node_id)
        if item is not None:
            item.on_params_changed()
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

    def _members_of(self, frame) -> tuple:
        """(node ids, nested frame ids) a frame owns, by geometry.

        Nodes by their centre, the way every other frame operation resolves
        membership. Nested frames by *full* containment rather than centre:
        a frame poking half out would take its own nodes with it, and the
        half sitting outside the parent was never the parent's to hide.
        """
        rect = QRectF(*frame.rect)
        nodes = [nid for nid, item in self.node_items.items()
                 if rect.contains(item.sceneBoundingRect().center())]
        order = {nid: i for i, nid in enumerate(self.graph.topo_order())}
        nodes.sort(key=lambda nid: order.get(nid, 0))
        frames = [fid for fid, item in self.frame_items.items()
                  if fid != frame.id and rect.contains(item.scene_rect())]
        return (nodes, frames)

    def _owner_of(self, node_id: str) -> Optional[str]:
        """The collapsed frame hiding this node, if any."""
        for frame_id, members in self._hidden.items():
            if node_id in members:
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

        # 1. membership. Captured on the fold, then only ever pruned, so
        #    anything that arrives in the vacated region afterwards stays put.
        live = {f.id for f in collapsed}
        for frame_id in list(self._hidden):
            if frame_id not in live:
                del self._hidden[frame_id]
                self._hidden_frames.pop(frame_id, None)
        for frame in collapsed:
            if frame.id not in self._hidden:
                nodes, frames = self._members_of(frame)
                self._hidden[frame.id] = nodes
                self._hidden_frames[frame.id] = frames
            else:
                self._hidden[frame.id] = [
                    nid for nid in self._hidden[frame.id]
                    if nid in self.node_items]
                self._hidden_frames[frame.id] = [
                    fid for fid in self._hidden_frames[frame.id]
                    if fid in self.frame_items]

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
        table = item.output_ports if side == "src" else item.input_ports
        port = table.get(port_name)
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

    def frame_item_moved(self, frame_id: str) -> None:
        """A collapsed frame moved, so the wires pinned to it must follow.
        node_item_moved cannot cover this: the wires' other ends are hidden
        nodes that did not themselves move relative to the box."""
        for pin in self._frame_pins.values():
            if pin.frame_item.frame.id != frame_id:
                continue
            for ci in self.connection_items.values():
                if ci.conn.id == pin.conn_id:
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

    @staticmethod
    def _repaint_ports(item) -> None:
        if item is None:
            return
        for port in (*item.input_ports.values(), *item.output_ports.values()):
            # prepareGeometryChange, not update: the label pill lives outside
            # the pin's usual 20x20 box, so the item's bounding rect really
            # does change and Qt's index has to be told
            port.prepareGeometryChange()
            port.update()

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

    def _on_frame_changed(self, frame: Frame) -> None:
        item = self.frame_items.get(frame.id)
        if item is not None:
            item.sync_from_model()
        # The captured membership is *not* dropped here: the rebuild prunes
        # frames that are no longer collapsed itself, and it has to see the
        # stale entry to know there is anything to undo. Clearing it first
        # leaves nothing to reconcile and the contents stay hidden.
        self._refresh_collapsed_frames()

    # ------------------------------------------------------------- helpers

    def is_port_connected(self, node_id: str, spec: PortSpec) -> bool:
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

    # ------------------------------------------------------- group drag/move

    def _selected_movables(self) -> list:
        """Selected items that participate in a drag: nodes and frames."""
        return [i for i in self.selectedItems()
                if isinstance(i, (NodeItem, FrameItem))]

    def begin_group_drag(self) -> dict:
        """Arm every selected node/frame for a group drag: flag each as
        dragging so its own itemChange snaps (Qt moves the whole selection by
        one delta, but only the pressed item was flagged before), and snapshot
        their start positions for the release commit."""
        starts: dict = {"nodes": {}, "frames": {}, "carried": {}}
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

    # ------------------------------------------------------------ wire drag

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
        self._pending = PendingConnectionItem(fixed)
        self.addItem(self._pending)
        self._pending.update_drag(port.scenePos(), None)

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
        if self._pending is not None:
            self.removeItem(self._pending)
            self._pending = None
        if self._drag_detach is not None:
            item = self.connection_items.get(self._drag_detach.id)
            if item is not None:
                item.show()
            self._drag_detach = None
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
