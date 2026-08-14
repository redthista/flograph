"""A pin on a collapsed frame, standing in for one wire's hidden end.

When a frame folds, the nodes inside it disappear but their wires to the
outside world do not — those are real edges in the graph and hiding them
would be a lie about what the flow does. Each wire that crosses the boundary
grows a pin on the box instead, and the wire terminates there.

One pin per crossing wire, deliberately not one per port: an inner node
feeding three outside nodes shows three pins. Deduping would make a pin mean
"some bundle of wires", and then dropping a wire on it would have no single
honest answer for what it connected to.

The pin is a real `PortItem`. That is what makes it live rather than
decorative: the whole wire-drag pipeline in the scene only ever asks a port
for its `node_id`, its `spec`, its scene position and its drag tint, and
finds candidates with `isinstance(item, PortItem)` — so a subclass parented
to the frame instead of to a node is accepted everywhere without the scene
learning a second kind of pin.
"""
from __future__ import annotations

from flograph.core.node import PortSpec

from .node_item import PortItem


class FramePortItem(PortItem):
    """One end of one crossing wire, drawn on a collapsed frame's box."""

    def __init__(self, frame_item, node, spec: PortSpec,
                 conn_id: str, side: str, *, link: bool = False) -> None:
        # Parented to the *frame*, not to the node it speaks for. Holding the
        # core NodeInstance rather than the hidden NodeItem matters: a node
        # item is removed from the scene when its node goes, and a pin left
        # pointing at a detached graphics item is a dangling reference,
        # whereas the dataclass is plain Python and cannot dangle.
        super().__init__(frame_item, spec)
        self.frame_item = frame_item
        self.inner_node = node
        self.conn_id = conn_id
        self.side = side          # "src" (an output) | "dst" (an input)
        self.link = link          # stands in for a Goto/From line, not a wire
        self.setToolTip(self.label_text())

    @property
    def node_id(self) -> str:
        """The hidden node this pin acts for — the identity every connect,
        disconnect and cycle check upstream of here works from."""
        return self.inner_node.id

    def label_text(self) -> str:
        """Which node's port this is. The port name alone would be useless on
        a box holding a dozen of them from half as many nodes."""
        label = getattr(self.inner_node, "label", "") or self.inner_node.id
        return f"{label} · {self.spec.name}"

    def _label_shown(self) -> bool:
        """Only while hovered.

        A node shows its port names when the canvas-wide setting says so, but
        this box is 60px square with pins running past the bottom of it —
        every name on permanently would be a wall of text wider than the
        frame it came from, which is the opposite of collapsing it.
        """
        return self._hover

    # The label pill is inside boundingRect (see PortItem.boundingRect), so
    # showing it on hover is a real geometry change, not just a repaint. The
    # base class only calls update(), which leaves the stale bounds in the
    # scene index and clips or smears the pill.

    def hoverEnterEvent(self, event) -> None:
        self.prepareGeometryChange()
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event) -> None:
        self.prepareGeometryChange()
        super().hoverLeaveEvent(event)
