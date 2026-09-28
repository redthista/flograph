"""Drop Output: a node that lets go of what it produced once it is read.

Off by default: a node keeps its output, as it always did. Turned on — the
opposite of Power BI's *Enable load*, for the nodes that only prepare data
for the next step — the node runs as usual,
its value is handed to the nodes that read it, and once the last of them in
that run has finished it is dropped from memory and never saved in the
project file. The node stays green: it ran, and it succeeded. Its badge and
its tooltip say there is nothing held to look at until it runs again, which
it does on its own whenever a node that reads it has to re-run.

The rules live here, Qt-free, for the engine, the file loader and the menu.
"""
from __future__ import annotations

from typing import Iterable

from .ports import is_flow


def readers(graph, node_id: str) -> set[str]:
    """The nodes that read this node's *value*: wires, Goto/From links,
    `${name}` variables and report embeds. Not order edges — "run after
    that" hands nothing over, so it is no reason to hold anything."""
    return {c.dst_node for c in graph._edges().out_of.get(node_id, ())
            if not is_flow(c.src_port)}


def shows_output(graph, node) -> bool:
    """Whether something on screen displays this node's value — its own
    card, a dashboard tile, a report page. Such a node always keeps its
    output: dropping it would leave that display blank."""
    from .usage import uses_of
    if getattr(node.spec, "card", None):
        return True
    return bool(uses_of(graph, node.id))


def can_drop_output(graph, node) -> bool:
    """Whether Drop Output may be turned on: a node that shows its output
    cannot, and nor can one with nothing to give (no outputs)."""
    return bool(node.spec.outputs) and not shows_output(graph, node)


def settled_on_open(graph, restored: Iterable[str]) -> list[str]:
    """The dropping nodes a reopened project can count as having run.

    Nothing of theirs is saved, so the cache cannot vouch for them. Their
    readers can: a reader's fingerprint takes in this node's, so a reader
    restored from the file proves this node is as it was when it last ran.
    A dropping node whose every reader was restored (or is itself settled —
    a chain of them) is clean, and a Run All does not run it for nothing.
    One with no readers at all has nothing to vouch for it, and stays dirty.
    """
    done = set(restored)
    settled: list[str] = []
    for node_id in reversed(graph.topo_order()):
        node = graph.nodes[node_id]
        if not node.drop_output or node_id in done:
            continue
        mine = readers(graph, node_id)
        if mine and mine <= done:
            done.add(node_id)
            settled.append(node_id)
    return settled
