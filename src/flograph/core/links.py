"""Named Goto/From links — wires the canvas doesn't draw.

A Goto node names a value; any number of From nodes elsewhere in the model
re-emit it. The pair binds by the *Goto's node id* (kept on the From's
`source` param), never by its display name — so renaming a link updates both
ends and the binding itself can never break. Two links may share a name
harmlessly.

Links are derived state: a pure function of the nodes present and their
params, recomputed by Graph whenever a node is added or removed or a link
param changes. They live in `graph.links`, separate from `graph.connections`:
topology reads (successors, input_connection, topo_order, ...) union the two,
while persistence and wire-drawing see only real connections. That split is
what makes links cheap — nothing serializes them, undo never captures them,
and the scheduler treats a link exactly like a wire.

Structurally a Goto is a reroute with a hidden *output* and a From a reroute
with a hidden *input*; the ports exist in the specs (so a link is an ordinary
edge) but the canvas never draws them.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .graph import Connection, Graph

GOTO_CARD = "goto"
FROM_CARD = "from"
LINK_PORT = "value"      # the port name both node scripts declare
SOURCE_PARAM = "source"  # From: the id of the Goto it reads
NAME_PARAM = "name"      # Goto: the link's display label
UNNAMED = "unnamed link"


def is_goto(node) -> bool:
    return node.spec.card == GOTO_CARD


def is_from(node) -> bool:
    return node.spec.card == FROM_CARD


def is_link_node(node) -> bool:
    return node.spec.card in (GOTO_CARD, FROM_CARD)


def link_id(from_node_id: str) -> str:
    """A From has at most one source, so its own id names the link."""
    return f"link:{from_node_id}"


def link_label(node) -> str:
    """The display label of a Goto (or of the Goto a From points at)."""
    name = node.params.get(NAME_PARAM)
    return name.strip() if isinstance(name, str) and name.strip() else UNNAMED


def goto_nodes(graph: "Graph") -> list:
    return [n for n in graph.nodes.values() if is_goto(n)]


def source_id(node) -> str:
    value = node.params.get(SOURCE_PARAM)
    return value if isinstance(value, str) else ""


def resolve_links(graph: "Graph") -> dict[str, "Connection"]:
    """The full link set for a graph, keyed by link id.

    Rebuilt whole rather than patched: a From may exist before its Goto (the
    load path adds nodes in file order), so there is no correct incremental
    version. Candidates are considered in node-insertion order and each is
    tested against the real wires *plus* the links accepted so far, which is
    what catches loops that no single link closes on its own. A rejected
    candidate is simply absent — `from_problem` explains it to the user.
    """
    from .graph import Connection  # local import: graph imports this module

    candidates = [
        (node_id, source_id(node))
        for node_id, node in graph.nodes.items() if is_from(node)
    ]
    if not candidates:  # the common case: don't walk the wires at all
        return {}

    adjacency: dict[str, set[str]] = {}
    for conn in graph.connections.values():
        adjacency.setdefault(conn.src_node, set()).add(conn.dst_node)

    links: dict[str, "Connection"] = {}
    for node_id, src in candidates:
        target = graph.nodes.get(src)
        if target is None or not is_goto(target):
            continue
        if src == node_id or _reaches(adjacency, node_id, src):
            continue  # the Goto already depends on this From
        links[link_id(node_id)] = Connection(
            id=link_id(node_id),
            src_node=src, src_port=LINK_PORT,
            dst_node=node_id, dst_port=LINK_PORT,
        )
        adjacency.setdefault(src, set()).add(node_id)
    return links


def from_problem(graph: "Graph", node_id: str) -> Optional[str]:
    """Why this From has no value to emit, phrased for the user — or None if
    it is fine (or isn't a From at all). The scheduler asks before falling
    back to its generic 'input not connected' text, which would name a port
    the user cannot see."""
    node = graph.nodes.get(node_id)
    if node is None or not is_from(node):
        return None
    src = source_id(node)
    if not src:
        return "not configured: no Goto selected"
    target = graph.nodes.get(src)
    if target is None or not is_goto(target):
        return "not configured: the Goto this reads from no longer exists"
    if link_id(node_id) not in graph.links:
        return (f"not configured: reading {link_label(target)!r} here would "
                f"create a loop")
    return None


def _reaches(adjacency: dict[str, set[str]], start: str, target: str) -> bool:
    """Is `target` downstream of `start` in the given edge set?"""
    seen: set[str] = set()
    stack = [start]
    while stack:
        for nxt in adjacency.get(stack.pop(), ()):
            if nxt == target:
                return True
            if nxt not in seen:
                seen.add(nxt)
                stack.append(nxt)
    return False
