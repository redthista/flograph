"""QUndoCommand set — the *only* code allowed to mutate the Graph.

Item interactions and widgets build commands and push them onto the window's
QUndoStack; redo() mutates the graph, graph events update the scene. That
one-way flow is what makes undo/redo, load, and paste all take the same path.
"""
from __future__ import annotations

from typing import Any, Optional

from PySide6.QtGui import QUndoCommand

from flopy.core import Connection, Frame, Graph, NodeInstance, NodeSpec, Page, Tile

_ID_MOVE = 1001
_ID_PARAM = 1002
_ID_TILE_RECT = 1003


class AddNodeCommand(QUndoCommand):
    def __init__(self, graph: Graph, node: NodeInstance,
                 parent: Optional[QUndoCommand] = None) -> None:
        super().__init__(f"add {node.label}", parent)
        self._graph = graph
        self._node = node

    def redo(self) -> None:
        self._graph.add_node(self._node)

    def undo(self) -> None:
        self._graph.remove_node(self._node.id)


class RemoveSelectionCommand(QUndoCommand):
    """Delete nodes and/or wires. Captures every connection that goes away
    (explicitly selected ones plus those attached to removed nodes) and
    restores everything in dependency order on undo."""

    def __init__(self, graph: Graph, node_ids: list[str],
                 conn_ids: list[str] = (),
                 parent: Optional[QUndoCommand] = None) -> None:
        super().__init__("delete selection", parent)
        self._graph = graph
        self._node_ids = list(node_ids)
        self._extra_conn_ids = [c for c in conn_ids]
        self._nodes: list[NodeInstance] = []
        self._connections: dict[str, Connection] = {}

    def redo(self) -> None:
        self._nodes = []
        self._connections = {}
        for conn_id in self._extra_conn_ids:
            if conn_id in self._graph.connections:
                conn = self._graph.disconnect(conn_id)
                self._connections[conn.id] = conn
        for node_id in self._node_ids:
            node, removed = self._graph.remove_node(node_id)
            self._nodes.append(node)
            for conn in removed:
                self._connections[conn.id] = conn

    def undo(self) -> None:
        for node in self._nodes:
            self._graph.add_node(node)
        for conn in self._connections.values():
            self._graph.connect(conn.src_node, conn.src_port,
                                conn.dst_node, conn.dst_port, conn_id=conn.id)


class ConnectCommand(QUndoCommand):
    def __init__(self, graph: Graph, src_node: str, src_port: str,
                 dst_node: str, dst_port: str,
                 parent: Optional[QUndoCommand] = None) -> None:
        super().__init__("connect", parent)
        self._graph = graph
        self._ends = (src_node, src_port, dst_node, dst_port)
        self._conn_id: Optional[str] = None
        self._displaced: Optional[Connection] = None

    def redo(self) -> None:
        conn, displaced = self._graph.connect(*self._ends, conn_id=self._conn_id)
        self._conn_id = conn.id  # stable across undo/redo cycles
        self._displaced = displaced

    def undo(self) -> None:
        self._graph.disconnect(self._conn_id)
        if self._displaced is not None:
            d = self._displaced
            self._graph.connect(d.src_node, d.src_port, d.dst_node, d.dst_port,
                                conn_id=d.id)


class DisconnectCommand(QUndoCommand):
    def __init__(self, graph: Graph, conn_id: str,
                 parent: Optional[QUndoCommand] = None) -> None:
        super().__init__("disconnect", parent)
        self._graph = graph
        self._conn_id = conn_id
        self._conn: Optional[Connection] = None

    def redo(self) -> None:
        self._conn = self._graph.disconnect(self._conn_id)

    def undo(self) -> None:
        c = self._conn
        self._graph.connect(c.src_node, c.src_port, c.dst_node, c.dst_port,
                            conn_id=c.id)


class MoveNodesCommand(QUndoCommand):
    """One drag (or nudge) of any number of nodes; consecutive moves of the
    same node set merge into a single undo step."""

    def __init__(self, graph: Graph,
                 moves: dict[str, tuple[tuple[float, float], tuple[float, float]]],
                 parent: Optional[QUndoCommand] = None) -> None:
        super().__init__("move", parent)
        self._graph = graph
        self._moves = dict(moves)  # node_id -> (old_pos, new_pos)

    def id(self) -> int:
        return _ID_MOVE

    def redo(self) -> None:
        for node_id, (_, new) in self._moves.items():
            self._graph.move_node(node_id, new)

    def undo(self) -> None:
        for node_id, (old, _) in self._moves.items():
            self._graph.move_node(node_id, old)

    def mergeWith(self, other: QUndoCommand) -> bool:
        if not isinstance(other, MoveNodesCommand):
            return False
        if set(other._moves) != set(self._moves):
            return False
        for node_id, (_, new) in other._moves.items():
            old, _ = self._moves[node_id]
            self._moves[node_id] = (old, new)
        return True


