"""Graph <-> JSON (.flograph project files).

Versioned via an integer `schema` and a MIGRATIONS chain. Builtin nodes
serialize by type_id only; a non-null "code" means the instance carries a
script — a fork the user edited, or (see `_portable_code`) the library
text of a `user.*` node, embedded so a project that uses custom nodes is
one self-contained file. On load that script is re-parsed, except when
the type_id resolves to a user node this machine already has and the
embedded text matches it exactly: then the instance relinks to the
library and is not treated as a fork. A builtin type_id the registry no
longer knows (missing plugin, renamed/removed stdlib node) becomes a
broken placeholder node instead of failing the whole load — see
`_broken_spec`. So does a forked node whose script
won't load here at all: a top-level `import` of a package this machine
lacks must not cost you the rest of the project, so the node keeps its code
and its params and carries the reason, and re-saving writes it back
untouched.

Cached outputs are never embedded in this JSON. A node loads dirty here
unless flograph.engine.cache_persistence restores its output — from the
``cache/`` tree inside the .flograph bundle, or from a legacy sidecar
directory next to a plain-JSON project file. See that module for the
save/load flow and its independent versioning, and `core.container` for
the bundle format. `load` here reads the graph half whichever way the file
is stored — a ``.flograph`` bundle, an older plain-JSON ``.flograph``, or a
``.flowf`` workflow export. `save` writes plain JSON only: it backs the
``.flowf`` export and the pre-bundle era; the bundle writer, which needs
the cache too, lives in cache_persistence.
"""
from __future__ import annotations

import json
from importlib.metadata import PackageNotFoundError, version as _pkg_version
from pathlib import Path
from typing import Any, Callable, Iterable

from . import dotenv
from .datatypes import PortType
from .graph import Connection, Frame, Graph, GraphError, Page, Shape, Tile
from .node import NodeInstance, NodeSpec, NodeStatus
from .page_setup import PageSetup
from .ports import PortDirection, PortSpec
from .ports import PortDirection, PortSpec, is_flow
from .registry import NodeRegistry
from .script import NodeScriptError, parse_spec
from .user_nodes import USER_PREFIX

try:  # stamp saved files with the installed distribution version (single source)
    FLOGRAPH_VERSION = _pkg_version("flograph")
except PackageNotFoundError:  # running from a source tree without an install
    FLOGRAPH_VERSION = "0.0.0+unknown"

SCHEMA_VERSION = 1

MIGRATIONS: dict[int, Callable[[dict], dict]] = {
    # e.g. 1: _migrate_1_to_2
}


