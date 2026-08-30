"""Edge-scroll while wiring (G3): hold the free end of a wire against a
viewport border and the canvas glides that way until the far port arrives,
so two nodes that are never on screen together can still be wired without
letting go, panning, and starting again."""
import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, Qt
from PySide6.QtGui import QUndoStack
from PySide6.QtWidgets import QGraphicsSceneMouseEvent

from flograph.core import Frame, Graph
from flograph.ui.canvas import NodeGraphScene, NodeGraphView
from flograph.ui.canvas.base_view import (EDGE_SCROLL_MARGIN,
                                          edge_scroll_delta)

JOIN = "flograph.transform.join"
SCRIPT = "flograph.scripting.python_script"

RECT = QRect(0, 0, 600, 400)


def _scene_mouse(item, kind, pos):
    event = QGraphicsSceneMouseEvent(kind)
    event.setPos(pos)
    event.setScenePos(item.mapToScene(pos))
    event.setButton(Qt.LeftButton)
    event.setButtons(Qt.LeftButton)
    event.setModifiers(Qt.NoModifier)
    event.setAccepted(True)
    return event


def _scene_press(item, pos):
    return _scene_mouse(item, QEvent.GraphicsSceneMousePress, pos)


def _scene_release(item, pos):
    return _scene_mouse(item, QEvent.GraphicsSceneMouseRelease, pos)


@pytest.fixture
def env(qtbot, registry):
    graph = Graph()
    scene = NodeGraphScene(graph, QUndoStack(), registry=registry)
    view = NodeGraphView(scene)
    view.resize(600, 400)
    qtbot.addWidget(view)
    a = registry.instantiate(JOIN, pos=(0, 0))
    graph.add_node(a)
    b = registry.instantiate(SCRIPT, pos=(1200, 800))
    graph.add_node(b)
    return graph, scene, view, a, b


