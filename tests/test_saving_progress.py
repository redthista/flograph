"""The GUI half of saving: a cache-free project writes its (small) bundle
synchronously, a project with cached results writes the whole .flograph
archive on a pool thread behind the status line's second bar, a disk-full
save says so instead of vanishing, and the drive the project lives on is
watched for running low (K1/K2).

Settings kept off the real store -- see test_minimap_settings.py."""
import errno
import threading
import zlib
from pathlib import Path

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QCheckBox, QFrame

from flograph.core import Graph, NodeRegistry, container, serialization
from flograph.engine import cache_persistence
from flograph.engine.cache import OutputCache
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


class TestSaveDuringARun:
    def test_what_the_run_made_is_what_the_file_holds(self, qtbot, window,
                                                      cached_constant,
                                                      tmp_path):
        # Issue 8: a Save while the engine was busy copied the previous
        # file's results, so a re-run value reopened as the old one.
        path = tmp_path / "proj.flograph"
        window._project_path = str(path)
        assert window._save() is True
        qtbot.waitUntil(lambda: window._cache_save_signals is None,
                        timeout=10000)

        window.engine.cache.set(cached_constant.id, {"value": "re-run"},
                                wall_time=0.01)
        window.engine._active = True             # a run is going
        try:
            assert window._save() is True
            qtbot.waitUntil(lambda: window._cache_save_signals is None,
                            timeout=10000)
        finally:
            window.engine._active = False

        reloaded = serialization.load(path, window.registry)
        fresh = OutputCache()
        assert cache_persistence.register_cache(reloaded, fresh, path) == [
            cached_constant.id]
        assert fresh.outputs_for(cached_constant.id) == {"value": "re-run"}


class TestResultsASaveCouldNotStore:
    def _visible_toasts(self, window):
        return [t for t in window.findChildren(QFrame, "unsaved_results_toast")
                if t.isVisibleTo(window)]

    def test_said_in_the_corner_once_per_node(self, qtbot, window, registry,
                                              tmp_path):
        const = window.graph.add_node(
            registry.instantiate("flograph.util.constant"))
        window.engine.cache.set(const.id, {"value": threading.Lock()},
                                wall_time=0.01)
        window._project_path = str(tmp_path / "proj.flograph")

        assert window._save() is True
        qtbot.waitUntil(lambda: window._cache_save_signals is None,
                        timeout=10000)
        toasts = self._visible_toasts(window)
        assert len(toasts) == 1
        for toast in toasts:
            toast.close()

        # the same node on the next save is not news
        assert window._save() is True
        qtbot.waitUntil(lambda: window._cache_save_signals is None,
                        timeout=10000)
        assert self._visible_toasts(window) == []


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
    def test_a_failed_workflow_export_names_itself_in_a_dialog(
            self, qtbot, window, monkeypatch, tmp_path):
        # Export Workflow is a plain serialization.save; a full disk there
        # must surface as a dialog, not a bare traceback
        window._project_path = str(tmp_path / "proj.flograph")
        seen = {}

        def boom(graph, path):
            raise OSError(errno.ENOSPC, "No space left on device")

        monkeypatch.setattr(mod.serialization, "save", boom)
        monkeypatch.setattr(mod.QMessageBox, "critical",
                            lambda p, t, x: seen.update(title=t, text=x))
        monkeypatch.setattr(mod.QFileDialog, "getSaveFileName",
                            staticmethod(lambda *a, **k: (
                                str(tmp_path / "wf.flowf"), "")))

        assert window._export_workflow() is False
        assert seen["title"] == "Export failed"
        assert "full" in seen["text"]

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


class TestWorkflowExport:
    def _pick(self, monkeypatch, path):
        monkeypatch.setattr(mod.QFileDialog, "getSaveFileName",
                            staticmethod(lambda *a, **k: (str(path), "")))

    def test_export_writes_plain_json_and_leaves_the_project_alone(
            self, qtbot, window, cached_constant, monkeypatch, tmp_path):
        window._project_path = str(tmp_path / "proj.flograph")
        flowf = tmp_path / "wf.flowf"
        self._pick(monkeypatch, flowf)

        assert window._export_workflow() is True
        assert flowf.exists()
        assert not container.is_bundle(flowf)          # plain JSON
        import json
        json.loads(flowf.read_text())
        # the working file is untouched: still aimed at the .flograph, no
        # background write kicked off
        assert window._project_path == str(tmp_path / "proj.flograph")
        assert window._cache_save_signals is None
        assert "Exported workflow" in window.status_message()

    def test_opening_a_flowf_then_save_routes_to_save_as(
            self, qtbot, window, registry, monkeypatch, tmp_path):
        graph = Graph()
        graph.add_node(registry.instantiate("flograph.util.constant"))
        flowf = tmp_path / "wf.flowf"
        serialization.save(graph, flowf)

        assert window.open_path(str(flowf)) is True
        assert window._project_path == str(flowf)

        # Ctrl+S on an opened .flowf must not write the .flowf — it opens
        # Save As for a real .flograph
        target = tmp_path / "adopted.flograph"
        self._pick(monkeypatch, target)
        assert window._save() is True
        qtbot.waitUntil(lambda: window._cache_save_signals is None,
                        timeout=10000)
        assert container.is_bundle(target)
        assert window._project_path == str(target)

    def test_save_as_over_a_flowf_name_yields_a_flograph(
            self, qtbot, window, monkeypatch, tmp_path):
        window._project_path = None
        self._pick(monkeypatch, tmp_path / "typed.flowf")
        assert window._save_as() is True
        qtbot.waitUntil(lambda: window._cache_save_signals is None,
                        timeout=10000)
        assert window._project_path == str(tmp_path / "typed.flograph")


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

