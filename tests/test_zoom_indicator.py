"""Canvas zoom: the view's set_zoom/zoom_changed API behind the status-bar
zoom indicator."""
import pytest
from PySide6.QtGui import QUndoStack

from flograph.core import Graph, NodeRegistry
from flograph.ui.canvas import NodeGraphScene
from flograph.ui.canvas.view import NodeGraphView


@pytest.fixture(scope="module")
def registry():
    reg = NodeRegistry()
    reg.load_builtins()
    return reg


@pytest.fixture
def view(qtbot, registry):
    graph = Graph()
    scene = NodeGraphScene(graph, QUndoStack(), registry=registry)
    view = NodeGraphView(scene)
    qtbot.addWidget(view)
    return view


def test_set_zoom_emits_and_applies(view, qtbot):
    seen = []
    view.zoom_changed.connect(seen.append)
    view.set_zoom(2.0)
    assert view.zoom == pytest.approx(2.0)
    assert seen and seen[-1] == pytest.approx(2.0)


def test_set_zoom_clamps_to_range(view):
    view.set_zoom(99.0)
    assert view.zoom == pytest.approx(4.0)   # ZOOM_MAX
    view.set_zoom(0.0001)
    assert view.zoom == pytest.approx(0.1)   # ZOOM_MIN


def test_reset_to_hundred_percent(view):
    view.set_zoom(0.5)
    view.set_zoom(1.0)   # what the status-bar indicator click does
    assert view.zoom == pytest.approx(1.0)


def test_same_zoom_is_a_no_op(view):
    seen = []
    view.zoom_changed.connect(seen.append)
    view.set_zoom(view.zoom)
    assert not seen
