"""The Show Plot card: Plot and Show Figure combined into a single on-canvas
node — a dataframe wire in, a rendered figure preview out."""
import pandas as pd
import pytest
from PySide6.QtGui import QUndoStack

from flopy.core import Graph, NodeRegistry, PortType, can_connect
from flopy.ui.canvas import NodeGraphScene
from flopy.ui.mainwindow import MainWindow


@pytest.fixture(scope="module")
def registry():
    reg = NodeRegistry()
    reg.load_builtins()
    return reg


@pytest.fixture
def env(qtbot, registry):
    graph = Graph()
    stack = QUndoStack()
    scene = NodeGraphScene(graph, stack, registry=registry)
    return graph, stack, scene


def test_show_plot_is_registered_with_a_dataframe_in_figure_out(registry):
    spec = registry.get("flopy.viz.show_plot")
    assert [p.name for p in spec.inputs] == ["table"]
    assert [p.name for p in spec.outputs] == ["figure"]
    assert spec.inputs[0].type == PortType.DATAFRAME
    assert spec.outputs[0].type == PortType.FIGURE
    assert can_connect(PortType.DATAFRAME, spec.inputs[0].type)
    for name in ("kind", "x", "y", "title", "width", "height"):
        assert spec.param(name) is not None


def test_show_plot_item_is_a_figure_card_with_placeholder(env, registry):
    graph, stack, scene = env
    node = graph.add_node(registry.instantiate("flopy.viz.show_plot"))
    item = scene.node_items[node.id]
    assert item.figure_card
    assert item._figure_view is not None
    assert item._figure_placeholder is not None
    assert item._figure_placeholder.isVisible()
    assert item._figure_view.isHidden()
    assert list(item.input_ports) == ["table"]
    assert list(item.output_ports) == ["figure"]


def test_show_plot_resize_updates_width_and_height(env, registry):
    graph, stack, scene = env
    node = graph.add_node(registry.instantiate("flopy.viz.show_plot"))
    item = scene.node_items[node.id]
    graph.set_param(node.id, "width", 600)
    graph.set_param(node.id, "height", 400)
    assert item.width == 600.0
    assert item.body_height == 400.0
    graph.set_param(node.id, "width", 10)  # clamped to minimum
    assert item.width == 260.0


@pytest.fixture
def window(qtbot, registry):
    win = MainWindow(registry)
    win.confirm_close = False
    qtbot.addWidget(win)
    return win


def test_set_figure_draws_synchronously(qtbot, monkeypatch):
    """Embedded in a QGraphicsProxyWidget the canvas never gets a real
    expose event, so set_figure must draw immediately — without it the card
    shows a blank/garbage buffer until a resize forces a redraw."""
    from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
    from matplotlib.figure import Figure

    from flopy.ui.inspector.figure_view import FigureView

    draws = []
    original = FigureCanvasQTAgg.draw
    monkeypatch.setattr(
        FigureCanvasQTAgg, "draw",
        lambda self, *a, **k: (draws.append(1), original(self, *a, **k))[1])
    view = FigureView()
    qtbot.addWidget(view)
    figure = Figure()
    figure.add_subplot().plot([1, 2, 3], [2, 4, 9])
    view.set_figure(figure)
    assert draws, "set_figure must draw the canvas synchronously"


def test_running_the_graph_draws_and_pushes_the_plot_onto_the_canvas_card(
        qtbot, window):
    import json

    win = window
    show = win.registry.instantiate("flopy.viz.show_plot", pos=(300, 0))
    table = win.registry.instantiate("flopy.io.table", pos=(-300, 0))
    win.graph.add_node(table)
    win.graph.add_node(show)
    win.graph.set_param(table.id, "data", json.dumps({
        "columns": ["x", "y"], "rows": [["1", "2"], ["2", "4"], ["3", "9"]],
    }))
    win.graph.connect(table.id, "table", show.id, "table")

    item = win.scene.node_items[show.id]
    assert item._figure_placeholder.isVisible()

    with qtbot.waitSignal(win.engine.run_finished, timeout=20000) as blocker:
        win.engine.run_all()

    assert blocker.args[0], "run finished with a node failure"
    assert item._figure_view.isVisible()
    assert item._figure_placeholder.isHidden()
