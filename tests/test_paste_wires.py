"""Copy and paste keeps every wire, and leaves the copies selected.

A node that had grown ports (a wire dropped on Concatenate's spare makes a
permanent `in3`) pasted as the bare script: the clipboard never carried the
grown ports, so the wire to `in3` named a port the copy did not have. That
ConnectCommand raised out of the paste halfway through — every wire after it
was lost, and the selection was never moved off the originals.
"""
import pytest

from flograph.core import NodeRegistry

CONCAT = "flograph.transform.concatenate"
SCRIPT = "flograph.scripting.python_script"


@pytest.fixture(scope="module")
def registry():
    reg = NodeRegistry()
    reg.load_builtins()
    return reg


@pytest.fixture
def window(qtbot, registry):
    from flograph.ui.mainwindow import MainWindow
    win = MainWindow(registry)
    win.confirm_close = False
    qtbot.addWidget(win)
    yield win
    win.undo_stack.clear()


def _add(window, registry, type_id, node_id, pos):
    node = registry.instantiate(type_id, pos=pos)
    node.id = node_id
    window.graph.add_node(node)
    return node


def _three_into_concat(window, registry):
    graph = window.graph
    for i, nid in enumerate(("a", "b", "c")):
        _add(window, registry, SCRIPT, nid, (0.0, 120.0 * i))
    _add(window, registry, CONCAT, "cat", (300.0, 100.0))
    graph.connect("a", "out1", "cat", "top")
    graph.connect("b", "out1", "cat", "bottom")
    graph.connect("c", "out1", "cat", "more")      # grows in3
    assert "in3" in {p.name for p in graph.nodes["cat"].spec.inputs}
    window.scene.clearSelection()
    for item in window.scene.node_items.values():
        item.setSelected(True)
    return graph


def _paste(window):
    before = set(window.graph.nodes)
    window._insert_payload(window._selection_payload())
    return {n for n in window.graph.nodes if n not in before}


def test_grown_ports_travel_with_the_copy(window, registry):
    graph = _three_into_concat(window, registry)
    new = _paste(window)
    copy = next(graph.nodes[n] for n in new if graph.nodes[n].type_id == CONCAT)
    assert [p.name for p in copy.extra_inputs] == ["in3"]
    wired = {c.dst_port for c in graph.connections.values()
             if c.dst_node == copy.id}
    assert wired == {"top", "bottom", "in3"}


def test_the_copies_are_selected_not_the_originals(window, registry):
    _three_into_concat(window, registry)
    new = _paste(window)
    selected = {i.node.id for i in window.scene.selected_node_items()}
    assert selected == new


def test_a_wire_that_cannot_be_made_is_skipped_not_fatal(window, registry):
    """Whatever the reason a copied wire no longer fits, the rest of the
    paste still lands: the other wires, and the selection on the copies."""
    _three_into_concat(window, registry)
    payload = window._selection_payload()
    payload["connections"].insert(0, {"src": ["a", "out1"],
                                      "dst": ["cat", "no_such_port"]})
    before = set(window.graph.nodes)
    window._insert_payload(payload)
    new = {n for n in window.graph.nodes if n not in before}
    new_wires = [c for c in window.graph.connections.values()
                 if c.dst_node in new]
    assert len(new_wires) == 3
    assert {i.node.id for i in window.scene.selected_node_items()} == new
    # the macro was closed, so one undo takes the whole paste back
    window.undo_stack.undo()
    assert set(window.graph.nodes) == before


def test_undo_works_after_the_paste(window, registry):
    """The other half of the original report: after the failed paste Undo
    was greyed out, because the paste's macro was never closed."""
    _three_into_concat(window, registry)
    before = set(window.graph.nodes)
    wires_before = set(window.graph.connections)
    _paste(window)
    assert window.undo_stack.canUndo()
    window.undo_stack.undo()
    assert set(window.graph.nodes) == before
    assert set(window.graph.connections) == wires_before
    window.undo_stack.redo()
    assert len(window.graph.nodes) == 2 * len(before)


def test_an_older_clipboard_without_grown_ports_still_wires_up(window,
                                                               registry):
    """Copied by a version that didn't carry extra_inputs: the wire to
    `in3` is regrown by connect() rather than dropped by the paste."""
    _three_into_concat(window, registry)
    payload = window._selection_payload()
    for entry in payload["nodes"]:
        entry.pop("extra_inputs", None)
    before = set(window.graph.nodes)
    window._insert_payload(payload)
    new = set(window.graph.nodes) - before
    wired = {c.dst_port for c in window.graph.connections.values()
             if c.dst_node in new}
    assert wired == {"top", "bottom", "in3"}
    assert window.undo_stack.canUndo()


def test_look_settings_travel_with_the_copy(window, registry):
    node = _add(window, registry, SCRIPT, "a", (0.0, 0.0))
    node.canvas_preview_enabled = False
    node.ports_collapsed = True
    node.compact_view = True
    node.mark_text = "Hi"
    node.exclusive_override = True
    window.scene.clearSelection()
    window.scene.node_items["a"].setSelected(True)
    (new_id,) = _paste(window)
    copy = window.graph.nodes[new_id]
    assert copy.canvas_preview_enabled is False
    assert copy.ports_collapsed is True
    assert copy.compact_view is True
    assert copy.mark_text == "Hi"
    assert copy.exclusive_override is True
