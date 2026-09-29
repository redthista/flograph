"""How well a node fits a wire dropped on empty canvas.

Dropping a fresh wire opens the node palette, and the palette used to be
filtered and nothing more: every node with *a* port the wire could reach.
That is the right set but the wrong order, because the type system is
coarse. Most nodes put out a table, `object` inputs take a table, a number
or a figure alike, and `any` takes everything — so dragging back from a
chart's style input offered a hundred and twenty nodes, and the one that
makes styles was somewhere among them.

So the palette ranks as well as filters, in three tiers:

- **suggested** — the port named this node type in its `suggest` option
  (``("style", "object", {"suggest": ["flograph.viz.plotly_style"]})``),
  or, dragging forward, the new node's input names the node the wire came
  from. This is how a style port leads with its style node.
- **exact** — a port of the wire's own type.
- **loose** — it only fits because one end is `any`, or a value widens to
  `object`. Still offered, below the rest.

Which port the new node is wired by follows the same thinking, in
`best_port`: the one that asked for it, then the one of the same name, then
the one of the same type — so picking Plotly Style from a chart's style
input wires its *style* output, not its `any`-typed figure output that
happens to come first.
"""
from __future__ import annotations

from typing import Optional

from .datatypes import PortType, can_connect
from .node import NodeSpec
from .ports import PortDirection, PortSpec

#: The tiers, best first — they sort.
SUGGESTED, EXACT, LOOSE = 0, 1, 2


def fitting_ports(spec: NodeSpec, port: PortSpec) -> list[PortSpec]:
    """The ports of `spec` a wire dragged from `port` could end on."""
    if port.direction == PortDirection.OUTPUT:
        return [p for p in spec.inputs if can_connect(port.type, p.type)]
    return [p for p in spec.outputs if can_connect(p.type, port.type)]


def wire_fit(spec: NodeSpec, port: PortSpec,
             from_type_id: str) -> Optional[int]:
    """The tier `spec` sits in for a wire dragged from `port` on a node of
    type `from_type_id`, or None when it cannot take the wire at all."""
    ports = fitting_ports(spec, port)
    if not ports:
        return None
    if any(_asked_for(p, spec, port, from_type_id) for p in ports):
        return SUGGESTED
    # from an `any` port nothing is looser than anything else
    if port.type == PortType.ANY or any(p.type == port.type for p in ports):
        return EXACT
    return LOOSE


def best_port(spec: NodeSpec, port: PortSpec,
              from_type_id: str) -> Optional[PortSpec]:
    """The port of `spec` to wire a dropped wire to: the one that asked for
    it, then the same name, then the same type, then the first that fits."""
    ports = fitting_ports(spec, port)
    if not ports:
        return None
    # min() keeps the first of equals, so declaration order breaks ties
    return min(ports, key=lambda p: (
        not _asked_for(p, spec, port, from_type_id),
        p.name != port.name,
        p.type != port.type))


def _asked_for(candidate: PortSpec, spec: NodeSpec, port: PortSpec,
               from_type_id: str) -> bool:
    """Did one end of this wire name the node at the other in `suggest`?
    Only inputs carry the option, so it is the dragged port dragging back,
    and the candidate dragging forward."""
    if port.direction == PortDirection.INPUT:
        return spec.type_id in port.suggest
    return from_type_id in candidate.suggest
