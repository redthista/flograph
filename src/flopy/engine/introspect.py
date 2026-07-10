"""Introspection of cached upstream data.

flopy's take on KNIME table-spec propagation: nodes are arbitrary Python,
so output schemas can't be declared statically — but after a run the real
outputs sit in the cache. The properties panel uses this to offer column
pickers populated from whatever DataFrames actually feed a node.
"""
from __future__ import annotations

import sys

from flopy.core import Graph

from .cache import OutputCache


def upstream_columns(graph: Graph, cache: OutputCache, node_id: str) -> list[str]:
    """Column names of every cached DataFrame feeding node_id's inputs,
    in port order, deduplicated. Empty when nothing upstream has run yet."""
    pd = sys.modules.get("pandas")
    if pd is None or node_id not in graph.nodes:
        return []
    node = graph.nodes[node_id]
    seen: dict[str, None] = {}
    by_port = {p.name: p for p in node.spec.inputs}
    for conn in graph.connections.values():
        if conn.dst_node != node_id or conn.dst_port not in by_port:
            continue
        entry = cache.get(conn.src_node)
        if entry is None:
            continue
        value = entry.outputs.get(conn.src_port)
        if isinstance(value, pd.DataFrame):
            for col in value.columns:
                seen.setdefault(str(col))
    return list(seen)
