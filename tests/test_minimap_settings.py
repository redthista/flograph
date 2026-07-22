"""Canvas minimap: the enable toggle exposed in Settings > Canvas, and
MainWindow's wiring onto the modeling canvas's minimap overlay.

No real MainWindow.show() here — see tests/test_gpu_viewport_setting.py's
module docstring for why that's unsafe under this offscreen test harness.
Since the window is never shown, QWidget.isVisible() would read False
regardless of the toggle (it also depends on every ancestor being shown) —
isHidden() is used instead, since it only reflects setVisible()/hide()
calls made on the minimap widget itself.
Settings kept off the real store (avoid polluting the developer's actual
flograph.conf)."""
import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QCheckBox

from flograph.core import NodeRegistry
from flograph.ui import mainwindow as mod
from flograph.ui.settings_dialog import SettingsDialog


@pytest.fixture(autouse=True)
def _isolated_settings(tmp_path, monkeypatch):
    ini_path = str(tmp_path / "test_settings.ini")
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


class TestMinimapSettingOnMainWindow:
    def test_defaults(self, window):
        assert window.minimap_enabled is True
        assert window.view.minimap.isHidden() is False

    def test_minimap_is_not_covered_by_the_viewport_widget(self, window):
        """Regression: _apply_gpu_viewport_setting() calls view.setViewport()
        unconditionally at startup (even with GPU off, to install the plain
        QWidget viewport), which installs a *new* viewport widget as a
        sibling of the minimap — landing on top of it in stacking order and
        making the minimap invisible in practice despite isVisible()/
        isHidden() reporting it as shown. This is the actual reason the
        minimap appeared to be "lost" with no code change or setting at
        fault."""
        view = window.view
        kids = view.children()
        assert kids.index(view.minimap) > kids.index(view.viewport())

    def test_minimap_stays_on_top_after_toggling_gpu_viewport(self, window):
        window.action_gpu_viewport.setChecked(True)
        view = window.view
        kids = view.children()
        assert kids.index(view.minimap) > kids.index(view.viewport())

        window.action_gpu_viewport.setChecked(False)
        kids = view.children()
        assert kids.index(view.minimap) > kids.index(view.viewport())

    def test_set_minimap_enabled_persists_and_applies_to_view(self, window):
        window.set_minimap_enabled(False)
        assert window.view.minimap.isHidden() is True
        assert window.settings.value(
            "canvas/minimap_enabled", True, type=bool) is False

        window.set_minimap_enabled(True)
        assert window.view.minimap.isHidden() is False
        assert window.settings.value(
            "canvas/minimap_enabled", False, type=bool) is True


class TestMinimapSettingDialog:
    def test_checkbox_reflects_initial_state(self, window):
        dlg = SettingsDialog(window, window)
        checkbox = dlg.findChild(QCheckBox, "minimap_enabled_checkbox")
        assert checkbox is not None
        assert checkbox.isChecked() is True

    def test_unchecking_hides_the_minimap(self, window):
        dlg = SettingsDialog(window, window)
        checkbox = dlg.findChild(QCheckBox, "minimap_enabled_checkbox")

        checkbox.setChecked(False)
        assert window.minimap_enabled is False
        assert window.view.minimap.isHidden() is True