class SetParamCommand(QUndoCommand):
    """Edits of the same param merge while it stays the latest command."""

    def __init__(self, graph: Graph, node_id: str, name: str, new_value: Any,
                 parent: Optional[QUndoCommand] = None) -> None:
        super().__init__(f"set {name}", parent)
        self._graph = graph
        self._node_id = node_id
        self._name = name
        self._old = graph.node(node_id).params.get(name)
        self._new = new_value

    def id(self) -> int:
        return _ID_PARAM

    def redo(self) -> None:
        self._graph.set_param(self._node_id, self._name, self._new)

    def undo(self) -> None:
        self._graph.set_param(self._node_id, self._name, self._old)

    def mergeWith(self, other: QUndoCommand) -> bool:
        if (not isinstance(other, SetParamCommand)
                or other._node_id != self._node_id
                or other._name != self._name):
            return False
        self._new = other._new
        return True


class SetCodeCommand(QUndoCommand):
    """Apply new code to a node. The graph re-parses the spec and drops
    connections to vanished/incompatible ports; undo restores the previous
    spec, override state, and those connections.

    The caller must have validated the source with parse_spec first —
    redo() must not raise."""

    def __init__(self, graph: Graph, node_id: str, new_source: str,
                 parent: Optional[QUndoCommand] = None) -> None:
        super().__init__("edit code", parent)
        self._graph = graph
        self._node_id = node_id
        self._new_source = new_source
        node = graph.node(node_id)
        self._old_override = node.code_override
        self._old_spec: NodeSpec = node.spec
        self._old_params = dict(node.params)
        self._dropped: list[Connection] = []

    def redo(self) -> None:
        self._dropped = self._graph.set_code(self._node_id, self._new_source)

    def undo(self) -> None:
        self._graph.restore_spec(self._node_id, self._old_override, self._old_spec)
        self._graph.node(self._node_id).params = dict(self._old_params)
        for conn in self._dropped:
            self._graph.connect(conn.src_node, conn.src_port,
                                conn.dst_node, conn.dst_port, conn_id=conn.id)


class ResetCodeCommand(QUndoCommand):
    """Discard a node's forked code and go back to the library spec."""

    def __init__(self, graph: Graph, node_id: str, library_spec: NodeSpec,
                 parent: Optional[QUndoCommand] = None) -> None:
        super().__init__("reset to library", parent)
        self._graph = graph
        self._node_id = node_id
        self._library_spec = library_spec
        node = graph.node(node_id)
        self._old_override = node.code_override
        self._old_spec = node.spec
        self._old_params = dict(node.params)
        self._dropped: list[Connection] = []

    def redo(self) -> None:
        self._dropped = self._graph.apply_spec(
            self._node_id, None, self._library_spec)

    def undo(self) -> None:
        self._graph.restore_spec(self._node_id, self._old_override, self._old_spec)
        self._graph.node(self._node_id).params = dict(self._old_params)
        for conn in self._dropped:
            self._graph.connect(conn.src_node, conn.src_port,
                                conn.dst_node, conn.dst_port, conn_id=conn.id)


class SetLabelCommand(QUndoCommand):
    def __init__(self, graph: Graph, node_id: str, new_label: Optional[str],
                 parent: Optional[QUndoCommand] = None) -> None:
        super().__init__("rename node", parent)
        self._graph = graph
        self._node_id = node_id
        self._old = graph.node(node_id).label_override
        self._new = new_label

    def redo(self) -> None:
        self._graph.set_label(self._node_id, self._new)

    def undo(self) -> None:
        self._graph.set_label(self._node_id, self._old)


class AddFrameCommand(QUndoCommand):
    def __init__(self, graph: Graph, frame: Frame,
                 parent: Optional[QUndoCommand] = None) -> None:
        super().__init__("add frame", parent)
        self._graph = graph
        self._frame = frame

    def redo(self) -> None:
        self._graph.add_frame(self._frame)

    def undo(self) -> None:
        self._graph.remove_frame(self._frame.id)


class RemoveFrameCommand(QUndoCommand):
    def __init__(self, graph: Graph, frame_id: str,
                 parent: Optional[QUndoCommand] = None) -> None:
        super().__init__("remove frame", parent)
        self._graph = graph
        self._frame_id = frame_id
        self._frame: Optional[Frame] = None

    def redo(self) -> None:
        self._frame = self._graph.remove_frame(self._frame_id)

    def undo(self) -> None:
        self._graph.add_frame(self._frame)


