"""Right-clicking the canvas opens the node palette.

It used to open a menu of nested category submenus — every node in the
library behind a category you had to guess first, and the one place in the
app where finding a node meant reading rather than typing. It is the same
searchable popup a dropped wire opens now, with the two things on that menu
that were not nodes kept as rows of their own.

Right-clicking *inside a frame* lands here too: same split as the drag, the
title bar is the frame and the body is canvas.
"""
import pytest
from PySide6.QtCore import QPoint, QPointF, QSettings
from PySide6.QtGui import QContextMenuEvent, QUndoStack

from flograph.core import Frame, Graph, NodeRegistry
from flograph.ui import mainwindow as mod
from flograph.ui.canvas import NodeGraphScene
from flograph.ui.canvas.palette import EXTRA_ROLE, TYPE_ID_ROLE
from flograph.ui.canvas.view import NodeGraphView
from flograph.ui.mainwindow import MainWindow


@pytest.fixture(autouse=True)
def _isolated_settings(tmp_path, monkeypatch):
    ini_path = str(tmp_path / "test_settings.ini")
    monkeypatch.setattr(
        mod, "QSettings",
        lambda *a, **k: QSettings(ini_path, QSettings.IniFormat))


@pytest.fixture(scope="module")
def registry():
    reg = NodeRegistry()
    reg.load_builtins()
    return reg


@pytest.fixture
def window(qtbot, registry):
    win = MainWindow(registry)
    win.confirm_close = False
    qtbot.addWidget(win)
    yield win
    win._palette_popup.hide()


def rows(popup):
    return [popup._list.item(i) for i in range(popup._list.count())]


def labels(popup):
    return [item.text() for item in rows(popup)]


class TestThePopupItself:
    def _popup(self, window, extras=(("Frame", "frame"),)):
        window._palette_popup.popup_at(QPoint(0, 0), extras=extras)
        return window._palette_popup

    def test_the_extras_are_listed_with_the_nodes(self, window):
        popup = self._popup(window)
        assert any(text.startswith("Frame ") for text in labels(popup))
        assert len(labels(popup)) > 10   # the library is there too

    def test_an_extra_row_carries_a_key_rather_than_a_type_id(self, window):
        popup = self._popup(window)
        first = rows(popup)[0]
        assert first.data(EXTRA_ROLE) == "frame"
        assert first.data(TYPE_ID_ROLE) is None

    def test_enter_on_an_empty_search_still_adds_a_node(self, window):
        """The popup is here to add a node — an extra sitting at the top of
        the list must not become what Enter means."""
        popup = self._popup(window)
        assert popup._list.currentItem().data(EXTRA_ROLE) is None
        assert popup._list.currentItem().data(TYPE_ID_ROLE)

    def test_typing_narrows_to_the_extra(self, window):
        popup = self._popup(window)
        popup._search.setText("fra")
        assert popup._list.currentItem().data(EXTRA_ROLE) == "frame"

    def test_choosing_an_extra_says_so_on_its_own_signal(self, window,
                                                          qtbot):
        popup = self._popup(window)
        with qtbot.waitSignal(popup.extra_chosen, timeout=1000) as blocker:
            popup._accept(rows(popup)[0])
        assert blocker.args == ["frame"]

    def test_choosing_a_node_still_says_type_id(self, window, qtbot):
        popup = self._popup(window)
        node_row = next(r for r in rows(popup) if r.data(TYPE_ID_ROLE))
        with qtbot.waitSignal(popup.chosen, timeout=1000) as blocker:
            popup._accept(node_row)
        assert blocker.args == [node_row.data(TYPE_ID_ROLE)]

    def test_a_wire_drop_has_no_extras(self, window):
        """Dropping a wire is asking for a node to connect; a frame is not
        an answer to that."""
        window._palette_popup.popup_at(QPoint(0, 0))
        assert all(item.data(EXTRA_ROLE) is None
                   for item in rows(window._palette_popup))


