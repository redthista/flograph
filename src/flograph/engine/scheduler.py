"""Execution scheduling: dirty subgraph -> topo-ordered plan -> serial
execution on a single-thread pool, with per-node caching.

ExecutionEngine lives on the GUI thread. Workers hand results back via queued
signals; all graph/cache mutation happens here, never on pool threads.
"""
from __future__ import annotations

import time
from typing import Iterable, Optional

from PySide6.QtCore import QObject, QThreadPool, QTimer, Signal

from flograph.core.graph import Graph
from flograph.core.links import from_problem
from flograph.core.node import NodeStatus

from .cache import OutputCache
from .context import CancellationToken
from .errors import NodeError
from .runstats import (SAMPLE_MS, NodeRun, ProcessSampler, RunHistory,
                       RunRecord)
from .worker import NodeRunnable, WorkerSignals


def build_plan(graph: Graph, targets: Iterable[str],
               cache: "Optional[OutputCache]" = None) -> list[str]:
    """The nodes that must execute to satisfy `targets`: every *dirty* node
    among the targets and their ancestors, in topological order. Clean nodes
    are skipped — their outputs come from the cache.

    `cache` is consulted only to tell a frozen node that has something to
    serve from one that does not; None means "nothing is cached".
    """
    wanted = set(targets)
    for target in list(wanted):
        wanted |= graph.upstream(target)
    # A deactivated node never runs, and nor does anything that would have
    # consumed its output. Dropping the descendants here rather than letting
    # them start and fail matters: they would each report a missing upstream
    # value, which reads as a broken graph instead of the deliberate choice
    # it is. A node deactivated *downstream* of the targets is not in
    # `wanted` to begin with, so this only ever removes.
    for node_id, node in graph.nodes.items():
        if not node.active:
            wanted -= {node_id} | graph.downstream(node_id)
        elif node.frozen and cache is not None and cache.has(node_id):
            # The opposite of deactivating: the node itself is skipped but
            # everything below it stays, running off the value it is
            # pinning. Dirtiness does not get a say — a pin that a stray
            # edit could knock loose would not be worth setting.
            #
            # A frozen node with nothing cached is left in on purpose. You
            # cannot pause something that has not produced anything yet, so
            # it runs once to fill the pin and is skipped from then on.
            wanted.discard(node_id)
    return [nid for nid in graph.topo_order()
            if nid in wanted and graph.nodes[nid].dirty]


def skipped_summary(graph: Graph, targets: Iterable[str],
                    cache: "Optional[OutputCache]",
                    plan: Iterable[str]) -> tuple:
    """`(clean, frozen, inactive)` — why the nodes this run left out were
    left out.

    Walks the same closure build_plan does rather than having build_plan
    hand the numbers back: the plan is what the engine needs and this is
    what the stats panel needs, and keeping them apart leaves build_plan a
    function that returns one thing.
    """
    considered = set(targets)
    for target in list(considered):
        considered |= graph.upstream(target)
    blocked: set = set()
    for node_id, node in graph.nodes.items():
        if not node.active:
            blocked |= {node_id} | graph.downstream(node_id)
    running = set(plan)
    clean = frozen = inactive = 0
    for node_id in considered - running:
        node = graph.nodes.get(node_id)
        if node is None:
            continue
        if node_id in blocked:
            inactive += 1
        elif node.frozen and cache is not None and cache.has(node_id):
            frozen += 1
        else:
            clean += 1
    return clean, frozen, inactive