def _portable_code(node: NodeInstance) -> "str | None":
    """What goes in a node's serialized ``code`` slot.

    A forked instance emits its override, exactly as before. An unforked
    instance of a ``user.*`` node emits the library script's text as well,
    so a project that uses custom nodes travels as one self-contained
    file: open it on a machine that has never seen that user node and it
    still loads and runs. It rides the same ``code`` mechanism a fork uses
    — only filled in from the library rather than from a hand edit — so
    ``load`` needs almost no new logic: it relinks the instance to the
    real user node when this machine has it (``code`` equal to the
    registry's source) and otherwise keeps the embedded copy as a local
    fork, the way any code-carrying node with no matching type already
    behaves.

    Builtin and plugin nodes still emit ``None``: the type_id is enough,
    a builtin ships with every install and a plugin is distributed as its
    own package rather than pasted into each project file. A broken
    placeholder emits ``None`` too — there is no real source to carry.
    """
    if node.code_override is not None:
        return node.code_override
    if (node.type_id.startswith(USER_PREFIX + ".")
            and not node.spec.builtin and not node.spec.broken):
        return node.spec.source
    return None


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
                    "code": _portable_code(n),
                    "label": n.label_override,
                    "description": n.description,
                    "active": n.active,
                    "locked": n.locked,
                    "frozen": n.frozen,
                    "manual": n.manual,
                    "frozen_fingerprint": n.frozen_fingerprint,
                    "exclusive": n.exclusive_override,
                    "preview": n.canvas_preview_enabled,
                    "port_labels": n.port_labels,
                    "flow_pins": n.flow_pins,
                    "ports_collapsed": n.ports_collapsed,
                    "color": n.color,
                    "compact_view": n.compact_view,
                    "mark": n.mark,
                    "mark_text": n.mark_text,
                    "mark_image": n.mark_image,
                    "z": n.z,
                    # ports grown past the script (spare promotions); absent
                    # in older files, which never grew any
                    "extra_inputs": [
                        {"name": p.name, "type": p.type.value}
                        for p in n.extra_inputs
                    ],
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
                    "active": f.active,
                    "manual": f.manual,
                    "collapsed": f.collapsed,
                    "expanded_size": (list(f.expanded_size)
                                      if f.expanded_size else None),
                    "members": list(f.members),
                    "member_frames": list(f.member_frames),
                    "nudged": [list(entry) for entry in f.nudged],
                    "source": f.source,
                    "source_fingerprint": f.source_fingerprint,
                }
                for f in graph.frames.values()
            ],
            "shapes": [
                {
                    "id": s.id,
                    "kind": s.kind,
                    "rect": list(s.rect),
                    "z": s.z,
                    "hidden": s.hidden,
                    "stroke": s.stroke,
                    "fill": s.fill,
                    "stroke_width": s.stroke_width,
                    "dashed": s.dashed,
                    "text": s.text,
                    "text_color": s.text_color,
                    "font_size": s.font_size,
                    "flip": s.flip,
                }
                for s in graph.shapes.values()
            ],
            "pages": [
                {
                    "id": p.id,
                    "title": p.title,
                    "kind": p.kind,
                    "body": p.body,
                    "color": p.color,
                    "maximized_tile": p.maximized_tile,
                    "view_mode": p.view_mode,
                    "fit_to_window": p.fit_to_window,
                    # only what the user changed — see PageSetup.to_dict
                    "setup": p.setup.to_dict(),
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
            # Where `${env:NAME}` reads its secrets from — the path only.
            # The values stay in that file and never enter this one.
            "env_path": graph.env_path,
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
        # the flow port is implicit on every spec, broken placeholders
        # included, so it must not be synthesized as a data port here
        if not is_flow(src_port):
            output_ports_needed.setdefault(src_node, set()).add(src_port)
        if not is_flow(dst_port):
            input_ports_needed.setdefault(dst_node, set()).add(dst_port)

    graph = Graph()
    # Absent in files written before variables existed, which is what the
    # empty default means anyway: use the per-user secrets file.
    graph.env_path = str(payload.get("env_path", "") or "")
    for entry in node_entries:
        type_id = entry["type"]
        code = entry.get("code")
        broken_reason = None
        if code is not None:
            reg_spec = registry.maybe_get(type_id)
            if (type_id.startswith(USER_PREFIX + ".") and reg_spec is not None
                    and not reg_spec.builtin and code == reg_spec.source):
                # A user node whose script the file carried a copy of (see
                # `_portable_code`), and this machine has the real one: use
                # it and drop `code`, so the instance stays linked to the
                # library rather than becoming a fork of an identical
                # script. A genuine fork's `code` differs from the source,
                # so it falls through to the parse below.
                spec = reg_spec
                code = None
            else:
                try:
                    spec = parse_spec(code, type_id, builtin=False)
                except NodeScriptError as exc:
                    # the file is still worth opening: one node that can't
                    # load here (a missing package, most often) must not
                    # take the other fifty with it
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
            # absent in anything written before these existed, and the
            # absent meaning is the harmless one in both cases
            active=entry.get("active", True),
            locked=entry.get("locked", False),
            frozen=entry.get("frozen", False),
            manual=entry.get("manual", False),
            frozen_fingerprint=entry.get("frozen_fingerprint"),
            # absent = follow the script's NODE['exclusive'], which is what
            # every node written before concurrent execution existed wants
            exclusive_override=entry.get("exclusive"),
            canvas_preview_enabled=entry.get("preview", True),
            # absent = follow the canvas preference, which is
            # what every node written before this existed wants
            port_labels=entry.get("port_labels"),
            flow_pins=entry.get("flow_pins"),
            ports_collapsed=entry.get("ports_collapsed", False),
            color=entry.get("color"),
            # absent = follow the canvas preference, which is what every node
            # written before the compact square existed wants
            compact_view=entry.get("compact_view"),
            # absent = no override, so the node draws its category's mark —
            # which is what every node written before marks existed wants
            mark=entry.get("mark", "") or "",
            mark_text=entry.get("mark_text", "") or "",
            mark_image=entry.get("mark_image", "") or "",
            # absent before layering existed: add_node then assigns z in
            # load order, which is exactly the old stacking
            z=entry.get("z"),
        )
        # regrow ports this instance had grown past its script, before any
        # wire references them (connections are applied just below). A
        # missing type or junk entry is skipped rather than fatal — a grown
        # port lost to a bad edit costs a dropped wire, not a project.
        extras = []
        for p in entry.get("extra_inputs") or []:
            try:
                extras.append(PortSpec(
                    p["name"], PortType(p["type"]),
                    PortDirection.INPUT, optional=True))
            except (KeyError, ValueError, TypeError):
                continue
        if extras:
            node.adopt_extra_inputs(extras)
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
            # absent before a frame carried run flags: a frame that says
            # nothing holds nothing back, which is how they all behaved
            active=bool(entry.get("active", True)),
            manual=bool(entry.get("manual", False)),
            # absent before frames could collapse, which is the old meaning
            collapsed=bool(entry.get("collapsed", False)),
            expanded_size=(tuple(entry["expanded_size"])
                           if entry.get("expanded_size") else None),
            members=tuple(entry.get("members", ())),
            member_frames=tuple(entry.get("member_frames", ())),
            nudged=tuple(tuple(n) for n in entry.get("nudged", ())),
            source=entry.get("source", ""),
            source_fingerprint=entry.get("source_fingerprint", ""),
        ))

    for entry in payload.get("shapes", []):
        graph.add_shape(Shape(
            id=entry["id"],
            kind=entry.get("kind", "rect"),
            rect=tuple(entry.get("rect", (0, 0, 160, 110))),
            z=entry.get("z"),
            hidden=bool(entry.get("hidden", False)),
            stroke=entry.get("stroke", ""),
            fill=entry.get("fill", ""),
            stroke_width=float(entry.get("stroke_width", 2.0)),
            dashed=bool(entry.get("dashed", False)),
            text=entry.get("text", ""),
            text_color=entry.get("text_color", ""),
            font_size=float(entry.get("font_size", 0.0)),
            flip=bool(entry.get("flip", False)),
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
            # absent in files written before view mode existed — they were
            # all being edited, so that is the right default
            view_mode=bool(entry.get("view_mode", False)),
            # absent before pages could scale themselves; those pages sat at
            # whatever zoom the reader left them at, which is False
            fit_to_window=bool(entry.get("fit_to_window", False)),
            # absent in files written before page setup existed, and absent
            # in any page left at the defaults — both mean "the defaults"
            setup=PageSetup.from_dict(entry.get("setup")),
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
    from . import container
    if container.is_bundle(path):
        with container.BundleReader(path) as reader:
            text = reader.read_text(container.PROJECT_MEMBER)
        if text is None:
            raise GraphError(
                "not a flograph project: the bundle has no project.json")
    else:
        text = Path(path).read_text()
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise GraphError(f"not a flograph project: invalid JSON ({exc})") from exc
    graph = graph_from_dict(data, registry)
    # Secrets are loaded here because this is the only place that knows where
    # the project file sits, and `env_path` is stored relative to it.
    dotenv.bind(graph, dotenv.resolve_path(graph.env_path, str(path)))
    return graph
