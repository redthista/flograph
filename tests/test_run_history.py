"""Run statistics saved beside the cache.

A run's record used to live only for the session — reopening a project
meant a blank statistics window until something ran again. Now each save
writes runs.json into the side-car, and opening loads it back. The records
are plain scalar dataclasses, so this is mostly a question of refusing to
let a bad file matter.
"""
import pytest

from flograph.core import Graph, NodeRegistry
from flograph.engine import ExecutionEngine
from flograph.engine.cache_persistence import (
    load_run_history, save_run_history,
)
from flograph.engine.runstats import NodeRun, RunHistory, RunRecord


@pytest.fixture(scope="module")
def registry():
    reg = NodeRegistry()
    reg.load_builtins()
    return reg


def _record(ok=True, nodes=2):
    r = RunRecord(when=1000.0, wall_time=4.25, ok=ok,
                  skipped_clean=3, workers=4, peak_concurrency=2)
    for i in range(nodes):
        r.nodes.append(NodeRun(
            node_id=f"n{i}", label=f"Step {i}",
            outcome="ok" if ok else "failed",
            started=i * 1.5, wall_time=1.5 - i * 0.25,
            output_bytes=1000 * (i + 1), summary=f"{i} rows",
            rss_start=10_000_000, rss_peak=12_000_000 + i,
            concurrent=1 + (i % 2)))
    return r


class TestRoundTrip:
    def test_a_record_survives_the_dict_round_trip(self):
        original = _record()
        clone = RunRecord.from_dict(original.to_dict())
        assert clone.when == original.when
        assert clone.wall_time == original.wall_time
        assert clone.skipped_clean == 3 and clone.workers == 4
        assert [(n.node_id, n.label, n.outcome, n.wall_time)
                for n in clone.nodes] == [
            (n.node_id, n.label, n.outcome, n.wall_time) for n in original.nodes]
        assert clone.nodes[1].rss_growth == original.nodes[1].rss_growth

    def test_partial_junk_degrades_to_defaults(self):
        clone = RunRecord.from_dict({"when": "5", "nodes": [{"node_id": "x"},
                                                            "not-a-dict", 7]})
        assert clone.when == 5.0
        assert [n.node_id for n in clone.nodes] == ["x"]


class TestSidecarPersistence:
    def test_save_then_load_preserves_order_and_content(self, tmp_path):
        history = RunHistory(limit=5)
        history.add(_record(ok=True))
        history.add(_record(ok=False, nodes=1))     # newest last
        path = tmp_path / "proj.flograph"

        save_run_history(history, path)

        loaded = load_run_history(path)
        assert len(loaded) == 2
        assert loaded[0].ok is True                  # oldest first on disk
        assert loaded[-1].ok is False

    def test_missing_file_means_no_history(self, tmp_path):
        assert load_run_history(tmp_path / "never.flograph") == []

    def test_a_corrupt_file_is_no_history_not_a_crash(self, tmp_path):
        path = tmp_path / "proj.flograph"
        side = tmp_path / "proj.flograph.cache"
        side.mkdir()
        (side / "runs.json").write_text("{runs: [broken")

        assert load_run_history(path) == []

    def test_reset_caches_leaves_the_run_log_alone(self, registry, tmp_path):
        """The run log lives beside the blobs but is not a blob: wiping the
        cache must not forget what runs cost."""
        from flograph.engine.cache import OutputCache
        from flograph.engine.cache_persistence import save_cache

        graph = Graph()
        const = graph.add_node(registry.instantiate("flograph.util.constant"))
        cache = OutputCache()
        cache.set(const.id, {"value": "v"}, wall_time=0.01)
        history = RunHistory(limit=5)
        history.add(_record())
        path = tmp_path / "proj.flograph"

        save_run_history(history, path)
        cache.clear()                    # Reset Caches
        save_cache(graph, cache, path)   # next save prunes the side-car

        assert load_run_history(path)[0].wall_time == _record().wall_time


class TestWindowIntegration:
    @pytest.fixture(autouse=True)
    def _isolated_settings(self, tmp_path, monkeypatch):
        from PySide6.QtCore import QSettings

        from flograph.ui import mainwindow as mod
        ini_path = str(tmp_path / "settings.ini")
        monkeypatch.setattr(
            mod, "QSettings",
            lambda *a, **k: QSettings(ini_path, QSettings.IniFormat))

    def test_reopening_shows_the_previous_run(self, qtbot, registry, tmp_path):
        from flograph.ui import mainwindow as mod

        def window():
            win = mod.MainWindow(registry)
            win.confirm_close = False
            qtbot.addWidget(win)
            return win

        first = window()
        const = first.graph.add_node(
            registry.instantiate("flograph.util.constant"))
        with qtbot.waitSignal(first.engine.run_finished, timeout=20000):
            first.engine.run_all()
        project = tmp_path / "withhistory.flograph"
        first._project_path = str(project)
        assert first._save() is True
        qtbot.waitUntil(lambda: first._cache_save_signals is None,
                        timeout=10000)
        expected = first.engine.history.latest

        second = window()
        assert second.open_path(str(project), confirm=False) is True
        restored = second.engine.history.latest
        assert restored is not None
        assert restored.wall_time == expected.wall_time
        assert [n.label for n in restored.nodes] == \
            [n.label for n in expected.nodes]
        # and the status-bar readout has something to say immediately
        assert second.resource_monitor._run_text() != "Run: —"
