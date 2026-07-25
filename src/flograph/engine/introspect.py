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


def cached_input(graph: Graph, cache: OutputCache, node_id: str,
                 port: str):
    """Whatever is sitting in the cache on the far end of `node_id`'s `port`
    input, or None when it's unconnected or hasn't run."""
    conn = graph.input_connection(node_id, port)
    entry = cache.get(conn.src_node) if conn else None
    return entry.outputs.get(conn.src_port) if entry else None


def slicer_options(graph: Graph, cache: OutputCache,
                   node_id: str) -> "list[str] | None":
    """The values a Slicer's card should list.

    Connected, that's the unique values (sorted, as strings) of the column
    it filters on, read from the cached *upstream* DataFrame — the slicer's
    own output is already filtered, so it can't be the source. Unconnected,
    it's the "values" param, and needs no run at all: a standalone slicer is
    a value picker, so making it demand a run before showing anything would
    be asking for data it doesn't have.

    None means "nothing usable yet", so hosts can show a run-me placeholder.
    """
    node = graph.nodes.get(node_id)
    if node is None:
        return None
    if graph.input_connection(node_id, "table") is None:
        from flograph.core.controls import lines_to_values
        return lines_to_values(node.params.get("values", ""))
    pd = sys.modules.get("pandas")
    source = cached_input(graph, cache, node_id, "table") if pd else None
    column = str(node.params.get("column", "") or "").strip()
    if not isinstance(source, pd.DataFrame) or column not in source.columns:
        return None
    return sorted(source[column].astype(str).unique())


def control_upstream(graph: Graph, cache: OutputCache,
                     node_id: str) -> dict:
    """Everything a control node's own input ports currently supply, keyed by
    port name, ready for ControlWidget.set_upstream().

    Only connected ports with something cached appear, so an unwired setting
    simply falls through to the node's typed-in param. Each port name says
    how to read what arrived: `minimum`/`maximum` reduce a column to one end
    of its range, `options` becomes a list, anything else is passed as-is.

    Resolved here rather than in the widget so the canvas card and the
    dashboard tile of the same node can't disagree about what upstream said.
    """
    from flograph.core.controls import (as_iso_date, reduce_bound,
                                        values_from_source)

    node = graph.nodes.get(node_id)
    if node is None:
        return {}
    is_date = node.spec.control == "date"
    resolved: dict = {}
    for port in node.spec.inputs:
        source = cached_input(graph, cache, node_id, port.name)
        if source is None:
            continue
        if port.name == "options":
            resolved[port.name] = values_from_source(
                source, node.params.get("column", ""))
        elif port.name in ("minimum", "maximum"):
            bound = reduce_bound(source, high=port.name == "maximum")
            if bound is None:
                continue
            resolved[port.name] = as_iso_date(bound) if is_date else bound
        else:
            resolved[port.name] = source
    return {k: v for k, v in resolved.items() if v is not None and v != ""}


def choice_options(graph: Graph, cache: OutputCache,
                   node_id: str) -> "list[str] | None":
    """The options a Choice control should offer: derived from whatever is
    cached on its "options" input, or None when that input is unconnected —
    at which point the control falls back to its own typed-in list.

    Both the hosts and the node's own run() go through
    core.controls.values_from_source, so what the dropdown shows and what
    the node validates against can't drift apart."""
    from flograph.core.controls import values_from_source

    node = graph.nodes.get(node_id)
    if node is None or graph.input_connection(node_id, "options") is None:
        return None
    source = cached_input(graph, cache, node_id, "options")
    return values_from_source(source, node.params.get("column", "")) \
        if source is not None else None


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
