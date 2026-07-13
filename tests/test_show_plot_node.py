"""The Show Plot card: Plot and Show Figure combined into a single on-canvas
node — a dataframe wire in, a rendered figure preview out."""
import pandas as pd
import pytest
from PySide6.QtGui import QUndoStack

from flograph.core import Graph, NodeRegistry, PortType, can_connect
from flograph.ui.canvas import NodeGraphScene
from flograph.ui.mainwindow import MainWindow


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
    spec = registry.get("flograph.viz.show_plot")
    assert [p.name for p in spec.inputs] == ["table"]
    assert [p.name for p in spec.outputs] == ["figure"]
    assert spec.inputs[0].type == PortType.DATAFRAME
    assert spec.outputs[0].type == PortType.FIGURE
    assert can_connect(PortType.DATAFRAME, spec.inputs[0].type)
    for name in ("kind", "x", "y", "title", "width", "height", "scale"):
        assert spec.param(name) is not None


def test_show_plot_item_is_a_figure_card_with_placeholder(env, registry):
    graph, stack, scene = env
    node = graph.add_node(registry.instantiate("flograph.viz.show_plot"))
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
    node = graph.add_node(registry.instantiate("flograph.viz.show_plot"))
    item = scene.node_items[node.id]
    graph.set_param(node.id, "width", 600)
    graph.set_param(node.id, "height", 400)
    assert item.width == 600.0
    assert item.body_height == 400.0
    graph.set_param(node.id, "width", 10)  # clamped to minimum
    assert item.width == 260.0


def test_show_plot_scale_param_zooms_the_embedded_figure(env, registry):
    graph, stack, scene = env
    node = graph.add_node(registry.instantiate("flograph.viz.show_plot"))
    item = scene.node_items[node.id]
    proxy = item._figure_proxy
    assert proxy.scale() == 1.0

    graph.set_param(node.id, "scale", 150)
    rect = item._figure_proxy_rect()
    assert proxy.scale() == 1.5
    assert proxy.size().width() == pytest.approx(rect.width() / 1.5)
    assert proxy.size().height() == pytest.approx(rect.height() / 1.5)

    graph.set_param(node.id, "scale", 9999)  # clamped to 400%
    assert proxy.scale() == 4.0


def test_figure_view_renders_at_the_requested_ratio(qtbot):
    """Card scale, view zoom and screen DPR all magnify the figure through
    transforms the canvas can't see; it must render its buffer at the
    matching device pixel ratio or the magnified raster goes soft."""
    from matplotlib.figure import Figure

    from flograph.ui.inspector.figure_view import FigureView

    view = FigureView()
    qtbot.addWidget(view)
    figure = Figure()
    figure.add_subplot().plot([1, 2, 3], [2, 4, 9])

    view.set_render_ratio(2.0)
    view.set_figure(figure)
    assert view._canvas.device_pixel_ratio == 2.0

    # re-targeting with a figure already shown re-renders the same canvas
    canvas = view._canvas
    view.set_render_ratio(3.0)
    assert view._canvas is canvas
    assert canvas.device_pixel_ratio == 3.0
    assert canvas.figure is figure


def test_scale_param_bumps_the_embedded_canvas_resolution(env, registry):
    from matplotlib.figure import Figure

    graph, stack, scene = env
    node = graph.add_node(registry.instantiate("flograph.viz.show_plot"))
    item = scene.node_items[node.id]
    graph.set_param(node.id, "scale", 200)

    figure = Figure()
    figure.add_subplot().plot([1, 2], [3, 4])
    item.set_figure(figure)
    assert item._figure_view._canvas.device_pixel_ratio == 2.0


def test_view_zoom_compounds_into_the_render_ratio(qtbot, env, registry):
    """Zooming the node canvas into a figure card must re-render the figure
    at the zoomed resolution (debounced via the view's settle timer)."""
    from flograph.ui.canvas.view import NodeGraphView

    graph, stack, scene = env
    node = graph.add_node(registry.instantiate("flograph.viz.show_plot"))
    item = scene.node_items[node.id]
    view = NodeGraphView(scene)
    qtbot.addWidget(view)

    view.scale(2.0, 2.0)
    scene.refresh_render_ratios()  # what the settle timer fires
    # offscreen DPR is 1, so ratio = zoom 2 x card scale 1
    assert item._figure_view._render_ratio == 2.0

    graph.set_param(node.id, "scale", 200)
    assert item._figure_view._render_ratio == 4.0

    view.scale(10.0, 10.0)  # zoom clamps: never render beyond 8x
    scene.refresh_render_ratios()
    assert item._figure_view._render_ratio == 8.0


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

    from flograph.ui.inspector.figure_view import FigureView

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
    show = win.registry.instantiate("flograph.viz.show_plot", pos=(300, 0))
    table = win.registry.instantiate("flograph.io.table", pos=(-300, 0))
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
