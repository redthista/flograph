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


class CacheSaveSignals(QObject):
    # (done, total) after each planned entry, whatever became of it
    progressed = Signal(int, int)
    # The failure to show the user, or "" on success. A message rather than
    # an exception object: the text is chosen where the failure happened,
    # and a full-disk save has its own sentence (save_failure_text).
    finished = Signal(str)


class CacheSaveRunnable(QRunnable):
    """Writes a whole .flograph bundle from a cache_persistence.
    plan_project_save snapshot off the GUI thread, so saving a flow whose
    cache holds gigabytes does not look like a hang. The snapshot was taken
    before this started, so neither the graph nor the cache is touched here
    — editing and running go on while the archive streams out.

    `prev_path` is the file to copy unchanged/spilled blobs from — the same
    path on a plain Save, the old path on Save As. `carry_all` copies every
    blob the previous file held and re-pickles nothing (the mid-run save).

    An OSError — the disk filling up, most commonly — lands in `finished`
    as its human sentence rather than vanishing: that is K2's whole point.
    """

    def __init__(self, project_path: str,
                 plan: "cache_persistence.ProjectSavePlan",
                 signals: CacheSaveSignals, compress: bool = True,
                 prev_path: "str | None" = None,
                 carry_all: bool = False) -> None:
        super().__init__()
        self.project_path = project_path
        self.plan = plan
        self.signals = signals
        self.compress = compress
        self.prev_path = prev_path
        self.carry_all = carry_all

    def run(self) -> None:  # executes on a pool thread
        try:
            cache_persistence.write_project(
                self.project_path, self.plan,
                prev_path=self.prev_path, compress=self.compress,
                carry_all=self.carry_all,
                progress=lambda done, total: self.signals.progressed.emit(
                    done, total))
        except Exception as exc:
            self.signals.finished.emit(
                cache_persistence.save_failure_text("the project file", exc))
            return
        self.signals.finished.emit("")
