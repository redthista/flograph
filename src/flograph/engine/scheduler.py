"""Execution scheduling: dirty subgraph -> topo-ordered plan -> serial
execution on a single-thread pool, with per-node caching.

ExecutionEngine lives on the GUI thread. Workers hand results back via queued
signals; all graph/cache mutation happens here, never on pool threads.
"""
from __future__ import annotations

from typing import Iterable, Optional

from PySide6.QtCore import QObject, QThreadPool, Signal

from flograph.core.graph import Graph
from flograph.core.node import NodeStatus

from .cache import OutputCache
from .context import CancellationToken
from .errors import NodeError
from .worker import NodeRunnable, WorkerSignals


def build_plan(graph: Graph, targets: Iterable[str]) -> list[str]:
    """The nodes that must execute to satisfy `targets`: every *dirty* node
    among the targets and their ancestors, in topological order. Clean nodes
    are skipped — their outputs come from the cache."""
    wanted = set(targets)
    for target in list(wanted):
        wanted |= graph.upstream(target)
    return [nid for nid in graph.topo_order()
            if nid in wanted and graph.nodes[nid].dirty]


class ExecutionEngine(QObject):
    run_started = Signal()
    run_finished = Signal(bool)            # ok: no node failed
    node_log = Signal(str, str, str)       # node_id, line, stream
    node_failed = Signal(str, object)      # node_id, NodeError
    node_succeeded = Signal(str)           # node_id

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
        self._plan = build_plan(self.graph, targets)
        self._had_failure = False
        if not self._plan:
            return
        self._active = True
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
                    return f"not configured: input {port.name!r} is not connected"
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

    def _on_node_finished(self, node_id: str, outputs: dict, wall_time: float) -> None:
        self._current = None
        if node_id in self.graph.nodes:
            self.cache.set(node_id, outputs, wall_time)
            self.graph.mark_clean(node_id)
            self.graph.set_status(node_id, NodeStatus.DONE)
            self.node_succeeded.emit(node_id)
        self._dispatch()

    def _on_node_failed(self, node_id: str, error: NodeError) -> None:
        self._current = None
        self._had_failure = self._had_failure or not error.cancelled
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
        self.run_finished.emit(not self._had_failure)

    # ------------------------------------------------------------ reactions

    def _on_dirty_changed(self, node_id: str, dirty: bool) -> None:
        if dirty:
            self.cache.evict(node_id)
