"""Graph <-> JSON (.flograph project files).

Versioned via an integer `schema` and a MIGRATIONS chain. Builtin nodes
serialize by type_id only; a non-null "code" means the instance was forked
(or is a user script node) and its spec is re-parsed from that code on load.
A builtin type_id the registry no longer knows (missing plugin, renamed/
removed stdlib node) becomes a broken placeholder node instead of failing
the whole load — see `_broken_spec`. So does a forked node whose script
won't load here at all: a top-level `import` of a package this machine
lacks must not cost you the rest of the project, so the node keeps its code
and its params and carries the reason, and re-saving writes it back
untouched.

Cached outputs are never embedded in this JSON. A node loads dirty here
unless flograph.engine.cache_persistence restores its output from a side-car
cache directory next to the project file — see that module for the
save/load flow and its independent versioning.
"""
from __future__ import annotations

import json
from importlib.metadata import PackageNotFoundError, version as _pkg_version
from pathlib import Path
from typing import Any, Callable, Iterable

from .datatypes import PortType
from .graph import Connection, Frame, Graph, GraphError, Page, Tile
from .node import NodeInstance, NodeSpec, NodeStatus
from .ports import PortDirection, PortSpec
from .registry import NodeRegistry
from .script import NodeScriptError, parse_spec

try:  # stamp saved files with the installed distribution version (single source)
    FLOGRAPH_VERSION = _pkg_version("flograph")
except PackageNotFoundError:  # running from a source tree without an install
    FLOGRAPH_VERSION = "0.0.0+unknown"

SCHEMA_VERSION = 1

MIGRATIONS: dict[int, Callable[[dict], dict]] = {
    # e.g. 1: _migrate_1_to_2
}


def graph_to_dict(graph: Graph) -> dict[str, Any]:
    return {
        "flograph_version": FLOGRAPH_VERSION,
        "schema": SCHEMA_VERSION,
        "graph": {
            "nodes": [
                {
                    "id": n.id,
                    "type": n.type_id,
                    "pos": [n.pos[0], n.pos[1]],
                    "params": dict(n.params),
                    "code": n.code_override,
                    "label": n.label_override,
                    "description": n.description,
                    "preview": n.canvas_preview_enabled,
                    "port_labels": n.port_labels,
                    "ports_collapsed": n.ports_collapsed,
                    "color": n.color,
                    "z": n.z,
                }
                for n in graph.nodes.values()
            ],
            "connections": [
                {
                    "id": c.id,
                    "src": [c.src_node, c.src_port],
                    "dst": [c.dst_node, c.dst_port],
                }
                for c in graph.connections.values()
            ],
            "frames": [
                {
                    "id": f.id,
                    "title": f.title,
                    "rect": list(f.rect),
                    "color": f.color,
                    "z": f.z,
                }
                for f in graph.frames.values()
            ],
            "pages": [
                {
                    "id": p.id,
                    "title": p.title,
                    "kind": p.kind,
                    "body": p.body,
                    "color": p.color,
                    "maximized_tile": p.maximized_tile,
                    "tiles": [
                        {
                            "id": t.id,
                            "node": t.node_id,
                            "port": t.port,
                            "rect": list(t.rect),
                            "z": t.z,
                        }
                        for t in p.tiles.values()
                    ],
                }
                for p in graph.pages.values()
            ],
        },
    }


