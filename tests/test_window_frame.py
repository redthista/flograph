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
from PySide6.QtWidgets import QToolButton, QWidgetAction

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
    saved = {k: s.value(k) for k in ("window/custom_frame",
                                     "window/titlebar_compact",
                                     "window/titlebar_shortcuts")}
    s.setValue("window/custom_frame", True)
    s.setValue("window/titlebar_compact", False)
    s.setValue("window/titlebar_shortcuts", True)
    try:
        win = MainWindow(registry)
        win.confirm_close = False
        qtbot.addWidget(win)
        win.show()
        yield win
    finally:
        for k, v in saved.items():
            if v is None:
                s.remove(k)
            else:
                s.setValue(k, v)


# -- structure --------------------------------------------------------

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


# -- run / stop ------------------------------------------------------

def test_run_button_is_run_all_when_idle(frame_window):
    tb = frame_window._title_bar
    assert tb._run_btn.text().startswith("Run All")
    assert "F5" in tb._run_btn.toolTip()


def test_run_buttons_show_their_shortcut_by_default(frame_window):
    tb = frame_window._title_bar
    w = frame_window
    for btn, action, name in (
            (tb._run_btn, w.action_run, "Run All"),
            (tb._run_sel_btn, w.action_run_selected, "Run Selected"),
            (tb._reset_btn, w.action_reset_caches, "Reset Caches"),
            (tb._clear_cache_btn, w.action_reset_selected_caches,
             "Reset Selected Caches")):
        key = action.shortcut().toString()
        assert key
        assert btn.text() == f"{name}  ({key})"


def test_cache_actions_have_default_shortcuts(frame_window):
    reg = frame_window.shortcuts
    assert reg.entry("reset_caches").default.toString() == "Ctrl+Shift+R"
    assert reg.entry("reset_selected_caches").default.toString() == "Ctrl+R"


def test_reset_caches_shortcut_clears_everything(frame_window):
    a, b = _add_two_nodes(frame_window)
    for n in (a, b):
        frame_window.engine.cache.set(n.id, {"value": 1}, 0.0)
    frame_window.action_reset_caches.trigger()
    assert frame_window.engine.cache.get(a.id) is None
    assert frame_window.engine.cache.get(b.id) is None


def test_view_menu_toggle_hides_the_shortcuts(frame_window):
    tb = frame_window._title_bar
    frame_window._set_titlebar_shortcuts(False)
    assert tb._run_btn.text() == "Run All"
    assert tb._run_sel_btn.text() == "Run Selected"
    assert tb._reset_btn.text() == "Reset Caches"
    assert tb._clear_cache_btn.text() == "Reset Selected Caches"
    frame_window.engine.run_started.emit()
    assert tb._run_btn.text() == "Stop"
    frame_window.engine.run_finished.emit(True)
    frame_window._set_titlebar_shortcuts(True)
    assert tb._run_btn.text() == "Run All  (F5)"


def test_titlebar_shortcuts_action_is_in_the_view_menu(frame_window):
    from PySide6.QtWidgets import QMenu
    view = next(m for m in frame_window._menu_root.findChildren(QMenu)
               if m.title() == "&View")
    assert any("Shortcuts on Title-Bar Buttons" in a.text()
               for a in view.actions())


def test_no_cancel_button_on_the_bar(frame_window):
    tb = frame_window._title_bar
    texts = {b.text() for b in tb.findChildren(QToolButton)}
    assert "Cancel" not in texts


# -- selection ------------------------------------------------------

def _add_two_nodes(window):
    nodes = []
    for i in range(2):
        node = window.registry.instantiate("flograph.util.constant",
                                           pos=(i * 200.0, 0.0))
        window.graph.add_node(node)
        nodes.append(node)
    return nodes


def test_selection_buttons_hidden_with_no_selection(frame_window):
    tb = frame_window._title_bar
    assert not tb._run_sel_btn.isVisibleTo(tb)
    assert not tb._clear_cache_btn.isVisibleTo(tb)


