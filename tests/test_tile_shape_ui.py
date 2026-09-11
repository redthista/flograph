"""Setting the shape a visual takes on a dashboard page (N3).

The Shape menu on a tile's right-click, the Size and Shape dialog, and a
resize drag that keeps a stated shape. The arithmetic underneath is
test_tile_aspect.py.

Settings kept off the real store (avoid polluting the developer's actual
flograph.conf) -- see test_lod_settings.py's fixture of the same name."""
import pytest
from PySide6.QtCore import QPointF, QSettings, Qt
from PySide6.QtGui import QContextMenuEvent
from PySide6.QtWidgets import QMenu

from flograph.core import Page, Tile
from flograph.ui import mainwindow as mod
from flograph.ui.commands import (AddPageCommand, AddTileCommand,
                                  DuplicatePageCommand)
from flograph.ui.dashboard import dashboard_view, tile_shape
from flograph.ui.mainwindow import MainWindow


@pytest.fixture(autouse=True)
def _isolated_settings(tmp_path, monkeypatch):
    ini_path = str(tmp_path / "test_settings.ini")
    monkeypatch.setattr(
        mod, "QSettings",
        lambda *a, **k: QSettings(ini_path, QSettings.IniFormat))


@pytest.fixture(autouse=True)
def _clean_tile_clipboard():
    """The clipboard is a class attribute; one test's copy must not be the
    next test's paste."""
    dashboard_view.DashboardView._tile_clipboard = None
    yield
    dashboard_view.DashboardView._tile_clipboard = None


@pytest.fixture
def window(qtbot, registry):
    win = MainWindow(registry)
    win.confirm_close = False
    qtbot.addWidget(win)
    return win


def _page(window):
    window.undo_stack.push(
        AddPageCommand(window.graph, Page(id="p1", title="Board")))
    page = window._dashboard_pages["p1"]
    page.view.resize(900, 600)
    page.scene.snap_enabled = False   # exact sizes, not the grid's
    return page


def _tile(window, tile_id="t1", rect=(0.0, 0.0, 300.0, 200.0), aspect=None,
          type_id="flograph.viz.card", port="value"):
    node = window.registry.instantiate(type_id, pos=(0, 0))
    window.graph.add_node(node)
    window.undo_stack.push(AddTileCommand(
        window.graph, "p1",
        Tile(id=tile_id, node_id=node.id, port=port, rect=rect,
             aspect=aspect)))
    return window.graph.pages["p1"].tiles[tile_id]


def _menu(monkeypatch, pick=None) -> dict:
    """What the tile menu showed, and — when `pick` names a Shape entry —
    that entry chosen, so what the choice does actually runs. A QMenu
    subclass swapped into the module: exec is a C++ slot, and patching it
    leaves a real popup waiting for a click that never comes."""
    shown: dict = {}

    class _Recorder(QMenu):
        def exec(self, *args):
            shown["top"] = [a.text() for a in self.actions()]
            shape = next((a.menu() for a in self.actions()
                          if a.text() == "Shape"), None)
            shown["enabled"] = shape is not None and shape.isEnabled()
            entries = [a for a in (shape.actions() if shape else [])
                       if not a.isSeparator()]
            shown["shape"] = [a.text() for a in entries]
            shown["ticked"] = [a.text() for a in entries if a.isChecked()]
            return next((a for a in entries if a.text() == pick), None)
    monkeypatch.setattr(dashboard_view, "QMenu", _Recorder)
    return shown


def _right_click(page, tile_id="t1"):
    centre = page.view.mapFromScene(
        page.scene.tile_items[tile_id].sceneBoundingRect().center())
    page.view.contextMenuEvent(QContextMenuEvent(
        QContextMenuEvent.Mouse, centre,
        page.view.viewport().mapToGlobal(centre)))


class _Drag:
    def __init__(self, scene_pos, modifiers=Qt.NoModifier):
        self._pos = scene_pos
        self._mods = modifiers

    def scenePos(self):
        return self._pos

    def modifiers(self):
        return self._mods

    def accept(self):
        pass


