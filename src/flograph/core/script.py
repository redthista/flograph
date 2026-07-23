"""The node script contract.

A node is a Python module-shaped text that declares:

    NODE = {
        "label": "Filter Rows",
        "category": "Transform",
        "inputs":  [("table", "dataframe")],            # (name, type[, opts])
        "outputs": [("filtered", "dataframe")],
    }
    PARAMS = [  # optional
        {"name": "query", "type": "string", "default": ""},
    ]

    def run(ctx, table):        # inputs arrive as keyword args
        ...
        return {"filtered": table[mask]}   # dict keyed by output ports
                                           # (bare value ok for single output)

`ctx` is the engine's RunContext: ctx.params, ctx.log(msg),
ctx.check_cancelled(), ctx.progress(fraction), ctx.node_id.

Rules:
- Treat inputs as read-only (outputs are cached and shared by reference).
- Unconnected optional inputs arrive as None.
- Heavy imports belong inside run(), top-level code should only declare.
- Create matplotlib figures with matplotlib.figure.Figure(), never pyplot.

Scripts are executed with a virtual filename: parse_spec uses
"<spec:{type_id}>"; the engine compiles per-instance with "<node:{id}>" so
traceback frames map back to the node's editor.
"""
from __future__ import annotations

from typing import Any, Callable

from .datatypes import PortType
from .node import NodeSpec
from .params import ParamSpec
from .ports import PortDirection, PortSpec


class NodeScriptError(Exception):
    """The script text does not satisfy the node contract."""


# Rich-card kinds a node may declare via NODE["card"]. The value drives which
# canvas card / dashboard tile renders the node's output; None = ordinary node.
CARD_KINDS = frozenset({
    "webview", "figure", "table_viewer", "kpi", "slicer",
    "button", "note", "grid", "reroute", "goto", "from",
})


def spec_filename(type_id: str) -> str:
    return f"<spec:{type_id}>"


def node_filename(node_id: str) -> str:
    return f"<node:{node_id}>"


def _execute(source: str, filename: str) -> dict[str, Any]:
    namespace: dict[str, Any] = {}
    try:
        code = compile(source, filename, "exec")
    except SyntaxError as exc:
        raise NodeScriptError(
            f"syntax error on line {exc.lineno}: {exc.msg}"
        ) from exc
    try:
        exec(code, namespace)
    except Exception as exc:  # top-level code should only declare
        raise NodeScriptError(
            f"error while loading node script: {type(exc).__name__}: {exc}"
        ) from exc
    return namespace


def _parse_ports(
    entries: Any, direction: PortDirection, where: str
) -> list[PortSpec]:
    if not isinstance(entries, (list, tuple)):
        raise NodeScriptError(f"{where} must be a list of (name, type) tuples")
    ports: list[PortSpec] = []
    seen: set[str] = set()
    for i, entry in enumerate(entries):
        if not isinstance(entry, (list, tuple)) or len(entry) not in (2, 3):
            raise NodeScriptError(
                f"{where}[{i}] must be (name, type) or (name, type, opts)"
            )
        name, type_str = entry[0], entry[1]
        opts = entry[2] if len(entry) == 3 else {}
        if not isinstance(name, str) or not name.isidentifier():
            raise NodeScriptError(
                f"{where}[{i}]: port name {name!r} must be a valid identifier"
            )
        if name in seen:
            raise NodeScriptError(f"{where}: duplicate port name {name!r}")
        seen.add(name)
        try:
            port_type = PortType(type_str)
        except ValueError:
            valid = ", ".join(t.value for t in PortType)
            raise NodeScriptError(
                f"{where}[{i}]: unknown port type {type_str!r} (valid: {valid})"
            ) from None
        if not isinstance(opts, dict):
            raise NodeScriptError(f"{where}[{i}]: options must be a dict")
        ports.append(PortSpec(
            name=name,
            type=port_type,
            direction=direction,
            optional=bool(opts.get("optional", False)),
        ))
    return ports


def parse_spec(source: str, type_id: str, builtin: bool = False) -> NodeSpec:
    """Parse a node script into a NodeSpec, with precise error messages."""
    namespace = _execute(source, spec_filename(type_id))

    node_decl = namespace.get("NODE")
    if not isinstance(node_decl, dict):
        raise NodeScriptError("node script must define a NODE dict")
    label = node_decl.get("label")
    if not label or not isinstance(label, str):
        raise NodeScriptError("NODE['label'] must be a non-empty string")
    category = node_decl.get("category")
    if not category or not isinstance(category, str):
        raise NodeScriptError("NODE['category'] must be a non-empty string")

    card = node_decl.get("card")
    if card is not None and card not in CARD_KINDS:
        valid = ", ".join(sorted(CARD_KINDS))
        raise NodeScriptError(
            f"NODE['card'] {card!r} is not a valid card kind (valid: {valid})"
        )

    inputs = _parse_ports(node_decl.get("inputs", []), PortDirection.INPUT,
                          "NODE['inputs']")
    outputs = _parse_ports(node_decl.get("outputs", []), PortDirection.OUTPUT,
                           "NODE['outputs']")
    # zero ports is legal: display-only nodes (e.g. markdown notes) take no
    # part in dataflow

    params_decl = namespace.get("PARAMS", [])
    if not isinstance(params_decl, (list, tuple)):
        raise NodeScriptError("PARAMS must be a list of dicts")
    params: list[ParamSpec] = []
    seen_params: set[str] = set()
    for i, entry in enumerate(params_decl):
        try:
            spec = ParamSpec.from_dict(entry, where=f"PARAMS[{i}]")
        except ValueError as exc:
            raise NodeScriptError(str(exc)) from None
        if spec.name in seen_params:
            raise NodeScriptError(f"PARAMS: duplicate param name {spec.name!r}")
        seen_params.add(spec.name)
        params.append(spec)

    run = namespace.get("run")
    if not callable(run):
        raise NodeScriptError("node script must define a run(ctx, ...) function")

    return NodeSpec(
        type_id=type_id,
        label=label,
        category=category,
        inputs=inputs,
        outputs=outputs,
        params=params,
        source=source,
        builtin=builtin,
        doc=(namespace.get("__doc__") or "").strip(),
        card=card,
    )


def compile_run(source: str, node_id: str) -> Callable[..., Any]:
    """Execute a node script with the instance's virtual filename and return
    its run callable. Traceback frames from this callable carry
    "<node:{node_id}>" and can be mapped back to editor lines."""
    namespace = _execute(source, node_filename(node_id))
    run = namespace.get("run")
    if not callable(run):
        raise NodeScriptError("node script must define a run(ctx, ...) function")
    return run
