"""Between two panels there is one 1px line, in every theme — not the divider
plus Qt's own frames round the docks, lists and canvas (which read as three)."""
import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QDockWidget

from flograph.core import NodeRegistry
from flograph.ui import mainwindow as mod
from flograph.ui import theme


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    ini = str(tmp_path / "s.ini")
    monkeypatch.setattr(
        mod, "QSettings", lambda *a, **k: QSettings(ini, QSettings.IniFormat))
    yield
    app = QApplication.instance()
    if app is not None:
        theme.apply_theme(app, "dark")


@pytest.fixture(scope="module")
def registry():
    reg = NodeRegistry()
    reg.load_builtins()
    return reg


@pytest.mark.parametrize("name", ["dark", "light", "light_steel"])
def test_a_line_under_the_page_tabs(qtbot, registry, name):
    win = mod.MainWindow(registry)
    win.confirm_close = False
    qtbot.addWidget(win)
    theme.apply_theme(QApplication.instance(), name)
    win.resize(1300, 800)
    win.show()
    qtbot.waitExposed(win)
    qtbot.wait(300)
    host = win.page_bar_host
    bottom = host.mapTo(win, host.rect().bottomLeft()).y()   # its last row
    image = win.grab().toImage()
    line = theme.color("ui", "divider").name()
    assert image.pixelColor(700, bottom).name() == line
    assert image.pixelColor(700, bottom - 1).name() != line   # the tabs
    assert image.pixelColor(700, bottom + 1).name() != line   # the canvas
    # and it follows the tabs when they are put at the bottom instead
    win.set_page_bar_position("bottom")
    qtbot.wait(300)
    top = win.page_bar_host.mapTo(win, win.page_bar_host.rect().topLeft()).y()
    assert win.grab().toImage().pixelColor(700, top).name() == line


@pytest.mark.parametrize("name", ["dark", "light", "light_steel"])
def test_one_line_between_the_canvas_and_the_right_panels(
        qtbot, registry, name):
    win = mod.MainWindow(registry)
    win.confirm_close = False
    qtbot.addWidget(win)
    app = QApplication.instance()
    theme.apply_theme(app, name)
    win.resize(1300, 800)
    win.show()
    qtbot.waitExposed(win)
    qtbot.wait(300)
    docks = [d for d in win.findChildren(QDockWidget)
             if d.isVisible() and d.windowTitle() == "Properties"]
    assert docks, "the Properties dock should be open"
    dock = docks[0]
    image = win.grab().toImage()
    # the dock's left edge, in window coordinates; the divider is just left
    x = dock.mapTo(win, dock.rect().topLeft()).x() - 1
    y = 450
    line = theme.color("ui", "divider").name()
    assert image.pixelColor(x, y).name() == line
    # nothing but panel surface either side of it: no second and third line
    # (a few shades of difference is shading; Qt's old frames were 30-60)
    def near(a, b, tolerance=16):
        return all(abs(p - q) <= tolerance for p, q in zip(
            (a.red(), a.green(), a.blue()), (b.red(), b.green(), b.blue())))
    assert near(image.pixelColor(x - 1, y), image.pixelColor(x - 4, y))
    assert near(image.pixelColor(x + 1, y), image.pixelColor(x + 4, y))
