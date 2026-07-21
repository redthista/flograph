"""Page bar position setting (ideas.md follow-up): the Model/page tab strip
can live on the top or bottom edge of the window, configurable in
Settings > General. (Left/right were pulled -- see mainwindow.py's
_apply_page_bar_position docstring: the rotated label couldn't be made to
render reliably centered on real screens.)

MainWindow.set_page_bar_position() rearranges the outer window's central
layout (page_bar plus the dock host, which holds the canvas and every other
dock) rather than moving a QDockWidget -- see _apply_page_bar_position's
docstring in mainwindow.py for why: splitDockWidget() against an anchor with
an existing tab group (Inspector+Log, Properties+Code) reliably corrupts
that group the first time it's called more than once against the same
anchor, verified empirically. A plain QBoxLayout slot has no such failure
mode and no resize handle to fight with either.

Settings kept off the real store (avoid polluting the developer's actual
flograph.conf) -- see test_lod_settings.py's fixture of the same name."""
import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QComboBox, QVBoxLayout

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


class TestPageBarPositionOnMainWindow:
    def test_defaults_to_top(self, window):
        assert window.page_bar_position == "top"
        layout = window.centralWidget().layout()
        assert isinstance(layout, QVBoxLayout)
        assert layout.itemAt(0).widget() is window.page_bar
        assert layout.itemAt(1).widget() is window._dock_host

    @pytest.mark.parametrize("position, layout_cls, order", [
        ("top", QVBoxLayout, "page_bar_first"),
        ("bottom", QVBoxLayout, "dock_host_first"),
    ])
    def test_each_position_places_the_bar_on_the_right_edge(
            self, window, position, layout_cls, order):
        window.set_page_bar_position(position)
        layout = window.centralWidget().layout()
        assert isinstance(layout, layout_cls)
        first, second = layout.itemAt(0).widget(), layout.itemAt(1).widget()
        if order == "page_bar_first":
            assert (first, second) == (window.page_bar, window._dock_host)
        else:
            assert (first, second) == (window._dock_host, window.page_bar)

    def test_invalid_or_unchanged_position_is_a_no_op(self, window):
        layout_before = window.centralWidget().layout()
        window.set_page_bar_position("top")  # already the default
        assert window.centralWidget().layout() is layout_before
        window.set_page_bar_position("diagonal")  # not a real position
        assert window.centralWidget().layout() is layout_before
        assert window.page_bar_position == "top"

    def test_persists_to_settings(self, window):
        window.set_page_bar_position("bottom")
        assert window.settings.value("canvas/page_bar_position") == "bottom"

    def test_switching_repeatedly_never_disturbs_the_other_dock_tab_groups(
            self, window):
        """The whole reason this isn't a QDockWidget: splitDockWidget()
        against inspector_dock/properties_dock (each tabified with a
        partner) breaks on a second application. Round-tripping through
        every position covers that regression directly."""
        for position in ("top", "bottom", "top", "bottom"):
            window.set_page_bar_position(position)
        host = window._dock_host
        assert window.log_dock in host.tabifiedDockWidgets(window.inspector_dock)
        assert window.editor_dock in host.tabifiedDockWidgets(window.properties_dock)

    def test_reads_persisted_position_on_construction(
            self, qtbot, registry, window):
        window.set_page_bar_position("bottom")
        second = mod.MainWindow(registry)
        second.confirm_close = False
        qtbot.addWidget(second)
        assert second.page_bar_position == "bottom"
        layout = second.centralWidget().layout()
        assert isinstance(layout, QVBoxLayout)
        assert layout.itemAt(0).widget() is second._dock_host
        assert layout.itemAt(1).widget() is second.page_bar


class TestPageBarPositionSettingsDialog:
    def test_combo_reflects_initial_state(self, window):
        dlg = SettingsDialog(window, window)
        combo = dlg.findChild(QComboBox, "page_bar_position_combo")
        assert combo is not None
        assert combo.currentText() == "Top"

    def test_changing_the_combo_moves_the_bar(self, window):
        dlg = SettingsDialog(window, window)
        combo = dlg.findChild(QComboBox, "page_bar_position_combo")

        combo.setCurrentText("Bottom")
        assert window.page_bar_position == "bottom"
        layout = window.centralWidget().layout()
        assert isinstance(layout, QVBoxLayout)
        assert layout.itemAt(1).widget() is window.page_bar
