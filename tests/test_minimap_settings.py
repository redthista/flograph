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


def _click(widget, pos, *, release_at=None):
    """A real press/release pair at the widget's handlers — the gesture,
    not a call to set_collapsed (see the drag-select note in the memory of
    why calling the method proves nothing about the click)."""
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent

    def event(kind, at, buttons):
        at = QPointF(at)
        return QMouseEvent(kind, at, widget.mapToGlobal(at), Qt.LeftButton,
                           buttons, Qt.NoModifier)

    widget.mousePressEvent(event(QEvent.MouseButtonPress, pos, Qt.LeftButton))
    end = pos if release_at is None else release_at
    widget.mouseReleaseEvent(event(QEvent.MouseButtonRelease, end,
                                   Qt.NoButton))


class TestMinimapCollapse:
    def test_starts_open(self, window):
        from flograph.ui.canvas.minimap import HEIGHT, WIDTH
        assert window.view.minimap.collapsed is False
        assert window.view.minimap.size().toTuple() == (WIDTH, HEIGHT)

    def test_corner_toggle_folds_to_a_square_and_back(self, window):
        from flograph.ui.canvas.minimap import COLLAPSED, HEIGHT, WIDTH
        minimap = window.view.minimap
        minimap.reposition()        # the window is never shown here
        right = minimap.geometry().right()

        _click(minimap, minimap._toggle_rect().center())
        assert minimap.collapsed is True
        assert minimap.size().toTuple() == (COLLAPSED, COLLAPSED)
        # folds into its own corner, not towards the toggle
        assert minimap.geometry().right() == right
        assert window.settings.value(
            "canvas/minimap_collapsed", False, type=bool) is True

        _click(minimap, minimap.rect().center())
        assert minimap.collapsed is False
        assert minimap.size().toTuple() == (WIDTH, HEIGHT)
        assert window.settings.value(
            "canvas/minimap_collapsed", True, type=bool) is False

    def test_clicking_the_toggle_does_not_pan_the_canvas(self, window,
                                                         monkeypatch):
        minimap = window.view.minimap
        panned = []
        monkeypatch.setattr(window.view, "center_on_scene", panned.append)
        _click(minimap, minimap._toggle_rect().center())
        assert panned == []

    def test_clicking_the_map_still_pans_and_does_not_fold(self, window,
                                                           monkeypatch):
        minimap = window.view.minimap
        panned = []
        monkeypatch.setattr(window.view, "center_on_scene", panned.append)
        _click(minimap, minimap.rect().center())
        assert len(panned) == 1
        assert minimap.collapsed is False

    def test_a_press_dragged_off_the_toggle_cancels(self, window):
        minimap = window.view.minimap
        _click(minimap, minimap._toggle_rect().center(),
               release_at=minimap.rect().center())
        assert minimap.collapsed is False

    def test_folded_map_takes_no_snapshots(self, window):
        minimap = window.view.minimap
        minimap.set_collapsed(True)
        before = minimap.snapshots
        minimap.mark_stale()
        minimap._retake()
        assert minimap.snapshots == before

    def test_folded_state_survives_a_restart(self, qtbot, registry, window):
        window.set_minimap_collapsed(True)
        again = mod.MainWindow(registry)
        again.confirm_close = False
        qtbot.addWidget(again)
        assert again.view.minimap.collapsed is True
