"""The run actions' home.

With the native OS frame they sit on a flat toolbar (this file). With
flograph's own title bar they move onto the bar — see test_window_frame.
Undo/Redo are on neither; they live in the Edit menu.
"""
import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QMenu, QToolBar

from flograph.core import NodeRegistry
from flograph.ui.mainwindow import MainWindow
from flograph.ui import toolbar as toolbar_style


@pytest.fixture(scope="module")
def registry():
    reg = NodeRegistry()
    reg.load_builtins()
    return reg


@pytest.fixture
def native_window(qtbot, registry):
    """A MainWindow forced onto the native OS frame."""
    s = QSettings("flograph", "flograph")
    prior = s.value("window/custom_frame", True, type=bool)
    s.setValue("window/custom_frame", False)
    try:
        win = MainWindow(registry)
        win.confirm_close = False
        qtbot.addWidget(win)
        yield win
    finally:
        s.setValue("window/custom_frame", prior)


def _main_toolbar(win) -> QToolBar:
    return win.findChild(QToolBar, "toolbar_main")


def test_toolbar_carries_run_actions_and_reset_not_undo(native_window):
    labels = [a.text() for a in _main_toolbar(native_window).actions() if a.text()]
    assert labels == ["Run All", "Run Selected", "Cancel",
                      "Reset Selected Caches", "Reset Caches"]


def test_undo_redo_stay_in_the_edit_menu(native_window):
    edit = next(m for m in native_window._menu_root.findChildren(QMenu)
                if m.title() == "&Edit")
    assert {"Undo", "Redo"} <= {a.text() for a in edit.actions()}


def test_run_and_reset_actions_have_icons(native_window):
    for name in ("action_run", "action_run_selected",
                 "action_cancel", "action_reset_caches"):
        assert not getattr(native_window, name).icon().isNull()


def test_toolbar_is_styled_and_fixed(native_window):
    tb = _main_toolbar(native_window)
    assert not tb.isMovable() and not tb.isFloatable()
    assert "border-radius" in tb.styleSheet()


@pytest.mark.parametrize("kind",
                         ["run_all", "run_selected", "cancel", "reset_caches"])
def test_every_glyph_renders(kind):
    icon = toolbar_style.toolbar_icon(kind)
    assert not icon.isNull()
    assert icon.availableSizes()