class TestTheShapeMenu:
    def test_every_named_shape_is_offered(self, window, monkeypatch):
        page = _page(window)
        _tile(window)
        shown = _menu(monkeypatch)
        _right_click(page)
        assert "Shape" in shown["top"]
        assert shown["shape"][0] == "Any Shape"
        for label in ("Banner\t3:1", "Wide\t16:9", "Square\t1:1",
                      "Tall\t9:16", "Column\t1:3"):
            assert label in shown["shape"]
        assert shown["shape"][-1] == "Size and Shape…"

    def test_a_free_tile_ticks_any_shape(self, window, monkeypatch):
        page = _page(window)
        _tile(window)
        shown = _menu(monkeypatch)
        _right_click(page)
        assert shown["ticked"] == ["Any Shape"]

    def test_a_shaped_tile_ticks_its_shape(self, window, monkeypatch):
        page = _page(window)
        _tile(window, rect=(0, 0, 320, 180), aspect=16 / 9)
        shown = _menu(monkeypatch)
        _right_click(page)
        assert shown["ticked"] == ["Wide\t16:9"]

    def test_a_typed_shape_is_ticked_too(self, window, monkeypatch):
        """A shape from the dialog that is none of the named ones still
        shows — the menu must not call a shaped tile free."""
        page = _page(window)
        _tile(window, rect=(0, 0, 500, 200), aspect=2.5)
        shown = _menu(monkeypatch)
        _right_click(page)
        assert shown["ticked"] == ["Custom\t5:2"]

    def test_an_action_button_has_no_shape(self, window, monkeypatch):
        page = _page(window)
        _tile(window, rect=(0, 0, 150, 50),
              type_id="flograph.util.action_button", port=None)
        shown = _menu(monkeypatch)
        _right_click(page)
        assert "Shape" in shown["top"]
        assert shown["enabled"] is False


class TestChoosingAShape:
    def test_the_width_stays_and_the_height_follows(self, window,
                                                    monkeypatch):
        page = _page(window)
        tile = _tile(window, rect=(20, 40, 320, 200))
        _menu(monkeypatch, pick="Wide\t16:9")
        _right_click(page)
        assert tile.rect == (20, 40, 320, 180)
        assert tile.aspect == pytest.approx(16 / 9)
        # the item on the page follows the model
        assert page.scene.tile_items["t1"]._size == (320, 180)

    def test_one_undo_puts_back_the_size_and_the_shape(self, window,
                                                       monkeypatch):
        page = _page(window)
        tile = _tile(window, rect=(20, 40, 320, 200))
        _menu(monkeypatch, pick="Square\t1:1")
        _right_click(page)
        assert tile.rect == (20, 40, 320, 320)
        window.undo_stack.undo()
        assert tile.rect == (20, 40, 320, 200)
        assert tile.aspect is None

    def test_any_shape_frees_it_and_leaves_the_size(self, window,
                                                    monkeypatch):
        page = _page(window)
        tile = _tile(window, rect=(0, 0, 320, 180), aspect=16 / 9)
        _menu(monkeypatch, pick="Any Shape")
        _right_click(page)
        assert tile.aspect is None
        assert tile.rect == (0, 0, 320, 180)

    def test_every_selected_tile_takes_it(self, window, monkeypatch):
        page = _page(window)
        first = _tile(window, "t1", rect=(0, 0, 300, 200))
        second = _tile(window, "t2", rect=(400, 0, 240, 100))
        for item in page.scene.tile_items.values():
            item.setSelected(True)
        _menu(monkeypatch, pick="Square\t1:1")
        _right_click(page, "t1")
        assert first.rect[2:] == (300, 300)
        assert second.rect[2:] == (240, 240)
        window.undo_stack.undo()        # both, in one step
        assert first.rect[2:] == (300, 200)
        assert second.rect[2:] == (240, 100)

    def test_a_mixed_selection_ticks_nothing(self, window, monkeypatch):
        page = _page(window)
        _tile(window, "t1", rect=(0, 0, 320, 180), aspect=16 / 9)
        _tile(window, "t2", rect=(400, 0, 200, 200), aspect=1.0)
        for item in page.scene.tile_items.values():
            item.setSelected(True)
        shown = _menu(monkeypatch)
        _right_click(page, "t1")
        assert shown["ticked"] == []

    def test_the_same_shape_again_is_not_an_undo_step(self, window,
                                                      monkeypatch):
        page = _page(window)
        _tile(window, rect=(0, 0, 320, 180), aspect=16 / 9)
        before = window.undo_stack.count()
        _menu(monkeypatch, pick="Wide\t16:9")
        _right_click(page)
        assert window.undo_stack.count() == before


