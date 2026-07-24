"""Reset to defaults: MainWindow.reset_settings() / reset_window_layout()
and the two buttons in the Settings dialog footer.

No real MainWindow.show() here — see tests/test_gpu_viewport_setting.py's
module docstring for why that's unsafe under this offscreen test harness.
Both the window's settings store and the spreadsheet module's (a separate
QSettings instance, opened per call) are redirected to a temp file so a reset
can't touch the developer's actual flograph.conf.
"""
import pytest
from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QShowEvent
from PySide6.QtWidgets import QCheckBox, QComboBox, QMessageBox, QPushButton, QSpinBox

from flograph.core import NodeRegistry
from flograph.ui import mainwindow as mod
from flograph.ui import theme
from flograph.ui.canvas import grid
from flograph.ui.canvas.node_item import DEFAULT_LOD_THRESHOLD
from flograph.ui.settings_dialog import SettingsDialog
from flograph.ui.spreadsheet import view as sheet_view


@pytest.fixture(autouse=True)
def _isolated_settings(tmp_path, monkeypatch):
    ini_path = str(tmp_path / "test_settings.ini")

    def _store(*_args, **_kwargs):
        return QSettings(ini_path, QSettings.IniFormat)

    monkeypatch.setattr(mod, "QSettings", _store)
    monkeypatch.setattr(sheet_view, "QSettings", _store)


@pytest.fixture(autouse=True)
def _restore_theme_tints():
    yield
    theme.set_tints(theme.DEFAULT_TINT_SOFT, theme.DEFAULT_TINT_STRONG)


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


def _make_everything_non_default(window) -> None:
    """Move every resettable preference off its shipped value."""
    window.set_page_bar_position("bottom")
    window.set_lod_enabled(False)
    window.set_lod_threshold(0.8)
    window.set_snap_enabled(False)
    window.set_grid_step(40.0)
    window.set_minimap_enabled(False)
    window.set_tints(0.9, 0.1)
    window.settings.setValue("canvas/gpu_viewport", True)
    window._set_visuals_visible(True)
    sheet_view.set_autosize_default(False)
    sheet_view.set_date_formats_setting("%d-%b-%y")


class TestResetSettings:
    def test_every_preference_comes_back(self, window):
        _make_everything_non_default(window)
        window.reset_settings()

        assert window.page_bar_position == mod.DEFAULT_PAGE_BAR_POSITION
        assert window.lod_enabled is mod.DEFAULT_LOD_ENABLED
        assert window.lod_threshold == pytest.approx(DEFAULT_LOD_THRESHOLD)
        assert window.snap_enabled is mod.DEFAULT_SNAP_ENABLED
        assert window.grid_step == pytest.approx(grid.DEFAULT_STEP)
        assert window.minimap_enabled is mod.DEFAULT_MINIMAP_ENABLED
        assert window.tint_soft == pytest.approx(theme.DEFAULT_TINT_SOFT)
        assert window.tint_strong == pytest.approx(theme.DEFAULT_TINT_STRONG)
        assert window.visuals_visible is mod.DEFAULT_VISUALS_VISIBLE
        assert window.action_gpu_viewport.isChecked() is False
        assert sheet_view.autosize_default_enabled() is True
        assert sheet_view.date_formats_setting() == ""

    def test_it_reaches_the_canvas_not_just_the_values(self, window):
        """A reset has to look reset: the live scene/view follow it."""
        window.set_minimap_enabled(False)
        window.set_tints(0.9, 0.9)
        window.reset_settings()
        assert window.view.minimap.isVisibleTo(window.view)
        assert theme.TINT_SOFT == pytest.approx(theme.DEFAULT_TINT_SOFT)
        assert window.scene.grid_step == pytest.approx(grid.DEFAULT_STEP)

    def test_it_survives_a_restart(self, window, registry, qtbot):
        """Reset writes through to the store, so the next launch agrees."""
        _make_everything_non_default(window)
        window.reset_settings()

        reopened = mod.MainWindow(registry)
        reopened.confirm_close = False
        qtbot.addWidget(reopened)
        assert reopened.page_bar_position == mod.DEFAULT_PAGE_BAR_POSITION
        assert reopened.lod_enabled is True
        assert reopened.grid_step == pytest.approx(grid.DEFAULT_STEP)
        assert reopened.minimap_enabled is True
        assert reopened.tint_soft == pytest.approx(theme.DEFAULT_TINT_SOFT)
        assert reopened.visuals_visible is False
        assert reopened.action_gpu_viewport.isChecked() is False

    def test_a_stale_gpu_flag_is_cleared_even_with_the_action_already_off(
            self, window):
        """setChecked() on an already-off action emits nothing — the stored
        value would otherwise stay True and come back on the next launch."""
        window.action_gpu_viewport.setChecked(False)
        window.settings.setValue("canvas/gpu_viewport", True)
        window.reset_settings()
        assert window.settings.value(
            "canvas/gpu_viewport", False, type=bool) is False

    def test_open_dashboard_pages_follow_it(self, window):
        from flograph.core import Page
        from flograph.ui.commands import AddPageCommand
        window.undo_stack.push(
            AddPageCommand(window.graph, Page(id="p1", title="Board")))
        widget = window._dashboard_pages["p1"]
        widget.set_visuals_visible(True)

        window.reset_settings()
        assert not widget._side.isVisibleTo(widget)

    def test_history_and_credentials_are_left_alone(self, window):
        """A reset of *preferences* must not eat unrelated state."""
        window.settings.setValue("recent_files", ["/tmp/a.flograph"])
        window.settings.setValue("ai/api_key", "sk-secret")
        window.reset_settings()
        assert window.settings.value("recent_files") == ["/tmp/a.flograph"]
        assert window.settings.value("ai/api_key") == "sk-secret"