class TestEdgeScrollDelta:
    def test_the_middle_of_the_view_does_not_scroll(self):
        assert edge_scroll_delta(RECT, QPoint(300, 200)).isNull()

    def test_just_outside_the_bands_does_not_scroll(self):
        m = EDGE_SCROLL_MARGIN + 1
        assert edge_scroll_delta(
            RECT, QPoint(m, RECT.height() // 2)).isNull()

    def test_the_left_band_brings_the_left_into_view(self):
        """The result is a pan of the canvas content: holding at the left
        border slides content rightward, revealing what lay beyond it."""
        delta = edge_scroll_delta(RECT, QPoint(4, 200))
        assert delta.x() > 0
        assert delta.y() == 0

    def test_the_right_band_brings_the_right_into_view(self):
        delta = edge_scroll_delta(RECT, QPoint(RECT.width() - 4, 200))
        assert delta.x() < 0
        assert delta.y() == 0

    def test_top_and_bottom_work_on_their_own_axis(self):
        top = edge_scroll_delta(RECT, QPoint(300, 4))
        bottom = edge_scroll_delta(RECT, QPoint(300, RECT.height() - 4))
        assert top.x() == 0 and top.y() > 0
        assert bottom.x() == 0 and bottom.y() < 0

    def test_a_corner_scrolls_both_ways(self):
        delta = edge_scroll_delta(RECT, QPoint(4, RECT.height() - 4))
        assert delta.x() > 0
        assert delta.y() < 0

    def test_deeper_into_the_band_is_faster(self):
        shallow = abs(edge_scroll_delta(
            RECT, QPoint(EDGE_SCROLL_MARGIN - 1, 200)).x())
        deep = abs(edge_scroll_delta(RECT, QPoint(2, 200)).x())
        assert deep > shallow


class TestCanvasDragSignals:
    def test_beginning_and_ending_a_wire_drag_announce_themselves(self, env):
        _graph, scene, _view, a, _b = env
        seen = []
        scene.canvas_drag_changed.connect(seen.append)
        out = scene.node_items[a.id].output_ports["joined"]
        scene.begin_wire_drag(out)
        scene.cancel_wire_drag()
        assert seen == [True, False]
        assert not scene.wire_drag_active
        assert not scene.canvas_drag_active

    def test_restarting_a_wire_drag_ends_one_then_starts_the_next(self, env):
        _graph, scene, _view, a, _b = env
        seen = []
        scene.canvas_drag_changed.connect(seen.append)
        out = scene.node_items[a.id].output_ports["joined"]
        scene.begin_wire_drag(out)
        scene.begin_wire_drag(out)   # the restart cancels the first drag
        assert seen == [True, False, True]

    def test_beginning_over_nothing_does_not_emit_an_end(self, env):
        """cancel_wire_drag also runs at the top of begin_wire_drag; with
        no drag under way there is nothing to announce the end of."""
        _graph, scene, _view, a, _b = env
        seen = []
        scene.canvas_drag_changed.connect(seen.append)
        scene.begin_wire_drag(scene.node_items[a.id].output_ports["joined"])
        assert seen == [True]

    def test_a_group_drag_announces_itself_even_if_nothing_moves(self, env):
        """A click that never became a move still has to end the edge
        scrolling — commit's early return must not skip the end signal."""
        _graph, scene, _view, a, _b = env
        scene.node_items[a.id].setSelected(True)
        seen = []
        scene.canvas_drag_changed.connect(seen.append)
        starts = scene.begin_group_drag()
        assert seen == [True]
        assert scene.group_drag_active
        assert scene.canvas_drag_active
        scene.commit_group_move(starts)
        assert seen == [True, False]
        assert not scene.canvas_drag_active


class TestViewEdgeScroll:
    def test_the_scroll_timer_follows_the_drag(self, env):
        _graph, scene, view, a, _b = env
        assert not view._edge_timer.isActive()
        out = scene.node_items[a.id].output_ports["joined"]
        scene.begin_wire_drag(out)
        assert view._edge_timer.isActive()
        scene.cancel_wire_drag()
        assert not view._edge_timer.isActive()

    def test_a_missed_end_signal_stops_the_timer_anyway(self, env):
        """The belt: whatever strands the timer without a drag underneath
        it must stop it rather than scroll forever."""
        _graph, _scene, view, _a, _b = env
        view._set_edge_scrolling(True)
        assert view._edge_timer.isActive()
        view._edge_scroll_tick()
        assert not view._edge_timer.isActive()

    def test_holding_the_left_edge_pans_the_camera_left(self, env):
        _graph, scene, view, a, _b = env
        scene.begin_wire_drag(scene.node_items[a.id].output_ports["joined"])
        vp = view.viewport().rect()
        cursor = QPoint(4, vp.center().y())
        before = view.mapToScene(vp.center()).x()
        view.edge_scroll_at(view.viewport().mapToGlobal(cursor))
        after = view.mapToScene(vp.center()).x()
        assert after < before

    def test_the_middle_of_the_view_does_not_pan(self, env):
        _graph, scene, view, a, _b = env
        scene.begin_wire_drag(scene.node_items[a.id].output_ports["joined"])
        vp = view.viewport().rect()
        centre = view.viewport().mapToGlobal(vp.center())
        before_x = view.mapToScene(vp.center()).x()
        before_y = view.mapToScene(vp.center()).y()
        view.edge_scroll_at(centre)
        assert view.mapToScene(vp.center()).x() == before_x
        assert view.mapToScene(vp.center()).y() == before_y

    def test_the_free_end_of_the_wire_follows_the_hand(self, env):
        """The pan changes which scene point the cursor means; the drag
        must follow, exactly as if the mouse had moved there."""
        _graph, scene, view, a, _b = env
        scene.begin_wire_drag(scene.node_items[a.id].output_ports["joined"])
        vp = view.viewport().rect()
        cursor = QPoint(4, vp.center().y())
        view.edge_scroll_at(view.viewport().mapToGlobal(cursor))
        expected = view.mapToScene(cursor)
        path = scene._pending.path()
        last = path.elementAt(path.elementCount() - 1)
        end = QPointF(last.x, last.y)
        assert (end - expected).manhattanLength() < 0.001


class TestDraggingNodesToTheEdge:
    def test_a_dragged_node_rides_the_pan(self, env, qtbot):
        """Holding a node at the border must carry it with the scroll —
        and without snapping back on the next real mouse move."""
        _graph, scene, view, a, _b = env
        scene.snap_enabled = False
        view.show()
        item = scene.node_items[a.id]
        grab = view.mapFromScene(item.mapToScene(QPointF(0, 8)))
        qtbot.mousePress(view.viewport(), Qt.LeftButton, pos=grab)
        try:
            assert view._edge_timer.isActive()   # the press began a drag
            vp = view.viewport().rect()
            cursor = QPoint(4, vp.center().y())
            # a user's hand is already at the border when the ticks fire:
            # carry the drag there first, so each step is pan-sized
            qtbot.mouseMove(view.viewport(), pos=cursor)
            before = item.pos()
            view.edge_scroll_at(view.viewport().mapToGlobal(cursor))
            after = item.pos()
            # rode toward what lay off-screen to the left, level in y
            assert after.x() < before.x() - 5
            assert abs(after.y() - before.y()) < 0.5
            # no jump-back: Qt re-anchors to press + total travel, which
            # the ride already fed, so a 2px nudge lands 2px on
            qtbot.mouseMove(view.viewport(), pos=cursor + QPoint(2, 0))
            settled = item.pos()
            assert settled.x() == pytest.approx(after.x() + 2, abs=3)
        finally:
            qtbot.mouseRelease(view.viewport(), Qt.LeftButton, pos=cursor)

    def test_a_click_that_never_moves_does_not_ride(self, env, qtbot):
        _graph, scene, view, a, _b = env
        scene.snap_enabled = False
        view.show()
        item = scene.node_items[a.id]
        grab = view.mapFromScene(item.mapToScene(QPointF(0, 8)))
        qtbot.mousePress(view.viewport(), Qt.LeftButton, pos=grab)
        try:
            before = item.pos()
            vp = view.viewport().rect()
            centre = view.viewport().mapToGlobal(vp.center())
            view.edge_scroll_at(centre)
            assert item.pos() == before   # not in an edge band: nothing
        finally:
            qtbot.mouseRelease(view.viewport(), Qt.LeftButton,
                               pos=vp.center())


class TestDraggingAFrameToTheEdge:
    """A lone frame carrying its contents commits its own move, so it never
    went through begin_group_drag and the border glide skipped it."""

    def _frame(self, env):
        graph, scene, _view, *_ = env
        graph.add_frame(Frame(id="fr", title="Stage", rect=(0, 0, 300, 200)))
        return scene.frame_items["fr"]

    def test_a_lone_frame_drag_runs_the_edge_scroll_timer(self, env):
        _graph, scene, view, *_ = env
        item = self._frame(env)
        assert not view._edge_timer.isActive()
        press = _scene_press(item, QPointF(150.0, 6.0))  # title bar
        item.mousePressEvent(press)
        assert item._dragging
        assert scene.canvas_drag_active
        assert view._edge_timer.isActive()
        item.mouseReleaseEvent(_scene_release(item, QPointF(150.0, 6.0)))
        assert not scene.canvas_drag_active
        assert not view._edge_timer.isActive()

    def test_the_frame_rides_the_pan(self, env, qtbot):
        _graph, scene, view, *_ = env
        scene.snap_enabled = False
        view.show()
        item = self._frame(env)
        grab = view.mapFromScene(item.mapToScene(QPointF(150.0, 6.0)))
        qtbot.mousePress(view.viewport(), Qt.LeftButton, pos=grab)
        try:
            assert view._edge_timer.isActive()
            vp = view.viewport().rect()
            cursor = QPoint(4, vp.center().y())
            qtbot.mouseMove(view.viewport(), pos=cursor)
            before = item.pos()
            view.edge_scroll_at(view.viewport().mapToGlobal(cursor))
            after = item.pos()
            assert after.x() < before.x() - 5
            assert abs(after.y() - before.y()) < 0.5
        finally:
            qtbot.mouseRelease(view.viewport(), Qt.LeftButton, pos=cursor)
            assert not scene.canvas_drag_active


class TestStaleDragState:
    def test_a_middle_drag_pan_never_edge_scrolls(self, env):
        """The user's report: a plain middle-drag pan reaching the border
        should just pan, not also fire the drag-a-thing-to-the-edge scroll."""
        _graph, scene, view, a, _b = env
        scene.begin_wire_drag(scene.node_items[a.id].output_ports["joined"])
        view._panning = True
        vp = view.viewport().rect()
        before = view.mapToScene(vp.center()).x()
        view._edge_scroll_tick()          # _panning set: a no-op
        assert view.mapToScene(vp.center()).x() == before
        view._panning = False

    def test_replacing_the_graph_clears_a_stranded_drag(self, env):
        """A drag interrupted by Open never gets its mouse release;
        cancel_active_drags is what stops the view edge-scrolling for it."""
        _graph, scene, view, a, _b = env
        scene.node_items[a.id].setSelected(True)
        scene.begin_group_drag()          # a drag with no matching commit
        assert scene.canvas_drag_active
        assert view._edge_timer.isActive()
        scene.cancel_active_drags()
        assert not scene.canvas_drag_active
        assert not view._edge_timer.isActive()
        assert scene.node_items[a.id]._dragging is False

    def test_cancel_also_drops_a_wire_drag(self, env):
        _graph, scene, _view, a, _b = env
        scene.begin_wire_drag(scene.node_items[a.id].output_ports["joined"])
        assert scene.wire_drag_active
        scene.cancel_active_drags()
        assert not scene.wire_drag_active
        assert not scene.canvas_drag_active
