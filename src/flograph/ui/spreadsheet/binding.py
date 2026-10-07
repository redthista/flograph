"""How a Table node's grid commits what is typed into it — live, or held
until Submit.

Live (the default, and how every Table before this worked): each edit is
written to the node's ``data`` param, one undo step apiece, and so marks the
node and everything after it out of date the moment it lands.

Held (``apply = "submit"``): edits collect in the hidden ``draft`` param
instead. ``draft`` is cosmetic, so writing it marks nothing out of date and
starts no run — the flow keeps using the table as last submitted, however
many cells are typed. Submit moves the draft into ``data`` as one undo step
and asks for a run; Discard throws it away. Keeping the draft in a param
rather than in a widget is what makes the rest come free: every edit is
still undoable from the app's own stack, a save keeps work not yet
submitted, and the canvas card and a dashboard tile of the same node always
show the same draft, because both draw from the node.

Everything here is a plain function of (graph, undo stack, node id), so the
card, the tile and the pop-out editor share one set of rules.
"""
from __future__ import annotations

import json
from typing import Optional

LIVE = "live"
SUBMIT = "submit"


def apply_mode(node) -> str:
    return SUBMIT if (node is not None
                      and node.params.get("apply") == SUBMIT) else LIVE


def draft_of(node) -> str:
    return str(node.params.get("draft") or "") if node is not None else ""


def has_draft(node) -> bool:
    return bool(draft_of(node))


def shown_sheet(graph, cache, node_id: str):
    """What a grid of this node should show: the draft when there is one,
    else a linked table's merge with its input, else the stored cells."""
    node = graph.nodes.get(node_id)
    if node is None:
        return None
    draft = draft_of(node)
    if draft:
        return draft
    if cache is not None:
        from flograph.engine.introspect import merged_linked_sheet
        merged = merged_linked_sheet(graph, cache, node_id)
        if merged is not None:
            return merged
    return node.params.get("data")


def pending_changes(node) -> Optional[int]:
    """How many cells the draft changes, for the "3 changes not submitted"
    line; 0 when the draft changes the shape (rows, columns, a type) rather
    than cells alone, and None when there is no draft."""
    draft = draft_of(node)
    if not draft:
        return None
    from flograph.core.sheet import parse_sheet
    new = parse_sheet(draft)
    old = parse_sheet(node.params.get("data"))
    if (new.n_rows != old.n_rows or new.n_cols != old.n_cols
            or [(c.name, c.type) for c in new.columns]
            != [(c.name, c.type) for c in old.columns]):
        return 0
    return sum(1 for a, b in zip(new.rows, old.rows)
               for x, y in zip(a, b) if x != y)


def describe_pending(node) -> str:
    count = pending_changes(node)
    if count is None:
        return ""
    if count == 0:
        return "Table changed — not submitted"
    return f"{count} change{'s' if count != 1 else ''} not submitted"


def _same_sheet(a, b) -> bool:
    """Do two sheet JSONs (or dicts) hold the same table? Compared parsed:
    the same table can be spelled with its keys in another order."""
    if not a or not b:
        return not a and not b
    from flograph.core.sheet import parse_sheet, sheet_to_dict
    return sheet_to_dict(parse_sheet(a)) == sheet_to_dict(parse_sheet(b))


def _set(graph, node_id: str, name: str, value):
    from ..commands import SetParamCommand
    return SetParamCommand(graph, node_id, name, value, merge=False)


def commit_edit(graph, stack, node_id: str, data: dict) -> bool:
    """Commit one edit from a grid. True when it reached the flow's data
    (live mode) — the caller's cue to re-run if it re-runs on edits; False
    when it was held in the draft, or changed nothing."""
    node = graph.nodes.get(node_id)
    if node is None:
        return False
    new_json = json.dumps(data)
    if apply_mode(node) == SUBMIT:
        if new_json == draft_of(node):
            return False
        if _same_sheet(data, node.params.get("data")):
            # typed back to what was submitted: nothing is pending any more
            if has_draft(node):
                stack.push(_set(graph, node_id, "draft", ""))
            return False
        stack.push(_set(graph, node_id, "draft", new_json))
        return False
    if new_json == node.params.get("data"):
        return False
    stack.push(_set(graph, node_id, "data", new_json))
    return True


def submit(graph, stack, node_id: str) -> bool:
    """Move the draft into the flow's data, as one undo step. True when
    there was something to submit."""
    node = graph.nodes.get(node_id)
    draft = draft_of(node)
    if not draft:
        return False
    # beginMacro, not a parent QUndoCommand holding children: a Python
    # child command built with a parent has no Python owner, its wrapper is
    # collected, and Qt then calls redo() on a dead object (a segfault)
    stack.beginMacro(f"submit {node.label} edits")
    try:
        if draft != node.params.get("data"):
            stack.push(_set(graph, node_id, "data", draft))
        stack.push(_set(graph, node_id, "draft", ""))
    finally:
        stack.endMacro()
    return True