class TestResetWindowLayout:
    def _areas(self, window):
        return {dock.objectName():
                (window._dock_host.dockWidgetArea(dock),
                 dock.isVisibleTo(window._dock_host), dock.isFloating())
                for dock in window._docks}

    def test_it_restores_the_starting_dock_arrangement(self, window):
        started_as = self._areas(window)
        window.library_dock.setVisible(False)
        window.properties_dock.setFloating(True)
        window._dock_host.addDockWidget(Qt.LeftDockWidgetArea,
                                        window.inspector_dock)
        assert self._areas(window) != started_as

        window.reset_window_layout()
        assert self._areas(window) == started_as

    def test_a_closed_panel_comes_back(self, window):
        """The main reason to reach for this: a dock closed and not found
        again in the View menu."""
        for dock in window._docks:
            dock.setVisible(False)
        window.reset_window_layout()
        assert window.library_dock.isVisibleTo(window._dock_host)
        assert window.properties_dock.isVisibleTo(window._dock_host)
        assert window.inspector_dock.isVisibleTo(window._dock_host)

    def test_a_floating_panel_is_docked_again(self, window):
        window.library_dock.setFloating(True)
        window.reset_window_layout()
        assert window.library_dock.isFloating() is False
        assert (window._dock_host.dockWidgetArea(window.library_dock)
                == Qt.LeftDockWidgetArea)

    def test_it_restores_the_starting_size(self, window):
        window.resize(600, 400)
        window.reset_window_layout()
        assert (window.width(), window.height()) == mod.DEFAULT_WINDOW_SIZE

    def test_a_maximized_window_keeps_its_size(self, window):
        """The compositor can refuse a resize while Qt lays the widgets out
        for the size it asked for anyway — panels crammed into a corner of a
        window that never shrank. Panels still reset; the window doesn't."""
        window.setWindowState(Qt.WindowMaximized)
        assert window.isMaximized()
        window.library_dock.setFloating(True)

        window.reset_window_layout()
        assert window.isMaximized()
        assert window.library_dock.isFloating() is False

    def test_it_leaves_a_dashboard_page_alone(self, window):
        """A dashboard page hides the model-only docks to get the screen to
        itself. A reset that shows all five unconditionally drops the Node
        Library, Properties, Code, Inspector and Log on top of the board the
        user is looking at."""
        from flograph.core import Page
        from flograph.ui.commands import AddPageCommand
        window.undo_stack.push(
            AddPageCommand(window.graph, Page(id="p1", title="Board")))
        window.page_bar.select_page("p1")
        assert not window.library_dock.isVisibleTo(window._dock_host)

        window.reset_window_layout()
        for dock in window._docks:
            assert not dock.isVisibleTo(window._dock_host), dock.objectName()

    def test_the_model_page_still_gets_its_docks_back(self, window):
        for dock in window._docks:
            dock.setVisible(False)
        assert window.page_bar.current_page_id() is None
        window.reset_window_layout()
        assert window.library_dock.isVisibleTo(window._dock_host)

    def test_the_saved_layout_is_reset_too(self, window):
        """Otherwise the old arrangement comes straight back on relaunch."""
        window.settings.setValue("window_geometry", window.saveGeometry())
        window.reset_window_layout()
        assert window.settings.value("window_geometry") is None
        assert window.settings.value("dock_state") == window._dock_host.saveState()

    def test_the_view_menu_offers_it(self, window):
        assert window.action_reset_layout.text() == "Reset Window &Layout"


