"""Two settings for how you get around the canvas: what a left-drag on empty
canvas does (draw a selection band, or move the canvas), and what a plain
wheel tick does (zoom about the cursor, or scroll the canvas up and down with
Ctrl+wheel left to zoom).

Both are Settings > Canvas > Getting around, both reach every canvas view the
window owns, and neither changes what a press on an actual item does — the
frame case is the one worth pinning down, since a frame's box covers most of
a real flow and only its title bar belongs to the frame.

No real MainWindow.show() here — see tests/test_gpu_viewport_setting.py's
module docstring. Settings kept off the real store, like
tests/test_rubber_band_selection.py.
"""
import pytest
from PySide6.QtCore import QPoint, QPointF, QSettings, Qt
from PySide6.QtGui import QMouseEvent, QWheelEvent
from PySide6.QtWidgets import QComboBox

from flograph.core import Frame, NodeRegistry, Page
from flograph.ui import mainwindow as mod
from flograph.ui.canvas import base_view
from flograph.ui.commands import AddPageCommand
from flograph.ui.settings_dialog import SettingsDialog

CONST = "flograph.util.constant"


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
    win = mod.MainWindow(registry)
    win.confirm_close = False
    qtbot.addWidget(win)
    win.view.resize(1000, 800)
    win.view.set_zoom(1.0)
    win.view.centerOn(0.0, 0.0)
    return win


def _mouse(view, kind, pos: QPoint, buttons, modifier=Qt.NoModifier,
           button=Qt.LeftButton) -> None:
    """One synthetic mouse event straight at the view's handler — qtbot
    cannot carry a held button on the offscreen platform, and a drag is
    nothing without one."""
    local = QPointF(pos)
    event = QMouseEvent(kind, local, local, button, buttons, modifier)
    if kind == QMouseEvent.Type.MouseButtonPress:
        view.mousePressEvent(event)
    elif kind == QMouseEvent.Type.MouseMove:
        view.mouseMoveEvent(event)
    else:
        view.mouseReleaseEvent(event)


def _drag(view, start: QPoint, end: QPoint, modifier=Qt.NoModifier) -> None:
    """A left-button drag between two *viewport* points."""
    _mouse(view, QMouseEvent.Type.MouseButtonPress, start, Qt.LeftButton,
           modifier)
    _mouse(view, QMouseEvent.Type.MouseMove, end, Qt.LeftButton, modifier)
    _mouse(view, QMouseEvent.Type.MouseButtonRelease, end, Qt.NoButton,
           modifier, button=Qt.LeftButton)


def _wheel(view, notches: int = 1, modifier=Qt.NoModifier,
           pos: QPoint = QPoint(100, 100)) -> None:
    local = QPointF(pos)
    view.wheelEvent(QWheelEvent(
        local, local, QPoint(0, 0), QPoint(0, 120 * notches),
        Qt.NoButton, modifier, Qt.ScrollUpdate, False))


def _origin(view) -> QPointF:
    """Where the viewport's top-left corner is looking, in scene units — the
    cheapest way to ask "did the canvas move, and which way"."""
    return view.mapToScene(QPoint(0, 0))


def _empty_spot(view) -> QPoint:
    """A viewport point with nothing under it."""
    point = QPoint(60, 60)
    assert view._press_lands_on_canvas(point), "the test needs empty canvas"
    return point


class TestDefaults:
    def test_the_canvas_starts_as_it_always_was(self, window):
        assert window.left_drag_mode == "band"
        assert window.wheel_action == "zoom"

    def test_a_name_it_does_not_know_falls_back(self, window):
        window.view.set_left_drag_mode("sideways")
        window.view.set_wheel_action("sideways")
        assert window.view._left_drag_mode == base_view.DEFAULT_LEFT_DRAG_MODE
        assert window.view._wheel_action == base_view.DEFAULT_WHEEL_ACTION


class TestTheWheel:
    def test_by_default_it_still_zooms(self, window):
        before = window.view.zoom
        _wheel(window.view)
        assert window.view.zoom > before

    def test_set_to_scroll_it_walks_the_canvas_instead(self, window):
        window.set_wheel_action("scroll")
        zoom, origin = window.view.zoom, _origin(window.view)
        _wheel(window.view, notches=-1)
        assert window.view.zoom == zoom
        moved = _origin(window.view)
        assert moved.y() > origin.y(), "a notch down goes further down the flow"
        assert moved.x() == pytest.approx(origin.x())

    def test_a_notch_up_comes_back(self, window):
        window.set_wheel_action("scroll")
        origin = _origin(window.view)
        _wheel(window.view, notches=-1)
        _wheel(window.view, notches=1)
        assert _origin(window.view).y() == pytest.approx(origin.y(), abs=1.0)

    def test_shift_goes_sideways(self, window):
        window.set_wheel_action("scroll")
        origin = _origin(window.view)
        _wheel(window.view, notches=-1, modifier=Qt.ShiftModifier)
        moved = _origin(window.view)
        assert moved.x() > origin.x()
        assert moved.y() == pytest.approx(origin.y())

    def test_ctrl_still_zooms(self, window):
        window.set_wheel_action("scroll")
        origin, zoom = _origin(window.view), window.view.zoom
        _wheel(window.view, modifier=Qt.ControlModifier)
        assert window.view.zoom > zoom
        assert _origin(window.view) != origin, "zoom to cursor still holds"

    def test_ctrl_zooms_under_the_default_too(self, window):
        zoom = window.view.zoom
        _wheel(window.view, modifier=Qt.ControlModifier)
        assert window.view.zoom > zoom

    def test_a_locked_page_ignores_the_wheel_either_way(self, window):
        window.set_wheel_action("scroll")
        window.view.set_navigation_locked(True)
        origin, zoom = _origin(window.view), window.view.zoom
        _wheel(window.view, notches=-1)
        assert (_origin(window.view), window.view.zoom) == (origin, zoom)


