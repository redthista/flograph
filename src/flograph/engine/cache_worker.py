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
            try:
                outputs = cache_persistence.load_blob(self.project_path, node_id)
            except Exception:
                continue
            self.signals.entry_loaded.emit(node_id, outputs, meta.get("wall_time", 0.0))
        self.signals.finished.emit()
