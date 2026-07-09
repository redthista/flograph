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

from flopy.core import (
    Connection, Frame, Graph, NodeInstance, NodeRegistry, PortSpec, can_connect,
)
from flopy.core.node import NodeStatus

from ..commands import (
    AddNodeCommand, ConnectCommand, DisconnectCommand, MoveNodesCommand,
    RemoveSelectionCommand, UpdateFrameCommand,
)
from .connection_item import ConnectionItem, PendingConnectionItem
from .frame_item import FrameItem
from .node_item import NodeItem, PortItem

SCENE_EXTENT = 1_000_000.0
REROUTE_TYPE = "flopy.util.reroute"


class NodeGraphScene(QGraphicsScene):
    node_double_clicked = Signal(str)   # node_id
    node_rename_requested = Signal(str)  # node_id — header was double-clicked
    wire_dropped = Signal(object, QPointF)  # fixed PortItem, scene pos
    button_fired = Signal(str)          # node_id — an Action Button was clicked
    frame_run_requested = Signal(str)   # frame_id — a frame's run glyph was clicked

    def __init__(self, graph: Graph, undo_stack: QUndoStack,
                 registry: Optional[NodeRegistry] = None, parent=None) -> None:
        super().__init__(parent)
        self.graph = graph
        self.undo_stack = undo_stack
        self.registry = registry
        self.node_items: dict[str, NodeItem] = {}
        self.connection_items: dict[str, ConnectionItem] = {}
        self.frame_items: dict[str, FrameItem] = {}

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
        events.dirty_changed.connect(self._on_dirty_changed)
        events.label_changed.connect(self._on_label_changed)
        events.frame_added.connect(self._on_frame_added)
        events.frame_removed.connect(self._on_frame_removed)
        events.frame_changed.connect(self._on_frame_changed)

        # mirror pre-existing graph content (e.g. a loaded project)
        for node in graph.nodes.values():
            self._on_node_added(node)
        for conn in graph.connections.values():
            self._on_connected(conn)
        for frame in graph.frames.values():
            self._on_frame_added(frame)

    # ------------------------------------------------------- event mirrors

    def _on_node_added(self, node: NodeInstance) -> None:
        item = NodeItem(node)
        self.addItem(item)
        self.node_items[node.id] = item

    def _on_node_removed(self, node_id: str) -> None:
        item = self.node_items.pop(node_id, None)
        if item is not None:
            self.removeItem(item)

    def _on_connected(self, conn: Connection) -> None:
        src = self.node_items[conn.src_node].output_ports[conn.src_port]
        dst = self.node_items[conn.dst_node].input_ports[conn.dst_port]
        item = ConnectionItem(conn, src, dst)
        self.addItem(item)
        self.connection_items[conn.id] = item
        dst.update()  # input pin becomes filled

    def _on_disconnected(self, conn: Connection) -> None:
        item = self.connection_items.pop(conn.id, None)
        if item is not None:
            self.removeItem(item)
        dst_item = self.node_items.get(conn.dst_node)
        if dst_item is not None:
            port = dst_item.input_ports.get(conn.dst_port)
            if port is not None:
                port.update()

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

    def _on_param_changed(self, node_id: str, name: str, value) -> None:
        item = self.node_items.get(node_id)
        if item is not None:
            item.on_params_changed()

    def _on_status_changed(self, node_id: str, status: NodeStatus, message: str) -> None:
        item = self.node_items.get(node_id)
        if item is not None:
            item.on_status_changed()
            item.setToolTip(message if status == NodeStatus.ERROR else "")

    def _on_dirty_changed(self, node_id: str, dirty: bool) -> None:
        item = self.node_items.get(node_id)
        if item is not None:
            item.update()

    def _on_label_changed(self, node_id: str) -> None:
        item = self.node_items.get(node_id)
        if item is not None:
            item.update()

    def _on_frame_added(self, frame: Frame) -> None:
        item = FrameItem(frame)
        item.run_requested.connect(self.frame_run_requested.emit)
        self.addItem(item)
        self.frame_items[frame.id] = item

    def _on_frame_removed(self, frame_id: str) -> None:
        item = self.frame_items.pop(frame_id, None)
        if item is not None:
            self.removeItem(item)

    def _on_frame_changed(self, frame: Frame) -> None:
        item = self.frame_items.get(frame.id)
        if item is not None:
            item.sync_from_model()

    # ------------------------------------------------------------- helpers

    def is_port_connected(self, node_id: str, spec: PortSpec) -> bool:
        if spec.direction.value == "input":
            return self.graph.input_connection(node_id, spec.name) is not None
        return any(c.src_node == node_id and c.src_port == spec.name
                   for c in self.graph.connections.values())

    def selected_node_items(self) -> list[NodeItem]:
        return [i for i in self.selectedItems() if isinstance(i, NodeItem)]

    def node_item_moved(self, node_id: str) -> None:
        for ci in self.connection_items.values():
            if node_id in (ci.conn.src_node, ci.conn.dst_node):
                ci.update_path()

    def push_move_command(self, moves: dict) -> None:
        self.undo_stack.push(MoveNodesCommand(self.graph, moves))

    def delete_selection(self) -> None:
        from ..commands import RemoveFrameCommand
        node_ids = [i.node.id for i in self.selected_node_items()]
        conn_ids = [i.conn.id for i in self.selectedItems()
                    if isinstance(i, ConnectionItem)]
        frame_ids = [i.frame.id for i in self.selectedItems()
                     if isinstance(i, FrameItem)]
        if not (node_ids or conn_ids or frame_ids):
            return
        self.undo_stack.beginMacro("delete selection")
        if node_ids or conn_ids:
            self.undo_stack.push(
                RemoveSelectionCommand(self.graph, node_ids, conn_ids))
        for frame_id in frame_ids:
            self.undo_stack.push(RemoveFrameCommand(self.graph, frame_id))
        self.undo_stack.endMacro()

    # ---------------------------------------------------------- frame edits

    def push_frame_rect(self, frame_id: str, pos, size) -> None:
        self.undo_stack.push(UpdateFrameCommand(
            self.graph, frame_id,
            rect=(pos.x(), pos.y(), size[0], size[1])))

    def push_frame_move(self, frame_id: str, pos, size, node_moves: dict) -> None:
        self.undo_stack.beginMacro("move frame")
        self.push_frame_rect(frame_id, pos, size)
        if node_moves:
            self.push_move_command(node_moves)
        self.undo_stack.endMacro()

    def push_frame_title(self, frame_id: str, title: str) -> None:
        self.undo_stack.push(UpdateFrameCommand(self.graph, frame_id, title=title))

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
                # grab the wire: drag continues from its source output
                self._drag_detach = existing
                fixed = (self.node_items[existing.src_node]
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
            self.undo_stack.push(DisconnectCommand(self.graph, detach.id))
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
