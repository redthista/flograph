"""A tab group has one header: its tabs. A docked panel sharing its spot
with another gets no title bar of its own (it only repeated the current
tab's name under the tabs); alone, floating or closed-down to one, it gets
Qt's title bar back. Float and Close move to the tab's right-click menu.
"""
import pytest
from PySide6.QtCore import QPoint, QSettings
from PySide6.QtWidgets import QTabBar

from flograph.core import NodeRegistry
from flograph.ui import mainwindow as mod


@pytest.fixture(autouse=True)
def _isolated_settings(tmp_path, monkeypatch):
    ini = str(tmp_path / "flograph.ini")
    monkeypatch.setattr(mod, "QSettings",
                        lambda *a, **k: QSettings(ini, QSettings.IniFormat))


@pytest.fixture(scope="module")
def registry():
    reg = NodeRegistry()
    reg.load_builtins()
    return reg


@pytest.fixture
def shown(qtbot, registry):
    win = mod.MainWindow(registry)
    win.confirm_close = False
    qtbot.addWidget(win)
    win.resize(1400, 900)
    win.show()
    qtbot.wait(20)
    return win


def _titled(dock) -> bool:
    bar = dock.titleBarWidget()
    return bar is None or bar.height() > 0


def test_grouped_panels_drop_their_repeated_title(qtbot, shown):
    host = shown._dock_host
    qtbot.waitUntil(lambda: not _titled(shown.properties_dock), timeout=1000)
    assert host.in_group(shown.properties_dock)
    # a panel alone on its edge keeps its title bar
    assert _titled(shown.library_dock)
    assert _titled(shown.inspector_dock)


def test_title_returns_when_the_group_breaks_up(qtbot, shown):
    for dock in (shown.editor_dock, shown.log_dock):
        dock.close()
    qtbot.waitUntil(lambda: _titled(shown.properties_dock), timeout=1000)
    shown.log_dock.show()
    qtbot.waitUntil(lambda: not _titled(shown.properties_dock), timeout=1000)
    shown.log_dock.setFloating(True)
    qtbot.waitUntil(lambda: _titled(shown.log_dock), timeout=1000)


def test_tab_menu_offers_float_and_close(qtbot, shown):
    host = shown._dock_host
    qtbot.waitUntil(lambda: not _titled(shown.properties_dock), timeout=1000)
    bars = [b for b in host.findChildren(QTabBar)
            if b.isVisible() and b.parent() is host and b.count() > 1]
    assert bars
    bar = bars[0]
    index = next(i for i in range(bar.count())
                 if bar.tabText(i) == "Properties")
    pos = bar.mapTo(host, bar.tabRect(index).center())
    assert host._dock_tab_at(pos) is shown.properties_dock
    host._tab_target = shown.properties_dock
    menu = host.createPopupMenu()
    texts = [a.text() for a in menu.actions()]
    assert texts[:2] == ["Float Properties", "Close Properties"]
    menu.actions()[1].trigger()
    assert shown.properties_dock.isHidden()
