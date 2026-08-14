"""QUndoCommand set — the *only* code allowed to mutate the Graph.

Item interactions and widgets build commands and push them onto the window's
QUndoStack; redo() mutates the graph, graph events update the scene. That
one-way flow is what makes undo/redo, load, and paste all take the same path.
"""
from __future__ import annotations

import uuid
from typing import Any, Optional

from PySide6.QtGui import QUndoCommand

from flograph.core import Connection, Frame, Graph, NodeInstance, NodeSpec, Page, Tile

_ID_MOVE = 1001
_ID_PARAM = 1002
_ID_TILE_RECT = 1003
_ID_DESCRIPTION = 1004
_ID_PAGE_BODY = 1005
# The mark is live-applied from the Appearance dialog as the user tries
# things, so merging keeps clicking through sixteen swatches to find the
# right one a single undo step rather than sixteen.
_ID_MARK = 1006


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


class RestackCommand(QUndoCommand):
    """Adopt a new stacking order for one kind (nodes, frames, or one page's
    tiles). The previous order is captured up front rather than recomputed
    in undo(), so a restack of a restack still walks back correctly."""

    def __init__(self, graph: Graph, kind: str, order: list[str],
                 page_id: Optional[str] = None, text: str = "restack",
                 parent: Optional[QUndoCommand] = None) -> None:
        super().__init__(text, parent)
        self._graph = graph
        self._kind = kind
        self._page_id = page_id
        self._new = list(order)
        self._old = graph.stacking_order(kind, page_id)

    def redo(self) -> None:
        self._graph.restack(self._kind, self._new, self._page_id)

    def undo(self) -> None:
        self._graph.restack(self._kind, self._old, self._page_id)


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
    """Edits of the same param merge while it stays the latest command.

    Pass merge=False for edits that must stay individual undo steps
    (e.g. spreadsheet cell edits, where one Ctrl+Z should revert one cell).
    """

    def __init__(self, graph: Graph, node_id: str, name: str, new_value: Any,
                 parent: Optional[QUndoCommand] = None, *,
                 merge: bool = True) -> None:
        super().__init__(f"set {name}", parent)
        self._graph = graph
        self._node_id = node_id
        self._name = name
        self._old = graph.node(node_id).params.get(name)
        self._new = new_value
        self._merge = merge

    def id(self) -> int:
        return _ID_PARAM if self._merge else -1   # -1: Qt never merges

    def redo(self) -> None:
        self._graph.set_param(self._node_id, self._name, self._new)

    def undo(self) -> None:
        self._graph.set_param(self._node_id, self._name, self._old)

    def mergeWith(self, other: QUndoCommand) -> bool:
        if (not isinstance(other, SetParamCommand)
                or not self._merge or not other._merge
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


class SetDescriptionCommand(QUndoCommand):
    """Edits merge while it stays the latest command, same as SetParamCommand
    -- the field commits on every keystroke, and per-keystroke undo steps
    would make undo useless."""

    def __init__(self, graph: Graph, node_id: str, new_description: str,
                 parent: Optional[QUndoCommand] = None) -> None:
        super().__init__("set node description", parent)
        self._graph = graph
        self._node_id = node_id
        self._old = graph.node(node_id).description
        self._new = new_description

    def id(self) -> int:
        return _ID_DESCRIPTION

    def redo(self) -> None:
        self._graph.set_description(self._node_id, self._new)

    def undo(self) -> None:
        self._graph.set_description(self._node_id, self._old)

    def mergeWith(self, other: QUndoCommand) -> bool:
        if not isinstance(other, SetDescriptionCommand) or other._node_id != self._node_id:
            return False
        self._new = other._new
        return True


class SetActiveCommand(QUndoCommand):
    """Deactivate a node (and, in effect, everything downstream) or bring it
    back. Nothing is recomputed either way — switching a branch back on
    leaves it dirty, so the next run picks it up."""

    def __init__(self, graph: Graph, node_id: str, active: bool,
                 parent: Optional[QUndoCommand] = None) -> None:
        super().__init__("activate node" if active else "deactivate node",
                         parent)
        self._graph = graph
        self._node_id = node_id
        self._old = graph.node(node_id).active
        self._new = active

    def redo(self) -> None:
        self._graph.set_active(self._node_id, self._new)

    def undo(self) -> None:
        self._graph.set_active(self._node_id, self._old)


class SetFrozenCommand(QUndoCommand):
    """Pin a node's output against every subsequent run, or release it.

    The fingerprint is taken here, at the moment of freezing, so undo can put
    back not just the flag but the reading it was paired with — a redo that
    re-froze against a *newer* fingerprint would quietly launder a pin that
    should have been showing as stale.
    """

    def __init__(self, graph: Graph, node_id: str, frozen: bool,
                 parent: Optional[QUndoCommand] = None) -> None:
        super().__init__("freeze node" if frozen else "unfreeze node", parent)
        self._graph = graph
        self._node_id = node_id
        self._old = graph.node(node_id).frozen
        self._old_fp = graph.node(node_id).frozen_fingerprint
        self._new = frozen
        self._new_fp = None
        if frozen:
            from flograph.engine.cache_persistence import freeze_fingerprint
            try:
                self._new_fp = freeze_fingerprint(graph, node_id)
            except Exception:
                self._new_fp = None     # unhashable params: pin without one

    def redo(self) -> None:
        self._graph.set_frozen(self._node_id, self._new, self._new_fp)

    def undo(self) -> None:
        self._graph.set_frozen(self._node_id, self._old, self._old_fp)


class SetLockedCommand(QUndoCommand):
    """Freeze a node's params, code and position, or release them."""

    def __init__(self, graph: Graph, node_id: str, locked: bool,
                 parent: Optional[QUndoCommand] = None) -> None:
        super().__init__("lock node" if locked else "unlock node", parent)
        self._graph = graph
        self._node_id = node_id
        self._old = graph.node(node_id).locked
        self._new = locked

    def redo(self) -> None:
        self._graph.set_locked(self._node_id, self._new)

    def undo(self) -> None:
        self._graph.set_locked(self._node_id, self._old)


class SetPreviewEnabledCommand(QUndoCommand):
    def __init__(self, graph: Graph, node_id: str, enabled: bool,
                 parent: Optional[QUndoCommand] = None) -> None:
        super().__init__("toggle canvas preview", parent)
        self._graph = graph
        self._node_id = node_id
        self._old = graph.node(node_id).canvas_preview_enabled
        self._new = enabled

    def redo(self) -> None:
        self._graph.set_preview_enabled(self._node_id, self._new)

    def undo(self) -> None:
        self._graph.set_preview_enabled(self._node_id, self._old)


class SetExclusiveCommand(QUndoCommand):
    """Make one node run on its own, or let it run beside others. `exclusive`
    of None hands the node back to what its script declares."""

    def __init__(self, graph: Graph, node_id: str, exclusive: Optional[bool],
                 parent: Optional[QUndoCommand] = None) -> None:
        super().__init__("toggle exclusive execution", parent)
        self._graph = graph
        self._node_id = node_id
        self._old = graph.node(node_id).exclusive_override
        self._new = exclusive

    def redo(self) -> None:
        self._graph.set_exclusive(self._node_id, self._new)

    def undo(self) -> None:
        self._graph.set_exclusive(self._node_id, self._old)


class SetPortLabelsCommand(QUndoCommand):
    """Show/hide one node's floating port names. `shown` of None hands the
    node back to the canvas-wide preference."""

    def __init__(self, graph: Graph, node_id: str, shown: Optional[bool],
                 parent: Optional[QUndoCommand] = None) -> None:
        super().__init__("toggle port names", parent)
        self._graph = graph
        self._node_id = node_id
        self._old = graph.node(node_id).port_labels
        self._new = shown

    def redo(self) -> None:
        self._graph.set_port_labels(self._node_id, self._new)

    def undo(self) -> None:
        self._graph.set_port_labels(self._node_id, self._old)


class SetPortsCollapsedCommand(QUndoCommand):
    """Gather a node's pins into its header, or fan them back out."""

    def __init__(self, graph: Graph, node_id: str, collapsed: bool,
                 parent: Optional[QUndoCommand] = None) -> None:
        super().__init__("collapse ports" if collapsed else "expand ports",
                         parent)
        self._graph = graph
        self._node_id = node_id
        self._old = graph.node(node_id).ports_collapsed
        self._new = collapsed

    def redo(self) -> None:
        self._graph.set_ports_collapsed(self._node_id, self._new)

    def undo(self) -> None:
        self._graph.set_ports_collapsed(self._node_id, self._old)


class SetNodeColorCommand(QUndoCommand):
    def __init__(self, graph: Graph, node_id: str, color: Optional[str],
                 parent: Optional[QUndoCommand] = None) -> None:
        super().__init__("change node colour", parent)
        self._graph = graph
        self._node_id = node_id
        self._old = graph.node(node_id).color
        self._new = color

    # Deliberately does not merge, unlike the mark it sits beside in the
    # Appearance dialog: a colour arrives through a modal picker, so each one
    # is already a single deliberate act, and resetting to the theme default
    # is its own decision that deserves its own step back.

    def redo(self) -> None:
        self._graph.set_color(self._node_id, self._new)

    def undo(self) -> None:
        self._graph.set_color(self._node_id, self._old)


class SetCompactViewCommand(QUndoCommand):
    def __init__(self, graph: Graph, node_id: str, compact: Optional[bool],
                 parent: Optional[QUndoCommand] = None) -> None:
        super().__init__("change node view", parent)
        self._graph = graph
        self._node_id = node_id
        self._old = graph.node(node_id).compact_view
        self._new = compact

    def redo(self) -> None:
        self._graph.set_compact_view(self._node_id, self._new)

    def undo(self) -> None:
        self._graph.set_compact_view(self._node_id, self._old)


class SetNodeMarkCommand(QUndoCommand):
    def __init__(self, graph: Graph, node_id: str, mark: str, mark_text: str,
                 mark_image: str = "",
                 parent: Optional[QUndoCommand] = None) -> None:
        super().__init__("change node mark", parent)
        self._graph = graph
        self._node_id = node_id
        node = graph.node(node_id)
        self._old = (node.mark, node.mark_text, node.mark_image)
        self._new = (mark, mark_text, mark_image)

    def id(self) -> int:
        return _ID_MARK

    def redo(self) -> None:
        self._graph.set_mark(self._node_id, *self._new)

    def undo(self) -> None:
        self._graph.set_mark(self._node_id, *self._old)

    def mergeWith(self, other: QUndoCommand) -> bool:
        if (not isinstance(other, SetNodeMarkCommand)
                or other._node_id != self._node_id):
            return False
        self._new = other._new
        return True


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


class SetFrameCollapsedCommand(QUndoCommand):
    """Fold a frame down to a single box, or open it back out.

    Snapshots the whole fold — collapsed flag, rect, the size to grow back
    to, and the membership — because they only make sense together: undoing
    a collapse has to give back the region *and* exactly the nodes it took,
    not recompute a membership from geometry that has since moved.

    `members` / `member_frames` are supplied by the caller rather than
    worked out here: deciding what sits inside a frame needs the items'
    drawn bounds, which is the canvas's business, not the graph's.
    """

    def __init__(self, graph: Graph, frame_id: str, collapsed: bool,
                 members: tuple = (), member_frames: tuple = (),
                 collapsed_size: tuple = (60.0, 60.0), nudged: tuple = (),
                 parent: Optional[QUndoCommand] = None) -> None:
        super().__init__("collapse frame" if collapsed else "expand frame",
                         parent)
        self._graph = graph
        self._frame_id = frame_id
        frame = graph.frames[frame_id]
        self._old = (frame.collapsed, frame.rect, frame.expanded_size,
                     frame.members, frame.member_frames, frame.nudged)
        x, y, width, height = frame.rect
        if collapsed:
            # folding puts back whatever the last expand shoved aside, so the
            # record is spent and cleared
            self._new = (True, (x, y, *collapsed_size), (width, height),
                         tuple(members), tuple(member_frames), ())
        else:
            # grow back to whatever it was before it folded; a frame with no
            # remembered size was never folded, so its rect already is one
            grow = frame.expanded_size or (width, height)
            self._new = (False, (x, y, *grow), None, (), (), tuple(nudged))

    def _apply(self, state) -> None:
        collapsed, rect, expanded_size, members, member_frames, nudged = state
        self._graph.apply_frame_collapse(
            self._frame_id, collapsed=collapsed, rect=rect,
            expanded_size=expanded_size, members=members,
            member_frames=member_frames, nudged=nudged)

    def redo(self) -> None:
        self._apply(self._new)

    def undo(self) -> None:
        self._apply(self._old)


class SetFrameSourceCommand(QUndoCommand):
    """Record which library component a frame came from (or became)."""

    def __init__(self, graph: Graph, frame_id: str, source: str,
                 fingerprint: str,
                 parent: Optional[QUndoCommand] = None) -> None:
        super().__init__("link frame to component", parent)
        self._graph = graph
        self._frame_id = frame_id
        frame = graph.frames[frame_id]
        self._old = (frame.source, frame.source_fingerprint)
        self._new = (source, fingerprint)

    def redo(self) -> None:
        self._graph.set_frame_source(self._frame_id, *self._new)

    def undo(self) -> None:
        self._graph.set_frame_source(self._frame_id, *self._old)


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
        self._order = list(graph.pages)    # so undo restores the tab position

    def redo(self) -> None:
        self._page = self._graph.remove_page(self._page_id)

    def undo(self) -> None:
        self._graph.add_page(self._page)   # lands last; put it back where it was
        self._graph.reorder_pages(self._order)


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


class SetPageBodyCommand(QUndoCommand):
    """One report-page edit. Consecutive edits of the same page merge, so a
    burst of typing is one Ctrl+Z rather than one per character — the same
    bargain SetParamCommand makes for a text param."""

    def __init__(self, graph: Graph, page_id: str, body: str,
                 parent: Optional[QUndoCommand] = None) -> None:
        super().__init__("edit report", parent)
        self._graph = graph
        self._page_id = page_id
        self._old = graph.page(page_id).body
        self._new = body

    def id(self) -> int:
        return _ID_PAGE_BODY

    def redo(self) -> None:
        self._graph.set_page_body(self._page_id, self._new)

    def undo(self) -> None:
        self._graph.set_page_body(self._page_id, self._old)

    def mergeWith(self, other: QUndoCommand) -> bool:
        if (not isinstance(other, SetPageBodyCommand)
                or other._page_id != self._page_id):
            return False
        self._new = other._new
        return True


class SetPageColorCommand(QUndoCommand):
    def __init__(self, graph: Graph, page_id: str, color: Optional[str],
                 parent: Optional[QUndoCommand] = None) -> None:
        super().__init__("change page colour", parent)
        self._graph = graph
        self._page_id = page_id
        self._old = graph.page(page_id).color
        self._new = color

    def redo(self) -> None:
        self._graph.set_page_color(self._page_id, self._new)

    def undo(self) -> None:
        self._graph.set_page_color(self._page_id, self._old)


class SetPageMaximizedTileCommand(QUndoCommand):
    """Maximize a tile over its page, or restore the normal layout. Saved
    with the project, so it goes through the undo stack like every other
    page edit rather than being written behind it."""

    def __init__(self, graph: Graph, page_id: str, tile_id: Optional[str],
                 parent: Optional[QUndoCommand] = None) -> None:
        super().__init__("maximize tile" if tile_id else "restore tile",
                         parent)
        self._graph = graph
        self._page_id = page_id
        self._old = graph.page(page_id).maximized_tile
        self._new = tile_id

    def redo(self) -> None:
        self._graph.set_page_maximized_tile(self._page_id, self._new)

    def undo(self) -> None:
        self._graph.set_page_maximized_tile(self._page_id, self._old)


class SetPageViewModeCommand(QUndoCommand):
    """Switch a page between edit and view mode. Saved with the project, so
    like maximizing a tile it goes through the undo stack rather than being
    written behind it."""

    def __init__(self, graph: Graph, page_id: str, view_mode: bool,
                 parent: Optional[QUndoCommand] = None) -> None:
        super().__init__("view mode" if view_mode else "edit mode", parent)
        self._graph = graph
        self._page_id = page_id
        self._old = graph.page(page_id).view_mode
        self._new = bool(view_mode)

    def redo(self) -> None:
        self._graph.set_page_view_mode(self._page_id, self._new)

    def undo(self) -> None:
        self._graph.set_page_view_mode(self._page_id, self._old)


class SetPageSetupCommand(QUndoCommand):
    """Replace a report page's page geometry.

    Both states are copied out of the model rather than referenced: the
    setup is a mutable dataclass, and an undo that handed back the same
    object the dialog had been editing would restore nothing.
    """

    def __init__(self, graph: Graph, page_id: str, setup,
                 parent: Optional[QUndoCommand] = None) -> None:
        super().__init__("page setup", parent)
        self._graph = graph
        self._page_id = page_id
        self._old = graph.page(page_id).setup.copy()
        self._new = setup.copy()

    def redo(self) -> None:
        self._graph.set_page_setup(self._page_id, self._new)

    def undo(self) -> None:
        self._graph.set_page_setup(self._page_id, self._old)


class ReorderPagesCommand(QUndoCommand):
    def __init__(self, graph: Graph, order: list[str],
                 parent: Optional[QUndoCommand] = None) -> None:
        super().__init__("reorder pages", parent)
        self._graph = graph
        self._old = list(graph.pages)
        self._new = list(order)

    def redo(self) -> None:
        self._graph.reorder_pages(self._new)

    def undo(self) -> None:
        self._graph.reorder_pages(self._old)


class DuplicatePageCommand(QUndoCommand):
    def __init__(self, graph: Graph, page_id: str,
                 parent: Optional[QUndoCommand] = None) -> None:
        super().__init__("duplicate page", parent)
        self._graph = graph
        self._page_id = page_id
        self._new_page: Optional[Page] = None

    def redo(self) -> None:
        if self._new_page is not None:
            # Already created; just ensure it's in the graph (redo may be called again after undo)
            if self._new_page.id not in self._graph.pages:
                self._graph.add_page(self._new_page)
            return
        src = self._graph.page(self._page_id)
        # one id per copied tile: page.tiles is keyed by it *and* it is stored
        # on the tile, and remove_tile looks the tile up by that key
        id_map = {tile_id: uuid.uuid4().hex for tile_id in src.tiles}
        new_tiles = {
            # z carried over: these bypass add_tile (they go straight into the
            # new Page), so without it the copy would lose the stacking the
            # original was arranged into
            id_map[tile_id]: Tile(id=id_map[tile_id], node_id=t.node_id,
                                  port=t.port, rect=t.rect, z=t.z)
            for tile_id, t in src.tiles.items()
        }
        self._new_page = Page(
            id=uuid.uuid4().hex,
            title=f"{src.title} (copy)",
            kind=src.kind,
            body=src.body,
            tiles=new_tiles,
            color=src.color,
            # the copy opens looking like the original, remapped to its tiles
            maximized_tile=id_map.get(src.maximized_tile),
            view_mode=src.view_mode,
            # copied, not shared: two pages pointing at one mutable setup
            # would mean editing either one changed both
            setup=src.setup.copy(),
        )
        self._graph.add_page(self._new_page)

    def undo(self) -> None:
        if self._new_page is not None and self._new_page.id in self._graph.pages:
            self._graph.remove_page(self._new_page.id)


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