class TestLeftDragPan:
    def test_by_default_a_left_drag_does_not_move_the_canvas(self, window):
        origin = _origin(window.view)
        _drag(window.view, _empty_spot(window.view), QPoint(200, 300))
        assert _origin(window.view) == origin

    def test_set_to_pan_it_moves_the_canvas(self, window):
        window.set_left_drag_mode("pan")
        origin = _origin(window.view)
        _drag(window.view, _empty_spot(window.view), QPoint(160, 260))
        moved = _origin(window.view)
        # dragging right and down brings what lay up and to the left into view
        assert moved.x() < origin.x()
        assert moved.y() < origin.y()

    def test_it_draws_no_band_while_panning(self, window):
        window.set_left_drag_mode("pan")
        node = window.registry.instantiate(CONST, pos=(0.0, 0.0))
        window.graph.add_node(node)
        item = window.scene.node_items[node.id]
        start = window.view.mapFromScene(
            item.sceneBoundingRect().topLeft() - QPointF(80, 80))
        end = window.view.mapFromScene(
            item.sceneBoundingRect().bottomRight() + QPointF(80, 80))
        _drag(window.view, start, end)
        assert window.scene.selectedItems() == []

    def test_ctrl_gets_the_band_back(self, window):
        window.set_left_drag_mode("pan")
        node = window.registry.instantiate(CONST, pos=(0.0, 0.0))
        window.graph.add_node(node)
        item = window.scene.node_items[node.id]
        origin = _origin(window.view)
        start = window.view.mapFromScene(
            item.sceneBoundingRect().topLeft() - QPointF(80, 80))
        end = window.view.mapFromScene(
            item.sceneBoundingRect().bottomRight() + QPointF(80, 80))
        _drag(window.view, start, end, modifier=Qt.ControlModifier)
        assert item in window.scene.selectedItems()
        assert _origin(window.view) == origin, "the band must not also pan"

    def test_a_click_still_clears_the_selection(self, window):
        window.set_left_drag_mode("pan")
        node = window.registry.instantiate(CONST, pos=(0.0, 0.0))
        window.graph.add_node(node)
        item = window.scene.node_items[node.id]
        item.setSelected(True)
        spot = _empty_spot(window.view)
        _drag(window.view, spot, spot)
        assert window.scene.selectedItems() == []

    def test_a_node_still_takes_its_own_press(self, window):
        window.set_left_drag_mode("pan")
        node = window.registry.instantiate(CONST, pos=(0.0, 0.0))
        window.graph.add_node(node)
        item = window.scene.node_items[node.id]
        centre = window.view.mapFromScene(item.sceneBoundingRect().center())
        origin = _origin(window.view)
        _drag(window.view, centre, centre + QPoint(40, 40))
        assert _origin(window.view) == origin, "the node moved, not the canvas"
        assert item in window.scene.selectedItems()

    def test_a_frames_body_is_canvas(self, window):
        """The case that decides whether this is usable at all: a frame in a
        real flow is bigger than the viewport, so most of the empty canvas
        you would drag is inside one."""
        window.set_left_drag_mode("pan")
        window.graph.add_frame(
            Frame(id="f1", title="Stage", rect=(0.0, 0.0, 600.0, 400.0)))
        middle = window.view.mapFromScene(QPointF(300.0, 250.0))
        origin = _origin(window.view)
        _drag(window.view, middle, middle + QPoint(-50, -40))
        assert _origin(window.view).x() > origin.x()
        assert window.scene.frame_items["f1"].pos() == QPointF(0.0, 0.0)

    def test_a_frames_title_bar_is_still_the_frame(self, window):
        window.set_left_drag_mode("pan")
        window.graph.add_frame(
            Frame(id="f1", title="Stage", rect=(0.0, 0.0, 600.0, 400.0)))
        title = window.view.mapFromScene(QPointF(300.0, 8.0))
        origin = _origin(window.view)
        _drag(window.view, title, title + QPoint(30, 30))
        assert _origin(window.view) == origin

    def test_a_locked_page_never_pans(self, window):
        window.set_left_drag_mode("pan")
        window.view.set_navigation_locked(True)
        origin = _origin(window.view)
        _drag(window.view, QPoint(60, 60), QPoint(200, 200))
        assert _origin(window.view) == origin

    def test_middle_drag_pans_whatever_the_setting(self, window):
        origin = _origin(window.view)
        start, end = QPoint(60, 60), QPoint(160, 160)
        _mouse(window.view, QMouseEvent.Type.MouseButtonPress, start,
               Qt.MiddleButton, button=Qt.MiddleButton)
        _mouse(window.view, QMouseEvent.Type.MouseMove, end, Qt.MiddleButton,
               button=Qt.MiddleButton)
        _mouse(window.view, QMouseEvent.Type.MouseButtonRelease, end,
               Qt.NoButton, button=Qt.MiddleButton)
        assert _origin(window.view).x() < origin.x()
        assert not window.view._panning


