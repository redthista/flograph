"""Restores node output caches off the GUI thread.

Mirrors worker.py: resolving which entries are still valid (manifest read +
fingerprint hashing) is cheap and stays on the GUI thread. Unpickling each
blob is the part that can take a long time for large cached DataFrames or
figures, so it runs one node at a time on a pool thread. The runnable only
computes — the GUI thread is the one that calls cache.set/mark_clean, via
queued signals, same boundary the scheduler keeps for node execution.
"""
from __future__ import annotations

from typing import Any

from PySide6.QtCore import QObject, QRunnable, Signal

from . import cache_persistence


class CacheLoadSignals(QObject):
    entry_loaded = Signal(str, object, float)  # node_id, outputs, wall_time
    finished = Signal()


class CacheLoadRunnable(QRunnable):
    def __init__(
        self,
        project_path: str,
        entries: list[tuple[str, dict[str, Any]]],
        signals: CacheLoadSignals,
    ) -> None:
        super().__init__()
        self.project_path = project_path
        self.entries = entries
        self.signals = signals

    def run(self) -> None:  # executes on a pool thread
        for node_id, meta in self.entries:
            if cache_persistence.is_alias(meta):
                # shares another node's blob — there is nothing to unpickle,
                # and rebuilding it means reading the cache, which belongs to
                # the GUI thread (see cache_persistence.restore_aliases)
                continue
            try:
                outputs = cache_persistence.load_blob(self.project_path, node_id)
            except Exception:
                continue
            self.signals.entry_loaded.emit(node_id, outputs, meta.get("wall_time", 0.0))
        self.signals.finished.emit()


class CacheWarmSignals(QObject):
    warmed = Signal(str, object)     # node_id, outputs (None if it could not be read)
    # Carries the run generation it belongs to, so a warm still in flight from
    # a cancelled run cannot be mistaken for this one's. Passed through the
    # signal rather than captured in a lambda at the connect site — a lambda
    # there is not reliably kept alive, and a `finished` that never arrives
    # leaves the run waiting forever.
    finished = Signal(int)


class CacheWarmRunnable(QRunnable):
    """Reads spilled entries back before a run needs them.

    Same division of labour as CacheLoadRunnable, for the other direction:
    opening a project registers entries without loading them, so by the time
    a run starts its inputs may be on disk. Unpickling those on the GUI
    thread — which is where nodes are started from — would freeze the window
    for as long as the largest blob takes, so the engine warms them here
    first and dispatches when they are back.

    A blob that will not read comes back as None rather than being skipped:
    the engine has to *know*, so it can drop the entry and let the node
    recompute instead of handing the flow a missing input.
    """

    def __init__(self, project_path: str, node_ids: list[str],
                 signals: CacheWarmSignals, generation: int = 0) -> None:
        super().__init__()
        self.project_path = project_path
        self.node_ids = node_ids
        self.signals = signals
        self.generation = generation

    def run(self) -> None:  # executes on a pool thread
        for node_id in self.node_ids:
            try:
                outputs = cache_persistence.load_outputs(self.project_path, node_id)
            except Exception:
                outputs = None
            self.signals.warmed.emit(node_id, outputs)
        self.signals.finished.emit(self.generation)
