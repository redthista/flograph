"""Bypass: a node that is skipped but still passes its inputs on.

A bypassed node keeps its wires, params and place in the flow, and its script
does not run. Each of its outputs is handed one of its inputs instead, so the
nodes below it run as if it were not there — the thing Deactivate (which takes
the whole branch out) and Freeze (which serves the last result) cannot say.

Which input feeds which output is decided here, once, for the engine and the
canvas both — the engine to build the outputs, the canvas to draw the line
through the node that says where the data goes. In order:

1. the script's own answer, `NODE["bypass"] = {"output": "input", ...}`
   (`NODE["bypass"] = False` says the node cannot be bypassed at all);
2. an input with the same name — `table` in, `table` out;
3. the first input of the same port type, or of any type for an `any` output.

An output none of those reach gets None. That is deliberate: a node below it
that needs a value fails, loudly, rather than being quietly skipped — a
bypass that silently took half a branch with it would be the worse surprise.
"""
from __future__ import annotations

from typing import Optional

from .node import NodeInstance, NodeSpec
from .ports import PortType


def passthrough(spec: NodeSpec) -> dict[str, Optional[str]]:
    """`{output name: input name or None}` for every output of `spec`."""
    declared = spec.bypass if isinstance(spec.bypass, dict) else {}
    inputs = [p for p in spec.inputs if not p.spare]
    mapping: dict[str, Optional[str]] = {}
    for out in spec.outputs:
        if out.name in declared:
            mapping[out.name] = declared[out.name]
            continue
        same_name = next((p for p in inputs if p.name == out.name), None)
        if same_name is not None:
            mapping[out.name] = same_name.name
            continue
        same_type = next(
            (p for p in inputs
             if out.type == PortType.ANY or p.type == out.type), None)
        mapping[out.name] = same_type.name if same_type is not None else None
    return mapping


def can_bypass(spec: NodeSpec) -> bool:
    """Whether bypassing this node could hand anything on at all.

    False for a script that says so, for a node with no inputs (a source has
    nothing to pass — Deactivate is the switch for that), and for one whose
    outputs no input can feed. The menu greys Bypass out on these rather than
    offering a switch that would only empty every output.
    """
    if spec.bypass is False or not spec.inputs or spec.broken:
        return False
    return any(src is not None for src in passthrough(spec).values())


def bypass_outputs(node: NodeInstance, inputs: dict) -> dict:
    """The outputs a bypassed node produces from the input values it was
    given (`inputs` keyed by input port name, None for an unwired port)."""
    return {out: (inputs.get(src) if src is not None else None)
            for out, src in passthrough(node.spec).items()}
