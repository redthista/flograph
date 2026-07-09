"""Graph <-> JSON (.flopy project files).

Versioned via an integer `schema` and a MIGRATIONS chain. Builtin nodes
serialize by type_id only; a non-null "code" means the instance was forked
(or is a user script node) and its spec is re-parsed from that code on load.

Cached outputs are never embedded in this JSON. A node loads dirty here
unless flopy.engine.cache_persistence restores its output from a side-car
cache directory next to the project file — see that module for the
save/load flow and its independent versioning.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from .graph import Connection, Frame, Graph, GraphError
from .node import NodeInstance
from .registry import NodeRegistry
from .script import parse_spec

SCHEMA_VERSION = 1

MIGRATIONS: dict[int, Callable[[dict], dict]] = {
    # e.g. 1: _migrate_1_to_2
}


def graph_to_dict(graph: Graph) -> dict[str, Any]:
    return {
        "flopy_version": "0.1.0",
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
                }
                for f in graph.frames.values()
            ],
        },
    }


def graph_from_dict(data: dict[str, Any], registry: NodeRegistry) -> Graph:
    data = migrate(data)
    payload = data.get("graph")
    if not isinstance(payload, dict):
        raise GraphError("not a flopy project: missing 'graph' object")

    graph = Graph()
    for entry in payload.get("nodes", []):
        type_id = entry["type"]
        code = entry.get("code")
        if code is not None:
            spec = parse_spec(code, type_id, builtin=False)
        else:
            builtin = registry.maybe_get(type_id)
            if builtin is None:
                raise GraphError(
                    f"project uses unknown node type {type_id!r} and carries "
                    f"no code for it"
                )
            spec = builtin
        node = NodeInstance(
            id=entry["id"],
            spec=spec,
            code_override=code,
            params={**spec.default_params(), **entry.get("params", {})},
            pos=tuple(entry.get("pos", (0.0, 0.0))),
            label_override=entry.get("label"),
        )
        graph.add_node(node)

    for entry in payload.get("connections", []):
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
        ))
    return graph


def migrate(data: dict[str, Any]) -> dict[str, Any]:
    version = data.get("schema")
    if not isinstance(version, int):
        raise GraphError("not a flopy project: missing integer 'schema'")
    if version > SCHEMA_VERSION:
        raise GraphError(
            f"project schema {version} is newer than this flopy "
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
        raise GraphError(f"not a flopy project: invalid JSON ({exc})") from exc
    return graph_from_dict(data, registry)