class _FakeDialog:
    answer = ((500.0, 250.0), 2.0)
    seen: tuple = ()
    accept = True

    def __init__(self, size, aspect, count, parent):
        _FakeDialog.seen = (size, aspect, count)

    def exec(self):
        return 1 if self.accept else 0

    def values(self):
        return self.answer


class TestSizeAndShape:
    def test_the_dialog_starts_from_the_tile(self, window, monkeypatch):
        page = _page(window)
        _tile(window, rect=(0, 0, 320, 180), aspect=16 / 9)
        monkeypatch.setattr(tile_shape, "TileSizeDialog", _FakeDialog)
        _menu(monkeypatch, pick="Size and Shape…")
        _right_click(page)
        size, aspect, count = _FakeDialog.seen
        assert size == (320, 180)
        assert aspect == pytest.approx(16 / 9)
        assert count == 1

    def test_its_numbers_go_to_every_selected_tile(self, window,
                                                   monkeypatch):
        page = _page(window)
        first = _tile(window, "t1", rect=(0, 0, 300, 200))
        second = _tile(window, "t2", rect=(400, 40, 240, 100))
        for item in page.scene.tile_items.values():
            item.setSelected(True)
        monkeypatch.setattr(tile_shape, "TileSizeDialog", _FakeDialog)
        _menu(monkeypatch, pick="Size and Shape…")
        _right_click(page, "t1")
        assert first.rect == (0, 0, 500, 250)
        assert second.rect == (400, 40, 500, 250)   # each keeps its place
        assert first.aspect == second.aspect == 2.0
        assert _FakeDialog.seen[2] == 2

    def test_cancel_changes_nothing(self, window, monkeypatch):
        page = _page(window)
        tile = _tile(window, rect=(0, 0, 300, 200))
        monkeypatch.setattr(tile_shape, "TileSizeDialog", _FakeDialog)
        monkeypatch.setattr(_FakeDialog, "accept", False)
        before = window.undo_stack.count()
        _menu(monkeypatch, pick="Size and Shape…")
        _right_click(page)
        assert tile.rect == (0, 0, 300, 200)
        assert window.undo_stack.count() == before


class TestTheDialog:
    def _dialog(self, qtbot, size=(320, 200), aspect=None):
        dialog = tile_shape.TileSizeDialog(size, aspect)
        qtbot.addWidget(dialog)
        return dialog

    def test_choosing_a_shape_keeps_the_width(self, qtbot):
        dialog = self._dialog(qtbot)
        dialog.shape_box.setEditText("16:9  Wide")
        assert dialog.values() == ((320.0, 180.0), pytest.approx(16 / 9))

    def test_with_a_shape_the_sides_move_together(self, qtbot):
        dialog = self._dialog(qtbot, (320, 180), 16 / 9)
        dialog.width_box.setValue(640)
        assert dialog.height_box.value() == 360
        dialog.height_box.setValue(180)
        assert dialog.width_box.value() == 320

    def test_without_one_they_do_not(self, qtbot):
        dialog = self._dialog(qtbot)
        dialog.width_box.setValue(640)
        assert dialog.values() == ((640.0, 200.0), None)

    def test_a_typed_ratio_is_a_shape(self, qtbot):
        dialog = self._dialog(qtbot, (500, 200))
        dialog.shape_box.setEditText("5:2")
        assert dialog.values() == ((500.0, 200.0), 2.5)

    def test_words_that_are_not_a_shape_hold_ok_back(self, qtbot):
        dialog = self._dialog(qtbot)
        dialog.shape_box.setEditText("banana")
        assert not dialog._ok.isEnabled()
        assert "not a shape" in dialog.problem.text()
        dialog.shape_box.setEditText("4:3")
        assert dialog._ok.isEnabled()

    def test_it_opens_on_the_tile_s_shape(self, qtbot):
        dialog = self._dialog(qtbot, (320, 180), 16 / 9)
        assert dialog.shape_box.currentText() == "16:9  Wide"


