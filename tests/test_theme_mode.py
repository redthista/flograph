"""Light / dark / system chrome: the theme module's resolve + apply, and
MainWindow's persistence and the Settings combo that drives it.

The *canvas* is deliberately not covered — it never changes with the theme,
so there is nothing to assert about it here.

Settings are kept off the real store (see tests/test_tint_settings.py), and
the shared QApplication is put back to a dark theme after every test so a
switch here can't bleed into another file.
"""
import pytest
from PySide6.QtCore import Qt, QSettings
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication, QComboBox

from flograph.core import NodeRegistry
from flograph.ui import mainwindow as mod
from flograph.ui import theme
from flograph.ui.settings_dialog import SettingsDialog


@pytest.fixture(autouse=True)
def _isolated_settings(tmp_path, monkeypatch):
    ini_path = str(tmp_path / "test_settings.ini")
    monkeypatch.setattr(
        mod, "QSettings",
        lambda *a, **k: QSettings(ini_path, QSettings.IniFormat))


@pytest.fixture(autouse=True)
def _restore_theme():
    """APP_MODE, the app palette and the app stylesheet are all global."""
    yield
    app = QApplication.instance()
    if app is not None:
        theme.apply_theme(app, "dark")


@pytest.fixture(scope="module")
def registry() -> NodeRegistry:
    reg = NodeRegistry()
    reg.load_builtins()
    return reg


@pytest.fixture
def window(qtbot, registry):
    win = mod.MainWindow(registry)
    win.confirm_close = False
    qtbot.addWidget(win)
    return win


class TestResolve:
    def test_explicit_prefs_pass_through(self, qapp):
        assert theme.resolve_theme_pref(qapp, "light") == "light"
        assert theme.resolve_theme_pref(qapp, "dark") == "dark"

    def test_system_follows_the_style_hint(self, qapp, monkeypatch):
        for scheme, expected in ((Qt.ColorScheme.Light, "light"),
                                 (Qt.ColorScheme.Dark, "dark"),
                                 (Qt.ColorScheme.Unknown, "dark")):
            monkeypatch.setattr(qapp.styleHints(), "colorScheme",
                                lambda s=scheme: s)
            assert theme.resolve_theme_pref(qapp, "system") == expected


class TestApply:
    def test_light_sets_a_light_window_colour(self, qapp):
        theme.apply_theme(qapp, "light")
        assert theme.APP_MODE == "light"
        assert not theme.is_dark()
        assert qapp.palette().window().color().lightness() > 128

    def test_dark_sets_a_dark_window_colour(self, qapp):
        theme.apply_theme(qapp, "dark")
        assert theme.APP_MODE == "dark"
        assert theme.is_dark()
        assert qapp.palette().window().color().lightness() < 128

    def test_bad_pref_falls_back_to_system(self, qapp):
        theme.apply_theme(qapp, "chartreuse")
        assert theme.APP_MODE in ("light", "dark")

    def test_dark_theme_does_not_borrow_from_the_os(self, qapp, monkeypatch):
        """The bug this feature also fixes: on a light desktop, an *unset*
        palette role was resolved from the OS, so flograph's dark theme
        came out half-dark-half-light with unreadable text. Every role is
        now set in every state group, so the result must be byte-for-byte
        the same whatever the OS scheme says."""
        roles = [QPalette.Window, QPalette.WindowText, QPalette.Base,
                 QPalette.Text, QPalette.Button, QPalette.ButtonText,
                 QPalette.ToolTipBase, QPalette.ToolTipText,
                 QPalette.PlaceholderText, QPalette.Mid, QPalette.Light,
                 QPalette.Midlight, QPalette.Dark, QPalette.Shadow,
                 QPalette.Highlight, QPalette.HighlightedText,
                 QPalette.Link, QPalette.BrightText]
        groups = [QPalette.Active, QPalette.Inactive, QPalette.Disabled]

        def snapshot() -> dict:
            pal = qapp.palette()
            return {(g, r): pal.color(g, r).name()
                    for g in groups for r in roles}

        shots = []
        for scheme in (Qt.ColorScheme.Light, Qt.ColorScheme.Dark,
                       Qt.ColorScheme.Unknown):
            monkeypatch.setattr(qapp.styleHints(), "colorScheme",
                                lambda s=scheme: s)
            theme.apply_theme(qapp, "dark")
            shots.append(snapshot())
        assert shots[0] == shots[1] == shots[2]
        # every colour that carries text or a surface is genuinely dark or
        # genuinely light-on-dark — nothing pale-grey stranded in between
        window = QColor(shots[0][(QPalette.Active, QPalette.Window)])
        text = QColor(shots[0][(QPalette.Active, QPalette.WindowText)])
        assert window.lightness() < 70
        assert text.lightness() > 180

    def test_disabled_text_is_still_legible_in_dark(self, qapp):
        theme.apply_theme(qapp, "dark")
        pal = qapp.palette()
        disabled = pal.color(QPalette.Disabled, QPalette.Text).lightness()
        base = pal.color(QPalette.Disabled, QPalette.Base).lightness()
        assert disabled - base > 30

    def test_mid_role_is_readable_on_base_in_both_modes(self, qapp):
        # the dim-label colour (`color: palette(mid)`) has to clear its
        # background whichever way the theme is set
        for pref in ("light", "dark"):
            theme.apply_theme(qapp, pref)
            pal = qapp.palette()
            mid = pal.mid().color().lightness()
            base = pal.base().color().lightness()
            assert abs(mid - base) > 40, pref


class TestWindowSetting:
    def test_default_is_dark(self, window):
        assert window.theme_pref == "dark"

    def test_set_theme_pref_persists_and_applies(self, window, registry, qtbot):
        window.set_theme_pref("light")
        assert theme.APP_MODE == "light"
        reopened = mod.MainWindow(registry)
        reopened.confirm_close = False
        qtbot.addWidget(reopened)
        assert reopened.theme_pref == "light"

    def test_bad_value_is_ignored(self, window):
        window.set_theme_pref("dark")
        window.set_theme_pref("nonsense")
        assert window.theme_pref == "dark"

    def test_system_scheme_change_only_bites_in_system_mode(self, window):
        window.set_theme_pref("dark")
        window._on_system_color_scheme_changed()
        assert theme.APP_MODE == "dark"          # pinned, not moved


class TestSettingsDialog:
    def _combo(self, window, qtbot):
        dialog = SettingsDialog(window)
        qtbot.addWidget(dialog)
        return dialog, dialog.findChild(QComboBox, "theme_pref_combo")

    def test_combo_exists_on_general(self, window, qtbot):
        _dialog, combo = self._combo(window, qtbot)
        assert combo is not None

    def test_combo_shows_current_pref(self, window, qtbot):
        window.set_theme_pref("dark")
        _dialog, combo = self._combo(window, qtbot)
        assert combo.currentIndex() == 2

    def test_choosing_pushes_to_the_window(self, window, qtbot):
        _dialog, combo = self._combo(window, qtbot)
        combo.setCurrentIndex(1)                  # Light
        assert window.theme_pref == "light"
        assert theme.APP_MODE == "light"
