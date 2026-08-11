"""The graph model: nodes, connections, frames, and every invariant-preserving
mutation. Pure Python, no Qt. The UI mutates the graph exclusively through
QUndoCommands that call these methods; the scene and engine react to
`graph.events`.
"""
from __future__ import annotations

import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional, Sequence

from . import links
from .datatypes import can_connect
from .events import GraphEvents
from .layers import next_z, order_of
from .node import NodeInstance, NodeStatus, NodeSpec
from .page_setup import PageSetup
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


@dataclass(frozen=True)
class _EdgeIndex:
    """Three views of the same edge set, so the topology reads below are
    dictionary lookups rather than scans of every wire in the graph.

    Built by `Graph._edges()`; every field keeps the iteration order of
    `_iter_edges` — wires first, then derived links — because callers rely
    on it (`input_connection` returns the first match, and a real wire has
    to win over a link on the same port).
    """
    by_input: dict[tuple[str, str], Connection]
    into: dict[str, list[Connection]]
    out_of: dict[str, list[Connection]]


@dataclass
class Frame:
    id: str
    title: str = "Frame"
    rect: tuple[float, float, float, float] = (0.0, 0.0, 300.0, 200.0)
    color: str = "#33415c"
    z: Optional[int] = None   # stacking order among frames; see core.layers


@dataclass
class Tile:
    """A dashboard tile: a placed view of one node's output on a Page.

    `node_id` may dangle (the node was deleted, or the file references a
    node that no longer loads) — the UI shows a placeholder rather than the
    graph rejecting the tile, which keeps undo orderings and old files safe.
    """
    id: str
    node_id: str
    port: Optional[str] = None  # output port to render; None for action buttons
    rect: tuple[float, float, float, float] = (0.0, 0.0, 420.0, 320.0)
    z: Optional[int] = None   # stacking order on its page; see core.layers


@dataclass
class Page:
    """A page in the project: a dashboard (an infinite canvas of tiles) or a
    report (a markdown document that embeds node outputs by name).

    One dataclass for both because everything else about a page — title,
    colour, tab order, duplication, undo — is identical, and `kind` is what
    the window switches on to build the right widget. A report ignores
    `tiles`/`maximized_tile`; a dashboard ignores `body`. Files written
    before reports existed have no `kind` and load as dashboards.
    """
    id: str
    title: str = "Page"
    kind: str = "dashboard"       # "dashboard" | "report"
    body: str = ""                # report pages: the markdown source
    tiles: dict[str, Tile] = field(default_factory=dict)
    color: Optional[str] = None   # None = the theme's default tab colour
    # The tile shown maximized over the whole page, or None for the normal
    # layout. Saved with the project so a dashboard travels the way it was
    # laid out. May dangle (the tile was deleted) exactly like Tile.node_id
    # does — the UI ignores an id it can't resolve.
    maximized_tile: Optional[str] = None
    # Presentation mode. False = edit: a dashboard shows its visuals panel
    # and its tiles move and resize; a report shows its markdown source
    # beside the preview. True = view: the chrome for *arranging* the page
    # goes away and what is left is the page itself. Contents stay live
    # either way — a slicer still filters, a table still takes typing — so
    # this locks the layout, it does not make the page read-only.
    # Saved with the project, so a page handed over in view mode opens that
    # way for whoever opens it next.
    view_mode: bool = False
    # Report pages: how the document sits on the page — size, orientation,
    # margins, cover, running headers and footers. A dashboard ignores it.
    # Its defaults reproduce what reports did before it existed, so a page
    # nobody has set up behaves exactly as before.
    setup: PageSetup = field(default_factory=PageSetup)


