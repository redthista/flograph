"""Spare dashboard tiles are destroyed on the main thread.

A tile and the widget it builds hold each other through signal connections,
so a tile nobody refers to any more is only freed by Python's cycle
collector — which runs on whichever thread happens to allocate. On a flow's
worker thread that deleted a Qt widget off the GUI thread and segfaulted the
app (hover a slicer in the Visuals panel, then Run All). These pin that the
two ways a tile becomes spare delete it themselves.

Settings kept off the real store (avoid polluting the developer's actual
flograph.conf) -- see test_lod_settings.py's fixture of the same name."""
import pytest
import shiboken6
from PySide6.QtCore import QSettings

from flograph.core import Page, Tile
from flograph.ui import mainwindow as mod
from flograph.ui.commands import AddPageCommand, AddTileCommand, RemoveTileCommand
from flograph.ui.dashboard import tile_item
from flograph.ui.mainwindow import MainWindow


@pytest.fixture(autouse=True)
def _isolated_settings(tmp_path, monkeypatch):
    ini_path = str(tmp_path / "test_settings.ini")
    monkeypatch.setattr(
        mod, "QSettings",
        lambda *a, **k: QSettings(ini_path, QSettings.IniFormat))


@pytest.fixture
def window(qtbot, registry):
    win = MainWindow(registry)
    win.confirm_close = False
    qtbot.addWidget(win)
    return win


def _slicer(window):
    node = window.registry.instantiate("flograph.viz.slicer", pos=(0, 0))
    window.graph.add_node(node)
    return node


def test_a_removed_tile_is_deleted_by_the_event_loop(window, qtbot):
    window.undo_stack.push(
        AddPageCommand(window.graph, Page(id="p1", title="Board")))
    node = _slicer(window)
    window.undo_stack.push(AddTileCommand(
        window.graph, "p1", Tile(id="t1", node_id=node.id)))
    item = window._dashboard_pages["p1"].scene.tile_items["t1"]
    window.undo_stack.push(RemoveTileCommand(window.graph, "p1", "t1"))
    qtbot.waitUntil(lambda: not shiboken6.isValid(item), timeout=2000)
    # and undoing the removal still brings the tile back, as a new item
    window.undo_stack.undo()
    assert "t1" in window._dashboard_pages["p1"].scene.tile_items


def test_a_preview_tile_is_deleted_before_the_preview_returns(
        window, monkeypatch):
    from flograph.ui.dashboard import visual_preview
    made = []

    class Recording(tile_item.TileItem):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            made.append(self)

    monkeypatch.setattr(tile_item, "TileItem", Recording)
    node = _slicer(window)
    visual_preview.tile_pixmap(window.graph, window.engine, node)
    assert made, "the preview built no tile"
    assert not shiboken6.isValid(made[0])
