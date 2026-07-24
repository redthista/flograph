"""Colour muting strengths exposed in Settings > Canvas: MainWindow's
persistence and live re-apply, and the dialog's two spin boxes.

The muting itself (what the strengths do to a painted colour) lives in
tests/test_node_color_muting.py — this file is about the settings plumbing.

No real MainWindow.show() here — see tests/test_gpu_viewport_setting.py's
module docstring for why that's unsafe under this offscreen test harness.
Settings kept off the real store (avoid polluting the developer's actual
flograph.conf)."""
import pytest
from PySide6.QtCore import QSettings
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QSpinBox

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
def _restore_theme_tints():
    """theme tints are module state: a test that changes them must not leak
    into the next one."""
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


class TestThemeState:
    def test_defaults_are_the_starting_values(self):
        theme.set_tints(theme.DEFAULT_TINT_SOFT, theme.DEFAULT_TINT_STRONG)
        assert theme.TINT_SOFT == theme.DEFAULT_TINT_SOFT == 0.30
        assert theme.TINT_STRONG == theme.DEFAULT_TINT_STRONG == 0.55

    def test_set_tints_moves_both(self):
        theme.set_tints(0.1, 0.9)
        assert (theme.TINT_SOFT, theme.TINT_STRONG) == (0.1, 0.9)

    @pytest.mark.parametrize("value, expected", [
        (-1.0, 0.0), (0.0, 0.0), (1.0, 1.0), (2.5, 1.0),
    ])
    def test_out_of_range_is_clamped(self, value, expected):
        theme.set_tints(value, value)
        assert theme.TINT_SOFT == expected
        assert theme.TINT_STRONG == expected

    def test_full_strength_paints_the_raw_colour(self):
        """100% is the documented "no muting" end of the range."""
        theme.set_tints(1.0, 1.0)
        assert theme.tint(theme.NODE_BODY, "#ff0000",
                          theme.TINT_SOFT) == QColor("#ff0000")


class TestWindowSetting:
    def test_defaults_when_unset(self, window):
        assert window.tint_soft == theme.DEFAULT_TINT_SOFT
        assert window.tint_strong == theme.DEFAULT_TINT_STRONG

    def test_set_tints_applies_to_theme(self, window):
        window.set_tints(0.4, 0.8)
        assert (theme.TINT_SOFT, theme.TINT_STRONG) == (0.4, 0.8)

    def test_set_tints_persists(self, window, registry, qtbot):
        window.set_tints(0.42, 0.84)
        theme.set_tints(theme.DEFAULT_TINT_SOFT, theme.DEFAULT_TINT_STRONG)
        reopened = mod.MainWindow(registry)
        reopened.confirm_close = False
        qtbot.addWidget(reopened)
        assert reopened.tint_soft == pytest.approx(0.42)
        assert reopened.tint_strong == pytest.approx(0.84)
        # and a restored value is pushed onto the theme, not just stored
        assert theme.TINT_SOFT == pytest.approx(0.42)

    def test_node_cards_follow_the_new_strength(self, window):
        """The point of the setting: a change reaches painting immediately."""
        from flograph.ui.canvas.node_item import NodeItem
        from tests.conftest import make_node
        item = NodeItem(window.graph.add_node(make_node()))
        item.node.color = "#ff0000"
        before = item._body_color()
        window.set_tints(0.9, 0.9)
        assert item._body_color() != before
        assert item._body_color().red() > before.red()


class TestSettingsDialog:
    def _spins(self, window, qtbot):
        dialog = SettingsDialog(window)
        qtbot.addWidget(dialog)
        return (dialog,
                dialog.findChild(QSpinBox, "tint_soft_spinbox"),
                dialog.findChild(QSpinBox, "tint_strong_spinbox"))

    def test_spin_boxes_exist_on_the_canvas_page(self, window, qtbot):
        _dialog, soft, strong = self._spins(window, qtbot)
        assert soft is not None and strong is not None

    def test_they_show_the_current_values(self, window, qtbot):
        window.set_tints(0.25, 0.65)
        _dialog, soft, strong = self._spins(window, qtbot)
        assert soft.value() == 25
        assert strong.value() == 65

    def test_editing_pushes_to_the_window(self, window, qtbot):
        _dialog, soft, strong = self._spins(window, qtbot)
        soft.setValue(45)
        assert window.tint_soft == pytest.approx(0.45)
        assert theme.TINT_SOFT == pytest.approx(0.45)
        strong.setValue(70)
        assert window.tint_strong == pytest.approx(0.70)
        assert theme.TINT_STRONG == pytest.approx(0.70)
        # the other one is not disturbed
        assert window.tint_soft == pytest.approx(0.45)

    def test_range_covers_raw_to_none(self, window, qtbot):
        _dialog, soft, strong = self._spins(window, qtbot)
        for spin in (soft, strong):
            assert spin.minimum() == 0
            assert spin.maximum() == 100
