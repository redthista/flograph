"""How an input control's change is written — straight into the flow, or
held as a draft until Apply. The rules are `core.control_apply`; this is
the undo-stack half, shared by the canvas card, the dashboard tile, the
node menu and an Action Button set to Apply inputs, so none of them can
drift on what a press means.

Every function returns True when the flow's value changed — the caller's
cue to re-run the control and what it feeds — and False when the change
was held, or there was nothing to do.
"""
from __future__ import annotations

from flograph.core import control_apply as ca


def _set(graph, node_id: str, name: str, value):
    from .commands import SetParamCommand
    # merge=False: one Ctrl+Z undoes one adjustment, not the session
    return SetParamCommand(graph, node_id, name, value, merge=False)


def commit_value(graph, stack, node_id: str, value) -> bool:
    """The user moved the control to `value`. Live: it goes into `value`.
    Held: it goes into `draft` — or the draft is dropped, when the control
    was moved back to the value the flow already has."""
    node = graph.nodes.get(node_id)
    if node is None:
        return False
    if not ca.is_held(node):
        if value != node.params.get("value"):
            stack.push(_set(graph, node_id, "value", value))
        # True even when unchanged: the window's re-run is what a control
        # has always asked for here, and request_run on a clean subgraph
        # costs nothing
        return True
    if value == node.params.get("value"):
        if ca.has_draft(node):
            stack.push(_set(graph, node_id, "draft", ""))
        return False
    encoded = ca.encode(value)
    if encoded != ca.draft_text(node.params):
        stack.push(_set(graph, node_id, "draft", encoded))
    return False


def _apply_commands(graph, node_id: str) -> list:
    node = graph.nodes.get(node_id)
    ok, value = ca.decode(ca.draft_text(node.params)) if node else (False, None)
    if node is None or not ca.has_draft(node):
        return []
    commands = []
    if ok and value != node.params.get("value"):
        commands.append(_set(graph, node_id, "value", value))
    commands.append(_set(graph, node_id, "draft", ""))
    return commands


def apply(graph, stack, node_id: str) -> bool:
    """Move this control's draft into the flow, as one undo step."""
    return bool(apply_many(graph, stack, [node_id]))


def apply_many(graph, stack, ids) -> list[str]:
    """Apply every held change among `ids` as one undo step. Returns the
    ids whose flow value changed, for the caller to re-run in one go.

    Every command is built before the macro opens: a QUndoCommand raising
    inside beginMacro leaves the stack half-pushed and undo dead (see the
    paste-wires fix), so nothing that can fail happens inside it.
    """
    plan = [(i, _apply_commands(graph, i)) for i in ca.held_controls(graph, ids)]
    plan = [(i, cmds) for i, cmds in plan if cmds]
    if not plan:
        return []
    # beginMacro rather than a parent command holding children — a Python
    # child built with a parent has no Python owner (binding.submit says why)
    label = (f"apply {graph.nodes[plan[0][0]].label}" if len(plan) == 1
             else f"apply {len(plan)} inputs")
    stack.beginMacro(label)
    try:
        for _node_id, commands in plan:
            for command in commands:
                stack.push(command)
    finally:
        stack.endMacro()
    return [i for i, cmds in plan if len(cmds) > 1]


def discard(graph, stack, node_id: str) -> bool:
    """Throw this control's held change away; it shows the applied value
    again. Never changes the flow, so always False."""
    node = graph.nodes.get(node_id)
    if not ca.has_draft(node):
        return False
    command = _set(graph, node_id, "draft", "")
    command.setText(f"discard {node.label} change")
    stack.push(command)
    return False


def reset(graph, stack, node_id: str) -> bool:
    """Put the control back to its script's default. A user edit like any
    other, so a held control holds the reset too until it is applied."""
    node = graph.nodes.get(node_id)
    if node is None:
        return False
    return commit_value(graph, stack, node_id, ca.default_value(node))


def reset_many(graph, stack, ids) -> list[str]:
    """Reset every control among `ids`, as one undo step. Returns the ids
    whose flow value changed (live controls), for one re-run."""
    targets = [i for i in ids if i in graph.nodes
               and graph.nodes[i].spec.card == "control"
               and ca.shown_value(graph.nodes[i])
               != ca.default_value(graph.nodes[i])]
    if not targets:
        return []
    changed = []
    stack.beginMacro(f"reset {len(targets)} inputs" if len(targets) > 1
                     else f"reset {graph.nodes[targets[0]].label}")
    try:
        for node_id in targets:
            live = not ca.is_held(graph.nodes[node_id])
            if reset(graph, stack, node_id) and live:
                changed.append(node_id)
    finally:
        stack.endMacro()
    return changed