class Graph:
    def __init__(self) -> None:
        self.nodes: dict[str, NodeInstance] = {}
        self.connections: dict[str, Connection] = {}
        # Derived Goto/From links, never serialized and never user-editable
        # directly: see core.links and _refresh_links. Topology reads union
        # them with `connections`; persistence and wire-drawing don't.
        self.links: dict[str, Connection] = {}
        self.frames: dict[str, Frame] = {}
        self.pages: dict[str, Page] = {}
        self.events = GraphEvents()
        # Lookup tables over the edge set, rebuilt on demand rather than
        # patched at each mutation: there are only three places edges change
        # and hundreds that read them, so a whole rebuild costs nothing
        # amortised and cannot drift out of step with the dicts above the way
        # an incrementally-maintained index can. None means "stale".
        self._edge_index: Optional[_EdgeIndex] = None

    # ---------------------------------------------------------------- nodes

    def node(self, node_id: str) -> NodeInstance:
        try:
            return self.nodes[node_id]
        except KeyError:
            raise GraphError(f"no node with id {node_id!r}") from None

    def add_node(self, node: NodeInstance) -> NodeInstance:
        if node.id in self.nodes:
            raise GraphError(f"node id {node.id!r} already in graph")
        if node.z is None:
            node.z = next_z(self.nodes.values())
        self.nodes[node.id] = node
        self.events.node_added.emit(node)
        self._refresh_links()
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
        self._refresh_links()
        return node, removed

    def move_node(self, node_id: str, pos: tuple[float, float]) -> None:
        node = self.node(node_id)
        node.pos = (float(pos[0]), float(pos[1]))
        self.events.node_moved.emit(node_id, node.pos)

    def set_label(self, node_id: str, label: Optional[str]) -> None:
        node = self.node(node_id)
        node.label_override = label or None
        self.events.label_changed.emit(node_id)

    def set_description(self, node_id: str, description: str) -> None:
        node = self.node(node_id)
        node.description = description
        self.events.description_changed.emit(node_id)

    def set_active(self, node_id: str, active: bool) -> None:
        """Include this node in runs, or skip it and everything below it."""
        node = self.node(node_id)
        node.active = active
        self.events.active_changed.emit(node_id, active)

    def set_frozen(self, node_id: str, frozen: bool,
                   fingerprint: Optional[str] = None) -> None:
        """Pin this node's output, or release it.

        `fingerprint` is what the node's params and inputs hashed to at this
        moment; it is stored so a pin can later be told from one the graph
        has moved on from. The caller supplies it because computing it needs
        the engine's hashing, which core does not import.
        """
        node = self.node(node_id)
        node.frozen = frozen
        node.frozen_fingerprint = fingerprint if frozen else None
        self.events.frozen_changed.emit(node_id, frozen)
        if not frozen:
            # Releasing a pin is how you ask for the expensive thing to
            # happen again, so the node has to be dirty afterwards or the
            # next run would find nothing to do and quietly change nothing.
            # Harmless on the way back: re-freezing pins the cached value
            # again and dirtiness stops mattering.
            self.mark_dirty(node_id)

    def set_locked(self, node_id: str, locked: bool) -> None:
        """Freeze this node's params, code and position against editing."""
        node = self.node(node_id)
        node.locked = locked
        self.events.locked_changed.emit(node_id, locked)

    def set_preview_enabled(self, node_id: str, enabled: bool) -> None:
        node = self.node(node_id)
        node.canvas_preview_enabled = enabled
        self.events.preview_enabled_changed.emit(node_id, enabled)

    def set_port_labels(self, node_id: str,
                        shown: Optional[bool]) -> None:
        """Show/hide this node's floating port names. None hands the node
        back to the canvas-wide preference."""
        node = self.node(node_id)
        node.port_labels = shown
        self.events.port_labels_changed.emit(node_id)

    def set_ports_collapsed(self, node_id: str, collapsed: bool) -> None:
        """Gather this node's pins into the header, or fan them back out."""
        node = self.node(node_id)
        node.ports_collapsed = collapsed
        self.events.ports_collapsed_changed.emit(node_id)

    def set_color(self, node_id: str, color: Optional[str]) -> None:
        node = self.node(node_id)
        node.color = color or None
        self.events.color_changed.emit(node_id)

    def set_param(self, node_id: str, name: str, value: Any) -> None:
        node = self.node(node_id)
        spec = node.spec.param(name)
        if spec is None:
            raise GraphError(f"node {node.label!r} has no param {name!r}")
        node.params[name] = value
        self.events.param_changed.emit(node_id, name, value)
        if name == links.SOURCE_PARAM and links.is_from(node):
            self._refresh_links()   # marks the Froms it moved dirty itself
        if name == links.NAME_PARAM and links.is_link_node(node):
            return  # renaming a link is cosmetic: don't invalidate its subtree
        if spec.cosmetic:
            # declared presentation-only, so the cached output is still
            # correct — dirtying would re-run the node (and everything
            # downstream) to produce exactly what it already produced
            return
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
        self._refresh_links()  # editing a node's code can add/remove its card
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
        self._refresh_links()
        self.mark_dirty(node_id)

    # ---------------------------------------------------------------- links

    def _refresh_links(self) -> None:
        """Re-derive the whole Goto/From link set and adopt it.

        Rebuilt whole, never patched — a From can exist before the Goto it
        reads (the load path adds nodes in file order). Any From whose
        incoming link appeared or vanished is marked dirty here: its input
        changed without its own params changing, so nothing else would.
        """
        resolved = links.resolve_links(self)
        if resolved == self.links:
            return
        moved = {
            (resolved.get(key) or self.links[key]).dst_node
            for key in set(resolved) | set(self.links)
            if resolved.get(key) != self.links.get(key)
        }
        self.links = resolved
        self._invalidate_edges()
        self.events.links_changed.emit()
        for node_id in sorted(moved):
            if node_id in self.nodes:
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

        # only a real wire can be displaced: links aren't the user's to drop
        displaced = self.input_connection(dst_node, dst_port, include_links=False)
        if displaced is not None:
            self.disconnect(displaced.id)

        conn = Connection(
            id=conn_id or uuid.uuid4().hex,
            src_node=src_node, src_port=src_port,
            dst_node=dst_node, dst_port=dst_port,
        )
        self.connections[conn.id] = conn
        # before the emit and before mark_dirty: both walk the topology and
        # must see the edge that was just made
        self._invalidate_edges()
        self.events.connected.emit(conn)
        self.mark_dirty(dst_node)
        # links are only accepted when they don't close a loop, so the real
        # edge set is part of their input -- and the displacement above left a
        # transient state. Re-derive once, here at the end, and the invariant
        # "graph.links is acyclic against the current wires" holds after every
        # public mutation.
        self._refresh_links()
        return conn, displaced

    def disconnect(self, conn_id: str) -> Connection:
        conn = self.connections.pop(conn_id, None)
        if conn is None:
            raise GraphError(f"no connection with id {conn_id!r}")
        self._invalidate_edges()
        self.events.disconnected.emit(conn)
        if conn.dst_node in self.nodes:
            self.mark_dirty(conn.dst_node)
        self._refresh_links()  # removing a wire can unblock a refused link
        return conn

    def _iter_edges(self) -> Iterable[Connection]:
        """Every edge values flow along: drawn wires plus derived Goto/From
        links. The one place link-awareness lives — everything below inherits
        it. Persistence and wire-drawing read `self.connections` instead."""
        return (*self.connections.values(), *self.links.values())

    def _invalidate_edges(self) -> None:
        """Call after any change to `connections` or `links`. Cheap enough to
        call freely; the rebuild is deferred to the next read."""
        self._edge_index = None

    def _edges(self) -> _EdgeIndex:
        index = self._edge_index
        if index is None:
            by_input: dict[tuple[str, str], Connection] = {}
            into: dict[str, list[Connection]] = {}
            out_of: dict[str, list[Connection]] = {}
            for conn in self._iter_edges():
                # setdefault, not assignment: first edge on a port wins, which
                # is what the old `next(...)` scan did and is what keeps a real
                # wire ahead of a link claiming the same input
                by_input.setdefault((conn.dst_node, conn.dst_port), conn)
                into.setdefault(conn.dst_node, []).append(conn)
                out_of.setdefault(conn.src_node, []).append(conn)
            index = self._edge_index = _EdgeIndex(by_input, into, out_of)
        return index

    def input_connection(self, node_id: str, port: str,
                         include_links: bool = True) -> Optional[Connection]:
        if not include_links:
            # Only `connect` asks this, to find a wire it may displace — a
            # link is not the user's to drop. Not worth its own index.
            return next(
                (c for c in self.connections.values()
                 if c.dst_node == node_id and c.dst_port == port),
                None,
            )
        return self._edges().by_input.get((node_id, port))

    def in_connections(self, node_id: str) -> list[Connection]:
        return list(self._edges().into.get(node_id, ()))

    def out_connections(self, node_id: str) -> list[Connection]:
        return list(self._edges().out_of.get(node_id, ()))

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
        return {c.dst_node for c in self._edges().out_of.get(node_id, ())}

    def predecessors(self, node_id: str) -> set[str]:
        return {c.src_node for c in self._edges().into.get(node_id, ())}

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
        # Insertion rank up front: the tie-break below used ids.index, a
        # linear search per successor, which made a topological sort of a
        # large graph quadratic on its own.
        rank = {node_id: i for i, node_id in enumerate(ids)}
        indegree = {
            n: sum(1 for p in self.predecessors(n) if p in id_set) for n in ids
        }
        queue = deque(n for n in ids if indegree[n] == 0)
        order: list[str] = []
        while queue:
            current = queue.popleft()
            order.append(current)
            in_subset = [n for n in self.successors(current) if n in id_set]
            for nxt in sorted(in_subset, key=rank.__getitem__):
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
        # Leaving RUNNING — finished, failed, cancelled, re-queued — retires
        # whatever fraction the node last reported. Clearing it in the one
        # place every status change goes through beats resetting it at each
        # of the scheduler's exits and missing one.
        if status is not NodeStatus.RUNNING and node.progress:
            node.progress = 0.0
            self.events.progress_changed.emit(node_id, 0.0)
        self.events.status_changed.emit(node_id, status, message)

    def set_progress(self, node_id: str, fraction: float) -> None:
        """How far through its work the running node says it is (0..1)."""
        node = self.node(node_id)
        node.progress = max(0.0, min(1.0, float(fraction)))
        self.events.progress_changed.emit(node_id, node.progress)

    # --------------------------------------------------------------- frames

    def add_frame(self, frame: Frame) -> Frame:
        if frame.id in self.frames:
            raise GraphError(f"frame id {frame.id!r} already in graph")
        if frame.z is None:
            frame.z = next_z(self.frames.values())
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

    # ---------------------------------------------------------------- pages

    def page(self, page_id: str) -> Page:
        try:
            return self.pages[page_id]
        except KeyError:
            raise GraphError(f"no page with id {page_id!r}") from None

    def add_page(self, page: Page) -> Page:
        if page.id in self.pages:
            raise GraphError(f"page id {page.id!r} already in graph")
        self.pages[page.id] = page
        self.events.page_added.emit(page)
        return page

    def remove_page(self, page_id: str) -> Page:
        page = self.pages.pop(page_id, None)
        if page is None:
            raise GraphError(f"no page with id {page_id!r}")
        self.events.page_removed.emit(page_id)
        return page

    def update_page(self, page_id: str, *, title: Optional[str] = None) -> Page:
        page = self.page(page_id)
        if title is not None:
            page.title = title
        self.events.page_changed.emit(page)
        return page

    def set_page_color(self, page_id: str, color: Optional[str]) -> Page:
        """Separate from update_page so that None can mean "reset to the
        theme default" rather than "leave unchanged" (mirrors set_color)."""
        page = self.page(page_id)
        page.color = color or None
        self.events.page_changed.emit(page)
        return page

    def set_page_body(self, page_id: str, body: str) -> Page:
        """Replace a report page's markdown source. Its own event, not
        page_changed: the body arrives keystroke by keystroke and the tab
        bar has no interest in any of it."""
        page = self.page(page_id)
        page.body = body or ""
        self.events.page_body_changed.emit(page)
        return page

    def set_page_view_mode(self, page_id: str, view_mode: bool) -> Page:
        """Switch a page between edit and view mode. Separate from
        update_page for the same reason as set_page_color: False has to mean
        "edit mode", not "leave unchanged"."""
        page = self.page(page_id)
        page.view_mode = bool(view_mode)
        self.events.page_changed.emit(page)
        return page

    def set_page_setup(self, page_id: str, setup: PageSetup) -> Page:
        """Replace a report page's page geometry.

        A copy is stored, not the object handed in: the dialog edits a
        working copy and the undo stack holds the before and after states,
        and all three sharing one mutable dataclass would make an undo a
        no-op.
        """
        page = self.page(page_id)
        page.setup = setup.copy() if setup is not None else PageSetup()
        self.events.page_changed.emit(page)
        return page

    def set_page_maximized_tile(self, page_id: str,
                                tile_id: Optional[str]) -> Page:
        """Maximize `tile_id` over the page, or None for the normal layout.
        Separate from update_page for the same reason as set_page_color:
        None has to mean "nothing maximized", not "leave unchanged"."""
        page = self.page(page_id)
        page.maximized_tile = tile_id or None
        self.events.page_changed.emit(page)
        return page

    def reorder_pages(self, order: Sequence[str]) -> list[str]:
        """Rearrange pages into `order`. Page order is the tab order and is
        what serialization writes out, so this is the whole feature."""
        if set(order) != set(self.pages) or len(order) != len(self.pages):
            raise GraphError("reorder_pages needs every page id exactly once")
        self.pages = {page_id: self.pages[page_id] for page_id in order}
        result = list(self.pages)
        self.events.pages_reordered.emit(result)
        return result

    def add_tile(self, page_id: str, tile: Tile) -> Tile:
        # no node_id validation: dangling refs are legal (placeholder in UI)
        page = self.page(page_id)
        if tile.id in page.tiles:
            raise GraphError(f"tile id {tile.id!r} already on page {page_id!r}")
        if tile.z is None:
            tile.z = next_z(page.tiles.values())
        page.tiles[tile.id] = tile
        self.events.tile_added.emit(page_id, tile)
        return tile

    def remove_tile(self, page_id: str, tile_id: str) -> Tile:
        page = self.page(page_id)
        tile = page.tiles.pop(tile_id, None)
        if tile is None:
            raise GraphError(f"no tile with id {tile_id!r} on page {page_id!r}")
        self.events.tile_removed.emit(page_id, tile_id)
        return tile

    def update_tile(self, page_id: str, tile_id: str, *,
                    rect: Optional[tuple[float, float, float, float]] = None,
                    ) -> Tile:
        page = self.page(page_id)
        tile = page.tiles.get(tile_id)
        if tile is None:
            raise GraphError(f"no tile with id {tile_id!r} on page {page_id!r}")
        if rect is not None:
            tile.rect = tuple(float(v) for v in rect)  # type: ignore[assignment]
        self.events.tile_changed.emit(page_id, tile)
        return tile

    # ------------------------------------------------------- stacking order

    def _stack(self, kind: str, page_id: Optional[str] = None) -> dict:
        if kind == "node":
            return self.nodes
        if kind == "frame":
            return self.frames
        if kind == "tile":
            return self.page(page_id).tiles
        raise GraphError(f"no stacking order for {kind!r} "
                         "(valid: node, frame, tile)")

    def stacking_order(self, kind: str,
                       page_id: Optional[str] = None) -> list[str]:
        """Back-to-front ids of one stackable kind — nodes and frames stack
        on the model canvas, tiles on the page named by `page_id`."""
        return order_of(self._stack(kind, page_id).values())

    def restack(self, kind: str, order: Sequence[str],
                page_id: Optional[str] = None) -> None:
        """Adopt `order` (back-to-front) as the stacking order of that kind.

        z is rewritten as 0..n-1 across the whole kind, not just the items
        that moved — that normalization is what keeps saved files stable and
        stops repeated restacks from growing the numbers without bound. Ids
        missing from `order` keep their relative position at the back, so a
        stale ordering can never silently drop an item.
        """
        items = self._stack(kind, page_id)
        ranked = [i for i in order if i in items]
        ranked = [i for i in items if i not in set(ranked)] + ranked
        for index, item_id in enumerate(ranked):
            items[item_id].z = index
        self.events.restacked.emit(kind, page_id)
