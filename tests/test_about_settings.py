"""ideas.md item 20: an About page in Settings showing the installed
flograph version (plus Python/Qt versions), so users can tell what build
they're running without checking pyproject.toml. Also covers the Settings
nav being sorted ascending (General/Canvas/About -> About/Canvas/General)
rather than insertion order.

Settings kept off the real store (avoid polluting the developer's actual
flograph.conf) -- see test_lod_settings.py's fixture of the same name."""
import importlib.metadata

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QLabel

from flograph.core import NodeRegistry
from flograph.ui import mainwindow as mod
from flograph.ui.settings_dialog import SettingsDialog, _flograph_version


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


def _all_labels(widget):
    return widget.findChildren(QLabel)


class TestAboutPage:
    def test_about_is_a_nav_entry(self, window):
        dialog = SettingsDialog(window)
        items = [dialog._nav.item(i).text() for i in range(dialog._nav.count())]
        assert "About" in items

    def test_about_page_shows_the_installed_version(self, window):
        dialog = SettingsDialog(window)
        about_index = [
            dialog._nav.item(i).text() for i in range(dialog._nav.count())
        ].index("About")
        page = dialog._pages.widget(about_index)
        text = " ".join(label.text() for label in _all_labels(page))
        assert _flograph_version() in text

    def test_version_helper_matches_installed_metadata(self):
        assert _flograph_version() == importlib.metadata.version("flograph")


class TestNavSortOrder:
    def test_nav_entries_are_sorted_ascending(self, window):
        dialog = SettingsDialog(window)
        items = [dialog._nav.item(i).text() for i in range(dialog._nav.count())]
        assert items == sorted(items)
