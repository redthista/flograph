"""The graph model: nodes, connections, frames, and every invariant-preserving
mutation. Pure Python, no Qt. The UI mutates the graph exclusively through
QUndoCommands that call these methods; the scene and engine react to
`graph.events`.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Iterable, Optional

from .datatypes import can_connect
from .events import GraphEvents
from .node import NodeInstance, NodeStatus, NodeSpec
from .ports import PortDirection


class GraphError(Exception):
    pass


@dataclass(frozen=True)
class Connection:
    id: str
    src_node: str
    src_port: str
    dst_node: str
    dst_port: str


@dataclass
class Frame:
    id: str
    title: str = "Frame"
    rect: tuple[float, float, float, float] = (0.0, 0.0, 300.0, 200.0)
    color: str = "#33415c"


class Graph:
    def __init__(self) -> None:
        self.nodes: dict[str, NodeInstance] = {}
        self.connections: dict[str, Connection] = {}
        self.frames: dict[str, Frame] = {}
        self.events = GraphEvents()

    # ---------------------------------------------------------------- nodes

    def node(self, node_id: str) -> NodeInstance:
        try:
            return self.nodes[node_id]
        except KeyError:
            raise GraphError(f"no node with id {node_id!r}") from None

    def add_node(self, node: NodeInstance) -> NodeInstance:
        if node.id in self.nodes:
            raise GraphError(f"node id {node.id!r} already in graph")
        self.nodes[node.id] = node
        self.events.node_added.emit(node)
        return node

    def remove_node(self, node_id: str) -> tuple[NodeInstance, list[Connection]]:
        """Remove a node and every connection touching it.

        Returns (node, removed_connections) so an undo command can restore
        both.
        """
        node = self.node(node_id)
        removed = [
            c for c in self.connections.values()
            if node_id in (c.src_node, c.dst_node)
        ]
        for conn in removed:
            self.disconnect(conn.id)
        del self.nodes[node_id]
        self.events.node_removed.emit(node_id)
        return node, removed

    def move_node(self, node_id: str, pos: tuple[float, float]) -> None:
        node = self.node(node_id)
        node.pos = (float(pos[0]), float(pos[1]))
        self.events.node_moved.emit(node_id, node.pos)

    def set_label(self, node_id: str, label: Optional[str]) -> None:
        node = self.node(node_id)
        node.label_override = label or None
        self.events.label_changed.emit(node_id)

    def set_param(self, node_id: str, name: str, value: Any) -> None:
        node = self.node(node_id)
        if node.spec.param(name) is None:
            raise GraphError(f"node {node.label!r} has no param {name!r}")
        node.params[name] = value
        self.events.param_changed.emit(node_id, name, value)
        self.mark_dirty(node_id)

    def set_code(self, node_id: str, source: str) -> list[Connection]:
        """Apply new code to a node: re-parse its spec, drop connections whose
        ports vanished or became incompatible.

        Raises NodeScriptError if the source doesn't satisfy the contract.
        Returns the dropped connections (for undo).
        """
        from .script import parse_spec  # local import: avoid cycle

        node = self.node(node_id)
        new_spec = parse_spec(source, node.spec.type_id, builtin=False)
        return self.apply_spec(node_id, source, new_spec)

    def apply_spec(self, node_id: str, code_override: Optional[str],
                   spec: NodeSpec) -> list[Connection]:
        """Swap a node's spec (fork or reset-to-library), dropping connections
        the new port set can't carry. Returns the dropped connections."""
        node = self.node(node_id)
        node.code_override = code_override
        node.spec = spec
        # keep param values that still exist; adopt defaults for new ones
        node.params = {**spec.default_params(),
                       **{k: v for k, v in node.params.items() if spec.param(k)}}
        removed = [c for c in self._connections_of(node_id)
                   if not self._still_valid(c)]
        for conn in removed:
            self.disconnect(conn.id)
        self.events.code_changed.emit(node_id)
        self.mark_dirty(node_id)
        return removed

    def restore_spec(self, node_id: str, code_override: Optional[str], spec: NodeSpec) -> None:
        """Low-level: put back a previous spec/override pair (undo of set_code
        or 'reset to library'). Caller restores dropped connections itself."""
        node = self.node(node_id)
        node.code_override = code_override
        node.spec = spec
        node.params = {**spec.default_params(),
                       **{k: v for k, v in node.params.items() if spec.param(k)}}
        self.events.code_changed.emit(node_id)
        self.mark_dirty(node_id)

    # ----------------------------------------------------------- connections

    def connect(
        self,
        src_node: str,
        src_port: str,
        dst_node: str,
        dst_port: str,
        conn_id: Optional[str] = None,
    ) -> tuple[Connection, Optional[Connection]]:
        """Create a connection, validating everything.

        An input port holds at most one connection: an existing one is
        disconnected ("displaced") and returned so undo can restore it.
        """
        src = self.node(src_node)
        dst = self.node(dst_node)
        out_spec = src.spec.output(src_port)
        in_spec = dst.spec.input(dst_port)
        if out_spec is None:
            raise GraphError(f"node {src.label!r} has no output port {src_port!r}")
        if in_spec is None:
            raise GraphError(f"node {dst.label!r} has no input port {dst_port!r}")
        if not can_connect(out_spec.type, in_spec.type):
            raise GraphError(
                f"cannot connect {out_spec.type.value} -> {in_spec.type.value}"
            )
        if self.would_cycle(src_node, dst_node):
            raise GraphError("connection would create a cycle")

        displaced = self.input_connection(dst_node, dst_port)
        if displaced is not None:
            self.disconnect(displaced.id)

        conn = Connection(
            id=conn_id or uuid.uuid4().hex,
            src_node=src_node, src_port=src_port,
            dst_node=dst_node, dst_port=dst_port,
        )
        self.connections[conn.id] = conn
        self.events.connected.emit(conn)
        self.mark_dirty(dst_node)
        return conn, displaced

    def disconnect(self, conn_id: str) -> Connection:
        conn = self.connections.pop(conn_id, None)
        if conn is None:
            raise GraphError(f"no connection with id {conn_id!r}")
        self.events.disconnected.emit(conn)
        if conn.dst_node in self.nodes:
            self.mark_dirty(conn.dst_node)
        return conn

    def input_connection(self, node_id: str, port: str) -> Optional[Connection]:
        return next(
            (c for c in self.connections.values()
             if c.dst_node == node_id and c.dst_port == port),
            None,
        )

    def in_connections(self, node_id: str) -> list[Connection]:
        return [c for c in self.connections.values() if c.dst_node == node_id]

    def out_connections(self, node_id: str) -> list[Connection]:
        return [c for c in self.connections.values() if c.src_node == node_id]

    def _connections_of(self, node_id: str) -> list[Connection]:
        return [c for c in self.connections.values()
                if node_id in (c.src_node, c.dst_node)]

    def _still_valid(self, conn: Connection) -> bool:
        src = self.nodes.get(conn.src_node)
        dst = self.nodes.get(conn.dst_node)
        if src is None or dst is None:
            return False
        out_spec = src.spec.output(conn.src_port)
        in_spec = dst.spec.input(conn.dst_port)
        return (
            out_spec is not None
            and in_spec is not None
            and can_connect(out_spec.type, in_spec.type)
        )

    # ------------------------------------------------------------- topology

    def successors(self, node_id: str) -> set[str]:
        return {c.dst_node for c in self.connections.values() if c.src_node == node_id}

    def predecessors(self, node_id: str) -> set[str]:
        return {c.src_node for c in self.connections.values() if c.dst_node == node_id}

    def would_cycle(self, src_node: str, dst_node: str) -> bool:
        """Would a wire src_node -> dst_node close a cycle? True iff src_node
        is reachable downstream from dst_node (or they are the same node)."""
        if src_node == dst_node:
            return True
        return src_node in self.downstream(dst_node)

    def downstream(self, node_id: str) -> set[str]:
        """All nodes strictly downstream of node_id."""
        seen: set[str] = set()
        stack = [node_id]
        while stack:
            for nxt in self.successors(stack.pop()):
                if nxt not in seen:
                    seen.add(nxt)
                    stack.append(nxt)
        return seen

    def upstream(self, node_id: str) -> set[str]:
        """All nodes strictly upstream of node_id."""
        seen: set[str] = set()
        stack = [node_id]
        while stack:
            for prev in self.predecessors(stack.pop()):
                if prev not in seen:
                    seen.add(prev)
                    stack.append(prev)
        return seen

    def topo_order(self, subset: Optional[Iterable[str]] = None) -> list[str]:
        """Kahn's algorithm over the whole graph (or an induced subgraph),
        deterministic in node insertion order."""
        ids = list(self.nodes) if subset is None else [
            n for n in self.nodes if n in set(subset)
        ]
        id_set = set(ids)
        indegree = {
            n: sum(1 for p in self.predecessors(n) if p in id_set) for n in ids
        }
        queue = [n for n in ids if indegree[n] == 0]
        order: list[str] = []
        while queue:
            current = queue.pop(0)
            order.append(current)
            in_subset = [n for n in self.successors(current) if n in id_set]
            for nxt in sorted(in_subset, key=ids.index):
                indegree[nxt] -= 1
                if indegree[nxt] == 0:
                    queue.append(nxt)
        if len(order) != len(ids):
            raise GraphError("graph contains a cycle")
        return order

    # ------------------------------------------------------- dirty & status

    def mark_dirty(self, node_id: str) -> None:
        """Mark a node and everything downstream of it dirty."""
        for nid in [node_id, *self.downstream(node_id)]:
            node = self.nodes[nid]
            if not node.dirty:
                node.dirty = True
                self.events.dirty_changed.emit(nid, True)

    def mark_clean(self, node_id: str) -> None:
        node = self.node(node_id)
        if node.dirty:
            node.dirty = False
            self.events.dirty_changed.emit(node_id, False)

    def set_status(self, node_id: str, status: NodeStatus, message: str = "") -> None:
        node = self.node(node_id)
        node.status = status
        node.status_message = message
        self.events.status_changed.emit(node_id, status, message)

    # --------------------------------------------------------------- frames

    def add_frame(self, frame: Frame) -> Frame:
        if frame.id in self.frames:
            raise GraphError(f"frame id {frame.id!r} already in graph")
        self.frames[frame.id] = frame
        self.events.frame_added.emit(frame)
        return frame

    def remove_frame(self, frame_id: str) -> Frame:
        frame = self.frames.pop(frame_id, None)
        if frame is None:
            raise GraphError(f"no frame with id {frame_id!r}")
        self.events.frame_removed.emit(frame_id)
        return frame

    def update_frame(self, frame_id: str, *, title: Optional[str] = None,
                     rect: Optional[tuple[float, float, float, float]] = None,
                     color: Optional[str] = None) -> Frame:
        frame = self.frames.get(frame_id)
        if frame is None:
            raise GraphError(f"no frame with id {frame_id!r}")
        if title is not None:
            frame.title = title
        if rect is not None:
            frame.rect = tuple(float(v) for v in rect)  # type: ignore[assignment]
        if color is not None:
            frame.color = color
        self.events.frame_changed.emit(frame)
        return frame