class TestADashboardPage:
    @pytest.fixture
    def page_view(self, window):
        window.undo_stack.push(
            AddPageCommand(window.graph, Page(id="p1", title="Board")))
        view = window._canvas_pages()[0].view
        view.resize(800, 600)
        view.set_zoom(1.0)
        view.centerOn(0.0, 0.0)
        return view

    def test_it_pans_like_the_canvas(self, window, page_view):
        window.set_left_drag_mode("pan")
        origin = _origin(page_view)
        _drag(page_view, QPoint(60, 60), QPoint(160, 160))
        assert _origin(page_view).x() < origin.x()

    def test_a_maximized_tile_turns_the_pan_away(self, window, page_view):
        """Panning a tile that is pinned to the viewport would only slide it
        out of sight — the same reason the wheel and middle-drag are already
        turned away while one is maximized."""
        window.set_left_drag_mode("pan")
        page_view._fs_tile = object()
        origin = _origin(page_view)
        _drag(page_view, QPoint(60, 60), QPoint(160, 160))
        assert _origin(page_view) == origin


class TestTheWindowWiring:
    def test_both_persist(self, window):
        window.set_left_drag_mode("pan")
        window.set_wheel_action("scroll")
        assert window.settings.value("canvas/left_drag_mode") == "pan"
        assert window.settings.value("canvas/wheel_action") == "scroll"

    def test_a_page_made_afterwards_is_born_with_them(self, window):
        """The setting is pushed at the views that exist; a dashboard page
        opened later has to pick it up as it is built."""
        window.set_left_drag_mode("pan")
        window.set_wheel_action("scroll")
        window.undo_stack.push(
            AddPageCommand(window.graph, Page(id="p1", title="Board")))
        views = [page.view for page in window._canvas_pages()]
        assert views, "the page should have a view by now"
        for view in views:
            assert view._left_drag_mode == "pan"
            assert view._wheel_action == "scroll"

    def test_a_page_open_already_is_told(self, window):
        window.undo_stack.push(
            AddPageCommand(window.graph, Page(id="p1", title="Board")))
        window.set_left_drag_mode("pan")
        window.set_wheel_action("scroll")
        for page in window._canvas_pages():
            assert page.view._left_drag_mode == "pan"
            assert page.view._wheel_action == "scroll"

    def test_reset_puts_them_back(self, window):
        window.set_left_drag_mode("pan")
        window.set_wheel_action("scroll")
        window.reset_settings()
        assert window.left_drag_mode == base_view.DEFAULT_LEFT_DRAG_MODE
        assert window.wheel_action == base_view.DEFAULT_WHEEL_ACTION


class TestTheDialog:
    def test_the_combos_start_where_the_window_is(self, window, qtbot):
        window.set_left_drag_mode("pan")
        window.set_wheel_action("scroll")
        dialog = SettingsDialog(window)
        qtbot.addWidget(dialog)
        assert dialog.findChild(
            QComboBox, "left_drag_mode_combo").currentData() == "pan"
        assert dialog.findChild(
            QComboBox, "wheel_action_combo").currentData() == "scroll"

    def test_picking_move_the_canvas_pushes_it(self, window, qtbot):
        dialog = SettingsDialog(window)
        qtbot.addWidget(dialog)
        combo = dialog.findChild(QComboBox, "left_drag_mode_combo")
        combo.setCurrentIndex(combo.findData("pan"))
        assert window.left_drag_mode == "pan"
        assert window.view._left_drag_mode == "pan"

    def test_picking_scroll_pushes_it(self, window, qtbot):
        dialog = SettingsDialog(window)
        qtbot.addWidget(dialog)
        combo = dialog.findChild(QComboBox, "wheel_action_combo")
        combo.setCurrentIndex(combo.findData("scroll"))
        assert window.wheel_action == "scroll"
        assert window.view._wheel_action == "scroll"

    def test_a_reset_refreshes_the_combos(self, window, qtbot):
        dialog = SettingsDialog(window)
        qtbot.addWidget(dialog)
        window.set_left_drag_mode("pan")
        dialog.refresh_from(window)
        assert dialog.findChild(
            QComboBox, "left_drag_mode_combo").currentData() == "pan"