def discard(graph, stack, node_id: str) -> bool:
    node = graph.nodes.get(node_id)
    if not has_draft(node):
        return False
    discard_cmd = _set(graph, node_id, "draft", "")
    discard_cmd.setText(f"discard {node.label} edits")
    stack.push(discard_cmd)
    return True


def set_mode(graph, stack, node_id: str, mode: str) -> bool:
    """Switch between live and held. Going live with a draft pending submits
    it — "apply each edit as it is made" has nothing to wait for. True when
    that put new data into the flow."""
    node = graph.nodes.get(node_id)
    if node is None or mode not in (LIVE, SUBMIT) or apply_mode(node) == mode:
        return False
    draft = draft_of(node)
    changed = False
    stack.beginMacro("apply table edits live" if mode == LIVE
                     else "hold table edits until Submit")
    try:
        if mode == LIVE and draft:
            if draft != node.params.get("data"):
                stack.push(_set(graph, node_id, "data", draft))
                changed = True
            stack.push(_set(graph, node_id, "draft", ""))
        stack.push(_set(graph, node_id, "apply", mode))
    finally:
        stack.endMacro()
    return changed


class SheetHost:
    """What a ribbon asks of whoever owns the grid. The card and the tile
    each hand it one of these; the defaults describe a grid with no node
    behind it (a test, a bare editor), where everything applies at once."""

    def can_hold(self) -> bool:
        """Can edits be held until Submit here? Only with a node behind."""
        return False

    def mode(self) -> str:
        return LIVE

    def pending_text(self) -> str:
        return ""

    def submit(self) -> None:
        pass

    def discard(self) -> None:
        pass

    def set_mode(self, mode: str) -> None:
        pass

    def linked(self) -> bool:
        return False

    def undo_stack(self):
        """The stack Undo/Redo on the ribbon drive, or None to leave the
        buttons off (the app's own Ctrl+Z still works)."""
        return None

    def can_open_editor(self) -> bool:
        return False

    def rules(self) -> str:
        """The conditional-formatting rules text, or "" (none)."""
        return ""

    def can_format(self) -> bool:
        return False

    def set_rules(self, text: str) -> None:
        pass

    def open_editor(self) -> None:
        pass


class NodeSheetHost(SheetHost):
    """A SheetHost over a Table node in a graph. ``on_submitted`` is how the
    owner re-runs what follows once new data is in; ``open_editor_fn``
    opens the full-window editor (the card has one, a dialog does not).
    ``graph`` may be a callable returning the graph: a canvas card builds
    its grid before it has a scene to find the graph through."""

    def __init__(self, graph, stack_fn, node_id: str, on_submitted=None,
                 linked_fn=None, open_editor_fn=None) -> None:
        self._graph_ref = graph
        self._stack_fn = stack_fn
        self._node_id = node_id
        self._on_submitted = on_submitted
        self._linked_fn = linked_fn
        self._open_editor_fn = open_editor_fn

    @property
    def _graph(self):
        ref = self._graph_ref
        return ref() if callable(ref) else ref

    def _node(self):
        graph = self._graph
        return graph.nodes.get(self._node_id) if graph is not None else None

    def can_hold(self) -> bool:
        node = self._node()
        return node is not None and node.spec.param("apply") is not None

    def mode(self) -> str:
        return apply_mode(self._node())

    def pending_text(self) -> str:
        return describe_pending(self._node())

    def submit(self) -> None:
        stack = self._stack_fn()
        if (stack is not None and self._graph is not None
                and submit(self._graph, stack, self._node_id)):
            if self._on_submitted is not None:
                self._on_submitted()

    def discard(self) -> None:
        stack = self._stack_fn()
        if stack is not None and self._graph is not None:
            discard(self._graph, stack, self._node_id)

    def set_mode(self, mode: str) -> None:
        stack = self._stack_fn()
        if (stack is not None and self._graph is not None
                and set_mode(self._graph, stack, self._node_id, mode)):
            if self._on_submitted is not None:
                self._on_submitted()

    def linked(self) -> bool:
        return bool(self._linked_fn and self._linked_fn())

    def undo_stack(self):
        return self._stack_fn()

    def can_open_editor(self) -> bool:
        return self._open_editor_fn is not None

    def rules(self) -> str:
        node = self._node()
        return str(node.params.get("rules") or "") if node is not None else ""

    def can_format(self) -> bool:
        node = self._node()
        return node is not None and node.spec.param("rules") is not None

    def set_rules(self, text: str) -> None:
        """Write the rules as one undo step. Cosmetic: nothing re-runs."""
        stack = self._stack_fn()
        node = self._node()
        if stack is None or node is None or text == self.rules():
            return
        command = _set(self._graph, self._node_id, "rules", text)
        command.setText("conditional formatting")
        stack.push(command)

    def open_editor(self) -> None:
        if self._open_editor_fn is not None:
            self._open_editor_fn()