class TestDefaultDockSizes:
    """resizeDocks only bites once the window has been laid out, so the
    default widths are applied again on first show -- but only for someone
    who has no layout of their own to lose."""

    def _show_once(self, window, monkeypatch):
        applied = []
        monkeypatch.setattr(window, "_apply_default_dock_sizes",
                            lambda: applied.append(True))
        window.showEvent(QShowEvent())
        return applied

    def test_a_fresh_install_gets_them(self, window, monkeypatch):
        assert window.settings.value("dock_state") is None
        assert self._show_once(window, monkeypatch) == [True]

    def test_a_saved_layout_is_left_alone(self, window, monkeypatch):
        window.settings.setValue("dock_state", window._dock_host.saveState())
        assert self._show_once(window, monkeypatch) == []

    def test_only_on_the_first_show(self, window, monkeypatch):
        applied = []
        monkeypatch.setattr(window, "_apply_default_dock_sizes",
                            lambda: applied.append(True))
        window.showEvent(QShowEvent())
        window.showEvent(QShowEvent())
        assert applied == [True]


class TestDefaultWindowSize:
    def test_a_fresh_install_gets_the_default_size(self, window):
        assert (window.width(), window.height()) == mod.DEFAULT_WINDOW_SIZE

    def test_a_saved_geometry_wins(self, window, registry, qtbot):
        """The saved size is the user's; only a reset overrides it."""
        window.resize(900, 700)
        window._save_window_state()
        reopened = mod.MainWindow(registry)
        reopened.confirm_close = False
        qtbot.addWidget(reopened)
        assert (reopened.width(), reopened.height()) != mod.DEFAULT_WINDOW_SIZE


class TestSettingsDialogButtons:
    def _dialog(self, window, qtbot) -> SettingsDialog:
        dialog = SettingsDialog(window)
        qtbot.addWidget(dialog)
        return dialog

    def test_both_buttons_are_there(self, window, qtbot):
        dialog = self._dialog(window, qtbot)
        assert dialog.findChild(QPushButton, "reset_settings_button")
        assert dialog.findChild(QPushButton, "reset_layout_button")

    def test_the_layout_button_resets_the_layout(self, window, qtbot):
        dialog = self._dialog(window, qtbot)
        window.resize(600, 400)
        dialog.findChild(QPushButton, "reset_layout_button").click()
        assert (window.width(), window.height()) == mod.DEFAULT_WINDOW_SIZE

    def test_the_settings_button_asks_first(self, window, qtbot, monkeypatch):
        monkeypatch.setattr(QMessageBox, "question",
                            lambda *a, **k: QMessageBox.No)
        dialog = self._dialog(window, qtbot)
        window.set_minimap_enabled(False)
        dialog.findChild(QPushButton, "reset_settings_button").click()
        assert window.minimap_enabled is False

    def test_confirming_resets(self, window, qtbot, monkeypatch):
        monkeypatch.setattr(QMessageBox, "question",
                            lambda *a, **k: QMessageBox.Yes)
        dialog = self._dialog(window, qtbot)
        _make_everything_non_default(window)
        dialog.findChild(QPushButton, "reset_settings_button").click()
        assert window.minimap_enabled is True
        assert window.tint_soft == pytest.approx(theme.DEFAULT_TINT_SOFT)

    def test_the_controls_show_the_new_values(self, window, qtbot, monkeypatch):
        """The dialog builds its widgets from the window's values once, so a
        reset behind its back has to rebuild them — stale controls here would
        push the old value straight back the next time one is touched."""
        monkeypatch.setattr(QMessageBox, "question",
                            lambda *a, **k: QMessageBox.Yes)
        dialog = self._dialog(window, qtbot)
        _make_everything_non_default(window)
        dialog.findChild(QPushButton, "reset_settings_button").click()

        assert dialog.findChild(QSpinBox, "tint_soft_spinbox").value() == round(
            theme.DEFAULT_TINT_SOFT * 100)
        assert dialog.findChild(QCheckBox, "minimap_enabled_checkbox").isChecked()
        assert dialog.findChild(QCheckBox, "lod_enabled_checkbox").isChecked()
        assert dialog.findChild(QCheckBox, "snap_enabled_checkbox").isChecked()
        assert dialog.findChild(
            QComboBox, "page_bar_position_combo").currentText() == "Top"

    def test_rebuilding_keeps_the_selected_page(self, window, qtbot, monkeypatch):
        monkeypatch.setattr(QMessageBox, "question",
                            lambda *a, **k: QMessageBox.Yes)
        dialog = self._dialog(window, qtbot)
        dialog._nav.setCurrentRow(2)
        before = dialog._nav.currentItem().text()
        dialog.findChild(QPushButton, "reset_settings_button").click()
        assert dialog._nav.currentItem().text() == before
        assert dialog._nav.count() == 4
