"""CacheSaveRunnable: the background half of a save.

The runnable takes a plan snapshot from cache_persistence.plan_cache_save
and writes it on a pool thread, reporting progress and finishing with ""
or a human sentence for whatever went wrong. The GUI-thread half that
drives it is covered in test_saving_progress.py; here it is driven by hand.
"""
from pathlib import Path

from PySide6.QtCore import QThreadPool

import pytest

from flograph.core import Graph, NodeRegistry
from flograph.engine import ExecutionEngine
from flograph.engine.cache_worker import CacheSaveRunnable, CacheSaveSignals
from flograph.engine.cache_persistence import plan_cache_save


@pytest.fixture(scope="module")
def registry():
    reg = NodeRegistry()
    reg.load_builtins()
    return reg


def _planned(registry, tmp_path, compress=True):
    graph = Graph()
    engine = ExecutionEngine(graph)
    const = graph.add_node(registry.instantiate("flograph.util.constant"))
    engine.cache.set(const.id, {"value": "hello"}, wall_time=0.01)
    path = tmp_path / "proj.flograph"
    plan = plan_cache_save(graph, engine.cache)
    signals = CacheSaveSignals()
    runnable = CacheSaveRunnable(str(path), plan, signals, compress=compress)
    return path, const, signals, runnable


class TestCacheSaveRunnable:
    def test_writes_the_side_car_and_finishes_clean(self, qtbot, registry,
                                                    tmp_path):
        path, _, signals, runnable = _planned(registry, tmp_path)

        with qtbot.waitSignal(signals.finished, timeout=5000) as finished:
            QThreadPool.globalInstance().start(runnable)

        assert finished.args[0] == ""
        assert (Path(str(path) + ".cache") / "manifest.json").exists()

    def test_progress_is_reported_per_entry(self, qtbot, registry, tmp_path):
        path, _, signals, runnable = _planned(registry, tmp_path)
        seen = []
        signals.progressed.connect(lambda d, t: seen.append((d, t)))

        with qtbot.waitSignal(signals.finished, timeout=5000):
            QThreadPool.globalInstance().start(runnable)

        assert seen[-1] == (1, 1)

    def test_a_failed_write_finishes_with_a_sentence_not_an_exception(
            self, qtbot, registry, tmp_path):
        # a FILE where the side-car directory goes — mkdir raises OSError,
        # which must land in `finished` as text rather than killing the pool
        (tmp_path / "proj.flograph.cache").write_text("not a directory")
        path, _, signals, runnable = _planned(registry, tmp_path)

        with qtbot.waitSignal(signals.finished, timeout=5000) as finished:
            QThreadPool.globalInstance().start(runnable)

        message = finished.args[0]
        assert message          # something human, whatever the OS said
        assert "cached results" in message
