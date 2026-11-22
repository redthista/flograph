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


# ---------------------------------------------------------------- light canvas
#
# The canvas follows the theme too: a light mode with a dark canvas was the
# half-and-half the first version shipped, and a dark node on a dark canvas
# is the contrast complaint light mode exists to answer.

def _luminance(color: QColor) -> float:
    def lin(c: float) -> float:
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    return (0.2126 * lin(color.redF()) + 0.7152 * lin(color.greenF())
            + 0.0722 * lin(color.blueF()))


def _contrast(a: QColor, b: QColor) -> float:
    hi, lo = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


class TestLightCanvas:
    def test_canvas_switches_with_the_theme_and_back(self, qapp):
        theme.apply_theme(qapp, "dark")
        dark_bg, dark_body = theme.CANVAS_BG.name(), theme.NODE_BODY.name()
        theme.apply_theme(qapp, "light")
        assert theme.CANVAS_BG.name() != dark_bg
        assert theme.NODE_BODY.name() != dark_body
        assert theme.CANVAS_BG.lightness() > 180
        theme.apply_theme(qapp, "dark")
        assert theme.CANVAS_BG.name() == dark_bg
        assert theme.NODE_BODY.name() == dark_body

    def test_a_node_stands_out_from_its_canvas(self, qapp):
        theme.apply_theme(qapp, "light")
        # a light card is lifted by a shadow and a category stripe as well
        # as by value, so the fill gap itself is modest
        assert _contrast(theme.NODE_BODY, theme.CANVAS_BG) >= 1.05
        assert _contrast(theme.NODE_BORDER, theme.NODE_BODY) >= 1.5
        assert theme.category_color("io") is not None
        theme.apply_theme(qapp, "dark")
        assert theme.category_color("io") is None
        theme.apply_theme(qapp, "light")
        assert theme.NODE_HEADER.name() != theme.NODE_BODY.name()
        assert _contrast(theme.NODE_TEXT, theme.NODE_BODY) >= 7
        assert _contrast(theme.NODE_SUBTEXT, theme.NODE_BODY) >= 4.5

    def test_wires_and_status_lights_read_on_the_light_canvas(self, qapp):
        from flograph.core import PortType
        from flograph.core.node import NodeStatus
        theme.apply_theme(qapp, "light")
        for port_type in PortType:
            assert _contrast(theme.wire_color(port_type),
                             theme.CANVAS_BG) >= 2.2, port_type
        for status in NodeStatus:
            assert _contrast(theme.status_color(status),
                             theme.NODE_BODY) >= 2.5, status

    def test_the_dark_canvas_is_exactly_what_it_was(self, qapp):
        theme.apply_theme(qapp, "light")
        theme.apply_theme(qapp, "dark")
        assert theme.CANVAS_BG.name() == "#1b1c20"
        assert theme.NODE_BODY.name() == "#2a2c33"
        assert theme.NODE_HEADER.name() == "#363943"
        assert theme.status_color(
            __import__("flograph.core.node", fromlist=["NodeStatus"])
            .NodeStatus.DONE).name() == "#22c55e"


class TestSkin:
    def test_dark_mode_leaves_text_alone(self, qapp):
        theme.apply_theme(qapp, "dark")
        qss = "QLabel { color: #e5e7eb; background: #2a2c33; }"
        assert theme.skin(qss) == qss
        assert theme.skin_color("#c8cbd2").name() == "#c8cbd2"

    def test_light_mode_translates_neutrals_only(self, qapp):
        theme.apply_theme(qapp, "light")
        out = theme.skin("QLabel { color: #e5e7eb; background: #2a2c33;"
                         " border: 1px solid #22c55e; color2: #ffffff; }")
        assert "#e5e7eb" not in out and "#2a2c33" not in out
        # status green and white mean the same in both modes
        assert "#22c55e" in out and "#ffffff" in out

    def test_set_qss_round_trips_through_a_theme_switch(self, qapp):
        from PySide6.QtWidgets import QLabel
        theme.apply_theme(qapp, "dark")
        label = QLabel("x")
        qss = "QLabel { color: #e5e7eb; background: #34363f; }"
        theme.set_qss(label, qss)
        assert label.styleSheet() == qss
        theme.apply_theme(qapp, "light")
        assert label.styleSheet() != qss
        theme.apply_theme(qapp, "dark")
        assert label.styleSheet() == qss

    def test_a_grid_built_in_light_returns_to_dark(self, qapp):
        from PySide6.QtWidgets import QTableView
        theme.apply_theme(qapp, "light")
        view = QTableView()
        theme.style_scroll_area(view, theme.grid_stylesheet())
        assert theme.NODE_BODY.name() in view.styleSheet()
        theme.apply_theme(qapp, "dark")
        assert theme.NODE_BODY.name() in view.styleSheet()   # #2a2c33

    def test_listeners_hear_about_a_switch(self, qapp):
        heard = []
        theme.on_change(lambda: heard.append(theme.APP_MODE))
        try:
            theme.apply_theme(qapp, "light")
            theme.apply_theme(qapp, "dark")
        finally:
            theme._listeners.pop()
        assert heard == ["light", "dark"]

    def test_the_skin_covers_every_canvas_colour_it_is_built_from(self):
        for name in ("CANVAS_BG", "NODE_BODY", "NODE_HEADER", "NODE_BORDER",
                     "NODE_TEXT", "NODE_SUBTEXT"):
            dark = theme.dark_hex(name).lower()
            assert theme._SKIN[dark] == theme._CANVAS_LIGHT[name]


class TestChromeFollowsTheTheme:
    def test_title_bar_and_toolbar_colours(self, qapp):
        theme.apply_theme(qapp, "light")
        light_bar = theme.chrome("bar_bg")
        theme.apply_theme(qapp, "dark")
        assert theme.chrome("bar_bg") != light_bar
        assert QColor(theme.chrome("bar_bg")).lightness() < 60

    def test_window_restyles_itself_live(self, window, qapp):
        window.set_theme_pref("light")
        assert theme.chrome("bar_bg") in window._title_bar.styleSheet()
        window.set_theme_pref("dark")
        assert theme.chrome("bar_bg") in window._title_bar.styleSheet()

    def test_toolbar_run_colour_deepens_on_light(self, qapp):
        from flograph.ui import toolbar
        theme.apply_theme(qapp, "light")
        light_run = toolbar.RUN.name()
        theme.apply_theme(qapp, "dark")
        assert toolbar.RUN.name() == "#22c55e" != light_run
