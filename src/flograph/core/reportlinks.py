"""Report edges — what makes a node that renders a report page depend on
everything that page shows.

A report *page* names its embeds by label (`![[Sales Chart]]`), which is fine
for a page: it is a view outside the flow, rendered when someone looks. A node
that renders one — Save Report — is *inside* the flow, and there the label
lookup is a dependency the scheduler cannot see. It would run before the chart
it saves was drawn, and never again when the chart changed.

So, exactly as `core.varlinks` does for `${name}`, every embed on the chosen
page becomes a derived, portless edge from the embedded node to the reader.
Unioned into `Graph._iter_edges()`, the reader is then ordered after, dirtied
by and fingerprinted against what its report shows, by machinery that already
exists. A reader declares itself with NODE["reads_report"], naming its
`page_ref` param.

Rebuilt whole on every change that can move it — a node added, removed or
renamed, the reader's page param, the page's text — and cheap when there are
no readers, which is almost every project.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from .report import find_embeds

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .graph import Connection, Graph

REPORT_KIND = "report"


def link_id(reader_id: str, source_id: str) -> str:
    return f"report:{reader_id}:{source_id}"


def is_reader(node) -> bool:
    return bool(getattr(node.spec, "reads_report", ""))


def readers(graph: "Graph") -> list:
    return [n for n in graph.nodes.values() if is_reader(n)]


def page_of(graph: "Graph", node):
    """The report page a reader is set to, or None."""
    page_id = str(node.params.get(node.spec.reads_report) or "")
    page = graph.pages.get(page_id)
    return page if page is not None and page.kind == REPORT_KIND else None


def readers_of(graph: "Graph", page_id: str) -> list[str]:
    """The ids of the readers set to this page."""
    return [n.id for n in readers(graph)
            if str(n.params.get(n.spec.reads_report) or "") == page_id]


def embedded_nodes(graph: "Graph", body: str) -> list[str]:
    """Every node a page's text embeds, by label, in first-seen order. A
    label two nodes share names both: the page shows a warning for it, and
    depending on both is the answer that can never be stale."""
    wanted = {e.ref.strip().casefold() for e in find_embeds(body or "")}
    if not wanted:
        return []
    return [node_id for node_id, node in graph.nodes.items()
            if node.label.casefold() in wanted]


def resolve_report_links(graph: "Graph") -> dict[str, "Connection"]:
    """The full report-edge set for a graph, keyed by edge id.

    Tested against every other edge, as `resolve_var_links` is, so a page
    that embeds its own saver — or something downstream of it — is left
    without that edge instead of closing a loop.
    """
    from .graph import Connection  # local import: graph imports this module

    found = readers(graph)
    if not found:
        return {}
    adjacency: dict[str, set[str]] = {}
    for conn in (*graph.connections.values(), *graph.links.values(),
                 *graph.var_links.values()):
        adjacency.setdefault(conn.src_node, set()).add(conn.dst_node)

    edges: dict[str, "Connection"] = {}
    for node in found:
        page = page_of(graph, node)
        if page is None:
            continue
        for src in embedded_nodes(graph, page.body):
            if src == node.id or _reaches(adjacency, node.id, src):
                continue
            key = link_id(node.id, src)
            edges[key] = Connection(id=key, src_node=src, src_port="",
                                    dst_node=node.id, dst_port="")
            adjacency.setdefault(src, set()).add(node.id)
    return edges


def report_problem(graph: "Graph", node_id: str) -> Optional[str]:
    """Why this reader cannot run, phrased for the user — or None."""
    node = graph.nodes.get(node_id)
    if node is None or not is_reader(node):
        return None
    page_id = str(node.params.get(node.spec.reads_report) or "")
    if not page_id:
        return "not configured: choose the report page to save"
    page = graph.pages.get(page_id)
    if page is None:
        return "not configured: the chosen report page has been deleted"
    if page.kind != REPORT_KIND:
        return f"not configured: {page.title!r} is not a report page"
    looped = [src for src in embedded_nodes(graph, page.body)
              if link_id(node_id, src) not in graph.report_links]
    if looped:
        label = graph.nodes[looped[0]].label
        return (f"not configured: the report embeds {label!r}, which runs "
                f"after this node — saving it here would create a loop")
    return None


def _reaches(adjacency: dict[str, set[str]], start: str, target: str) -> bool:
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
