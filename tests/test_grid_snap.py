"""Snap-to-grid: the snap math, edge hit-testing on cards/tiles, the
_dragging gate on move snapping, and the main-window toggle propagation."""
import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtWidgets import QGraphicsItem

from flopy.core import Frame, NodeRegistry, Page, Tile
from flopy.ui.canvas import grid
from flopy.ui.commands import AddFrameCommand, AddPageCommand, AddTileCommand
from flopy.ui.mainwindow import MainWindow


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
    return win


class _FakeScene:
    def __init__(self, enabled=True, step=20.0):
        self.snap_enabled = enabled
        self.grid_step = step


# --------------------------------------------------------------- snap math

class TestSnapMath:
    @pytest.mark.parametrize("value, step, expected", [
        (23, 20, 20), (31, 20, 40), (0, 20, 0), (11, 20, 20),
        (23, 10, 20), (27, 10, 30), (23, 40, 40), (17, 40, 0),
    ])
    def test_snap_rounds_to_nearest_line(self, value, step, expected):
        assert grid.snap(value, step) == expected

    def test_snap_point(self):
        assert grid.snap_point(23, 38, 20) == (20, 40)

    def test_snap_zero_step_is_identity(self):
        assert grid.snap(23, 0) == 23

    def test_presets_and_default(self):
        assert grid.DEFAULT_STEP == grid.GRID_PRESETS["Normal"]
        assert set(grid.GRID_PRESETS) == {"Compact", "Normal", "Relaxed"}


class TestSnappingActive:
    def test_enabled_scene_without_modifier(self, qtbot):
        assert grid.snapping_active(_FakeScene(enabled=True)) is True

    def test_bypass_modifier_disables(self):
        assert grid.snapping_active(
            _FakeScene(enabled=True), Qt.ControlModifier) is False

    def test_disabled_scene(self):
        assert grid.snapping_active(_FakeScene(enabled=False)) is False

    def test_none_scene(self):
        assert grid.snapping_active(None) is False


# ------------------------------------------------------- node edge hit-test

class TestNodeEdge:
    def _note(self, window):
        node = window.registry.instantiate("flopy.util.note")
        window.graph.add_node(node)
        item = window.scene.node_items[node.id]
        item.setSelected(True)
        return item

    def test_edges_and_corner(self, window):
        item = self._note(window)
        w, h = item.width, item.body_height
        assert item._edge_at(QPointF(w, h / 2)) == "right"
        assert item._edge_at(QPointF(w / 2, h)) == "bottom"
        assert item._edge_at(QPointF(w, h)) == "corner"
        assert item._edge_at(QPointF(w / 2, h / 2)) is None

    def test_unselected_has_no_edges(self, window):
        item = self._note(window)
        item.setSelected(False)
        w, h = item.width, item.body_height
        assert item._edge_at(QPointF(w, h)) is None

    def test_plain_node_never_resizes(self, window):
        node = window.registry.instantiate("flopy.util.constant")
        window.graph.add_node(node)
        item = window.scene.node_items[node.id]
        item.setSelected(True)
        w, h = item.width, item.body_height
        assert item._edge_at(QPointF(w, h)) is None


class TestNodeMoveSnap:
    def _note(self, window):
        node = window.registry.instantiate("flopy.util.note")
        window.graph.add_node(node)
        return window.scene.node_items[node.id]

    def test_snaps_only_while_dragging(self, window):
        item = self._note(window)
        window.scene.snap_enabled = True
        window.scene.grid_step = 20

        item._dragging = True
        out = item.itemChange(
            QGraphicsItem.ItemPositionChange, QPointF(23, 38))
        assert (out.x(), out.y()) == (20, 40)

        # programmatic moves (load, nudge, align) must stay exact
        item._dragging = False
        out = item.itemChange(
            QGraphicsItem.ItemPositionChange, QPointF(23, 38))
        assert (out.x(), out.y()) == (23, 38)

    def test_no_snap_when_disabled(self, window):
        item = self._note(window)
        window.scene.snap_enabled = False
        item._dragging = True
        out = item.itemChange(
            QGraphicsItem.ItemPositionChange, QPointF(23, 38))
        assert (out.x(), out.y()) == (23, 38)