class TestDraggingAShapedTile:
    def _drag(self, item, edge, delta, modifiers=Qt.NoModifier):
        item._resizing = True
        item._resize_edge = edge
        item._press_size = item._size
        item._press_pos = item.pos()
        item._press_scene_pos = QPointF(0, 0)
        item.mouseMoveEvent(_Drag(QPointF(*delta), modifiers))
        item.mouseReleaseEvent(_Drag(QPointF(*delta), modifiers))
        return item._size

    def test_the_right_edge_brings_the_height(self, window):
        page = _page(window)
        tile = _tile(window, rect=(0, 0, 320, 180), aspect=16 / 9)
        item = page.scene.tile_items["t1"]
        assert self._drag(item, "right", (320, 0)) == (640, 360)
        assert tile.rect[2:] == (640, 360)       # and it was saved
        assert tile.aspect == pytest.approx(16 / 9)

    def test_the_bottom_edge_brings_the_width(self, window):
        page = _page(window)
        _tile(window, rect=(0, 0, 320, 180), aspect=16 / 9)
        item = page.scene.tile_items["t1"]
        assert self._drag(item, "bottom", (0, 90)) == (480, 270)

    def test_the_corner_follows_the_bigger_pull(self, window):
        page = _page(window)
        _tile(window, rect=(0, 0, 400, 200), aspect=2.0)
        item = page.scene.tile_items["t1"]
        # +10% across, +50% down: the height leads
        assert self._drag(item, "corner", (40, 100)) == (600, 300)

    def test_a_shape_holds_at_the_smallest_size(self, window):
        page = _page(window)
        _tile(window, rect=(0, 0, 200, 600), aspect=1 / 3)
        item = page.scene.tile_items["t1"]
        assert self._drag(item, "right", (-500, 0)) == (160, 480)

    def test_a_free_tile_is_free(self, window):
        page = _page(window)
        _tile(window, rect=(0, 0, 300, 200))
        item = page.scene.tile_items["t1"]
        assert self._drag(item, "right", (150, 0)) == (450, 200)

    def test_shift_keeps_a_free_tile_s_shape(self, window):
        page = _page(window)
        tile = _tile(window, rect=(0, 0, 300, 200))
        item = page.scene.tile_items["t1"]
        assert self._drag(item, "right", (150, 0),
                          Qt.ShiftModifier) == (450, 300)
        assert tile.aspect is None      # held for the drag, not stated

    def test_a_shaped_edge_promises_the_diagonal(self, window):
        page = _page(window)
        _tile(window, rect=(0, 0, 320, 180), aspect=16 / 9)
        item = page.scene.tile_items["t1"]
        item._apply_edge_cursor(QPointF(320, 90))
        assert item.cursor().shape() == Qt.SizeFDiagCursor


class TestTheShapeTravels:
    def test_copy_and_paste(self, window):
        page = _page(window)
        _tile(window, rect=(0, 0, 320, 180), aspect=16 / 9)
        item = page.scene.tile_items["t1"]
        page.view._copy_tiles(item)
        page.view._paste_tiles(anchor=item)
        pasted = [t for t in window.graph.pages["p1"].tiles.values()
                  if t.id != "t1"]
        assert len(pasted) == 1
        assert pasted[0].aspect == pytest.approx(16 / 9)

    def test_duplicating_the_page(self, window):
        _page(window)
        _tile(window, rect=(0, 0, 320, 180), aspect=16 / 9)
        window.undo_stack.push(DuplicatePageCommand(window.graph, "p1"))
        copy = next(p for p in window.graph.pages.values() if p.id != "p1")
        assert [t.aspect for t in copy.tiles.values()] == \
            [pytest.approx(16 / 9)]