def graph_from_dict(data: dict[str, Any], registry: NodeRegistry) -> Graph:
    data = migrate(data)
    payload = data.get("graph")
    if not isinstance(payload, dict):
        raise GraphError("not a flograph project: missing 'graph' object")

    node_entries = payload.get("nodes", [])
    conn_entries = payload.get("connections", [])
    input_ports_needed: dict[str, set[str]] = {}
    output_ports_needed: dict[str, set[str]] = {}
    for entry in conn_entries:
        src_node, src_port = entry["src"]
        dst_node, dst_port = entry["dst"]
        output_ports_needed.setdefault(src_node, set()).add(src_port)
        input_ports_needed.setdefault(dst_node, set()).add(dst_port)

    graph = Graph()
    for entry in node_entries:
        type_id = entry["type"]
        code = entry.get("code")
        broken_reason = None
        if code is not None:
            try:
                spec = parse_spec(code, type_id, builtin=False)
            except NodeScriptError as exc:
                # the file is still worth opening: one node that can't load
                # here (a missing package, most often) must not take the
                # other fifty with it
                broken_reason = str(exc)
                spec = None
        else:
            # left with no reason on purpose: an unresolvable type_id keeps
            # its own long-standing wording below
            spec = registry.maybe_get(type_id)
        if spec is None:
            spec = _broken_spec(
                type_id,
                inputs=input_ports_needed.get(entry["id"], ()),
                outputs=output_ports_needed.get(entry["id"], ()),
                reason=broken_reason,
            )
        node = NodeInstance(
            id=entry["id"],
            spec=spec,
            code_override=code,
            params={**spec.default_params(), **entry.get("params", {})},
            pos=tuple(entry.get("pos", (0.0, 0.0))),
            label_override=entry.get("label"),
            description=entry.get("description", ""),
            canvas_preview_enabled=entry.get("preview", True),
            # absent = follow the canvas preference, which is
            # what every node written before this existed wants
            port_labels=entry.get("port_labels"),
            ports_collapsed=entry.get("ports_collapsed", False),
            color=entry.get("color"),
            # absent before layering existed: add_node then assigns z in
            # load order, which is exactly the old stacking
            z=entry.get("z"),
        )
        if spec.broken:
            node.status = NodeStatus.ERROR
            node.status_message = broken_reason or (
                f"Unknown node type {type_id!r} — the node script may have "
                f"been removed, renamed, or belong to a missing plugin."
            )
        graph.add_node(node)

    for entry in conn_entries:
        src_node, src_port = entry["src"]
        dst_node, dst_port = entry["dst"]
        graph.connect(src_node, src_port, dst_node, dst_port,
                      conn_id=entry.get("id"))

    for entry in payload.get("frames", []):
        graph.add_frame(Frame(
            id=entry["id"],
            title=entry.get("title", "Frame"),
            rect=tuple(entry.get("rect", (0, 0, 300, 200))),
            color=entry.get("color", "#33415c"),
            # absent before layering existed: add_frame then assigns z in
            # load order, which is exactly the old stacking
            z=entry.get("z"),
        ))

    for entry in payload.get("pages", []):
        page = graph.add_page(Page(
            id=entry["id"],
            title=entry.get("title", "Page"),
            # absent before report pages existed — every old page is a
            # dashboard, which is exactly what those files meant
            kind=entry.get("kind") or "dashboard",
            body=entry.get("body", ""),
            color=entry.get("color"),
            # absent in files written before dashboards could maximize a tile
            maximized_tile=entry.get("maximized_tile"),
        ))
        # tiles referencing missing nodes load as-is: the dashboard shows a
        # placeholder for them, mirroring the _broken_spec philosophy
        for tile_entry in entry.get("tiles", []):
            graph.add_tile(page.id, Tile(
                id=tile_entry["id"],
                node_id=tile_entry["node"],
                port=tile_entry.get("port"),
                rect=tuple(tile_entry.get("rect", (0, 0, 420, 320))),
                z=tile_entry.get("z"),
            ))
    return graph


def _broken_spec(type_id: str, inputs: Iterable[str],
                 outputs: Iterable[str],
                 reason: "str | None" = None) -> NodeSpec:
    """A placeholder spec for a node whose real spec isn't available here —
    an unresolvable type_id, or a forked script that won't load on this
    machine.

    Ports are synthesized as PortType.ANY from the connections that touched
    this node in the file, so its wiring survives the round trip even though
    the real port types are unknown; the node still won't run. `reason` is
    what the node shows and what the status bar reports, so it has to say
    what would fix it.
    """
    return NodeSpec(
        type_id=type_id,
        label=type_id.rsplit(".", 1)[-1],
        category="Broken",
        inputs=[PortSpec(name=n, type=PortType.ANY, direction=PortDirection.INPUT,
                         optional=True) for n in sorted(inputs)],
        outputs=[PortSpec(name=n, type=PortType.ANY, direction=PortDirection.OUTPUT)
                for n in sorted(outputs)],
        params=[],
        source="",
        doc=reason or (f"Node type {type_id!r} is not available in this "
                       "build of flograph."),
        broken=True,
    )


def migrate(data: dict[str, Any]) -> dict[str, Any]:
    version = data.get("schema")
    if not isinstance(version, int):
        raise GraphError("not a flograph project: missing integer 'schema'")
    if version > SCHEMA_VERSION:
        raise GraphError(
            f"project schema {version} is newer than this flograph "
            f"(supports up to {SCHEMA_VERSION})"
        )
    while version < SCHEMA_VERSION:
        data = MIGRATIONS[version](data)
        version = data["schema"]
    return data


def save(graph: Graph, path: str | Path) -> None:
    Path(path).write_text(json.dumps(graph_to_dict(graph), indent=2))


def load(path: str | Path, registry: NodeRegistry) -> Graph:
    try:
        data = json.loads(Path(path).read_text())
    except json.JSONDecodeError as exc:
        raise GraphError(f"not a flograph project: invalid JSON ({exc})") from exc
    return graph_from_dict(data, registry)
