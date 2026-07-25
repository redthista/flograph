"""Introspection of cached upstream data.

flograph's take on table-spec propagation: nodes are arbitrary Python,
so output schemas can't be declared statically — but after a run the real
outputs sit in the cache. The properties panel uses this to offer column
pickers populated from whatever DataFrames actually feed a node.
"""
from __future__ import annotations

import sys

from flograph.core import Graph

from .cache import OutputCache


def slicer_options(graph: Graph, cache: OutputCache,
                   node_id: str) -> "list[str] | None":
    """Unique values (sorted, as strings) of the column a Slicer filters on,
    read from the cached upstream DataFrame — the slicer's own output is
    already filtered, so it can't be the source. None when nothing usable
    has run yet, so hosts can show a run-me placeholder."""
    pd = sys.modules.get("pandas")
    node = graph.nodes.get(node_id)
    if pd is None or node is None:
        return None
    conn = graph.input_connection(node_id, "table")
    entry = cache.get(conn.src_node) if conn else None
    source = entry.outputs.get(conn.src_port) if entry else None
    column = str(node.params.get("column", "") or "").strip()
    if not isinstance(source, pd.DataFrame) or column not in source.columns:
        return None
    return sorted(source[column].astype(str).unique())


def linked_table_source(graph: Graph, cache: OutputCache, node_id: str):
    """The cached upstream DataFrame feeding a Table node's "table" input,
    or None when it's unconnected, hasn't run, or isn't a frame."""
    conn = graph.input_connection(node_id, "table")
    entry = cache.get(conn.src_node) if conn else None
    value = entry.outputs.get(conn.src_port) if entry else None
    return value if hasattr(value, "itertuples") else None


def merged_linked_sheet(graph: Graph, cache: OutputCache,
                        node_id: str) -> "dict | None":
    """A linked Table node's sheet as it should be *shown* after a run —
    input-owned columns refreshed from upstream, the user's own columns
    (formula sources intact) carried over — as a sheet dict.

    None when there's no usable input, which means the node's stored sheet
    already stands on its own. Every host that displays a Table node's grid
    goes through here, so the canvas card and a dashboard tile of the same
    node never disagree about what a run produced."""
    from flograph.core.sheet import (merge_linked_sheet, parse_sheet,
                                     sheet_from_dataframe, sheet_to_dict)
    frame = linked_table_source(graph, cache, node_id)
    node = graph.nodes.get(node_id)
    if frame is None or node is None:
        return None
    return sheet_to_dict(merge_linked_sheet(
        sheet_from_dataframe(frame), parse_sheet(node.params.get("data"))))


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
