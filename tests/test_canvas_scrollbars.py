"""Show scroll bars on the canvas (asked for in place of the right-button
pan): a setting that turns the hidden horizontal and vertical bars into
visible, draggable ones — a where-am-I for large flows. Panning itself was
never scrollbar-driven, so this changes nothing but their visibility. The
bars map the whole scrollable span onto their length, so the span is
fitted to the flow (plus a margin) rather than world-sized — otherwise one
pixel of bar is thousands of canvas pixels and the smallest drag sends
everything past like a bullet."""
import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QUndoStack, QWheelEvent

from flograph.core import Graph
from flograph.ui.canvas import NodeGraphScene, NodeGraphView
from flograph.ui.canvas.base_view import ZOOM_MIN
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
    scroll at canvas speed and grow with it. Only while the bars are shown —
    with them off the span stays world-sized so a pan is never walled in."""

    def test_the_span_is_world_sized_until_the_bars_are_shown(self, qtbot,
                                                              registry):
        scene = NodeGraphScene(Graph(), QUndoStack(), registry=registry)
        assert scene.sceneRect().width() > 100_000
        scene.set_rect_fitted(True)
        qtbot.waitUntil(lambda: scene.sceneRect().width() < 5000, timeout=2000)
        scene.set_rect_fitted(False)
        assert scene.sceneRect().width() > 100_000

    def test_the_setting_drives_the_fit_through_the_view(self, qtbot,
                                                         registry):
        scene = NodeGraphScene(Graph(), QUndoStack(), registry=registry)
        v = NodeGraphView(scene)
        qtbot.addWidget(v)
        assert scene.sceneRect().width() > 100_000
        v.set_scrollbars_enabled(True)
        qtbot.waitUntil(lambda: scene.sceneRect().width() < 5000, timeout=2000)
        v.set_scrollbars_enabled(False)
        assert scene.sceneRect().width() > 100_000

    def test_the_span_follows_the_flow_not_the_world(self, qtbot,
                                                      registry):
        graph = Graph()
        scene = NodeGraphScene(graph, QUndoStack(), registry=registry)
        scene.set_rect_fitted(True)
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
        view.set_scrollbars_enabled(True)
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


class TestTheSpanDoesNotDriftTheView:
    """0.1.15: "when I have the scroll bars on and I zoom out the page can
    slowly move without me asking it to."

    A view cannot scroll outside the scene rect, and Qt applies that the
    instant the transform changes — inside `scale()`. With the bars on the
    span is fitted to the flow, so zooming out far enough that the viewport
    no longer fits in it left the zoom half-applied: Qt pulled the view back
    inside, the 250 ms refit grew the span to match, and the next tick did
    it again. Measured on the unfixed code, the scene point under the
    cursor wandered from (638, 148) to (-1669, -1222) over sixteen wheel
    ticks — the canvas sliding out from under the pointer.

    The invariant these hold to is the one a zoom actually promises: **the
    point under the cursor stays under the cursor**. Asserting on the view
    centre instead would pass for a zoom that was wrong in a different way,
    since the centre is *supposed* to move when the anchor is off-centre.
    """

    ANCHOR = QPoint(180, 140)     # off-centre, as a real cursor is

    def _view_on_a_flow(self, qtbot, registry):
        graph = Graph()
        scene = NodeGraphScene(graph, QUndoStack(), registry=registry)
        view = NodeGraphView(scene)
        view.resize(900, 600)
        view.show()
        qtbot.addWidget(view)
        for pos in ((0, 0), (900, 600), (1800, 200)):
            graph.add_node(registry.instantiate(JOIN, pos=pos))
        view.set_scrollbars_enabled(True)
        qtbot.waitUntil(lambda: scene.sceneRect().width() < 5000,
                        timeout=2000)
        view.set_zoom(1.0)
        view.centerOn(900, 300)
        scene.flush_rect_fit()
        return graph, scene, view

    def _wheel_out(self, view, scene, ticks=16):
        """Zoom out a tick at a time, refitting between as the debounce
        does, and report where the anchored scene point ended up."""
        where = QPointF(self.ANCHOR)
        for _ in range(ticks):
            if view.zoom <= ZOOM_MIN:
                break        # the limit is not drift; stop before it
            view.wheelEvent(QWheelEvent(
                where, view.mapToGlobal(self.ANCHOR), QPoint(0, 0),
                QPoint(0, -120), Qt.NoButton, Qt.NoModifier,
                Qt.ScrollUpdate, False))
            scene.flush_rect_fit()
        return view.mapToScene(self.ANCHOR)

    def test_what_is_under_the_cursor_stays_under_the_cursor(self, qtbot,
                                                             registry):
        _graph, scene, view = self._view_on_a_flow(qtbot, registry)
        before = view.mapToScene(self.ANCHOR)
        after = self._wheel_out(view, scene)
        assert abs(after.x() - before.x()) < 1.0
        assert abs(after.y() - before.y()) < 1.0

    def test_it_holds_with_the_bars_off_too(self, qtbot, registry):
        """The span is world-sized then, so there was never anything to
        clamp — this is the control, and it passed before the fix."""
        _graph, scene, view = self._view_on_a_flow(qtbot, registry)
        view.set_scrollbars_enabled(False)
        before = view.mapToScene(self.ANCHOR)
        after = self._wheel_out(view, scene)
        assert abs(after.x() - before.x()) < 1.0

    def test_the_span_keeps_up_with_the_zoom_rather_than_lagging(
            self, qtbot, registry):
        """The cause, named: the span has to cover what the view shows at
        the moment the transform changes, not a beat later."""
        _graph, scene, view = self._view_on_a_flow(qtbot, registry)
        self._wheel_out(view, scene, ticks=12)
        visible = view.mapToScene(view.viewport().rect()).boundingRect()
        assert scene.sceneRect().contains(visible)

    def test_sitting_still_and_refitting_moves_nothing(self, qtbot,
                                                        registry):
        """A refit must be a fixed point, or each one feeds the next."""
        _graph, scene, view = self._view_on_a_flow(qtbot, registry)
        self._wheel_out(view, scene, ticks=8)
        before = view.mapToScene(view.viewport().rect().center())
        span = scene.sceneRect()
        for _ in range(5):
            scene.flush_rect_fit()
        assert view.mapToScene(view.viewport().rect().center()) == before
        assert scene.sceneRect() == span

    def test_zooming_back_in_comes_back_to_where_it_started(self, qtbot,
                                                            registry):
        """Out and back is a round trip, which it cannot be if either
        direction quietly loses ground."""
        _graph, scene, view = self._view_on_a_flow(qtbot, registry)
        before = view.mapToScene(self.ANCHOR)
        where = QPointF(self.ANCHOR)
        for delta in (-120,) * 8 + (120,) * 8:
            view.wheelEvent(QWheelEvent(
                where, view.mapToGlobal(self.ANCHOR), QPoint(0, 0),
                QPoint(0, delta), Qt.NoButton, Qt.NoModifier,
                Qt.ScrollUpdate, False))
            scene.flush_rect_fit()
        after = view.mapToScene(self.ANCHOR)
        assert abs(after.x() - before.x()) < 1.0
        assert abs(after.y() - before.y()) < 1.0

    def test_the_middle_of_the_viewport_is_the_middle_of_the_viewport(
            self, qtbot, registry):
        """`QRect::center()` truncates — the middle of a 900px viewport is
        449, not 449.5 — so the scene point it maps to was half a pixel up
        and left of the real centre. Harmless read once; fed back into
        `centerOn` it lands a whole scroll step away, which is how a
        restored canvas walked 2.5 units per save/open cycle (0.1.15 #4).
        """
        _graph, scene, view = self._view_on_a_flow(qtbot, registry)
        view.set_zoom(0.4)
        view.centerOn(300.0, 200.0)
        centre = view.viewport_centre()
        assert centre.x() == pytest.approx(300.0, abs=0.01)
        assert centre.y() == pytest.approx(200.0, abs=0.01)

    def test_asking_for_the_centre_it_reports_moves_nothing(self, qtbot,
                                                             registry):
        """The property that makes it safe to persist: read it, hand it
        straight back, and the view has not moved. Ten times over, because
        the failure was a step at a time."""
        _graph, scene, view = self._view_on_a_flow(qtbot, registry)
        view.set_zoom(0.4)
        view.centerOn(300.0, 200.0)
        first = view.viewport_centre()
        for _ in range(10):
            view.centerOn(view.viewport_centre())
        assert view.viewport_centre().x() == pytest.approx(first.x(), abs=0.01)
        assert view.viewport_centre().y() == pytest.approx(first.y(), abs=0.01)

    def test_stepping_the_zoom_does_not_creep_either(self, qtbot, registry):
        """`set_zoom` (the +/- buttons and the zoom box) reads the centre
        and hands it back, so it had the same half-pixel loss on every
        step."""
        _graph, scene, view = self._view_on_a_flow(qtbot, registry)
        view.set_zoom(1.0)
        view.centerOn(300.0, 200.0)
        before = view.viewport_centre()
        for zoom in (0.9, 0.8, 0.7, 0.6, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0):
            view.set_zoom(zoom)
        after = view.viewport_centre()
        assert after.x() == pytest.approx(before.x(), abs=1)
        assert after.y() == pytest.approx(before.y(), abs=1)

    def test_where_the_view_is_parked_is_still_reachable(self, qtbot,
                                                         registry):
        """The union is still doing its job: a view sent far past the flow
        keeps its place inside the span, so a refit cannot clamp it back."""
        _graph, scene, view = self._view_on_a_flow(qtbot, registry)
        view.centerOn(9000, 9000)
        parked = view.mapToScene(view.viewport().rect().center())
        scene.flush_rect_fit()
        assert scene.sceneRect().contains(parked)
        assert view.mapToScene(view.viewport().rect().center()) == parked
