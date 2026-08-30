"""flograph's own title bar (window/custom_frame, the default).

The OS decorations are gone; one bar carries the app mark, a hamburger
holding the whole menu tree, the open-workflow switcher, the run actions
and the minimise / maximise / close buttons. Move and resize are handed
to the compositor, which the offscreen platform cannot exercise — so the
tests here cover the wiring, not the drag.
"""
import pytest
from PySide6.QtCore import QEvent, QSettings, Qt
from PySide6.QtGui import QUndoCommand

from flograph.core import NodeRegistry
from flograph.ui import window_frame
from flograph.ui.mainwindow import MainWindow


@pytest.fixture(scope="module")
def registry():
    reg = NodeRegistry()
    reg.load_builtins()
    return reg


@pytest.fixture
def frame_window(qtbot, registry):
    s = QSettings("flograph", "flograph")
    prior = s.value("window/custom_frame", True, type=bool)
    s.setValue("window/custom_frame", True)
    try:
        win = MainWindow(registry)
        win.confirm_close = False
        qtbot.addWidget(win)
        win.show()
        yield win
    finally:
        s.setValue("window/custom_frame", prior)


def test_the_window_is_frameless(frame_window):
    assert frame_window.windowFlags() & Qt.FramelessWindowHint


def test_the_title_bar_replaces_the_menu_widget(frame_window):
    assert frame_window.menuWidget() is frame_window._title_bar


def test_no_toolbar_in_frame_mode(frame_window):
    from PySide6.QtWidgets import QToolBar
    assert not frame_window.findChildren(QToolBar)


def test_hamburger_holds_the_whole_menu_tree(frame_window):
    menu = frame_window._title_bar._menu_btn.menu()
    assert [a.text() for a in menu.actions()] == [
        "&File", "&Edit", "&Run", "&Tools", "&View", "&Help"]


def test_run_actions_are_on_the_bar(frame_window):
    labels = [b.text() for b in frame_window._title_bar._run_btns]
    assert labels == ["Run All", "Run Selected", "Cancel", "Reset Caches"]
    # the buttons drive the window's own actions
    btn = frame_window._title_bar._run_btns[0]
    assert btn.defaultAction() is frame_window.action_run


def test_project_switcher_shows_the_workflow_name(frame_window, tmp_path):
    tb = frame_window._title_bar
    assert tb._project_btn.text() == "untitled"
    frame_window._project_path = str(tmp_path / "sales.flograph")
    frame_window._update_title()
    assert tb._project_btn.text() == "sales.flograph"


def test_project_menu_lists_recent_workflows(frame_window, tmp_path, monkeypatch):
    p = tmp_path / "old.flograph"
    p.write_text("{}")
    monkeypatch.setattr(frame_window, "_recent_files_existing",
                        lambda: [str(p)])
    tb = frame_window._title_bar
    tb._project_menu.aboutToShow.emit()
    texts = [a.text() for a in tb._project_menu.actions()]
    assert "old.flograph" in texts


def test_save_button_tracks_unsaved_changes(frame_window):
    tb = frame_window._title_bar
    assert tb._save_btn.toolTip() == "All changes saved"
    frame_window.undo_stack.push(QUndoCommand("edit"))
    frame_window._update_title()
    assert "Save" in tb._save_btn.toolTip()


def test_project_menu_offers_save(frame_window):
    tb = frame_window._title_bar
    tb._project_menu.aboutToShow.emit()
    texts = [a.text() for a in tb._project_menu.actions()]
    assert "&Save" in texts and "Save &As…" in texts


def test_maximise_button_tracks_window_state(frame_window):
    tb = frame_window._title_bar
    frame_window.showMaximized()
    frame_window._frameless.eventFilter(
        frame_window, QEvent(QEvent.WindowStateChange))
    assert tb._btn_max.toolTip() == "Restore"
    frame_window.showNormal()
    frame_window._frameless.eventFilter(
        frame_window, QEvent(QEvent.WindowStateChange))
    assert tb._btn_max.toolTip() == "Maximise"


def test_eight_resize_grips_exist_and_hide_when_maximised(frame_window):
    fr = frame_window._frameless
    assert len(fr._grips) == 8
    frame_window.showNormal()
    fr._reposition()
    assert all(g.isVisibleTo(frame_window) for g in fr._grips)
    frame_window.showMaximized()
    fr._reposition()
    assert all(not g.isVisible() for g in fr._grips)


@pytest.mark.parametrize("kind", ["logo", "hamburger", "chevron", "save",
                                  "min", "max", "restore", "close"])
def test_frame_glyphs_render(kind):
    icon = window_frame.frame_icon(kind)
    assert not icon.isNull() and icon.availableSizes()


def test_app_icon_has_sizes():
    assert window_frame.app_icon().availableSizes()
