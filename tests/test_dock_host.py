"""The right-click menu over a dock title bar (QMainWindow.createPopupMenu).

Qt's default build of that menu sends a re-opened dock back to wherever it
last lived. DockHost changes only the "turn it on" path: the dock lands in
the dock you right-clicked. Turning one off, and the menu when the click
missed every dock, are unchanged.

Logical state only -- which docks are hidden, which tab group they sit in
-- so nothing here shows a top-level window (see test_dock_edges.py's
docstring for why that is avoided under the offscreen harness).
"""
import pytest
from PySide6.QtCore import QSettings

from flograph.core import NodeRegistry
from flograph.ui import mainwindow as mod


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
    return win


def _action(menu, title):
    for action in menu.actions():
        if action.text() == title:
            return action
    raise AssertionError(f"no {title!r} action in the menu")


def test_reopening_a_dock_lands_it_in_the_right_clicked_one(window):
    """Navigator starts closed on the right. Right-click Library (left
    edge), turn Navigator on -> it tabs in beside Library, not back on the
    right."""
    host = window._dock_host
    assert window.navigator_dock.isHidden()

    host._menu_target = window.library_dock
    menu = host.createPopupMenu()
    _action(menu, "Navigator").setChecked(True)

    assert not window.navigator_dock.isHidden()
    assert window.navigator_dock in host.tabifiedDockWidgets(
        window.library_dock)


def test_reopened_dock_is_kept_open_across_a_page_round_trip(window):
    """_reveal_dock bookkeeping has to run, or the next page switch closes
    it again."""
    host = window._dock_host
    host._menu_target = window.library_dock
    menu = host.createPopupMenu()
    _action(menu, "Navigator").setChecked(True)

    assert window.navigator_dock in window._docks_open_on_model_page


def test_no_target_leaves_the_dock_where_it_was(window):
    """Click that missed every dock: plain show(), so Navigator comes back
    in its own right-hand tab group."""
    host = window._dock_host
    host._menu_target = None
    menu = host.createPopupMenu()
    _action(menu, "Navigator").setChecked(True)

    assert not window.navigator_dock.isHidden()
    assert window.navigator_dock not in host.tabifiedDockWidgets(
        window.library_dock)


def test_turning_a_dock_off_still_just_closes_it(window):
    host = window._dock_host
    assert not window.library_dock.isHidden()

    host._menu_target = window.properties_dock
    menu = host.createPopupMenu()
    _action(menu, "Node Library").setChecked(False)

    assert window.library_dock.isHidden()


def test_menu_lists_every_dock_with_its_visibility(window):
    host = window._dock_host
    host._menu_target = None
    menu = host.createPopupMenu()

    checked = {a.text(): a.isChecked() for a in menu.actions() if a.text()}
    assert checked["Properties"] is True
    assert checked["Navigator"] is False
