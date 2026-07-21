"""Snap-to-grid: the snap math, edge hit-testing on cards/tiles, the
_dragging gate on move snapping, and the main-window toggle propagation.

Snap-to-grid and grid resolution live in Settings > Canvas (moved off the
main toolbar) and default to enabled -- see mainwindow.py's
set_snap_enabled/set_grid_step.

Settings kept off the real store (avoid polluting the developer's actual
flograph.conf) -- see test_lod_settings.py's fixture of the same name."""
import pytest
from PySide6.QtCore import QPointF, QSettings, Qt
from PySide6.QtWidgets import QCheckBox, QComboBox, QGraphicsItem

from flograph.core import Frame, NodeRegistry, Page, Tile
from flograph.ui import mainwindow as mod
from flograph.ui.canvas import grid
from flograph.ui.commands import AddFrameCommand, AddPageCommand, AddTileCommand
from flograph.ui.mainwindow import MainWindow
from flograph.ui.settings_dialog import SettingsDialog


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
        node = window.registry.instantiate("flograph.util.note")
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
        node = window.registry.instantiate("flograph.util.constant")
        window.graph.add_node(node)
        item = window.scene.node_items[node.id]
        item.setSelected(True)
        w, h = item.width, item.body_height
        assert item._edge_at(QPointF(w, h)) is None


class TestNodeMoveSnap:
    def _note(self, window):
        node = window.registry.instantiate("flograph.util.note")
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
    node = window.registry.instantiate("flograph.viz.show_table")
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
    def test_defaults_to_enabled(self, window):
        assert window.snap_enabled is True
        assert window.scene.snap_enabled is True

    def test_toggle_applies_to_all_scenes(self, window):
        window.set_snap_enabled(False)
        assert window.scene.snap_enabled is False

        # a page created afterwards inherits the current setting
        window.undo_stack.push(
            AddPageCommand(window.graph, Page(id="pp", title="X")))
        assert window._dashboard_pages["pp"].scene.snap_enabled is False

    def test_default_grid_step_is_normal(self, window):
        assert window.grid_step == grid.DEFAULT_STEP

    def test_set_grid_step_applies_to_all_scenes(self, window):
        window.set_grid_step(grid.GRID_PRESETS["Compact"])
        assert window.scene.grid_step == grid.GRID_PRESETS["Compact"]

    def test_persists_to_settings(self, window):
        window.set_snap_enabled(False)
        window.set_grid_step(grid.GRID_PRESETS["Relaxed"])
        assert window.settings.value("snap/enabled", type=bool) is False
        assert window.settings.value("snap/step", type=float) == \
            grid.GRID_PRESETS["Relaxed"]

    def test_reads_persisted_settings_on_construction(self, qtbot, registry,
                                                        window):
        window.set_snap_enabled(False)
        window.set_grid_step(grid.GRID_PRESETS["Compact"])
        second = MainWindow(registry)
        second.confirm_close = False
        qtbot.addWidget(second)
        assert second.snap_enabled is False
        assert second.grid_step == grid.GRID_PRESETS["Compact"]


class TestSnapSettingsDialog:
    def test_checkbox_and_combo_reflect_initial_state(self, window):
        dlg = SettingsDialog(window, window)
        checkbox = dlg.findChild(QCheckBox, "snap_enabled_checkbox")
        combo = dlg.findChild(QComboBox, "grid_step_combo")
        assert checkbox is not None and combo is not None
        assert checkbox.isChecked() is True
        assert combo.currentData() == grid.DEFAULT_STEP
        assert combo.isEnabled()

    def test_unchecking_disables_the_setting_and_the_combo(self, window):
        dlg = SettingsDialog(window, window)
        checkbox = dlg.findChild(QCheckBox, "snap_enabled_checkbox")
        combo = dlg.findChild(QComboBox, "grid_step_combo")

        checkbox.setChecked(False)
        assert window.snap_enabled is False
        assert window.scene.snap_enabled is False
        assert not combo.isEnabled()

    def test_changing_the_combo_updates_the_grid_step(self, window):
        dlg = SettingsDialog(window, window)
        combo = dlg.findChild(QComboBox, "grid_step_combo")

        compact_index = list(grid.GRID_PRESETS).index("Compact")
        combo.setCurrentIndex(compact_index)
        assert window.grid_step == grid.GRID_PRESETS["Compact"]
        assert window.scene.grid_step == grid.GRID_PRESETS["Compact"]


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


# --------------------------------------------------- multi-select group drag

class TestGroupDragSnap:
    """Dragging a multi-selection must snap *every* selected node and frame,
    not just the item under the cursor, and commit them as one move
    (issues.md #5)."""

    def _selection(self, window):
        scene = window.scene
        scene.snap_enabled = True
        scene.grid_step = 20
        n1 = window.registry.instantiate("flograph.util.note")
        n2 = window.registry.instantiate("flograph.util.note")
        window.graph.add_node(n1)
        window.graph.add_node(n2)
        i1 = scene.node_items[n1.id]
        i2 = scene.node_items[n2.id]
        i1.setPos(23, 38)   # off-grid; _dragging is False so it stays put
        i2.setPos(111, 47)
        window.undo_stack.push(AddFrameCommand(
            window.graph, Frame(id="gf", rect=(63, 57, 400, 260))))
        frame = scene.frame_items["gf"]
        for item in (i1, i2, frame):
            item.setSelected(True)
        return scene, i1, i2, frame

    def test_all_selected_items_snap(self, window):
        scene, i1, i2, frame = self._selection(window)
        starts = scene.begin_group_drag()
        # the regression: the non-anchor items must snap too, not just one
        for item in (i1, i2, frame):
            assert item._dragging is True
            out = item.itemChange(
                QGraphicsItem.ItemPositionChange, QPointF(23, 38))
            assert (out.x(), out.y()) == (20, 40)
        assert set(starts["nodes"]) == {i1.node.id, i2.node.id}
        assert set(starts["frames"]) == {"gf"}

    def test_group_move_commits_nodes_and_frame(self, window):
        scene, i1, i2, frame = self._selection(window)
        starts = scene.begin_group_drag()
        i1.setPos(60, 60)   # simulate the drag (snapped while _dragging)
        i2.setPos(140, 80)
        frame.setPos(80, 80)
        scene.commit_group_move(starts)

        assert i1._dragging is False and frame._dragging is False
        assert window.graph.nodes[i1.node.id].pos == (60, 60)
        assert window.graph.nodes[i2.node.id].pos == (140, 80)
        assert window.graph.frames["gf"].rect == (80, 80, 400, 260)

        # the whole selection reverts in a single undo step
        window.undo_stack.undo()
        assert window.graph.nodes[i1.node.id].pos == (23, 38)
        assert window.graph.frames["gf"].rect == (63, 57, 400, 260)

    def test_nothing_moved_pushes_no_command(self, window):
        scene, i1, i2, frame = self._selection(window)
        before = scene.undo_stack.index()
        starts = scene.begin_group_drag()
        scene.commit_group_move(starts)   # released without moving
        assert scene.undo_stack.index() == before
        assert i1._dragging is False and frame._dragging is False
