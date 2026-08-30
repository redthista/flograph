"""The GUI half of saving: a cache-free project writes its (small) bundle
synchronously, a project with cached results writes the whole .flograph
archive on a pool thread behind the status line's second bar, a disk-full
save says so instead of vanishing, and the drive the project lives on is
watched for running low (K1/K2).

Settings kept off the real store -- see test_minimap_settings.py."""
import errno
import zlib
from pathlib import Path

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QCheckBox

from flograph.core import Graph, NodeRegistry, container, serialization
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


@pytest.fixture
def cached_constant(window, registry):
    """A one-node flow whose result is in the cache — something to write."""
    const = window.graph.add_node(
        registry.instantiate("flograph.util.constant"))
    window.engine.cache.set(const.id, {"value": "hello"}, wall_time=0.01)
    return const


class TestBackgroundCacheSave:
    def test_save_finishes_with_the_bundle_written(self, qtbot, window,
                                                   cached_constant,
                                                   tmp_path):
        path = tmp_path / "proj.flograph"
        window._project_path = str(path)

        assert window._save() is True

        # a project with cached results lands off-thread; wait it out
        qtbot.waitUntil(lambda: window._cache_save_signals is None,
                        timeout=10000)
        assert container.is_bundle(path)
        with container.BundleReader(path) as reader:
            assert reader.has(container.MANIFEST_MEMBER)
            assert reader.has(container.blob_member(cached_constant.id))
        assert window._save_bar.isHidden()
        assert window.status_message().startswith("Saved ")

    def test_a_second_save_waits_for_the_first(self, window, cached_constant,
                                               tmp_path):
        window._project_path = str(tmp_path / "proj.flograph")
        window._cache_save_signals = mod.CacheSaveSignals(parent=window)

        assert window._save() is False
        assert "try again" in window.status_message()

        window._cache_save_signals = None      # put it back: nothing pending

    def test_save_as_refuses_before_moving_the_project(self, window,
                                                       tmp_path):
        window._project_path = str(tmp_path / "old.flograph")
        window._cache_save_signals = mod.CacheSaveSignals(parent=window)

        assert window._save_as() is False
        # the project did not silently move to a file that was never written
        assert window._project_path == str(tmp_path / "old.flograph")
        window._cache_save_signals = None

    def test_runs_wait_for_a_write_in_flight(self, window, cached_constant):
        window._cache_save_signals = mod.CacheSaveSignals(parent=window)

        assert window._cache_still_writing() is True
        window._run_all()                       # must not start anything
        assert not window.engine.active

        window._cache_save_signals = None
        assert window._cache_still_writing() is False

    def test_nothing_cached_writes_the_bundle_synchronously(self, qtbot,
                                                            window, tmp_path):
        path = tmp_path / "empty.flograph"
        window._project_path = str(path)

        assert window._save() is True
        assert window._cache_save_signals is None   # no background thread
        assert container.is_bundle(path)
        assert window.status_message().startswith("Saved ")


class TestCompressionSetting:
    def test_default_is_on_and_the_toggle_persists(self, window):
        assert window.cache_compression_enabled is True
        window.set_cache_compression_enabled(False)
        assert window.settings.value("saving/compress_cache", True,
                                     type=bool) is False
        window.set_cache_compression_enabled(True)
        assert window.settings.value("saving/compress_cache", True,
                                     type=bool) is True

    def _blob_in_bundle(self, path, node_id):
        with container.BundleReader(path) as reader:
            return reader.read_bytes(container.blob_member(node_id))

    def test_off_writes_raw_blobs(self, qtbot, window, cached_constant,
                                  registry, tmp_path):
        window.set_cache_compression_enabled(False)
        const_id = cached_constant.id
        path = tmp_path / "raw.flograph"
        window._project_path = str(path)

        window._save()
        qtbot.waitUntil(lambda: window._cache_save_signals is None,
                        timeout=10000)

        assert self._blob_in_bundle(path, const_id)[:1] == b"\x80"

    def test_on_writes_zlib_blobs(self, qtbot, window, cached_constant,
                                  tmp_path):
        assert window.cache_compression_enabled is True
        const_id = cached_constant.id
        path = tmp_path / "zipped.flograph"
        window._project_path = str(path)

        window._save()
        qtbot.waitUntil(lambda: window._cache_save_signals is None,
                        timeout=10000)

        blob = self._blob_in_bundle(path, const_id)
        assert blob[:1] != b"\x80"
        zlib.decompress(blob)   # really a zlib stream

    def test_the_settings_dialog_row_round_trips(self, qtbot, window):
        dialog = SettingsDialog(window)
        qtbot.addWidget(dialog)
        box = dialog.findChild(QCheckBox, "cache_compression_checkbox")
        assert box is not None
        assert box.isChecked() is True
        box.setChecked(False)
        assert window.cache_compression_enabled is False


class TestDiskFullOnSave:
    def test_a_failed_json_write_names_itself_in_a_dialog(
            self, qtbot, window, monkeypatch, tmp_path):
        # the plain-JSON path (cache not bundled): serialization.save fails
        window.set_save_cache_in_project(False)
        window._project_path = str(tmp_path / "proj.flograph")
        seen = {}

        def boom(graph, path):
            raise OSError(errno.ENOSPC, "No space left on device")

        def fake_critical(parent, title, text):
            seen["title"], seen["text"] = title, text

        monkeypatch.setattr(mod.serialization, "save", boom)
        monkeypatch.setattr(mod.QMessageBox, "critical", fake_critical)

        assert window._save() is False
        assert seen["title"] == "Save failed"
        assert "full" in seen["text"]
        # and nothing pretended otherwise: no background write was started
        assert window._cache_save_signals is None

    def test_a_failed_bundle_write_reaches_a_dialog(
            self, qtbot, window, cached_constant, monkeypatch, tmp_path):
        # the bundle path: the background write fails, and the failure
        # surfaces in a dialog rather than vanishing on the pool thread
        target = tmp_path / "proj.flograph"
        target.mkdir()                       # os.replace onto a dir -> OSError
        (target / "x").write_text("non-empty")
        window._project_path = str(target)
        seen = {}
        monkeypatch.setattr(mod.QMessageBox, "critical",
                            lambda p, t, x: seen.setdefault("t", (t, x)))

        assert window._save() is True        # kicks off the background write
        qtbot.waitUntil(lambda: window._cache_save_signals is None,
                        timeout=10000)
        assert seen["t"][0] == "Save failed"


class TestDiskWatchWiring:
    def test_opening_a_project_points_the_watch_at_its_drive(
            self, qtbot, window, registry, tmp_path):
        path = tmp_path / "proj.flograph"
        graph = Graph()
        graph.add_node(registry.instantiate("flograph.util.constant"))
        serialization.save(graph, path)

        assert window.open_path(str(path)) is True
        # full path kept (the kernel resolves its mount), label non-empty
        assert window.resource_monitor._disk_path == str(path)
        assert window.resource_monitor._disk_drive

    def test_a_new_project_unwatches(self, qtbot, window, registry, tmp_path):
        path = tmp_path / "proj.flograph"
        graph = Graph()
        graph.add_node(registry.instantiate("flograph.util.constant"))
        serialization.save(graph, path)
        window.open_path(str(path))

        window._new_project()
        assert window.resource_monitor._disk_path is None
        assert window.resource_monitor._disk_drive is None