class TestSaveBeforeProjectSwitch:
    """flograph issue #92: finish saving the outgoing graph first."""

    @pytest.mark.parametrize("action", ["open", "new", "example", "close"])
    def test_save_finishes_before_leaving_the_current_project(
            self, action, qtbot, window, cached_constant, monkeypatch, tmp_path):
        from PySide6.QtCore import QTimer
        from flograph.ui.commands import SetParamCommand

        outgoing = tmp_path / "outgoing.flograph"
        incoming = tmp_path / "incoming.flograph"
        serialization.save(Graph(), incoming)
        window._project_path = str(outgoing)
        window.undo_stack.push(SetParamCommand(
            window.graph, cached_constant.id, "value", "changed"))
        monkeypatch.setattr(mod.QMessageBox, "question",
                            lambda *a, **k: mod.QMessageBox.Save)
        original_write = cache_persistence.write_project
        started, release = threading.Event(), threading.Event()
        observed = []

        def delayed_write(*args, **kwargs):
            started.set()
            if not release.wait(5):
                raise OSError("test did not release save")
            return original_write(*args, **kwargs)

        def inspect_then_release():
            if not started.is_set():
                QTimer.singleShot(10, inspect_then_release)
                return
            observed.append((window._project_path,
                             cached_constant.id in window.graph.nodes))
            release.set()

        monkeypatch.setattr(cache_persistence, "write_project", delayed_write)
        QTimer.singleShot(10, inspect_then_release)
        try:
            if action == "open":
                assert window.open_path(str(incoming))
            elif action == "new":
                window._new_project()
            elif action == "example":
                window._open_example(incoming)
            else:
                window.confirm_close = True
                from PySide6.QtGui import QCloseEvent
                event = QCloseEvent()
                window.closeEvent(event)
                assert event.isAccepted()
            qtbot.waitUntil(lambda: bool(observed), timeout=6000)
            assert observed == [(str(outgoing), True)]
            assert window._cache_save_signals is None
            saved = serialization.load(outgoing, window.registry)
            assert saved.nodes[cached_constant.id].params["value"] == "changed"
        finally:
            release.set()
            window.confirm_close = False

    @pytest.mark.parametrize("cached", [False, True])
    def test_failed_save_keeps_the_current_project(
            self, cached, qtbot, window, registry, monkeypatch, tmp_path):
        from flograph.ui.commands import SetParamCommand

        node = window.graph.add_node(
            registry.instantiate("flograph.util.constant"))
        window.undo_stack.push(SetParamCommand(window.graph, node.id,
                                               "value", "keep me"))
        if cached:
            window.engine.cache.set(node.id, {"value": "keep me"}, wall_time=0.01)
        outgoing = tmp_path / "outgoing.flograph"
        incoming = tmp_path / "incoming.flograph"
        serialization.save(Graph(), incoming)
        window._project_path = str(outgoing)
        errors = []
        monkeypatch.setattr(mod.QMessageBox, "question",
                            lambda *a, **k: mod.QMessageBox.Save)
        monkeypatch.setattr(mod.QMessageBox, "critical",
                            lambda *a: errors.append(a[1]))

        def fail(*args, **kwargs):
            raise OSError(errno.ENOSPC, "No space left on device")

        monkeypatch.setattr(cache_persistence, "write_project", fail)
        assert window.open_path(str(incoming)) is False
        assert window._project_path == str(outgoing)
        assert node.id in window.graph.nodes
        assert not window.undo_stack.isClean()
        assert errors == ["Save failed"]

    def test_cancelling_the_wait_leaves_the_save_connected(
            self, qtbot, window, cached_constant, monkeypatch, tmp_path):
        from PySide6.QtCore import QTimer
        from PySide6.QtWidgets import QProgressDialog

        window._project_path = str(tmp_path / "outgoing.flograph")
        release = threading.Event()
        original_write = cache_persistence.write_project

        def delayed_write(*args, **kwargs):
            if not release.wait(5):
                raise OSError("test did not release save")
            return original_write(*args, **kwargs)

        monkeypatch.setattr(cache_persistence, "write_project", delayed_write)
        assert window._save()
        signals = window._cache_save_signals
        QTimer.singleShot(10, lambda: window.findChild(QProgressDialog).cancel())
        try:
            assert window._confirm_discard() is False
            assert window._cache_save_signals is signals
            assert cached_constant.id in window.graph.nodes
        finally:
            release.set()
            qtbot.waitUntil(lambda: window._cache_save_signals is None,
                            timeout=6000)
        assert window.status_message().startswith("Saved ")

    def test_clean_project_also_finishes_a_save_already_in_flight(
            self, qtbot, window, cached_constant, monkeypatch, tmp_path):
        from PySide6.QtCore import QTimer

        outgoing = tmp_path / "outgoing.flograph"
        incoming = tmp_path / "incoming.flograph"
        serialization.save(Graph(), incoming)
        window._project_path = str(outgoing)
        release = threading.Event()
        original_write = cache_persistence.write_project

        def delayed_write(*args, **kwargs):
            if not release.wait(5):
                raise OSError("test did not release save")
            return original_write(*args, **kwargs)

        monkeypatch.setattr(cache_persistence, "write_project", delayed_write)
        monkeypatch.setattr(mod.QMessageBox, "question",
                            lambda *a, **k: pytest.fail("clean project prompted"))
        assert window.undo_stack.isClean()
        assert window._save()
        QTimer.singleShot(10, release.set)
        try:
            assert window.open_path(str(incoming))
            assert window._cache_save_signals is None
            assert container.is_bundle(outgoing)
            assert window._project_path == str(incoming)
        finally:
            release.set()
