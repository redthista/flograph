"""The main window's top toolbar.

It was restyled to a flat, rounded-button look and its contents changed:
Undo/Redo came off (they stay in the Edit menu, where a toolbar button
was only ever a shortcut for the keystroke everyone already knows), and
Reset Caches went on next to the run actions it belongs with.
"""
import pytest
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
def window(qtbot, registry):
    win = MainWindow(registry)
    win.confirm_close = False
    qtbot.addWidget(win)
    return win


def _main_toolbar(win) -> QToolBar:
    return win.findChild(QToolBar, "toolbar_main")


def test_toolbar_carries_run_actions_and_reset_not_undo(window):
    labels = [a.text() for a in _main_toolbar(window).actions() if a.text()]
    assert labels == ["Run All", "Run Selected", "Cancel", "Reset Caches"]


def test_undo_redo_stay_in_the_edit_menu(window):
    edit = next(m for m in window.menuBar().findChildren(QMenu)
                if m.title() == "&Edit")
    assert {"Undo", "Redo"} <= {a.text() for a in edit.actions()}


def test_run_and_reset_actions_have_icons(window):
    for name in ("action_run", "action_run_selected",
                 "action_cancel", "action_reset_caches"):
        assert not getattr(window, name).icon().isNull()


def test_toolbar_is_styled_and_fixed(window):
    tb = _main_toolbar(window)
    assert not tb.isMovable() and not tb.isFloatable()
    assert "border-radius" in tb.styleSheet()


@pytest.mark.parametrize("kind",
                         ["run_all", "run_selected", "cancel", "reset_caches"])
def test_every_glyph_renders(kind):
    icon = toolbar_style.toolbar_icon(kind)
    assert not icon.isNull()
    assert icon.availableSizes()