class UpdateFrameCommand(QUndoCommand):
    def __init__(self, graph: Graph, frame_id: str, *,
                 title: Optional[str] = None,
                 rect: Optional[tuple] = None,
                 color: Optional[str] = None,
                 parent: Optional[QUndoCommand] = None) -> None:
        super().__init__("edit frame", parent)
        self._graph = graph
        self._frame_id = frame_id
        frame = graph.frames[frame_id]
        self._old = (frame.title, frame.rect, frame.color)
        self._new = (title if title is not None else frame.title,
                     tuple(rect) if rect is not None else frame.rect,
                     color if color is not None else frame.color)

    def redo(self) -> None:
        title, rect, color = self._new
        self._graph.update_frame(self._frame_id, title=title, rect=rect, color=color)

    def undo(self) -> None:
        title, rect, color = self._old
        self._graph.update_frame(self._frame_id, title=title, rect=rect, color=color)


class AddPageCommand(QUndoCommand):
    def __init__(self, graph: Graph, page: Page,
                 parent: Optional[QUndoCommand] = None) -> None:
        super().__init__("add page", parent)
        self._graph = graph
        self._page = page

    def redo(self) -> None:
        self._graph.add_page(self._page)

    def undo(self) -> None:
        self._graph.remove_page(self._page.id)


class RemovePageCommand(QUndoCommand):
    def __init__(self, graph: Graph, page_id: str,
                 parent: Optional[QUndoCommand] = None) -> None:
        super().__init__("remove page", parent)
        self._graph = graph
        self._page_id = page_id
        self._page: Optional[Page] = None  # tiles ride along with the Page

    def redo(self) -> None:
        self._page = self._graph.remove_page(self._page_id)

    def undo(self) -> None:
        self._graph.add_page(self._page)


class RenamePageCommand(QUndoCommand):
    def __init__(self, graph: Graph, page_id: str, title: str,
                 parent: Optional[QUndoCommand] = None) -> None:
        super().__init__("rename page", parent)
        self._graph = graph
        self._page_id = page_id
        self._old = graph.page(page_id).title
        self._new = title

    def redo(self) -> None:
        self._graph.update_page(self._page_id, title=self._new)

    def undo(self) -> None:
        self._graph.update_page(self._page_id, title=self._old)


class AddTileCommand(QUndoCommand):
    def __init__(self, graph: Graph, page_id: str, tile: Tile,
                 parent: Optional[QUndoCommand] = None) -> None:
        super().__init__("add tile", parent)
        self._graph = graph
        self._page_id = page_id
        self._tile = tile

    def redo(self) -> None:
        self._graph.add_tile(self._page_id, self._tile)

    def undo(self) -> None:
        self._graph.remove_tile(self._page_id, self._tile.id)


class RemoveTileCommand(QUndoCommand):
    def __init__(self, graph: Graph, page_id: str, tile_id: str,
                 parent: Optional[QUndoCommand] = None) -> None:
        super().__init__("remove tile", parent)
        self._graph = graph
        self._page_id = page_id
        self._tile_id = tile_id
        self._tile: Optional[Tile] = None

    def redo(self) -> None:
        self._tile = self._graph.remove_tile(self._page_id, self._tile_id)

    def undo(self) -> None:
        self._graph.add_tile(self._page_id, self._tile)


class MoveResizeTileCommand(QUndoCommand):
    """One drag of a tile (move or resize — both are just rect changes);
    consecutive rect changes of the same tile merge into one undo step."""

    def __init__(self, graph: Graph, page_id: str, tile_id: str,
                 old_rect: tuple, new_rect: tuple,
                 parent: Optional[QUndoCommand] = None) -> None:
        super().__init__("move tile", parent)
        self._graph = graph
        self._page_id = page_id
        self._tile_id = tile_id
        self._old = tuple(old_rect)
        self._new = tuple(new_rect)

    def id(self) -> int:
        return _ID_TILE_RECT

    def redo(self) -> None:
        self._graph.update_tile(self._page_id, self._tile_id, rect=self._new)

    def undo(self) -> None:
        self._graph.update_tile(self._page_id, self._tile_id, rect=self._old)

    def mergeWith(self, other: QUndoCommand) -> bool:
        if (not isinstance(other, MoveResizeTileCommand)
                or other._page_id != self._page_id
                or other._tile_id != self._tile_id):
            return False
        self._new = other._new
        return True
