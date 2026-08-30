"""Rebindable keyboard shortcuts: the registry and its Settings page.

The registry owns every menu/toolbar action's key, so the things worth
pinning are that a rebind reaches the real QAction, survives a restart,
and is refused when it would collide -- a duplicate is not a cosmetic
problem, it stops both shortcuts firing.

No real MainWindow.show() -- see test_gpu_viewport_setting.py's module
docstring for why that is unsafe under this offscreen test harness.
Settings kept off the real store (avoid polluting the developer's actual
flograph.conf).
"""
import pytest
from PySide6.QtCore import QSettings
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import QLabel

from flograph.core import NodeRegistry
from flograph.ui import mainwindow as mod
from flograph.ui.settings_dialog import SettingsDialog
from flograph.ui.shortcuts import slug


@pytest.fixture
def ini_path(tmp_path):
    return str(tmp_path / "test_settings.ini")


@pytest.fixture(autouse=True)
def _isolated_settings(ini_path, monkeypatch):
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


class TestSlug:
    @pytest.mark.parametrize("label, expected", [
        ("&New", "new"),
        ("Save &As…", "save_as"),
        ("Manage &Packages…", "manage_packages"),
        ("Distribute Horizontally", "distribute_horizontally"),
        ("Hide All Panels", "hide_all_panels"),
    ])
    def test_labels_become_stable_ids(self, label, expected):
        assert slug(label) == expected


class TestRegistry:
    def test_every_menu_action_is_registered(self, window):
        keys = {entry.key for entry in window.shortcuts.entries()}
        for expected in ("new", "save", "undo", "run_all", "settings",
                         "hide_all_panels"):
            assert expected in keys

    def test_entries_are_grouped_the_way_the_menus_are(self, window):
        assert window.shortcuts.groups() == [
            "File", "Edit", "Run", "Tools", "View", "Help"]
        assert window.shortcuts.entry("save").group == "File"
        assert window.shortcuts.entry("hide_all_panels").group == "View"
        assert window.shortcuts.entry("documentation").group == "Help"

    def test_defaults_come_from_the_action_itself(self, window):
        entry = window.shortcuts.entry("hide_all_panels")
        assert entry.default == QKeySequence("Ctrl+Shift+H")
        assert entry.is_default() is True

    def test_a_rebind_reaches_the_real_action(self, window):
        assert window.shortcuts.set_binding(
            "hide_all_panels", QKeySequence("Ctrl+Alt+P")) is None
        assert window.action_toggle_panels.shortcut() == QKeySequence("Ctrl+Alt+P")

    def test_a_clash_is_refused_and_names_the_culprit(self, window):
        """Qt fires neither of two actions sharing a key, so applying the
        duplicate would silently break Save as well."""
        clash = window.shortcuts.set_binding(
            "hide_all_panels", QKeySequence("Ctrl+S"))

        assert clash == "Save"
        assert window.action_toggle_panels.shortcut() == QKeySequence("Ctrl+Shift+H")
        assert window.action_save.shortcut() == QKeySequence("Ctrl+S")

    def test_rebinding_a_command_to_its_own_key_is_not_a_clash(self, window):
        assert window.shortcuts.set_binding(
            "save", QKeySequence("Ctrl+S")) is None

    def test_a_command_can_be_unbound(self, window):
        """Some commands ship with no key at all, so empty is a legal
        value rather than a way of asking for the default back."""
        assert window.shortcuts.set_binding(
            "duplicate", QKeySequence()) is None
        assert window.action_duplicate.shortcut().isEmpty() is True

    def test_an_unbound_command_does_not_collide_with_another(self, window):
        window.shortcuts.set_binding("duplicate", QKeySequence())
        assert window.shortcuts.set_binding(
            "add_frame", QKeySequence()) is None

    def test_reset_restores_one_default(self, window):
        window.shortcuts.set_binding(
            "hide_all_panels", QKeySequence("Ctrl+Alt+P"))
        window.shortcuts.reset("hide_all_panels")

        assert window.action_toggle_panels.shortcut() == QKeySequence("Ctrl+Shift+H")
        assert window.shortcuts.entry("hide_all_panels").is_default() is True

    def test_reset_all_restores_everything(self, window):
        window.shortcuts.set_binding("save", QKeySequence("Ctrl+Alt+1"))
        window.shortcuts.set_binding("run_all", QKeySequence("Ctrl+Alt+2"))

        window.shortcuts.reset_all()

        assert all(entry.is_default() for entry in window.shortcuts.entries())


