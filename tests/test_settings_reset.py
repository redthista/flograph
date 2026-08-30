"""ideas.md item 19: reset the window layout, and reset every stored
preference back to defaults, from Settings > General.

Settings are kept off the real store (avoid polluting the developer's actual
flograph.conf) -- see test_lod_settings.py's fixture of the same name.
"""
import pytest
from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QCheckBox, QComboBox, QPushButton, QSpinBox

from flograph.core import NodeRegistry
from flograph.ui import mainwindow as mod
from flograph.ui import theme
from flograph.ui.canvas import grid
from flograph.ui.settings_dialog import SettingsDialog


@pytest.fixture(autouse=True)
def _isolated_settings(tmp_path, monkeypatch):
    ini_path = str(tmp_path / "test_settings.ini")
    monkeypatch.setattr(
        mod, "QSettings",
        lambda *a, **k: QSettings(ini_path, QSettings.IniFormat))
    # the spreadsheet module reaches for the real store by org/app name
    monkeypatch.setattr(
        "flograph.ui.spreadsheet.view.QSettings",
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


class TestButtons:
    def test_general_page_offers_both_resets(self, window):
        dialog = SettingsDialog(window)
        names = {b.objectName() for b in dialog.findChildren(QPushButton)}
        assert {"reset_layout_button", "reset_settings_button"} <= names

    def test_both_ask_before_doing_anything(self, window, monkeypatch):
        """Neither reset is undoable, so a stray click must not fire."""
        from PySide6.QtWidgets import QMessageBox
        asked = []
        monkeypatch.setattr(
            QMessageBox, "question",
            lambda *a, **k: asked.append(a[1]) or QMessageBox.Cancel)
        called = []
        monkeypatch.setattr(window, "reset_window_layout",
                            lambda: called.append("layout"))
        monkeypatch.setattr(window, "reset_settings",
                            lambda: called.append("all"))
        dialog = SettingsDialog(window)
        for name in ("reset_layout_button", "reset_settings_button"):
            dialog.findChild(QPushButton, name).click()
        assert len(asked) == 2
        assert called == []  # Cancel means nothing happened

    def test_confirming_runs_the_reset(self, window, monkeypatch):
        from PySide6.QtWidgets import QMessageBox
        monkeypatch.setattr(QMessageBox, "question",
                            lambda *a, **k: QMessageBox.Yes)
        called = []
        monkeypatch.setattr(window, "reset_settings",
                            lambda: called.append("all"))
        dialog = SettingsDialog(window)
        dialog.findChild(QPushButton, "reset_settings_button").click()
        assert called == ["all"]


class TestWindowLayout:
    def test_reset_restores_the_default_dock_arrangement(self, window):
        default = bytes(window._default_dock_state)
        window._dock_host.removeDockWidget(window.library_dock)
        assert bytes(window._dock_host.saveState()) != default
        window.reset_window_layout()
        assert bytes(window._dock_host.saveState()) == default

    def test_reset_brings_a_closed_panel_back(self, window):
        window.properties_dock.hide()
        window.reset_window_layout()
        assert not window.properties_dock.isHidden()

    def test_reset_forgets_the_saved_layout(self, window):
        window._save_window_state()
        assert window.settings.value("dock_state") is not None
        window.reset_window_layout()
        assert window.settings.value("dock_state") is None

    def test_reset_leaves_the_window_geometry_alone(self, window):
        """Someone whose panels have gone missing wants them back, not their
        window resized out from under them."""
        window.resize(900, 640)
        before = window.size()
        window.reset_window_layout()
        assert window.size() == before


class TestResetAll:
    def _make_everything_non_default(self, window):
        window.set_page_bar_position("bottom")
        window.set_lod_enabled(False)
        window.set_lod_threshold(0.75)
        window.set_snap_enabled(False)
        window.set_grid_visible(False)
        window.set_minimap_enabled(False)
        window.set_tints(0.9, 0.95)
        from flograph.ui.spreadsheet import (set_autosize_default,
                                             set_date_formats_setting)
        set_autosize_default(False)
        set_date_formats_setting("%d-%b-%y")

    def test_every_preference_goes_back_to_its_default(self, window):
        self._make_everything_non_default(window)
        window.reset_settings()
        from flograph.ui.spreadsheet import (autosize_default_enabled,
                                             date_formats_setting)
        assert window.page_bar_position == "top"
        assert window.lod_enabled is True
        assert window.lod_threshold == mod.DEFAULT_LOD_THRESHOLD
        assert window.snap_enabled is True
        assert window.grid_step == grid.DEFAULT_STEP
        assert window.grid_visible is True
        assert window.minimap_enabled is True
        assert window.tint_soft == theme.DEFAULT_TINT_SOFT
        assert window.tint_strong == theme.DEFAULT_TINT_STRONG
        assert autosize_default_enabled() is True
        assert date_formats_setting() == ""

    def test_defaults_are_applied_live_not_on_next_launch(self, window):
        """The whole point of resetting from a live dialog: the canvas has
        to change now, not after a restart."""
        window.set_minimap_enabled(False)
        assert window.view.minimap.isHidden()
        window.reset_settings()
        assert not window.view.minimap.isHidden()

    def test_the_recent_files_list_is_cleared(self, window, tmp_path):
        # the menu drops entries whose file is gone, so this one has to exist
        project = tmp_path / "a.flograph"
        project.write_text("{}")
        window.settings.setValue("recent_files", [str(project)])
        window._rebuild_recent_menu()
        assert window._recent_menu.isEnabled()
        window.reset_settings()
        assert not window._recent_menu.isEnabled()

    def test_the_window_layout_goes_too(self, window):
        default = bytes(window._default_dock_state)
        window._dock_host.removeDockWidget(window.editor_dock)
        window.reset_settings()
        assert bytes(window._dock_host.saveState()) == default

    def test_an_open_dialog_is_pulled_back_into_sync(self, qtbot, window):
        """Pages bind once at build time and live-apply from there, which is
        right for a user turning knobs — but a reset moves the values
        underneath an already open dialog."""
        self._make_everything_non_default(window)
        dialog = SettingsDialog(window)
        window._settings_dialog = dialog
        assert dialog.findChild(QCheckBox, "lod_enabled_checkbox").isChecked() \
            is False
        window.reset_settings()
        qtbot.waitUntil(
            lambda: dialog.findChild(
                QCheckBox, "lod_enabled_checkbox").isChecked() is True)
        assert dialog.findChild(
            QSpinBox, "lod_threshold_spinbox").value() \
            == round(mod.DEFAULT_LOD_THRESHOLD * 100)
        assert dialog.findChild(
            QComboBox, "page_bar_position_combo").currentText() == "Top"
        assert dialog.findChild(
            QCheckBox, "minimap_enabled_checkbox").isChecked() is True

    def test_syncing_the_dialog_does_not_write_back(self, window):
        """The controls push user intent at the window; replaying them while
        re-syncing would be a no-op at best and a stale write at worst."""
        dialog = SettingsDialog(window)
        window._settings_dialog = dialog
        window.set_lod_threshold(0.75)
        dialog.refresh_from(window)
        assert window.lod_threshold == 0.75

    def test_dependent_controls_are_re_enabled(self, window):
        window.set_snap_enabled(False)
        dialog = SettingsDialog(window)
        assert not dialog.findChild(QComboBox, "grid_step_combo").isEnabled()
        window.set_snap_enabled(True)
        dialog.refresh_from(window)
        assert dialog.findChild(QComboBox, "grid_step_combo").isEnabled()