def test_selection_buttons_appear_with_a_selection(frame_window):
    tb = frame_window._title_bar
    nodes = _add_two_nodes(frame_window)
    frame_window.scene.node_items[nodes[0].id].setSelected(True)
    assert tb._run_sel_btn.isVisibleTo(tb)
    assert tb._clear_cache_btn.isVisibleTo(tb)
    assert tb._clear_cache_btn.text().startswith("Reset Selected Caches")
    frame_window.scene.clearSelection()
    assert not tb._run_sel_btn.isVisibleTo(tb)
    assert not tb._clear_cache_btn.isVisibleTo(tb)


def test_clear_cache_button_evicts_only_selected_nodes(frame_window):
    tb = frame_window._title_bar
    a, b = _add_two_nodes(frame_window)
    for n in (a, b):
        frame_window.engine.cache.set(n.id, {"value": 1}, 0.0)
    frame_window.scene.node_items[a.id].setSelected(True)
    tb._clear_cache_btn.click()
    assert frame_window.engine.cache.get(a.id) is None
    assert frame_window.engine.cache.get(b.id) is not None


def test_run_button_becomes_stop_during_a_run(frame_window):
    tb = frame_window._title_bar
    frame_window.engine.run_started.emit()
    assert tb._run_btn.text().startswith("Stop")
    assert "Esc" in tb._run_btn.toolTip()
    assert not tb._run_sel_btn.isEnabled()
    frame_window.engine.run_finished.emit(True)
    assert tb._run_btn.text().startswith("Run All")
    assert tb._run_sel_btn.isEnabled()


def test_clicking_stop_cancels_the_engine(frame_window, monkeypatch):
    tb = frame_window._title_bar
    calls = []
    monkeypatch.setattr(frame_window.engine, "cancel",
                        lambda: calls.append("cancel"))
    monkeypatch.setattr(type(frame_window.engine), "active",
                        property(lambda self: True))
    tb._on_run_clicked()
    assert calls == ["cancel"]


# -- project switcher ----------------------------------------------

def test_switcher_drops_the_flograph_extension(frame_window, tmp_path):
    tb = frame_window._title_bar
    assert tb._project_btn.text() == "untitled"
    frame_window._project_path = str(tmp_path / "sales.flograph")
    frame_window._update_title()
    assert tb._project_btn.text() == "sales"


def test_switcher_carries_an_initials_tile(frame_window, tmp_path):
    tb = frame_window._title_bar
    frame_window._project_path = str(tmp_path / "sales.flograph")
    frame_window._update_title()
    assert not tb._project_btn.icon().isNull()


@pytest.mark.parametrize("name, want", [
    ("sales", "SA"),
    ("quarterly-report", "QR"),
    ("Monthly_Close", "MC"),
    ("q3 numbers final", "QN"),
    ("x", "X"),
])
def test_initials_rule(name, want):
    assert window_frame.initials_for(name) == want


def test_project_menu_offers_save_new_open(frame_window):
    tb = frame_window._title_bar
    tb._project_menu.aboutToShow.emit()
    texts = [a.text() for a in tb._project_menu.actions()]
    assert "&Save" in texts and "Save &As…" in texts
    assert "&New" in texts and "&Open…" in texts


def test_recent_rows_show_name_and_folder(frame_window, tmp_path, monkeypatch):
    proj = tmp_path / "books" / "ledger.flograph"
    proj.parent.mkdir()
    proj.write_text("{}")
    monkeypatch.setattr(frame_window, "_recent_files_existing",
                        lambda: [str(proj)])
    from PySide6.QtWidgets import QLabel
    tb = frame_window._title_bar
    tb._project_menu.aboutToShow.emit()
    rows = [a.defaultWidget() for a in tb._project_menu.actions()
            if isinstance(a, QWidgetAction)]
    assert len(rows) == 1
    texts = [w.text() for w in rows[0].findChildren(QLabel) if w.text()]
    assert "ledger" in texts
    assert any("books" in t for t in texts)


