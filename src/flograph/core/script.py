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
`ctx.progress(0..1)` is how a loop says where it has got to: it fills the
ring in the node's status LED and the status bar line. Calls are throttled,
so report as often as is convenient.

Rules:
- Treat inputs as read-only (outputs are cached and shared by reference).
  The engine guards what it can guard for free: a pandas input arrives as a
  copy-on-write shallow copy, and a list, dict, set or bytearray is rebuilt
  one level deep, so appending to a list or writing a column lands on your
  copy and cannot reach the node upstream. A numpy input arrives read-only
  and raises if you write to it — take `arr.copy()` first. Reaching *through*
  an input (`rows[0]["x"] = 1`) and anything else that gets passed along, a
  figure or a connection, are still yours to honour.
- Unconnected optional inputs arrive as None.
- Heavy imports belong inside run(), top-level code should only declare.
  This is not just about speed: the script is *executed* to read NODE and
  PARAMS, so a top-level `import` runs whenever the node is loaded — when
  the library is built, when a project is opened, when code is applied. An
  import inside run() costs nothing until the node actually runs, and a
  missing package then fails only that node. See MissingDependencyError for
  what happens when a top-level one isn't available.
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


class MissingDependencyError(NodeScriptError):
    """A node script's top-level code imports a package that isn't installed.

    Its own class because it is the one script error that is nobody's
    mistake: the script is fine, this machine just doesn't have the library.
    That happens the moment a project moves between machines, so it has to
    stay recoverable — the node loads as a placeholder holding its code, and
    installing the package (or moving the import into run()) fixes it.
    """

    def __init__(self, module: str, where: str = "node script") -> None:
        self.module = module
        super().__init__(
            f"{where} needs the {module!r} package, which isn't installed — "
            "install it from Manage Packages…, or move the import inside "
            "run() so it's only needed when the node actually runs")


def missing_module_hint(exc: BaseException) -> "str | None":
    """The "install this" line for a ModuleNotFoundError raised anywhere —
    inside run() as well as at import time — or None for other errors."""
    name = getattr(exc, "name", None)
    if not isinstance(exc, ModuleNotFoundError) or not name:
        return None
    return (f"The {name!r} package isn't installed. Install it from "
            "Manage Packages…, then run again.")


# Rich-card kinds a node may declare via NODE["card"]. The value drives which
# canvas card / dashboard tile renders the node's output; None = ordinary node.
CARD_KINDS = frozenset({
    "webview", "figure", "table_viewer", "kpi", "slicer",
    "button", "note", "grid", "reroute", "goto", "from", "control",
    "report",
})

# Widget shapes for NODE["card"] == "control": input controls whose value the
# user sets on the card or on a dashboard page, rather than a rendered output.
# One host renders all of them from this declaration plus the node's PARAMS,
# so a new control is a node script — see flograph.ui.controls for the
# well-known param names each shape reads.
CONTROL_KINDS = frozenset({
    "slider",    # value along a track, int or float
    "range",     # two handles on one track -> a low/high pair
    "number",    # spin box
    "text",      # single-line text entry
    "date",      # calendar picker
    "toggle",    # single checkbox -> bool
    "choice",    # dropdown of fixed or upstream-supplied options
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
    except ModuleNotFoundError as exc:
        # told apart from every other load failure: the script is correct,
        # this machine is just missing a package, and that is fixable
        raise MissingDependencyError(exc.name or "?") from exc
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

    control = node_decl.get("control")
    if card == "control":
        if control not in CONTROL_KINDS:
            valid = ", ".join(sorted(CONTROL_KINDS))
            raise NodeScriptError(
                f"NODE['control'] {control!r} is not a valid control kind "
                f"(valid: {valid}) — a card of 'control' must say which"
            )
    elif control is not None:
        raise NodeScriptError(
            "NODE['control'] only applies when NODE['card'] is 'control'")

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
        control=control,
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