class ExecutionEngine(QObject):
    run_started = Signal()
    run_finished = Signal(bool)            # ok: no node failed
    node_log = Signal(str, str, str)       # node_id, line, stream
    node_failed = Signal(str, object)      # node_id, NodeError
    node_succeeded = Signal(str)           # node_id
    run_recorded = Signal(object)          # RunRecord — a finished run's cost

    def __init__(self, graph: Graph, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self.graph = graph
        self.cache = OutputCache()
        # the process-wide pool, never a per-engine child: destroying a pool
        # races with its expiring workers (QThread destroyed while running,
        # fatal) whenever an engine is dropped with its window. Serial
        # execution is enforced by _dispatch (one NodeRunnable in flight),
        # not by the pool's thread count.
        self.pool = QThreadPool.globalInstance()

        self._plan: list[str] = []
        self._current: Optional[str] = None
        self._token: Optional[CancellationToken] = None
        self._had_failure = False
        self._active = False

        # What runs cost, kept for the session (see engine.runstats).
        self.history = RunHistory()
        # Polling process memory is cheap but not free and not everyone wants
        # it; the main window drives this from Settings > Statistics.
        self.sampling_enabled = True
        self._sampler = ProcessSampler()
        self._record: Optional[RunRecord] = None
        self._node_run: Optional[NodeRun] = None
        self._run_started = 0.0
        # Polls process memory while a node holds the floor. Lives on the
        # GUI thread, which is idle during a run — the work is on the pool —
        # so it actually gets to fire.
        self._sample_timer = QTimer(self)
        self._sample_timer.setInterval(SAMPLE_MS)
        self._sample_timer.timeout.connect(self._sample)

        graph.events.dirty_changed.connect(self._on_dirty_changed)
        graph.events.node_removed.connect(self.cache.evict)

    # ------------------------------------------------------------ public API

    @property
    def active(self) -> bool:
        return self._active

    def run_all(self) -> None:
        self.run_targets(list(self.graph.nodes))

    def run_to(self, node_id: str) -> None:
        self.run_targets([node_id])

    def run_targets(self, targets: list[str]) -> None:
        if self._active:
            return
        self._token = CancellationToken()
        self._plan = build_plan(self.graph, targets, self.cache)
        self._had_failure = False
        if not self._plan:
            return
        self._active = True
        self._open_record(targets)
        for node_id in self._plan:
            self.graph.set_status(node_id, NodeStatus.QUEUED)
        self.run_started.emit()
        self._dispatch()

    def cancel(self) -> None:
        """Cooperative cancel: unstarted nodes leave the plan immediately; the
        running node stops at its next ctx.check_cancelled()."""
        if not self._active or self._token is None:
            return
        self._token.cancel()
        if self._record is not None:
            self._record.cancelled = True
        for node_id in self._plan:
            self.graph.set_status(node_id, NodeStatus.IDLE)
        self._plan.clear()
        if self._current is None:
            self._finish()

    # ------------------------------------------------------------- dispatch

    def _dispatch(self) -> None:
        while self._current is None and self._plan:
            node_id = self._plan.pop(0)
            node = self.graph.nodes.get(node_id)
            if node is None:
                continue

            problem = self._blocking_problem(node_id)
            if problem is not None:
                mark_error = not problem.startswith("upstream")
                if mark_error:
                    self.graph.set_status(node_id, NodeStatus.ERROR, problem)
                    self._had_failure = True
                    self.node_failed.emit(node_id, NodeError(
                        node_id=node_id, message=problem,
                        exc_type="NotConfigured", formatted_tb=problem,
                    ))
                else:
                    self.graph.set_status(node_id, NodeStatus.IDLE)
                self._prune_downstream(node_id)
                continue

            self._start_node(node_id)
            return

        if self._current is None:
            self._finish()

    def _blocking_problem(self, node_id: str) -> Optional[str]:
        """Why this node can't run: a required input is unconnected, or an
        upstream node failed / was pruned (no cached value available)."""
        node = self.graph.nodes[node_id]
        for port in node.spec.inputs:
            conn = self.graph.input_connection(node_id, port.name)
            if conn is None:
                if not port.optional:
                    # a From's input is a link the canvas doesn't draw, so the
                    # generic message would name a port the user can't see
                    return (from_problem(self.graph, node_id)
                            or f"not configured: input {port.name!r} is not connected")
                continue
            if not self.cache.has(conn.src_node):
                return f"upstream node did not produce output"
        return None

    def _prune_downstream(self, node_id: str) -> None:
        downstream = self.graph.downstream(node_id)
        for nid in [n for n in self._plan if n in downstream]:
            self._plan.remove(nid)
            self.graph.set_status(nid, NodeStatus.IDLE)

    def _start_node(self, node_id: str) -> None:
        node = self.graph.nodes[node_id]
        inputs = {}
        for port in node.spec.inputs:
            conn = self.graph.input_connection(node_id, port.name)
            inputs[port.name] = (
                self.cache.outputs_for(conn.src_node).get(conn.src_port)
                if conn is not None else None
            )

        signals = WorkerSignals()  # created on the GUI thread, before pool.start
        signals.finished.connect(self._on_node_finished)
        signals.failed.connect(self._on_node_failed)
        signals.logged.connect(self.node_log)

        self._current = node_id
        self._open_node_run(node_id)
        self.graph.set_status(node_id, NodeStatus.RUNNING)
        self.pool.start(NodeRunnable(
            node_id=node_id,
            source=node.source,
            params=dict(node.params),
            inputs=inputs,
            output_ports=list(node.spec.outputs),
            token=self._token,
            signals=signals,
        ))

    # ------------------------------------------- worker results (GUI thread)

    def _alias_source(self, node_id: str, outputs: dict) -> tuple:
        """`(source_node, source_port)` if this node merely re-served a value
        that is already cached, `(None, None)` otherwise.

        Goto, From and Reroute all return their input untouched, so what they
        produce *is* the object sitting in the upstream entry. Saying so is
        worth the few lines: without it one DataFrame behind a link chain is
        counted once per hop in the memory readout, pickled once per hop into
        the side-car cache, and — the part that actually costs RAM — comes
        back as that many independent copies when the project is reopened.

        The test is object identity, not node type. Identity is the thing
        that matters: if it is the same object there is nothing extra to
        account for, whatever produced it, and anything that builds a new
        value fails the test and is cached normally. A frozen node is never
        aliased — a pin has to own what it is pinning, or it would not
        survive the upstream node being edited, which is the whole point of
        it.
        """
        node = self.graph.nodes.get(node_id)
        if node is None or node.frozen or len(outputs) != 1:
            return None, None
        (value,) = outputs.values()
        for port in node.spec.inputs:
            conn = self.graph.input_connection(node_id, port.name)
            if conn is None:
                continue
            entry = self.cache.get(conn.src_node)
            if entry is not None and entry.outputs.get(conn.src_port) is value:
                return conn.src_node, conn.src_port
        return None, None

    def _on_node_finished(self, node_id: str, outputs: dict, wall_time: float) -> None:
        self._current = None
        if node_id in self.graph.nodes:
            alias_of, alias_port = self._alias_source(node_id, outputs)
            self.cache.set(node_id, outputs, wall_time,
                           alias_of=alias_of, alias_port=alias_port)
            self.graph.mark_clean(node_id)
            self.graph.set_status(node_id, NodeStatus.DONE)
            self.node_succeeded.emit(node_id)
        self._close_node_run("ok", wall_time, node_id)
        self._dispatch()

    def _on_node_failed(self, node_id: str, error: NodeError) -> None:
        self._current = None
        self._had_failure = self._had_failure or not error.cancelled
        self._close_node_run(
            "cancelled" if error.cancelled else "failed", None, node_id)
        if node_id in self.graph.nodes:
            self.graph.set_status(node_id, NodeStatus.ERROR, error.message)
            self._prune_downstream(node_id)
            self.node_failed.emit(node_id, error)
        self._dispatch()

    def _finish(self) -> None:
        if not self._active:
            return
        self._active = False
        self._token = None
        self._close_record()
        self.run_finished.emit(not self._had_failure)

    # ----------------------------------------------------------- recording

    def _open_record(self, targets: Iterable[str]) -> None:
        rss = self._sampler.rss()
        self._record = RunRecord(rss_start=rss, rss_peak=rss)
        (self._record.skipped_clean, self._record.skipped_frozen,
         self._record.skipped_inactive) = skipped_summary(
            self.graph, targets, self.cache, self._plan)
        self._run_started = time.perf_counter()
        if self.sampling_enabled:
            self._sample_timer.start()

    def _open_node_run(self, node_id: str) -> None:
        if self._record is None:
            return
        node = self.graph.nodes.get(node_id)
        rss = self._sampler.rss()
        self._node_run = NodeRun(
            node_id=node_id,
            label=node.label if node is not None else node_id,
            started=time.perf_counter() - self._run_started,
            rss_start=rss, rss_peak=rss,
        )

    def _close_node_run(self, outcome: str, wall_time: "Optional[float]",
                        node_id: str) -> None:
        run = self._node_run
        self._node_run = None
        if run is None or self._record is None or run.node_id != node_id:
            return
        run.outcome = outcome
        # The worker's own measurement when there is one: it brackets the
        # node's code and nothing else, where the clock here would also be
        # charging it for the queued signal that carried the result back.
        run.wall_time = (wall_time if wall_time is not None
                         else max(0.0, time.perf_counter()
                                  - self._run_started - run.started))
        entry = self.cache.get(node_id)
        if entry is not None:
            run.output_bytes = entry.memory_bytes
            first = next(iter(entry.outputs), None)
            if first is not None:
                run.summary = entry.summary(first)
        self._record.nodes.append(run)

    def _close_record(self) -> None:
        record = self._record
        self._record = None
        self._node_run = None
        self._sample_timer.stop()
        if record is None:
            return
        record.wall_time = time.perf_counter() - self._run_started
        record.ok = not self._had_failure
        self.history.add(record)
        self.run_recorded.emit(record)

    def _sample(self) -> None:
        """One poll of process memory, charged to whoever is running."""
        rss = self._sampler.rss()
        if not rss:
            self._sample_timer.stop()   # unavailable here; stop asking
            return
        if self._record is not None:
            self._record.rss_peak = max(self._record.rss_peak, rss)
        if self._node_run is not None:
            self._node_run.rss_peak = max(self._node_run.rss_peak, rss)

    # ------------------------------------------------------------ reactions

    def _on_dirty_changed(self, node_id: str, dirty: bool) -> None:
        if dirty:
            node = self.graph.nodes.get(node_id)
            if node is not None and node.frozen:
                # The pin *is* the cached value, so evicting it here would
                # destroy the thing the freeze exists to protect — and the
                # node would then quietly run again on the next pass, which
                # is the one outcome freezing is meant to rule out. Anything
                # upstream marking it dirty is exactly the case being
                # defended against, not an exception to it.
                return
            self.cache.evict(node_id)
