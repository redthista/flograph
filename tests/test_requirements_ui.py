"""AC in the window: Settings ▸ Packages keeps an index that installs use,
and opening a flow that needs something missing says so, with Tools ▸ What
This Flow Needs listing it and handing the names to Manage Packages."""
import json
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QLabel, QLineEdit, QPushButton

from flograph import packages
from flograph.core import NodeRegistry
from flograph.ui import mainwindow as mod
from flograph.ui import update_check
from flograph.ui.packages_dialog import PackagesDialog, configured_index
from flograph.ui.settings_dialog import SettingsDialog

MIRROR = "https://mirror.example.com/simple"

CODE = '''"""Needs Things

Imports two packages nobody has.
"""
NODE = {"label": "Needs Things", "category": "Scripting",
        "inputs": [], "outputs": [("out", "any")]}


def run(ctx):
    import zzq_nowhere_pkg
    from qqz_absent_pkg import thing
    return {"out": 1}
'''


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


@pytest.fixture
def toasts(monkeypatch):
    shown = []
    monkeypatch.setattr(
        update_check, "NoticeToast",
        lambda window, headline, *a, **k: SimpleNamespace(
            show_in_corner=lambda: shown.append(headline)))
    return shown


def _flow(tmp_path, nodes) -> str:
    path = tmp_path / "flow.flograph"
    path.write_text(json.dumps({
        "flograph_version": "0.1.14", "schema": 1,
        "graph": {"nodes": nodes, "connections": [], "frames": [],
                  "pages": []}}))
    return str(path)


NEEDY = {"id": "n1", "type": "flograph.scripting.python_script",
         "pos": [0, 0], "params": {}, "code": CODE, "label": "Needs Things"}
NOTE = {"id": "n2", "type": "flograph.util.note", "pos": [0, 200],
        "params": {"text": "hello", "width": 200, "height": 80},
        "code": None, "label": None}


class TestSettingsPackagesPage:

    def _page(self, window, qtbot):
        dialog = SettingsDialog(window)
        qtbot.addWidget(dialog)
        assert "Packages" in dialog.page_names()
        return (dialog, dialog.findChild(QLineEdit, "package_index_url_edit"),
                dialog.findChild(QLineEdit, "package_trusted_host_edit"),
                dialog.findChild(QLabel, "package_index_in_force_label"))

    def test_an_index_is_kept_and_said(self, window, qtbot):
        _dialog, url, host, in_force = self._page(window, qtbot)
        url.setText(MIRROR)
        url.editingFinished.emit()
        host.setText("mirror.example.com")
        host.editingFinished.emit()
        index = configured_index(window.settings)
        assert index.url == MIRROR
        assert index.hosts() == ["mirror.example.com"]
        assert MIRROR in in_force.text()
        assert "Settings" in in_force.text()

    def test_a_bad_address_is_not_kept(self, window, qtbot):
        _dialog, url, _host, in_force = self._page(window, qtbot)
        url.setText("mirror.example.com/simple")
        url.editingFinished.emit()
        assert not configured_index(window.settings)
        assert in_force.text().startswith("⚠")

    def test_a_reset_empties_the_boxes(self, window, qtbot):
        dialog, url, _host, _in_force = self._page(window, qtbot)
        url.setText(MIRROR)
        url.editingFinished.emit()
        window.settings.clear()
        dialog.refresh_from(window)
        assert url.text() == ""


class TestManagePackagesUsesIt:

    def test_the_install_goes_to_the_index(self, window, qtbot, monkeypatch):
        window.settings.setValue("packages/index_url", MIRROR)
        dialog = PackagesDialog(window)
        qtbot.addWidget(dialog)
        assert MIRROR in dialog.findChild(QLabel,
                                          "packages_index_label").text()
        seen = []

        def build(action, specs, index=None, **kwargs):
            seen.append((action, specs, index))
            raise ValueError("stop here")      # no installer is started
        monkeypatch.setattr(packages, "build_command", build)
        dialog.prefill(["requests", "polars"])
        dialog._install()
        action, specs, index = seen[0]
        assert (action, specs) == ("install", ["requests", "polars"])
        assert index.url == MIRROR


class TestOpeningAFlowThatNeedsThings:

    def test_it_says_so(self, window, tmp_path, toasts):
        assert window.open_path(_flow(tmp_path, [NEEDY, NOTE]), confirm=False)
        assert toasts == ["This flow needs 2 things that aren’t installed"]

    def test_nothing_missing_nothing_said(self, window, tmp_path, toasts):
        assert window.open_path(_flow(tmp_path, [NOTE]), confirm=False)
        assert toasts == []

    def test_it_can_be_turned_off(self, window, tmp_path, toasts):
        window.settings.setValue("packages/notify_missing", False)
        assert window.open_path(_flow(tmp_path, [NEEDY]), confirm=False)
        assert toasts == []

    def test_the_list_and_the_hand_over(self, window, tmp_path, toasts,
                                        monkeypatch):
        window.open_path(_flow(tmp_path, [NEEDY, NOTE]), confirm=False)
        window._show_requirements()
        dialog = window._requirements_dialog
        names = [n.name for n in dialog.needs]
        assert "zzq_nowhere_pkg" in names and "qqz_absent_pkg" in names
        assert "pandas" not in names, "flograph's own are left out"
        install = dialog.findChild(QPushButton, "requirements_install_button")
        assert install.isEnabled()
        install.click()
        box = window._packages_dialog._install_edit.text().split()
        assert sorted(box) == ["qqz_absent_pkg", "zzq_nowhere_pkg"]
        dialog.close()
        window._packages_dialog.close()