class TestRightClickingTheCanvas:
    def test_it_opens_the_palette(self, window):
        window._show_add_node_menu(QPointF(120, 80), QPoint(0, 0))
        assert window._palette_popup.isVisible()

    def test_a_frame_is_on_offer(self, window):
        window._show_add_node_menu(QPointF(0, 0), QPoint(0, 0))
        assert ("Frame", "frame") in window._palette_popup._extras

    def test_the_frame_lands_where_it_was_opened(self, window):
        window._show_add_node_menu(QPointF(400, 300), QPoint(0, 0))
        window._palette_popup.hide()
        window._palette_extra_chosen("frame")
        frame = next(iter(window.graph.frames.values()))
        assert frame.rect[0] == pytest.approx(400, abs=60)
        assert frame.rect[1] == pytest.approx(300, abs=60)

    def test_a_node_lands_where_it_was_opened(self, window):
        window._show_add_node_menu(QPointF(500, 260), QPoint(0, 0))
        window._palette_popup.hide()
        window._add_node_from_palette("flograph.util.constant")
        node = next(iter(window.graph.nodes.values()))
        assert node.pos == (500.0, 260.0)

    def test_it_forgets_any_wire_the_palette_was_last_opened_for(self,
                                                                 window):
        """The popup is shared with the wire-drop flow, which leaves a
        pending connection behind it."""
        window._pending_wire = ("nid", "out", True, None)
        window._show_add_node_menu(QPointF(0, 0), QPoint(0, 0))
        assert window._pending_wire is None


class TestRightClickingAFrame:
    """The frame's title bar is the frame; its body is canvas."""

    @pytest.fixture
    def env(self, qtbot, registry):
        graph = Graph()
        scene = NodeGraphScene(graph, QUndoStack(), registry=registry)
        view = NodeGraphView(scene)
        qtbot.addWidget(view)
        view.resize(800, 600)
        graph.add_frame(Frame(id="f1", title="Stage",
                              rect=(0.0, 0.0, 600.0, 400.0)))
        return graph, scene, view

    def _right_click(self, view, scene_point):
        pos = view.mapFromScene(scene_point)
        event = QContextMenuEvent(QContextMenuEvent.Mouse, pos,
                                  view.viewport().mapToGlobal(pos))
        view.contextMenuEvent(event)

    def test_the_body_asks_for_the_canvas_menu(self, env, qtbot):
        _graph, _scene, view = env
        with qtbot.waitSignal(view.add_node_requested, timeout=1000):
            self._right_click(view, QPointF(300.0, 200.0))

    def test_the_title_bar_still_asks_for_the_frame_menu(self, env, qtbot):
        _graph, _scene, view = env
        with qtbot.waitSignal(view.frame_context_requested,
                              timeout=1000) as blocker:
            self._right_click(view, QPointF(300.0, 6.0))
        assert blocker.args[0] == "f1"

    def test_the_canvas_menu_is_asked_for_the_point_clicked(self, env, qtbot):
        """So the node lands under the cursor, not at the frame's corner."""
        _graph, _scene, view = env
        with qtbot.waitSignal(view.add_node_requested,
                              timeout=1000) as blocker:
            self._right_click(view, QPointF(320.0, 240.0))
        scene_pos = blocker.args[0]
        assert scene_pos.x() == pytest.approx(320.0, abs=2)
        assert scene_pos.y() == pytest.approx(240.0, abs=2)

    def test_a_collapsed_frame_keeps_its_menu_everywhere(self, env, qtbot):
        """It is a small square standing in for its contents — there is no
        canvas inside it to reach."""
        _graph, scene, view = env
        item = scene.frame_items["f1"]
        item.toggle_collapsed()      # the chevron's own path
        with qtbot.waitSignal(view.frame_context_requested, timeout=1000):
            self._right_click(view, item.sceneBoundingRect().center())