# ------------------------------------------------------- tile edge hit-test

def _make_tile(window):
    window.undo_stack.push(
        AddPageCommand(window.graph, Page(id="p1", title="Board")))
    node = window.registry.instantiate("flopy.viz.show_table")
    window.graph.add_node(node)
    window.undo_stack.push(AddTileCommand(
        window.graph, "p1", Tile(id="t1", node_id=node.id, port="table")))
    return window._dashboard_pages["p1"].scene.tile_items["t1"]


class TestTileEdge:
    def test_edges_and_corner(self, window):
        tile = _make_tile(window)
        w, h = tile._size
        assert tile._edge_at(QPointF(w, h / 2)) == "right"
        assert tile._edge_at(QPointF(w / 2, h)) == "bottom"
        assert tile._edge_at(QPointF(w, h)) == "corner"
        assert tile._edge_at(QPointF(w / 2, h / 2)) is None

    def test_move_snap_gated_on_dragging(self, window):
        tile = _make_tile(window)
        scene = window._dashboard_pages["p1"].scene
        scene.snap_enabled = True
        scene.grid_step = 20
        tile._dragging = True
        out = tile.itemChange(
            QGraphicsItem.ItemPositionChange, QPointF(23, 38))
        assert (out.x(), out.y()) == (20, 40)
        tile._dragging = False
        out = tile.itemChange(
            QGraphicsItem.ItemPositionChange, QPointF(23, 38))
        assert (out.x(), out.y()) == (23, 38)


# ---------------------------------------------------- main-window plumbing

class TestSnapSettings:
    def test_toggle_applies_to_all_scenes(self, window):
        # avoid writing real QSettings: flip the action and apply directly
        window.action_snap_grid.blockSignals(True)
        window.action_snap_grid.setChecked(True)
        window.action_snap_grid.blockSignals(False)
        window._apply_snap_settings()
        assert window.scene.snap_enabled is True

        # a page created afterwards inherits the current setting
        window.undo_stack.push(
            AddPageCommand(window.graph, Page(id="pp", title="X")))
        assert window._dashboard_pages["pp"].scene.snap_enabled is True

    def test_default_grid_step_is_normal(self, window):
        assert window._current_grid_step() == grid.DEFAULT_STEP


# ------------------------------------------------------------------- frames

class _FrameDrag:
    def __init__(self, scene_pos, modifiers=Qt.NoModifier):
        self._pos = scene_pos
        self._mods = modifiers

    def scenePos(self):
        return self._pos

    def modifiers(self):
        return self._mods

    def accept(self):
        pass


class TestFrameSnap:
    def _frame(self, window):
        window.undo_stack.push(AddFrameCommand(
            window.graph, Frame(id="f1", rect=(0, 0, 400, 260))))
        return window.scene.frame_items["f1"]

    def test_resize_snaps_size(self, window):
        frame = self._frame(window)
        window.scene.snap_enabled = True
        window.scene.grid_step = 20
        frame._resizing = True
        frame._press_scene_pos = QPointF(0, 0)
        frame._press_size = (400, 260)
        frame.mouseMoveEvent(_FrameDrag(QPointF(37, 23)))  # 437, 283
        assert frame._size == (440, 280)
        frame._resizing = False

    def test_resize_bypass_with_ctrl(self, window):
        frame = self._frame(window)
        window.scene.snap_enabled = True
        window.scene.grid_step = 20
        frame._resizing = True
        frame._press_scene_pos = QPointF(0, 0)
        frame._press_size = (400, 260)
        frame.mouseMoveEvent(_FrameDrag(QPointF(37, 23), Qt.ControlModifier))
        assert frame._size == (437, 283)
        frame._resizing = False

    def test_move_snaps_only_while_dragging(self, window):
        frame = self._frame(window)
        window.scene.snap_enabled = True
        window.scene.grid_step = 20
        frame._dragging = True
        out = frame.itemChange(
            QGraphicsItem.ItemPositionChange, QPointF(23, 38))
        assert (out.x(), out.y()) == (20, 40)
        frame._dragging = False
        out = frame.itemChange(
            QGraphicsItem.ItemPositionChange, QPointF(23, 38))
        assert (out.x(), out.y()) == (23, 38)
