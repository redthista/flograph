"""Finding a node in a graph that has outgrown one screen.

The same fuzzy match the Tab palette uses to find a node *type*, pointed at
the nodes actually on the canvas. Kept here rather than in the search bar
because the ranking is the part worth testing, and it needs no Qt to be
right.

A node is matched on its own name first and on its type second: "filter"
should still find the Filter Rows node somebody renamed to "drop cancelled
orders", but it must not outrank a node actually called "Filter".
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from .registry import fuzzy_score

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .graph import Graph
    from .node import NodeInstance

#: How much a hit on the node's *type* is worth against a hit on its name.
TYPE_WEIGHT = 0.5


def search_nodes(graph: "Graph", query: str) -> list["NodeInstance"]:
    """Nodes matching `query`, best first.

    An empty query is not "no matches" but "no filter": the whole graph in
    alphabetical order, which is what a search box with nothing typed in it
    should be offering. Ties break on name then id so the list is stable
    while typing rather than reshuffling equal-scoring rows.
    """
    nodes = list(graph.nodes.values())
    if not query.strip():
        return sorted(nodes, key=lambda node: (node.label.casefold(), node.id))
    scored = []
    for node in nodes:
        score = max(fuzzy_score(query, node.label),
                    fuzzy_score(query, node.spec.label) * TYPE_WEIGHT)
        if score > 0:
            scored.append((score, node))
    scored.sort(key=lambda pair: (-pair[0], pair[1].label.casefold(),
                                  pair[1].id))
    return [node for _, node in scored]
