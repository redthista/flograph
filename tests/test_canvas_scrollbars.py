"""Show scroll bars on the canvas (asked for in place of the right-button
pan): a setting that turns the hidden horizontal and vertical bars into
visible, draggable ones — a where-am-I for large flows. Panning itself was
never scrollbar-driven, so this changes nothing but their visibility. The
bars map the whole scrollable span onto their length, so the span is
fitted to the flow (plus a margin) rather than world-sized — otherwise one
pixel of bar is thousands of canvas pixels and the smallest drag sends
everything past like a bullet."""
import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QUndoStack

from flograph.core import Graph
from flograph.ui.canvas import NodeGraphScene, NodeGraphView
from flograph.ui.canvas.scene import SCENE_MARGIN
from flograph.ui.dashboard.dashboard_view import DashboardView

JOIN = "flograph.transform.join"


@pytest.fixture
def view(qtbot, registry):
    scene = NodeGraphScene(Graph(), QUndoStack(), registry=registry)
    v = NodeGraphView(scene)
    v.resize(600, 400)
    qtbot.addWidget(v)
    return v


class TestCanvasScrollbars:
    def test_hidden_by_default(self, view):
        assert view.horizontalScrollBarPolicy() == Qt.ScrollBarAlwaysOff
        assert view.verticalScrollBarPolicy() == Qt.ScrollBarAlwaysOff

    def test_the_setting_shows_both_axes(self, view):
        view.set_scrollbars_enabled(True)
        assert view.horizontalScrollBarPolicy() == Qt.ScrollBarAsNeeded
        assert view.verticalScrollBarPolicy() == Qt.ScrollBarAsNeeded

    def test_turning_it_back_off_hides_them_again(self, view):
        view.set_scrollbars_enabled(True)
        view.set_scrollbars_enabled(False)
        assert view.horizontalScrollBarPolicy() == Qt.ScrollBarAlwaysOff
        assert view.verticalScrollBarPolicy() == Qt.ScrollBarAlwaysOff

    def test_dashboard_views_get_it_too(self, qtbot):
        """Dashboard pages are the same base class, so the same setting
        reaches them through MainWindow's setter walking every view."""
        dv = DashboardView(None)
        qtbot.addWidget(dv)
        dv.set_scrollbars_enabled(True)
        assert dv.horizontalScrollBarPolicy() == Qt.ScrollBarAsNeeded


class TestFittedSpan:
    """The clever half: the bars cover the flow plus a margin, so they
    scroll at canvas speed and grow with it."""

    def test_the_span_follows_the_flow_not_the_world(self, qtbot,
                                                      registry):
        graph = Graph()
        scene = NodeGraphScene(graph, QUndoStack(), registry=registry)
        a = registry.instantiate(JOIN, pos=(0, 0))
        b = registry.instantiate(JOIN, pos=(1200, 800))
        graph.add_node(a)
        graph.add_node(b)
        qtbot.waitUntil(lambda: scene.sceneRect().width() < 5000,
                        timeout=2000)   # the refit is debounced
        rect = scene.sceneRect()
        # roughly the nodes' bounds plus one margin each side — not the
        # two-million-unit world the bars used to be stretched over
        assert rect.width() < 1200 + 2 * SCENE_MARGIN + 800
        assert rect.height() < 800 + 2 * SCENE_MARGIN + 500

    def test_a_bar_pixel_moves_about_one_canvas_pixel(self, qtbot,
                                                      registry):
        graph = Graph()
        scene = NodeGraphScene(graph, QUndoStack(), registry=registry)
        view = NodeGraphView(scene)
        view.resize(600, 400)
        view.show()
        qtbot.addWidget(view)
        node = registry.instantiate(JOIN, pos=(0, 0))
        graph.add_node(node)
        qtbot.waitUntil(lambda: scene.sceneRect().width() < 5000,
                        timeout=2000)
        view.set_zoom(1.0)
        bar = view.horizontalScrollBar()
        if bar.maximum() <= 0:
            pytest.skip("span fits the viewport; nothing to scroll")
        before = view.mapToScene(view.viewport().rect().center()).x()
        bar.setValue(bar.value() + max(1, int(bar.maximum() * 0.05)))
        after = view.mapToScene(view.viewport().rect().center()).x()
        # five percent of the whole bar ≈ a small slide across the margin,
        # not a jump to another county
        assert abs(after - before) < SCENE_MARGIN / 2
