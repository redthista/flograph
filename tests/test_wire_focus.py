"""Selecting a node brings its wires forward and lets the rest step back;
with nothing selected every wire is drawn the same quiet way (#118)."""
import pytest
from PySide6.QtGui import QUndoStack

from flograph.core import Graph, NodeRegistry
from flograph.ui.canvas.connection_item import wire_focus
from flograph.ui.canvas.scene import NodeGraphScene


@pytest.fixture(scope="module")
def registry():
    reg = NodeRegistry()
    reg.load_builtins()
    return reg


@pytest.fixture
def chain(qtbot, registry):
    graph = Graph()
    scene = NodeGraphScene(graph, QUndoStack(), registry=registry)
    a, b, c, d, e = (graph.add_node(registry.instantiate("flograph.io.table"))
                     for _ in range(5))
    ab = graph.connect(a.id, "table", b.id, "table")[0]
    bc = graph.connect(b.id, "table", c.id, "table")[0]
    de = graph.connect(d.id, "table", e.id, "table")[0]
    return scene, (a, b, c, d, e), (ab, bc, de)


def test_nothing_selected_means_no_focus(chain):
    scene, _nodes, wires = chain
    assert scene.focus_nodes == frozenset()
    assert all(wire_focus(scene, w) is None for w in wires)


def test_a_selected_node_brings_its_own_wires_forward(chain):
    scene, (a, b, c, d, e), (ab, bc, de) = chain
    scene.node_items[b.id].setSelected(True)
    assert scene.focus_nodes == {b.id}
    assert wire_focus(scene, ab) and wire_focus(scene, bc)
    assert wire_focus(scene, de) is False
    scene.clearSelection()
    assert scene.focus_nodes == frozenset()
    assert wire_focus(scene, de) is None


def test_only_a_change_of_selected_nodes_repaints(chain, monkeypatch):
    scene, (a, b, *_), _wires = chain
    calls = []
    monkeypatch.setattr(scene, "update", lambda *args: calls.append(1))
    scene.node_items[a.id].setSelected(True)
    assert len(calls) == 1
    scene._focus_wires()                   # same nodes selected: no repaint
    assert len(calls) == 1