def test_recent_row_opens_the_workflow(frame_window, tmp_path, monkeypatch):
    proj = tmp_path / "old.flograph"
    proj.write_text("{}")
    opened = []
    monkeypatch.setattr(frame_window, "open_path",
                        lambda p, *a, **k: opened.append(p))
    monkeypatch.setattr(frame_window, "_recent_files_existing",
                        lambda: [str(proj)])
    tb = frame_window._title_bar
    tb._project_menu.aboutToShow.emit()
    row = next(a.defaultWidget() for a in tb._project_menu.actions()
               if isinstance(a, QWidgetAction))
    row._on_open(str(proj))
    assert opened == [str(proj)]


# -- save indicator ----------------------------------------------

def test_save_button_hidden_until_dirty(frame_window):
    tb = frame_window._title_bar
    assert not tb._save_btn.isVisibleTo(tb)
    frame_window.undo_stack.push(QUndoCommand("edit"))
    frame_window._update_title()
    assert tb._save_btn.isVisibleTo(tb)
    assert tb._save_btn.text() == "Unsaved changes"


# -- compact ---------------------------------------------------

def test_compact_setting_drops_button_text(frame_window):
    tb = frame_window._title_bar
    assert tb._run_btn.toolButtonStyle() == Qt.ToolButtonTextBesideIcon
    frame_window.set_titlebar_compact(True)
    assert tb._run_btn.toolButtonStyle() == Qt.ToolButtonIconOnly
    assert tb._reset_btn.toolButtonStyle() == Qt.ToolButtonIconOnly
    # the workflow name is not a button label — it stays
    assert tb._project_btn.text() == "untitled"
    frame_window.set_titlebar_compact(False)
    assert tb._run_btn.toolButtonStyle() == Qt.ToolButtonTextBesideIcon


# -- window controls ------------------------------------------

def test_maximise_button_tracks_window_state(frame_window):
    tb = frame_window._title_bar
    frame_window.showMaximized()
    frame_window._frameless.eventFilter(
        frame_window, QEvent(QEvent.WindowStateChange))
    assert "Restore" in tb._btn_max.toolTip()
    frame_window.showNormal()
    frame_window._frameless.eventFilter(
        frame_window, QEvent(QEvent.WindowStateChange))
    assert "Maximise" in tb._btn_max.toolTip()


def test_eight_resize_grips_exist_and_hide_when_maximised(frame_window):
    fr = frame_window._frameless
    assert len(fr._grips) == 8
    frame_window.showNormal()
    fr._reposition()
    assert all(g.isVisibleTo(frame_window) for g in fr._grips)
    frame_window.showMaximized()
    fr._reposition()
    assert all(not g.isVisible() for g in fr._grips)


def test_every_bar_button_has_a_tooltip(frame_window):
    tb = frame_window._title_bar
    for btn in (tb._menu_btn, tb._project_btn, tb._save_btn, tb._run_btn,
                tb._run_sel_btn, tb._clear_cache_btn, tb._reset_btn,
                tb._btn_min, tb._btn_max, tb._btn_close):
        assert btn.toolTip(), btn


# -- glyphs ----------------------------------------------------

@pytest.mark.parametrize("kind", ["logo", "hamburger", "chevron", "save",
                                  "clear_cache", "min", "max", "restore",
                                  "close"])
def test_frame_glyphs_render(kind):
    icon = window_frame.frame_icon(kind)
    assert not icon.isNull() and icon.availableSizes()


def test_app_icon_has_sizes():
    assert window_frame.app_icon().availableSizes()


def test_initials_pixmap_is_drawn():
    pm = window_frame.initials_pixmap("sales report", 30)
    assert not pm.isNull() and pm.width() == 30