class TestPersistence:
    def test_a_rebind_survives_a_restart(self, window, qtbot, registry):
        window.shortcuts.set_binding(
            "hide_all_panels", QKeySequence("Ctrl+Alt+P"))

        win2 = mod.MainWindow(registry)
        win2.confirm_close = False
        qtbot.addWidget(win2)

        assert win2.action_toggle_panels.shortcut() == QKeySequence("Ctrl+Alt+P")

    def test_a_default_binding_writes_nothing(self, window, ini_path):
        """Rebinding back to the default should clear the override, not
        store a copy of it -- otherwise changing a default in code would
        never reach anyone who had once touched that row."""
        window.shortcuts.set_binding("save", QKeySequence("Ctrl+Alt+1"))
        window.shortcuts.set_binding("save", QKeySequence("Ctrl+S"))

        stored = QSettings(ini_path, QSettings.IniFormat)
        assert stored.value("shortcuts/save", None) is None

    def test_reset_settings_puts_the_keys_back(self, window):
        """settings.clear() drops the stored rebind but leaves it applied
        to the live action, so the old key would keep working."""
        window.shortcuts.set_binding(
            "hide_all_panels", QKeySequence("Ctrl+Alt+P"))

        window.reset_settings()

        assert window.action_toggle_panels.shortcut() == QKeySequence("Ctrl+Shift+H")


class TestSettingsPage:
    @pytest.fixture
    def dialog(self, qtbot, window):
        dlg = SettingsDialog(window)
        qtbot.addWidget(dlg)
        return dlg

    def test_the_page_is_in_the_nav(self, dialog):
        assert "Keyboard Shortcuts" in dialog._page_index

    def test_there_is_a_field_per_command(self, dialog, window):
        assert (set(dialog._shortcut_editors)
                == {entry.key for entry in window.shortcuts.entries()})

    def test_a_field_opens_showing_the_current_key(self, dialog):
        edit = dialog._shortcut_editors["hide_all_panels"]
        assert edit.keySequence() == QKeySequence("Ctrl+Shift+H")

    def test_capturing_a_key_rebinds_the_action(self, dialog, window):
        edit = dialog._shortcut_editors["hide_all_panels"]
        edit.setKeySequence(QKeySequence("Ctrl+Alt+P"))
        edit.editingFinished.emit()

        assert window.action_toggle_panels.shortcut() == QKeySequence("Ctrl+Alt+P")

    def test_a_clash_is_explained_and_the_field_put_back(self, dialog, window):
        note = dialog.findChild(QLabel, "shortcut_conflict_note")
        edit = dialog._shortcut_editors["hide_all_panels"]
        edit.setKeySequence(QKeySequence("Ctrl+S"))
        edit.editingFinished.emit()

        assert "Save" in note.text()
        assert note.isHidden() is False
        # the refused key must not be left sitting in the field
        assert edit.keySequence() == QKeySequence("Ctrl+Shift+H")
        assert window.action_toggle_panels.shortcut() == QKeySequence("Ctrl+Shift+H")

    def test_resetting_pulls_the_fields_back_into_line(self, dialog, window):
        edit = dialog._shortcut_editors["hide_all_panels"]
        edit.setKeySequence(QKeySequence("Ctrl+Alt+P"))
        edit.editingFinished.emit()

        window.shortcuts.reset_all()

        assert edit.keySequence() == QKeySequence("Ctrl+Shift+H")
