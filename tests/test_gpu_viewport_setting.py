"""GPU-Accelerated Canvas toggle: off by default, stays on when GL is
available, and self-reverts when it isn't.

Verified against a fake GL widget rather than the real QOpenGLWidget, and by
calling showEvent()/stubbing isVisible() directly rather than actually
showing a real MainWindow: under the offscreen QPA platform used for this
suite, showing more than one real MainWindow via qtbot within one pytest
process reliably corrupts the process's paint engine for unrelated *later*
tests — a segfault painting an unrelated FrameItem two test files later.
Confirmed pre-existing and unrelated to this feature by reproducing it
against a git-stashed, unmodified mainwindow.py (no GPU code, OpenGL module
not even loaded) — a latent test-harness issue, not something introduced
here. Calling the event handler / stubbing the property directly tests the
same toggle logic without needing the real (here, unstable) show/paint
pipeline; SettingsDialog itself IS constructed for real below (just never
shown), which is safe.

Settings kept off the real store (avoid polluting the developer's actual
flograph.conf)."""
import pytest
from PySide6.QtCore import QSettings
from PySide6.QtGui import QShowEvent
from PySide6.QtWidgets import QCheckBox, QWidget

from flograph.core import NodeRegistry
from flograph.ui import mainwindow as mod
from flograph.ui.settings_dialog import SettingsDialog


class _FakeGLContext:
    def __init__(self, valid: bool) -> None:
        self._valid = valid

    def isValid(self) -> bool:
        return self._valid


class _FakeGLWidget(QWidget):
    """Stand-in for QOpenGLWidget — see module docstring for why."""
    gl_available = True

    def context(self):
        return _FakeGLContext(self.gl_available)


@pytest.fixture(autouse=True)
def _isolated_settings(tmp_path, monkeypatch):
    ini_path = str(tmp_path / "test_settings.ini")
    monkeypatch.setattr(
        mod, "QSettings",
        lambda *a, **k: QSettings(ini_path, QSettings.IniFormat))


@pytest.fixture(autouse=True)
def _fake_gl(monkeypatch):
    _FakeGLWidget.gl_available = True
    monkeypatch.setattr(mod, "QOpenGLWidget", _FakeGLWidget)


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


class TestGpuViewportSetting:
    def test_off_by_default(self, window):
        assert not window.action_gpu_viewport.isChecked()
        assert type(window.view.viewport()) is QWidget

    def test_toggling_on_stays_on_when_gl_available(self, window, qtbot, monkeypatch):
        monkeypatch.setattr(type(window), "isVisible", lambda self: True)
        window.action_gpu_viewport.setChecked(True)
        qtbot.wait(20)  # let the deferred verify tick run
        assert window.action_gpu_viewport.isChecked()
        assert isinstance(window.view.viewport(), _FakeGLWidget)
        assert window.settings.value("canvas/gpu_viewport", False, type=bool) is True

    def test_toggling_on_reverts_when_gl_unavailable(self, window, qtbot, monkeypatch):
        monkeypatch.setattr(type(window), "isVisible", lambda self: True)
        _FakeGLWidget.gl_available = False
        window.action_gpu_viewport.setChecked(True)
        qtbot.waitUntil(lambda: not window.action_gpu_viewport.isChecked(),
                        timeout=2000)
        assert type(window.view.viewport()) is QWidget
        assert window.settings.value("canvas/gpu_viewport", True, type=bool) is False

    def test_persisted_on_before_first_show_is_not_checked_prematurely(
            self, window, qtbot):
        """The bug this guards: verifying at construction time (before the
        window is shown) would see no GL context yet on ANY machine — even a
        perfectly capable one — because a QOpenGLWidget only creates its
        context on first paint. So a persisted-on setting must survive
        construction unchanged and only get verified once actually shown."""
        _FakeGLWidget.gl_available = False
        window.settings.setValue("canvas/gpu_viewport", True)
        window.action_gpu_viewport.blockSignals(True)
        window.action_gpu_viewport.setChecked(True)  # simulate restored-on-launch
        window.action_gpu_viewport.blockSignals(False)
        assert window.action_gpu_viewport.isChecked()  # not touched yet

        window.showEvent(QShowEvent())
        qtbot.waitUntil(lambda: not window.action_gpu_viewport.isChecked(),
                        timeout=2000)
        assert type(window.view.viewport()) is QWidget

    def test_new_dashboard_page_matches_current_setting(self, window, qtbot):
        from flograph.core import Page
        from flograph.ui.commands import AddPageCommand
        page = Page(id="p1", title="Dash")
        window.undo_stack.push(AddPageCommand(window.graph, page))
        assert type(window._dashboard_pages["p1"].view.viewport()) is QWidget


class TestSettingsDialog:
    """SettingsDialog itself: constructed for real (never shown — the dialog
    isn't the thing that's unsafe here, a full *shown* MainWindow is), its
    Canvas page's checkbox bound both ways to the same action the tests
    above exercise directly."""

    def test_checkbox_reflects_initial_state(self, window):
        dlg = SettingsDialog(window, window)
        checkbox = dlg.findChild(QCheckBox, "gpu_viewport_checkbox")
        assert checkbox is not None
        assert checkbox.isChecked() == window.action_gpu_viewport.isChecked()

    def test_checking_it_enables_and_stays_on_when_gl_available(
            self, window, qtbot, monkeypatch):
        monkeypatch.setattr(type(window), "isVisible", lambda self: True)
        dlg = SettingsDialog(window, window)
        checkbox = dlg.findChild(QCheckBox, "gpu_viewport_checkbox")

        checkbox.setChecked(True)
        qtbot.wait(20)
        assert window.action_gpu_viewport.isChecked()
        assert checkbox.isChecked()

    def test_checking_it_reverts_and_unchecks_when_gl_unavailable(
            self, window, qtbot, monkeypatch):
        monkeypatch.setattr(type(window), "isVisible", lambda self: True)
        _FakeGLWidget.gl_available = False
        dlg = SettingsDialog(window, window)
        checkbox = dlg.findChild(QCheckBox, "gpu_viewport_checkbox")

        checkbox.setChecked(True)
        qtbot.waitUntil(lambda: not window.action_gpu_viewport.isChecked(),
                        timeout=2000)
        assert not checkbox.isChecked()  # the action's auto-revert bounced back
