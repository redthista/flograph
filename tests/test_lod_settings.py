"""Zoom-out node simplification (LOD): the enable toggle and zoom threshold
exposed in Settings > Canvas, and MainWindow's wiring onto every scene
(modeling canvas + dashboard pages).

The scene/item-level LOD math itself (flattening, port/proxy hiding) is
covered in tests/test_canvas_polish.py::TestZoomLOD — this file is about the
MainWindow/Settings-dialog plumbing on top of it.

No real MainWindow.show() here — see tests/test_gpu_viewport_setting.py's
module docstring for why that's unsafe under this offscreen test harness.
Settings kept off the real store (avoid polluting the developer's actual
flograph.conf)."""
import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QCheckBox, QSpinBox

from flograph.core import NodeRegistry
from flograph.ui import mainwindow as mod
from flograph.ui.canvas.node_item import DEFAULT_LOD_THRESHOLD
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


class TestLodSettingsOnMainWindow:
    def test_defaults(self, window):
        assert window.lod_enabled is True
        assert window.lod_threshold == DEFAULT_LOD_THRESHOLD
        assert window.scene.lod_enabled is True
        assert window.scene.lod_threshold == DEFAULT_LOD_THRESHOLD

    def test_set_lod_enabled_persists_and_applies_to_scene(self, window):
        window.set_lod_enabled(False)
        assert window.scene.lod_enabled is False
        assert window.settings.value("canvas/lod_enabled", True, type=bool) is False

    def test_set_lod_threshold_persists_and_applies_to_scene(self, window):
        window.set_lod_threshold(0.6)
        assert window.scene.lod_threshold == 0.6
        assert window.settings.value("canvas/lod_threshold", 0.0, type=float) == 0.6

    def test_change_takes_effect_immediately_without_a_zoom_change(
            self, window, registry):
        graph = window.graph
        node = graph.add_node(registry.instantiate("flograph.util.constant"))
        item = window.scene.node_items[node.id]
        window.view._apply_lod()  # zoom starts at 1.0: full detail
        assert not item._flat

        window.set_lod_threshold(2.0)  # now "1.0 zoom" is below threshold
        assert item._flat

    def test_adding_a_dashboard_page_does_not_crash_with_non_default_settings(
            self, window):
        """DashboardScene (report/tile pages) has no LOD concept at all —
        only NodeGraphScene (the modeling canvas) does. Regression: adding a
        page used to unconditionally assign lod_enabled/lod_threshold onto
        whatever scene it got, which was harmless for DashboardScene's own
        attributes but is exactly the class of scene-type assumption that
        crashed when _apply_lod_settings later called
        refresh_lod_settings() on it — see the test below."""
        from flograph.core import Page
        from flograph.ui.commands import AddPageCommand
        window.set_lod_enabled(False)
        window.set_lod_threshold(0.7)
        page = Page(id="p1", title="Dash")
        window.undo_stack.push(AddPageCommand(window.graph, page))
        assert "p1" in window._dashboard_pages

    def test_changing_lod_settings_with_a_dashboard_page_open_does_not_crash(
            self, window):
        """The reported bug: MainWindow._apply_lod_settings() iterated every
        scene including dashboard pages' DashboardScene and called
        refresh_lod_settings() on it unconditionally — DashboardScene has no
        such method (it shows tiles, not nodes), so this raised
        AttributeError as soon as any dashboard page existed."""
        from flograph.core import Page
        from flograph.ui.commands import AddPageCommand
        page = Page(id="p1", title="Dash")
        window.undo_stack.push(AddPageCommand(window.graph, page))

        window.set_lod_enabled(False)
        window.set_lod_threshold(0.7)
        assert window._dashboard_pages["p1"].scene is not None  # still alive, no crash


class TestLodSettingsDialog:
    def test_checkbox_and_spinbox_reflect_initial_state(self, window):
        dlg = SettingsDialog(window, window)
        checkbox = dlg.findChild(QCheckBox, "lod_enabled_checkbox")
        spin = dlg.findChild(QSpinBox, "lod_threshold_spinbox")
        assert checkbox is not None and spin is not None
        assert checkbox.isChecked() is True
        assert spin.value() == round(DEFAULT_LOD_THRESHOLD * 100)
        assert spin.isEnabled()

    def test_unchecking_disables_the_setting_and_the_spinbox(self, window):
        dlg = SettingsDialog(window, window)
        checkbox = dlg.findChild(QCheckBox, "lod_enabled_checkbox")
        spin = dlg.findChild(QSpinBox, "lod_threshold_spinbox")

        checkbox.setChecked(False)
        assert window.lod_enabled is False
        assert window.scene.lod_enabled is False
        assert not spin.isEnabled()

    def test_changing_the_spinbox_updates_the_threshold(self, window):
        dlg = SettingsDialog(window, window)
        spin = dlg.findChild(QSpinBox, "lod_threshold_spinbox")

        spin.setValue(70)
        assert window.lod_threshold == pytest.approx(0.7)
        assert window.scene.lod_threshold == pytest.approx(0.7)
