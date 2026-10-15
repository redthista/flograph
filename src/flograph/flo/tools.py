"""What the Flo Assistant can do to a flow, as tools a model calls.

Two rules shape everything here:

- **Every change is an undo command**, the same ones a click makes
  (`ui.commands`), pushed inside one macro per assistant turn — so a turn
  is one Ctrl+Z, and the canvas, dirtying, caching and saving all behave
  exactly as if you had done it by hand.
- **Every result goes out through the Disclosure.** Node params, labels,
  status messages and output descriptions pass `scrub()` / `describe()`,
  so the level in force is what the model sees. A tool that would need more
  than the level allows is not offered at all (`specs()`), and arguments
  coming back are un-aliased before they touch the graph.

A model refers to nodes by short handles (`n1`, `n2`) rather than the 32-
character ids, which cost tokens and confuse small models; the handles
stay stable for the life of the Toolbox (one chat).

Mistakes come back as `{"error": ...}` naming what *would* be valid — the
ports a node has, the params a type takes, the options a choice allows —
so the model can correct itself on the next step instead of guessing.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Optional

from ..core import ai_disclosure as disc
from ..core.ai_disclosure import Disclosure
from ..core.graph import Graph, GraphError
from ..core.ports import is_flow
from ..llm.toolcall import ToolCall, ToolSpec

ADVISE, ACT = "advise", "act"
MAX_DESCRIBED_NODES = 150
_X_STEP, _Y_STEP = 280.0, 160.0


def _schema(properties: dict, required: tuple = ()) -> dict:
    out = {"type": "object", "properties": properties}
    if required:
        out["required"] = list(required)
    return out


_NODE = {"type": "string", "description": "a node handle, e.g. n3"}

_READ_TOOLS = [
    ToolSpec("describe_flow",
             "The flow as it stands: every node with its handle, type, label, "
             "changed settings, run status, and which node feeds each input.",
             _schema({})),
    ToolSpec("get_node",
             "One node in full: all its settings with their types and choices, "
             "its inputs and outputs, what is wired to it, and its last error.",
             _schema({"node": _NODE}, ("node",))),
    ToolSpec("find_node_types",
             "Search the node library by what you want to do ('bar chart', "
             "'read excel', 'group by'). Returns type ids to use with add_node.",
             _schema({"query": {"type": "string"}}, ("query",))),
    ToolSpec("get_node_type",
             "A node type's inputs, outputs, settings (with defaults and "
             "choices) and documentation — read it before add_node.",
             _schema({"type_id": {"type": "string"}}, ("type_id",))),
]

_OUTPUT_TOOL = ToolSpec(
    "get_output",
    "What a node last produced: for a table its row count and columns with "
    "their types{profile}. Never any rows. Empty if the node has not run.",
    _schema({"node": _NODE,
             "port": {"type": "string", "description": "output name; "
                      "optional when the node has one output"}}, ("node",)))

_WRITE_TOOLS = [
    ToolSpec("add_node",
             "Add a node of a library type. Optionally set its settings, a "
             "label, and place it next to another node. Returns its handle.",
             _schema({"type_id": {"type": "string"},
                      "label": {"type": "string"},
                      "params": {"type": "object",
                                 "description": "setting name -> value"},
                      "near": _NODE}, ("type_id",))),
    ToolSpec("connect",
             "Wire an output of one node into an input of another. Port names "
             "may be left out when the node has only one.",
             _schema({"from_node": _NODE, "from_port": {"type": "string"},
                      "to_node": _NODE, "to_port": {"type": "string"}},
                     ("from_node", "to_node"))),
    ToolSpec("disconnect",
             "Remove the wire going into one input of a node.",
             _schema({"node": _NODE, "port": {"type": "string"}},
                     ("node", "port"))),
    ToolSpec("set_params",
             "Change settings on a node: setting name -> new value.",
             _schema({"node": _NODE, "params": {"type": "object"}},
                     ("node", "params"))),
    ToolSpec("rename_node",
             "Give a node a label of its own (empty to go back to the type's).",
             _schema({"node": _NODE, "label": {"type": "string"}},
                     ("node", "label"))),
    ToolSpec("delete_nodes",
             "Delete nodes and every wire attached to them.",
             _schema({"nodes": {"type": "array", "items": _NODE}}, ("nodes",))),
]


@dataclass
class Action:
    """One change a turn made, for the chat to show as a card."""
    tool: str
    summary: str
    node_ids: list = field(default_factory=list)


class Toolbox:
    def __init__(self, graph: Graph, registry, undo_stack, *,
                 disclosure: Disclosure, autonomy: str = ACT,
                 cache=None) -> None:
        self.graph = graph
        self.registry = registry
        self.stack = undo_stack
        self.disclosure = disclosure
        self.autonomy = autonomy
        self.cache = cache
        self._handles: dict[str, str] = {}      # handle -> node id
        self._by_id: dict[str, str] = {}        # node id -> handle
        self._macro_open = False
        self._macro_text = "Flo Assistant"
        self.actions: list[Action] = []
        self._learn_cached_columns()

    def set_view(self, disclosure: Disclosure, autonomy: Optional[str] = None) -> None:
        """Change what the model may see and do, between turns. The flow's
        columns are learned again: a node run since the last turn may have
        brought new names that level 0 has to hide."""
        self.disclosure = disclosure
        if autonomy is not None:
            self.autonomy = autonomy
        self._learn_cached_columns()

    # -- turn bracketing ----------------------------------------------------------

    def begin_turn(self, text: str = "") -> None:
        """Start a turn. The undo macro opens lazily, on the first change,
        so a turn that only reads leaves no empty step on the stack."""
        self.actions = []
        summary = " ".join((text or "").split())
        self._macro_text = "Flo Assistant" + (f": {summary[:50]}" if summary else "")

    def end_turn(self) -> None:
        if self._macro_open:
            self.stack.endMacro()
            self._macro_open = False

    def _push(self, command) -> None:
        if not self._macro_open:
            self.stack.beginMacro(self._macro_text)
            self._macro_open = True
        self.stack.push(command)

    # -- what is offered ----------------------------------------------------------

    def specs(self) -> list[ToolSpec]:
        tools = list(_READ_TOOLS)
        if self.disclosure.allows(disc.SCHEMA):
            profile = (", and per column its empty share, distinct count, "
                       "range and what it looks like"
                       if self.disclosure.allows(disc.PROFILE) else "")
            tools.append(ToolSpec(_OUTPUT_TOOL.name,
                                  _OUTPUT_TOOL.description.format(profile=profile),
                                  _OUTPUT_TOOL.parameters))
        if self.autonomy == ACT:
            tools.extend(_WRITE_TOOLS)
        return tools

    def execute(self, call: ToolCall) -> str:
        """Run one tool call; the result as JSON text, ready to send."""
        offered = {spec.name for spec in self.specs()}
        if call.bad_arguments is not None:
            result: dict = {"error": "the arguments were not valid JSON: "
                            f"{call.bad_arguments[:200]!r} — send a JSON object"}
        elif call.name not in offered:
            result = {"error": f"there is no tool {call.name!r} here; the tools "
                      f"are: {', '.join(sorted(offered))}"}
        else:
            args = self.disclosure.unalias(call.arguments or {})
            try:
                result = getattr(self, f"_tool_{call.name}")(**args)
            except TypeError as exc:
                result = {"error": f"bad arguments for {call.name}: {exc}"}
            except _ToolError as exc:
                result = {"error": str(exc)}
            except GraphError as exc:
                result = {"error": self.disclosure.scrub(str(exc))}
        return json.dumps(result, default=str, ensure_ascii=False)

    # -- handles ----------------------------------------------------------------

    def handle(self, node_id: str) -> str:
        if node_id not in self._by_id:
            name = f"n{len(self._handles) + 1}"
            self._handles[name] = node_id
            self._by_id[node_id] = name
        return self._by_id[node_id]

    def _node(self, handle: Any):
        node_id = self._handles.get(str(handle or "").strip())
        if node_id is None or node_id not in self.graph.nodes:
            known = ", ".join(self.handle(n) for n in self.graph.nodes) or "none"
            raise _ToolError(f"no node {handle!r} — the nodes are: {known}. "
                             "Call describe_flow to see them.")
        return self.graph.node(node_id)

    def _learn_cached_columns(self) -> None:
        """Teach the Disclosure every column name already in hand, so even
        level 0 can hide them wherever they turn up."""
        if self.cache is None:
            return
        for node_id in self.graph.nodes:
            for value in self._outputs(node_id).values():
                self.disclosure.learn(disc.column_names(value))

    def _outputs(self, node_id: str) -> dict:
        if self.cache is None:
            return {}
        try:
            return dict(self.cache.peek(node_id) or {})
        except Exception:
            return {}

    # -- describing ----------------------------------------------------------------

    def _status(self, node) -> dict:
        status = getattr(node.status, "value", str(node.status))
        out = {"status": "error" if status == "error" else
               ("out of date" if node.dirty else "up to date")}
        if status == "error" and node.status_message:
            out["error"] = self.disclosure.error_text(node.status_message[:500])
        return out

    def _changed_params(self, node) -> dict:
        out = {}
        for spec in node.spec.params:
            if spec.hidden:
                continue
            value = node.params.get(spec.name, spec.default)
            if value != spec.default:
                out[spec.name] = self.disclosure.param_value(value, spec.type)
        return out

    def _wired_inputs(self, node) -> dict:
        out = {}
        for conn in self.graph.in_connections(node.id):
            if is_flow(conn.dst_port):
                continue
            out[conn.dst_port] = f"{self.handle(conn.src_node)}.{conn.src_port}"
        return out

    def _tool_describe_flow(self) -> dict:
        nodes = []
        for node_id in self.graph.topo_order():
            node = self.graph.node(node_id)
            entry = {"node": self.handle(node_id), "type": node.type_id,
                     "label": self.disclosure.scrub(node.label)}
            params = self._changed_params(node)
            if params:
                entry["settings"] = params
            wired = self._wired_inputs(node)
            if wired:
                entry["inputs"] = wired
            entry.update(self._status(node))
            nodes.append(entry)
        out: dict = {"node_count": len(nodes),
                     "nodes": nodes[:MAX_DESCRIBED_NODES]}
        if len(nodes) > MAX_DESCRIBED_NODES:
            out["note"] = (f"only the first {MAX_DESCRIBED_NODES} are listed; "
                           "use get_node for the others")
        if not nodes:
            out["note"] = "the flow is empty"
        return out

    def _tool_get_node(self, node) -> dict:
        inst = self._node(node)
        params = []
        for spec in inst.spec.params:
            if spec.hidden:
                continue
            entry = {"name": spec.name, "type": spec.type,
                     "value": self.disclosure.param_value(
                         inst.params.get(spec.name, spec.default), spec.type)}
            if spec.label and spec.label != spec.name:
                entry["label"] = spec.label
            if spec.options:
                entry["choices"] = [self.disclosure.scrub(str(o)) for o in spec.options]
            params.append(entry)
        out = {"node": self.handle(inst.id), "type": inst.type_id,
               "label": self.disclosure.scrub(inst.label),
               "inputs": [{"name": p.name, "type": p.type.value,
                           **({"optional": True} if p.optional else {})}
                          for p in inst.spec.inputs if not p.spare],
               "outputs": [{"name": p.name, "type": p.type.value}
                           for p in inst.spec.outputs],
               "wired_inputs": self._wired_inputs(inst),
               "feeds": [f"{c.src_port} -> {self.handle(c.dst_node)}.{c.dst_port}"
                         for c in self.graph.out_connections(inst.id)
                         if not is_flow(c.dst_port)],
               "settings": params}
        out.update(self._status(inst))
        return out

    def _tool_find_node_types(self, query) -> dict:
        hits = search_types(self.registry, str(query or ""))
        if not hits:
            return {"types": [], "note": "nothing matched — try other words, "
                    "e.g. what the node reads, makes or does"}
        return {"types": hits}

    def _tool_get_node_type(self, type_id) -> dict:
        spec = self._type(type_id)
        return {"type_id": spec.type_id, "label": spec.label,
                "category": spec.category,
                "inputs": [{"name": p.name, "type": p.type.value,
                            **({"optional": True} if p.optional else {})}
                           for p in spec.inputs if not p.spare],
                "outputs": [{"name": p.name, "type": p.type.value}
                            for p in spec.outputs],
                "settings": [{"name": p.name, "type": p.type,
                              "default": p.default,
                              **({"choices": p.options} if p.options else {}),
                              **({"label": p.label} if p.label else {})}
                             for p in spec.params if not p.hidden],
                "documentation": (spec.doc or "")[:1500]}

    def _tool_get_output(self, node, port=None) -> dict:
        inst = self._node(node)
        outputs = self._outputs(inst.id)
        names = [p.name for p in inst.spec.outputs]
        if port is None:
            if len(names) != 1:
                raise _ToolError(f"{self.handle(inst.id)} has outputs "
                                 f"{names}; say which with 'port'")
            port = names[0]
        if port not in names:
            raise _ToolError(f"{self.handle(inst.id)} has no output {port!r}; "
                             f"it has {names}")
        if port not in outputs:
            return {"node": self.handle(inst.id), "port": port,
                    "note": "nothing yet — the node has not run since it changed"}
        return {"node": self.handle(inst.id), "port": port,
                **self.disclosure.describe(outputs[port])}

    # -- changing ----------------------------------------------------------------

    def _type(self, type_id):
        spec = self.registry.maybe_get(str(type_id or ""))
        if spec is None or spec.broken:
            close = [s.type_id for s in self.registry.search(
                str(type_id or "").rsplit(".", 1)[-1])[:5]]
            raise _ToolError(f"no node type {type_id!r}"
                             + (f" — did you mean one of {close}?" if close else
                                " — use find_node_types"))
        return spec

    def _checked_params(self, spec, params: dict) -> dict:
        if not isinstance(params, dict):
            raise _ToolError("params must be an object of setting name -> value")
        valid = {p.name: p for p in spec.params if not p.hidden}
        out = {}
        for name, value in params.items():
            pspec = valid.get(name)
            if pspec is None:
                raise _ToolError(f"{spec.label} has no setting {name!r}; its "
                                 f"settings are {sorted(valid)}")
            out[name] = _coerce(pspec, value)
        return out

    def _place(self, near_id: Optional[str]) -> tuple[tuple[float, float], str]:
        if near_id is not None:
            near = self.graph.node(near_id)
            taken = {(round(n.pos[0]), round(n.pos[1]))
                     for n in self.graph.nodes.values()}
            x, y = near.pos[0] + _X_STEP, near.pos[1]
            while (round(x), round(y)) in taken:
                y += _Y_STEP
            return (x, y), near.canvas
        if not self.graph.nodes:
            return (0.0, 0.0), ""
        right = max(self.graph.nodes.values(), key=lambda n: n.pos[0])
        return (right.pos[0] + _X_STEP, right.pos[1]), right.canvas

    def _tool_add_node(self, type_id, label=None, params=None, near=None) -> dict:
        from ..ui.commands import AddNodeCommand, SetLabelCommand, SetParamCommand
        spec = self._type(type_id)
        checked = self._checked_params(spec, params or {})
        near_id = self._node(near).id if near else None
        pos, canvas = self._place(near_id)
        node = self.registry.instantiate(spec.type_id, pos)
        node.canvas = canvas
        self._push(AddNodeCommand(self.graph, node))
        for name, value in checked.items():
            self._push(SetParamCommand(self.graph, node.id, name, value, merge=False))
        if label:
            self._push(SetLabelCommand(self.graph, node.id, str(label)))
        handle = self.handle(node.id)
        self.actions.append(Action("add_node", f"Added {node.label}", [node.id]))
        return {"node": handle, "label": self.disclosure.scrub(node.label),
                "inputs": [p.name for p in spec.inputs if not p.spare],
                "outputs": [p.name for p in spec.outputs]}

    def _port(self, inst, port, direction: str) -> str:
        ports = [p.name for p in (inst.spec.outputs if direction == "out"
                                  else inst.spec.inputs) if not p.spare]
        if direction == "in":
            ports += [p.name for p in inst.spec.inputs if p.spare][:1]
        if port in (None, ""):
            real = [p for p in ports if not any(
                s.spare and s.name == p for s in inst.spec.inputs)]
            if len(real) == 1:
                return real[0]
            kind = "outputs" if direction == "out" else "inputs"
            raise _ToolError(f"{self.handle(inst.id)} has {kind} {real}; "
                             f"say which")
        if port not in ports:
            kind = "output" if direction == "out" else "input"
            raise _ToolError(f"{self.handle(inst.id)} has no {kind} {port!r}; "
                             f"it has {ports}")
        return port

    def _tool_connect(self, from_node, to_node, from_port=None, to_port=None) -> dict:
        from ..ui.commands import ConnectCommand
        src, dst = self._node(from_node), self._node(to_node)
        src_port = self._port(src, from_port, "out")
        dst_port = self._port(dst, to_port, "in")
        if self.graph.would_cycle(src.id, dst.id):
            raise _ToolError("that wire would make a loop — "
                             f"{self.handle(dst.id)} already feeds "
                             f"{self.handle(src.id)}")
        self._push(ConnectCommand(self.graph, src.id, src_port, dst.id, dst_port))
        self.actions.append(Action(
            "connect", f"Connected {src.label} → {dst.label}", [src.id, dst.id]))
        return {"connected": f"{self.handle(src.id)}.{src_port} -> "
                             f"{self.handle(dst.id)}.{dst_port}"}

    def _tool_disconnect(self, node, port) -> dict:
        from ..ui.commands import DisconnectCommand
        inst = self._node(node)
        conn = self.graph.input_connection(inst.id, str(port))
        if conn is None:
            raise _ToolError(f"nothing is wired into {self.handle(inst.id)}.{port}")
        self._push(DisconnectCommand(self.graph, conn.id))
        self.actions.append(Action("disconnect", f"Unwired {inst.label}.{port}",
                                   [inst.id]))
        return {"disconnected": f"{self.handle(inst.id)}.{port}"}

    def _tool_set_params(self, node, params) -> dict:
        from ..ui.commands import SetParamCommand
        inst = self._node(node)
        checked = self._checked_params(inst.spec, params)
        for name, value in checked.items():
            self._push(SetParamCommand(self.graph, inst.id, name, value, merge=False))
        self.actions.append(Action(
            "set_params", f"Changed {', '.join(checked)} on {inst.label}", [inst.id]))
        return {"node": self.handle(inst.id), "changed": sorted(checked)}

    def _tool_rename_node(self, node, label) -> dict:
        from ..ui.commands import SetLabelCommand
        inst = self._node(node)
        old = inst.label
        self._push(SetLabelCommand(self.graph, inst.id, str(label) or None))
        self.actions.append(Action("rename_node",
                                   f"Renamed {old} to {inst.label}", [inst.id]))
        return {"node": self.handle(inst.id),
                "label": self.disclosure.scrub(inst.label)}

    def _tool_delete_nodes(self, nodes) -> dict:
        from ..ui.commands import RemoveSelectionCommand
        if isinstance(nodes, str):
            nodes = [nodes]
        insts = [self._node(n) for n in nodes or []]
        if not insts:
            raise _ToolError("name at least one node to delete")
        labels = [n.label for n in insts]
        self._push(RemoveSelectionCommand(self.graph, [n.id for n in insts]))
        self.actions.append(Action("delete_nodes", f"Deleted {', '.join(labels)}"))
        return {"deleted": [self._by_id[n.id] for n in insts]}


class _ToolError(Exception):
    """A mistake the model can fix; the message says how."""


# The node most people mean by a word, where the label alone can't say it:
# no node is called "Bar Chart" — that is Show Plotly with kind = bar — and
# "join" scores AsOf Join and Fuzzy Join as high as Join itself. A short,
# deliberate list; test_flo checks every id still exists.
USUAL_NODE = {
    "chart": "flograph.viz.show_plotly", "plot": "flograph.viz.show_plotly",
    "graph": "flograph.viz.show_plotly", "visualise": "flograph.viz.show_plotly",
    "visualize": "flograph.viz.show_plotly",
    "join": "flograph.transform.join", "merge": "flograph.transform.join",
    "group": "flograph.transform.group_by",
    "aggregate": "flograph.transform.group_by",
    "summarise": "flograph.transform.group_by",
    "summarize": "flograph.transform.group_by",
    "filter": "flograph.transform.filter_rows",
    "table": "flograph.viz.show_table",
}

_STOP_WORDS = {"a", "an", "the", "of", "to", "for", "and", "or", "in", "on",
               "by", "with", "from", "node", "nodes", "make", "show", "me"}


def search_types(registry, query: str, limit: int = 12) -> list[dict]:
    """Node types for what a model *says* it wants, not what a palette user
    types. The palette's fuzzy label match finds nothing for "bar chart" —
    no node is called that; a bar chart is Show Plotly with kind = bar. So
    every word is looked for in the label, the type id, the category, the
    documentation and the settings' choices, and a choice that matches is
    returned as the setting to use."""
    words = [w for w in "".join(c if c.isalnum() else " "
                                for c in query.lower()).split()
             if w not in _STOP_WORDS]
    if not words:
        return []
    scored = []
    for spec in registry.all():
        if spec.broken:
            continue
        label, doc = spec.label.lower(), (spec.doc or "").lower()
        score, settings = 0.0, {}
        for word in words:
            hit = 0.0
            if word in label.split():
                hit += 5
            elif word in label:
                hit += 3
            if word in spec.type_id.lower():
                hit += 1
            if word in spec.category.lower():
                hit += 1
            # a choice naming the word: one per word, the first such setting
            # (Show Plotly has four "group" modes; that is not four matches)
            for param in spec.params:
                match = next((o for o in param.options
                              if str(o).lower() == word), None)
                if match is not None:
                    settings.setdefault(param.name, match)
                    hit += 4
                    break
            count = doc.count(word)
            hit += 1 if count else 0
            hit += 1 if count >= 3 else 0
            score += hit
        if any(USUAL_NODE.get(w) == spec.type_id for w in words):
            score += 8
        # all the words is worth more than one word many times over
        if all(w in label or w in doc for w in words):
            score += 2
        # a general node beats a special-purpose one with a longer name
        score -= len(label) * 0.15
        if score:
            scored.append((score, spec, settings))
    scored.sort(key=lambda item: (-item[0], item[1].label))
    out = []
    for _score, spec, settings in scored[:limit]:
        entry = {"type_id": spec.type_id, "label": spec.label,
                 "category": spec.category}
        if spec.doc:
            entry["about"] = _first_line(spec.doc)
        if settings:
            entry["set"] = settings
        out.append(entry)
    return out


def _first_line(doc: str) -> str:
    for line in (doc or "").strip().splitlines():
        if line.strip():
            return line.strip()[:160]
    return ""


def _coerce(pspec, value):
    """A model's value as the param's type, or a _ToolError saying why not."""
    ptype = pspec.type
    try:
        if ptype == "int" and not isinstance(value, bool):
            return int(value)
        if ptype == "float" and not isinstance(value, bool):
            return float(value)
    except (TypeError, ValueError):
        raise _ToolError(f"{pspec.name!r} wants a {ptype}, not {value!r}") from None
    if ptype == "bool":
        if isinstance(value, str):
            return value.strip().lower() in ("true", "yes", "1", "on")
        return bool(value)
    if ptype == "choice" and pspec.options and value not in pspec.options:
        raise _ToolError(f"{pspec.name!r} must be one of {pspec.options}, "
                         f"not {value!r}")
    if ptype == "columns" and isinstance(value, list):
        return ", ".join(str(v) for v in value) if pspec.multi else \
            (str(value[0]) if value else "")
    return value
