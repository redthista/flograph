"""Execution scheduling: dirty subgraph -> topo-ordered plan -> concurrent
execution on the shared thread pool, with per-node caching.

ExecutionEngine lives on the GUI thread. Workers hand results back via queued
signals; all graph/cache mutation happens here, never on pool threads.

Several nodes run at once when the graph allows it: a node starts as soon as
every predecessor *in this plan* has finished, up to a worker limit. The plan
is still built in topological order, so what changes is only how many of its
nodes may be in flight together — a wide graph runs its branches side by side
instead of one after another, and a chain still runs in order because each
link waits on the one before it.
"""
from __future__ import annotations

import os
import sys
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Iterable, Optional

from PySide6.QtCore import QObject, QThreadPool, QTimer, Signal

from flograph.core.graph import Graph
from flograph.core.links import from_problem
from flograph.core.node import NodeInstance, NodeStatus
from flograph.core.varlinks import VariableError, var_problem

from . import pressure, varsubst
from .cache import OutputCache
from .cache_worker import CacheWarmRunnable, CacheWarmSignals
from .context import CancellationToken
from .errors import NodeError
from .runstats import (SAMPLE_MS, NodeRun, ProcessSampler, RunHistory,
                       RunRecord)
from .worker import NodeRunnable, WorkerSignals


# How long after the last reactive edit its re-run starts. Long enough that a
# burst — typing across a row, dragging a slider — pays for one run instead of
# one per commit, short enough that it still reads as the flow answering.
REACTIVE_DELAY_MS = 300

# Ceiling on the automatic worker count. Cores are not the binding constraint
# on a flow of any size — memory is: every branch in flight holds its own
# intermediates, and eight large frames at once is already a lot to ask of a
# laptop. Someone who knows their machine and their data can raise it in
# Settings; the default is chosen to not surprise anyone.
MAX_AUTO_WORKERS = 8

# How often a run re-reads how full the machine is. Reading it is a /proc
# scrape on Linux and one call on Windows, so this could be far more often;
# once a second is simply as fine-grained as the answer is useful.
PRESSURE_POLL_MS = 1000


def default_workers() -> int:
    """How many nodes run at once when nobody has said."""
    return max(1, min(os.cpu_count() or 1, MAX_AUTO_WORKERS))


def _memory_adapt_default() -> bool:
    """Whether new engines throttle themselves under memory pressure.

    Off via FLOGRAPH_MEMORY_ADAPT=0, which the test suite sets: several tests
    prove that nodes *do* run side by side, and a throttle that halves the
    limit because the machine running the tests happens to be busy would fail
    them for a reason that has nothing to do with what they test.
    """
    return os.environ.get("FLOGRAPH_MEMORY_ADAPT", "1") != "0"


def is_exclusive(node: NodeInstance) -> bool:
    """Must this node run on its own, with nothing else in flight?

    For the work that is not safe beside anything else: matplotlib, which is
    not thread-safe from a worker, and any node reaching for a resource that
    only tolerates one user — a file it writes, a device, a library with
    global state. The node's script declares it with NODE["exclusive"], and
    an instance may override that either way for code the user has forked.
    """
    if node.exclusive_override is not None:
        return node.exclusive_override
    return node.spec.exclusive


@dataclass
class _InFlight:
    """One node currently running, and what its completion will need.

    Per node rather than per engine: with several in flight, the alias map
    and the run record belong to the node they describe, and the one that
    finishes first must not take another's with it.
    """
    node_id: str
    # id(shallow copy handed to this node) -> (src_node, src_port), so a
    # pass-through node returning its input is still recognised as serving
    # the upstream value rather than one of its own.
    handed_in: dict[int, tuple[str, str]] = field(default_factory=dict)
    run: Optional[NodeRun] = None


# Values a node cannot change in place at all, so there is nothing to guard.
_IMMUTABLE = frozenset({str, bytes, int, float, bool, complex, type(None),
                        frozenset})


def _read_only_view(value, _nested: bool = False):
    """What a node actually receives on an input port.

    Cached outputs are handed downstream by reference, so the node contract
    has always been "treat your inputs as read-only". Nothing enforced it,
    and a node that wrote to its input instead reached back into the entry
    cached against the node *upstream* — silently rewriting a value other
    branches had already been served, or were about to be. A step that adds
    an item to a list has to show up after that step, not before it and not
    in the branch beside it, and that has to hold for whatever a node passes
    along, not only for frames.

    What each kind of value gets, and what it costs:

    - pandas: a copy-on-write shallow copy. It shares every block with the
      original (fifty of them over a 16 MB frame cost 0.09 MB), and the first
      write through it copies only the block being touched. Free, and silent
      — writing to a frame input just works.
    - list, dict, set, bytearray: the container itself is rebuilt, so append,
      pop, sort, `d[k] = v` and friends land on the node's own copy. The
      items inside are the same objects, not copies; rebuilding those too
      would mean allocating a dict per row of a 100k-row record list on every
      hop, which is real memory spent behind the user's back for a much rarer
      mistake. Reaching *through* an input to write — `rows[0]["x"] = 1` —
      is therefore still read-only by contract.
    - a pandas value held directly in one of those containers is guarded, so
      a list of frames is protected item by item; that one is free.
    - numpy: a read-only view. numpy has no copy-on-write, so the choice is
      between duplicating an array that may be gigabytes or refusing the
      write, and refusing is the only one that is both correct and free. The
      node raises where the mistake is instead of corrupting a branch it
      cannot see; `arr = arr.copy()` is the fix, and errors.py says so.
    - anything else — a matplotlib figure, a connection, a custom object — is
      passed through untouched. There is no general way to copy those cheaply
      or safely, so the contract remains the only guard.

    Cost per hop, measured: 0.08 ms for a 16 MB frame, 0.04 ms for a 16 MB
    array, 13 ms for a 200k-row list of dicts — that last one being the worst
    realistic case, and nearly all of it the per-item type test below.
    """
    # Dispatch on the exact type, cheapest first: every item of a container
    # comes back through here, so a 200k-row record list pays this test 200k
    # times and anything clever costs more than the guard is worth.
    #
    # Exact types only. A defaultdict rebuilt as a dict would lose its
    # factory and a Counter its methods, and reconstructing an arbitrary
    # subclass from its contents is not something that can be got right in
    # general — better an unguarded value than a changed one.
    cls = type(value)
    if cls in _IMMUTABLE:
        return value
    if cls is list:
        return value if _nested else [_read_only_view(i, True) for i in value]
    if cls is dict:
        return value if _nested else {k: _read_only_view(v, True)
                                      for k, v in value.items()}
    if cls is set:
        return value if _nested else set(value)
    if cls is bytearray:
        return value if _nested else bytearray(value)
    if cls is tuple:
        # Immutable in shape, so it only needs rebuilding if guarding an item
        # actually produced something different; keeping the original object
        # otherwise leaves pass-through aliasing alone.
        if _nested:
            return value
        items = tuple(_read_only_view(item, True) for item in value)
        return items if any(new is not old
                            for new, old in zip(items, value)) else value

    copy = getattr(value, "copy", None)
    if copy is not None and any(c.__module__.startswith("pandas.")
                                for c in cls.__mro__):
        try:
            return copy(deep=False)
        except (TypeError, ValueError):
            return value

    # numpy is read out of sys.modules rather than imported: holding an
    # ndarray means numpy is already loaded, so a miss here is a definitive
    # "not an array" and costs nothing on flows that never touch one.
    np = sys.modules.get("numpy")
    if np is not None and isinstance(value, np.ndarray):
        try:
            view = value.view()
            view.flags.writeable = False
            return view
        except (ValueError, AttributeError, TypeError):
            return value
    return value


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
    # node_id, 1-based position in the plan, plan size. The size is the plan
    # as built: _prune_downstream can shorten it mid-run, so a run may stop
    # short of its own total. An upper bound is still worth showing — the
    # alternative is a counter that walks backwards.
    node_started = Signal(str, int, int)
    node_progress = Signal(str, float)     # node_id, fraction 0..1
    run_recorded = Signal(object)          # RunRecord — a finished run's cost
    # The set of nodes with a reactive re-run queued has changed. Views paint
    # from it (see request_run / is_requested), so it has to say when it moves.
    request_changed = Signal()
    # A cached result could not be read back off disk. The node has been
    # dropped and marked dirty, so it will recompute — but silently losing a
    # cached value and silently recomputing it look identical from the
    # outside, and only one of them is what happened.
    cache_load_failed = Signal(str)        # node_id

    def __init__(self, graph: Graph, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self.graph = graph
        self.cache = OutputCache()
        # the process-wide pool, never a per-engine child: destroying a pool
        # races with its expiring workers (QThread destroyed while running,
        # fatal) whenever an engine is dropped with its window. How many nodes
        # run at once is decided by _dispatch, not by the pool's thread count
        # — the pool is only asked to be big enough not to be the limit.
        self.pool = QThreadPool.globalInstance()
        # 0 = automatic (default_workers()). The main window drives this from
        # Settings > General.
        self.max_workers = 0

        # How full the machine is, and what reads it. The probe is swappable
        # so the throttle can be tested at any pressure without a machine
        # actually being under any; `memory_adapt` is the off switch the test
        # suite uses, so a loaded CI box cannot make a concurrency test flaky
        # by throttling it halfway through.
        self.memory_probe = pressure.read_memory
        self.memory_adapt = _memory_adapt_default()
        self._pressure_level = pressure.CALM
        # Its own timer: runstats' sampler is behind a Settings toggle and
        # gives up permanently if the platform will not report memory.
        self._pressure_timer = QTimer(self)
        self._pressure_timer.setInterval(PRESSURE_POLL_MS)
        self._pressure_timer.timeout.connect(self._poll_pressure)

        # Nodes from the plan that have not started yet, and the subset of
        # those whose predecessors have all finished. Kahn's algorithm over
        # the plan, kept incrementally: _remaining_preds counts each pending
        # node's predecessors *within the plan*, and a node moves to _ready
        # when that reaches zero. Scanning the pending list for a runnable
        # node on every completion would be quadratic on a large flow, which
        # is the same reason Graph.topo_order keeps an insertion rank.
        self._pending: set[str] = set()
        self._ready: deque = deque()
        self._remaining_preds: dict[str, int] = {}
        # node_id -> _InFlight, for every node currently running.
        self._running: dict[str, _InFlight] = {}
        # An exclusive node has the process to itself, so nothing new starts
        # while one is running.
        self._exclusive_running = False
        # Size of the plan as built and how many nodes have been started from
        # it, for "node 3 of 12".
        self._plan_total = 0
        self._plan_done = 0
        self._token: Optional[CancellationToken] = None
        self._had_failure = False
        self._active = False
        # True while a run's spilled inputs are being read back off disk. The
        # plan is seeded and queued but nothing has started; _dispatch is
        # called when the last one lands.
        self._warming = False
        self._warm_remaining = 0
        # Bumped per run so a warm still in flight from a cancelled one
        # cannot decrement the new run's counter and dispatch it early.
        self._warm_generation = 0
        self._warm_signals: list = []

        # What runs cost, kept for the session (see engine.runstats).
        self.history = RunHistory()
        # Polling process memory is cheap but not free and not everyone wants
        # it; the main window drives this from Settings > Statistics.
        self.sampling_enabled = True
        self._sampler = ProcessSampler()
        self._record: Optional[RunRecord] = None
        self._run_started = 0.0
        # Polls process memory while a node holds the floor. Lives on the
        # GUI thread, which is idle during a run — the work is on the pool —
        # so it actually gets to fire.
        self._sample_timer = QTimer(self)
        self._sample_timer.setInterval(SAMPLE_MS)
        self._sample_timer.timeout.connect(self._sample)

        # Reactive re-runs (a typed cell, a dragged slider, a slicer tick)
        # collect here rather than each calling run_targets. Insertion-ordered
        # so a plan built from them is reproducible. See request_run.
        self._requested: dict[str, None] = {}
        self._request_timer = QTimer(self)
        self._request_timer.setSingleShot(True)
        self._request_timer.setInterval(REACTIVE_DELAY_MS)
        self._request_timer.timeout.connect(self._fire_request)

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
        plan = build_plan(self.graph, targets, self.cache)
        self._plan_total = len(plan)
        self._plan_done = 0
        self._had_failure = False
        if not plan:
            return
        self._active = True
        # Read the machine before the first node starts, not a second into
        # the run: a flow launched on an already-full machine should be
        # throttled from its first dispatch rather than after it has piled
        # eight branches on.
        self._poll_pressure()
        self._pressure_timer.start()
        self._seed_readiness(plan)
        self._open_record(targets, plan)
        for node_id in plan:
            self.graph.set_status(node_id, NodeStatus.QUEUED)
        self.run_started.emit()
        if not self._warm_plan(plan):
            self._dispatch()

    def _warm_plan(self, plan: list[str]) -> bool:
        """Read back any spilled entries this plan will consume. True if that
        started, in which case _dispatch waits for it.

        A project opens without loading its cached results, so the values a
        run reads may be on disk. They have to come back before the first
        node starts, and they must not come back on this thread: _start_node
        runs on the GUI thread, and unpickling a large frame there freezes
        the window. Only inputs from *outside* the plan are warmed — anything
        inside it is about to be recomputed anyway.
        """
        planned = set(plan)
        wanted: dict[str, str] = {}          # blob owner -> project path
        for node_id in plan:
            node = self.graph.nodes.get(node_id)
            if node is None:
                continue
            for port in node.spec.inputs:
                conn = self.graph.input_connection(node_id, port.name)
                if conn is None or conn.src_node in planned:
                    continue
                root = self.cache.blob_source(conn.src_node)
                if root is None or root in wanted:
                    continue
                entry = self.cache.get(root)
                if entry is not None and entry.blob:
                    wanted[root] = entry.blob
        if not wanted:
            return False

        # Grouped by project because that is what the runnable takes; in
        # practice one engine's cache is one project's.
        by_project: dict[str, list[str]] = {}
        for root, project in wanted.items():
            by_project.setdefault(project, []).append(root)
        self._warm_generation += 1
        generation = self._warm_generation
        self._warming = True
        self._warm_remaining = len(by_project)
        # Held for the duration: the runnable is the pool's, but nothing else
        # owns the signals object, and one collected early is a `finished`
        # that never arrives and a run that never starts.
        self._warm_signals = []
        for project, node_ids in by_project.items():
            signals = CacheWarmSignals()     # GUI thread, before pool.start
            signals.warmed.connect(self._on_entry_warmed)
            signals.finished.connect(self._on_warm_finished)
            self._warm_signals.append(signals)
            self.pool.start(
                CacheWarmRunnable(project, node_ids, signals, generation))
        return True

    def _on_entry_warmed(self, node_id: str, outputs: object) -> None:
        """One spilled entry came back — or didn't."""
        if outputs is None:
            # Unreadable blob. Drop it and dirty the node so it recomputes:
            # the alternative is handing the flow a missing input and calling
            # the result an answer. _blocking_problem now sees no entry and
            # takes the branch out of this run without calling it an error.
            self.cache.evict(node_id)
            if node_id in self.graph.nodes:
                self.graph.mark_dirty(node_id)
            self.cache_load_failed.emit(node_id)
            return
        self.cache.mark_resident(node_id, outputs)

    def _on_warm_finished(self, generation: int) -> None:
        if generation != self._warm_generation:
            return          # left over from a run that was already cancelled
        self._warm_remaining -= 1
        if self._warm_remaining > 0:
            return
        self._warming = False
        # Cancel during warming already finished the run; dispatching now
        # would start a plan nobody asked for any more.
        if self._active:
            self._dispatch()

    def _base_workers(self) -> int:
        """How many nodes would run at once if memory were no object."""
        return self.max_workers if self.max_workers > 0 else default_workers()

    def worker_limit(self) -> int:
        """How many nodes this engine will run at once, right now.

        Shrinks when the machine is running out of memory. Running eight
        branches at once is only a good idea while there is room for eight
        branches' worth of intermediates; past that point the honest thing is
        to get slower rather than to take the machine down, which is a trade
        the person on the other end of a shared flow cannot make for
        themselves and would not know how to.
        """
        return max(1, pressure.worker_cap(
            self._base_workers(), self._pressure_level,
            explicit=self.max_workers > 0))

    def _poll_pressure(self) -> None:
        """Re-read how much trouble the machine is in.

        On its own timer rather than sharing runstats' sampler: that one only
        runs when Settings > Statistics has sampling switched on, and stops
        for good if the platform will not report memory. Neither is a
        reasonable way to lose the thing that keeps a run from filling the
        machine.
        """
        if not self.memory_adapt:
            self._pressure_level = pressure.CALM
            return
        used, total, available = self.memory_probe()
        self._pressure_level = pressure.pressure_level(
            used, total, available, current=self._pressure_level)

    @property
    def running_nodes(self) -> frozenset:
        """Every node currently in flight."""
        return frozenset(self._running)

    def _seed_readiness(self, plan: list[str]) -> None:
        """Kahn bookkeeping for one plan: who is waiting on how many, and who
        can start now.

        Only predecessors *in the plan* count. Everything else the node needs
        is either cached already or missing, and _blocking_problem is what
        answers that — a clean upstream node is not something to wait for.
        """
        planned = set(plan)
        self._pending = set(plan)
        self._remaining_preds = {
            node_id: sum(1 for p in self.graph.predecessors(node_id)
                         if p in planned)
            for node_id in plan
        }
        # Plan order, so a run with nothing to overlap behaves exactly as the
        # serial one did and the stats read the same.
        self._ready = deque(node_id for node_id in plan
                            if self._remaining_preds[node_id] == 0)
        self._running.clear()
        self._exclusive_running = False
        # The pool is shared with cache restores (engine.cache_worker), so it
        # is asked for headroom beyond the nodes rather than exactly enough:
        # a run that filled the pool would otherwise leave a project's cache
        # load queued behind it.
        # Sized from what the run *could* use, not from what it is throttled
        # to right now: the pool only ever grows, so a run that started while
        # memory was tight would otherwise fix a small pool and be unable to
        # open back up when the pressure lifted.
        wanted = self._base_workers() + 2
        if self.pool.maxThreadCount() < wanted:
            self.pool.setMaxThreadCount(wanted)

    def request_run(self, targets: Iterable[str]) -> None:
        """Ask for these nodes to run soon, coalescing with anything else
        that has been asked for meanwhile.

        The reactive counterpart to run_targets, for the edits a user makes
        continuously — cells, sliders, slicer ticks — and it differs in two
        ways that only show up on a flow big enough to take a while.

        It waits for the editing to settle, so typing across a row costs one
        run rather than one per cell. And it never drops a request:
        run_targets is a no-op while a run is in flight, which for a reactive
        caller meant the edits made *during* a run silently never ran at all.
        The graph stayed dirty, the visuals stayed stale, and nothing said
        so. A request made under a running run survives it and fires when it
        finishes.
        """
        before = len(self._requested)
        self._requested.update(dict.fromkeys(targets))
        if self._requested:
            self._request_timer.start()
        if len(self._requested) != before:
            self.request_changed.emit()

    @property
    def pending_request(self) -> bool:
        """True while a reactive re-run is waiting for its turn — either for
        the editing to settle or for the run in flight to finish."""
        return bool(self._requested)

    def is_requested(self, node_id: str) -> bool:
        """Is this node covered by a reactive re-run that hasn't started yet?

        What a card or tile needs to tell "you changed something and nothing
        is coming" from "hold on, this is being recomputed" — the second is
        worth waiting for and the first is not, and while the request sits in
        the queue the node's own status cannot tell them apart."""
        return node_id in self._requested

    @property
    def requested_nodes(self) -> frozenset:
        """Every node a queued re-run covers, for a view that would rather
        hold the set than ask node by node."""
        return frozenset(self._requested)

    def clear_request(self) -> None:
        """Forget any pending reactive re-run."""
        self._request_timer.stop()
        if self._requested:
            self._requested.clear()
            self.request_changed.emit()

    def _fire_request(self) -> None:
        if self._active:
            return          # _finish re-arms the timer for us
        targets = [nid for nid in self._requested if nid in self.graph.nodes]
        self._requested.clear()
        if targets:
            # the plan takes over from here: its nodes go QUEUED, which is
            # what the views paint from once a run is actually under way
            self.run_targets(targets)
        self.request_changed.emit()

    def cancel(self) -> None:
        """Cooperative cancel: unstarted nodes leave the plan immediately;
        every running node stops at its next ctx.check_cancelled().

        One token covers the whole run, so nodes in flight are all told at
        once rather than in turn.
        """
        if not self._active or self._token is None:
            return
        # "stop" means stop: a queued reactive re-run would otherwise start
        # the moment this one gets out of the way.
        self.clear_request()
        self._token.cancel()
        if self._record is not None:
            self._record.cancelled = True
        for node_id in self._pending:
            self.graph.set_status(node_id, NodeStatus.IDLE)
        self._clear_pending()
        if not self._running:
            self._finish()

    def _clear_pending(self) -> None:
        self._pending.clear()
        self._ready.clear()
        self._remaining_preds.clear()

    # ------------------------------------------------------------- dispatch

    def _dispatch(self) -> None:
        """Start whatever is ready, up to the worker limit.

        Called once when a run begins and again after every completion, so
        the free slot a finishing node leaves is filled by whichever of its
        successors it just unblocked.
        """
        if not self._active or self._warming:
            # Warming holds the plan back on purpose, and with nothing yet
            # running the tail of this function would read that as "the run
            # is over" and finish it before a single node had started.
            return
        limit = self.worker_limit()
        while self._ready and not self._exclusive_running:
            if len(self._running) >= limit:
                break
            node_id = self._ready[0]
            node = self.graph.nodes.get(node_id)
            if node is None:
                self._ready.popleft()
                self._pending.discard(node_id)
                continue
            if is_exclusive(node) and self._running:
                # It gets the process to itself, so it waits for the floor to
                # clear. Left at the head of the queue: the completion that
                # empties _running dispatches again and finds it here.
                break

            self._ready.popleft()
            self._pending.discard(node_id)

            # _start_node can refuse too — a ${name} that cannot be resolved
            # is found there, where the values are — so both answers go
            # through the same refusal path.
            problem = self._blocking_problem(node_id)
            if problem is None:
                problem = self._start_node(node_id)
            if problem is not None:
                self._refuse(node_id, problem)
                continue

            if is_exclusive(node):
                break

        if self._running:
            return
        # Nothing in flight means nothing was holding the loop back — every
        # reason it breaks early needs a node already running — so _ready is
        # empty here and the run is over bar the bookkeeping.
        if self._pending:
            # Unreachable over a DAG: a pending node whose predecessors have
            # all finished is in _ready by construction. Releasing them rather
            # than returning is deliberate insurance — the alternative to a
            # wrong status here is a run that never ends, with Run disabled
            # and Cancel the only way out.
            for node_id in self._pending:
                self.graph.set_status(node_id, NodeStatus.IDLE)
            self._clear_pending()
        self._finish()

    def _refuse(self, node_id: str, problem: str) -> None:
        """A node that cannot start: report it and take its subtree with it.

        "upstream ..." is not this node's fault, so it goes quiet — it did
        not fail, it never got the chance to run.
        """
        if problem.startswith("upstream"):
            self.graph.set_status(node_id, NodeStatus.IDLE)
        else:
            self.graph.set_status(node_id, NodeStatus.ERROR, problem)
            self._had_failure = True
            self.node_failed.emit(node_id, NodeError(
                node_id=node_id, message=problem,
                exc_type="NotConfigured", formatted_tb=problem,
            ))
        # Everything below it goes with it, so there are no successors left
        # to release — the prune is the whole bookkeeping here.
        self._prune_downstream(node_id)

    def _release_successors(self, node_id: str) -> None:
        """One node finished: whoever was waiting only on it can start."""
        for succ in self.graph.successors(node_id):
            if succ not in self._pending:
                continue        # already started, pruned, or not in this plan
            remaining = self._remaining_preds.get(succ, 0) - 1
            self._remaining_preds[succ] = remaining
            if remaining <= 0:
                self._ready.append(succ)

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
        # A ${name} is a dependency with no port, so the loop above cannot
        # see it: an unresolvable reference, and a Variables node that
        # produced nothing, both have to be asked about separately.
        problem = var_problem(self.graph, node_id)
        if problem is not None:
            return problem
        for src in self.graph.var_sources(node_id):
            if not self.cache.has(src):
                return f"upstream node did not produce output"
        return None

    def _prune_downstream(self, node_id: str) -> None:
        """Drop everything below a node that failed or could not start.

        Nothing downstream can already be in flight: a node only starts once
        every predecessor in the plan has finished, so a node that is running
        has no unfinished ancestor to be pruned by.
        """
        downstream = self.graph.downstream(node_id)
        dropped = [nid for nid in self._pending if nid in downstream]
        if not dropped:
            return
        self._pending.difference_update(dropped)
        for nid in dropped:
            self._remaining_preds.pop(nid, None)
            self.graph.set_status(nid, NodeStatus.IDLE)
        # _ready is a deque and the dropped nodes may be anywhere in it, so it
        # is rebuilt rather than picked at; it holds only what can start now,
        # which is short.
        if any(nid in self._ready for nid in dropped):
            self._ready = deque(nid for nid in self._ready
                                if nid in self._pending)

    def _start_node(self, node_id: str) -> Optional[str]:
        """Dispatch a node, or return why it could not be dispatched.

        The `${name}` substitution happens here because this is the one
        place a node's params are handed to a worker — below this line
        nothing knows a variable was ever involved, which is what keeps the
        node contract unchanged. It runs before any state is registered, so
        a refusal leaves nothing half-started behind.
        """
        node = self.graph.nodes[node_id]
        try:
            params, variables = varsubst.resolve(self.graph, node_id, self.cache)
        except VariableError as exc:
            return f"not configured: {exc}"
        inflight = _InFlight(node_id=node_id)
        inputs = {}
        for port in node.spec.inputs:
            conn = self.graph.input_connection(node_id, port.name)
            if conn is None:
                inputs[port.name] = None
                continue
            value = self.cache.outputs_for(conn.src_node).get(conn.src_port)
            guarded = _read_only_view(value)
            inputs[port.name] = guarded
            if guarded is not value:
                inflight.handed_in[id(guarded)] = (conn.src_node, conn.src_port)

        signals = WorkerSignals()  # created on the GUI thread, before pool.start
        signals.finished.connect(self._on_node_finished)
        signals.failed.connect(self._on_node_failed)
        signals.logged.connect(self.node_log)
        signals.progressed.connect(self._on_node_progress)

        self._running[node_id] = inflight
        if is_exclusive(node):
            self._exclusive_running = True
        inflight.run = self._open_node_run(node_id)
        self.graph.set_status(node_id, NodeStatus.RUNNING)
        self._plan_done += 1
        self.node_started.emit(node_id, self._plan_done, self._plan_total)
        self.pool.start(NodeRunnable(
            node_id=node_id,
            source=node.source,
            params=params,
            variables=variables,
            inputs=inputs,
            output_ports=list(node.spec.outputs),
            token=self._token,
            signals=signals,
        ))
        return None

    # ------------------------------------------- worker results (GUI thread)

    def _on_node_progress(self, node_id: str, fraction: float) -> None:
        """A ctx.progress() call, already throttled by the RunContext.

        Onto the model for the canvas — every scene watches the graph's
        events, so a node on a page nobody is looking at costs nothing — and
        out as a signal for the status bar, which wants the run's view of it
        rather than one node's.
        """
        # Cancel clears the floor before the pool thread notices; anything
        # still in flight from an outgoing node is no longer worth drawing.
        if node_id not in self._running or node_id not in self.graph.nodes:
            return
        self.graph.set_progress(node_id, fraction)
        self.node_progress.emit(node_id, fraction)

    def _alias_source(self, node_id: str, outputs: dict,
                      handed_in: dict) -> tuple:
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
        # A pandas input arrives as a copy-on-write shallow copy (see
        # _read_only_view), so a pass-through node hands back that copy rather
        # than the cached object itself. It is still the same data — the copy
        # shares every block — so it still aliases; the identity to test is
        # against what was handed in.
        handed = handed_in.get(id(value))
        if handed is not None:
            return handed
        for port in node.spec.inputs:
            conn = self.graph.input_connection(node_id, port.name)
            if conn is None:
                continue
            entry = self.cache.get(conn.src_node)
            # `resident` explicitly: a spilled entry holds no outputs, so it
            # cannot be the identity source of a value in hand. Saying so
            # here keeps this from ever being "fixed" into a load — it runs
            # on every completion of every node, and reading a blob back to
            # answer an identity test would be the most expensive question
            # in the engine.
            if (entry is not None and entry.resident
                    and entry.outputs.get(conn.src_port) is value):
                return conn.src_node, conn.src_port
        return None, None

    def _on_node_finished(self, node_id: str, outputs: dict, wall_time: float) -> None:
        inflight = self._retire(node_id)
        if node_id in self.graph.nodes:
            alias_of, alias_port = self._alias_source(
                node_id, outputs,
                inflight.handed_in if inflight is not None else {})
            self.cache.set(node_id, outputs, wall_time,
                           alias_of=alias_of, alias_port=alias_port)
            self.graph.mark_clean(node_id)
            self.graph.set_status(node_id, NodeStatus.DONE)
            self.node_succeeded.emit(node_id)
        self._close_node_run(inflight, "ok", wall_time)
        self._release_successors(node_id)
        self._dispatch()

    def _on_node_failed(self, node_id: str, error: NodeError) -> None:
        inflight = self._retire(node_id)
        self._had_failure = self._had_failure or not error.cancelled
        self._close_node_run(
            inflight, "cancelled" if error.cancelled else "failed", None)
        if node_id in self.graph.nodes:
            self.graph.set_status(node_id, NodeStatus.ERROR, error.message)
            # Everything below it leaves the plan, so there is nothing left
            # for _release_successors to release.
            self._prune_downstream(node_id)
            self.node_failed.emit(node_id, error)
        self._dispatch()

    def _retire(self, node_id: str) -> "Optional[_InFlight]":
        """Take a node off the floor, whatever it finished as."""
        inflight = self._running.pop(node_id, None)
        if not self._running:
            self._exclusive_running = False
        return inflight

    def _finish(self) -> None:
        if not self._active:
            return
        self._active = False
        self._token = None
        self._exclusive_running = False
        # A cancel can land while inputs are still being read back. The run is
        # over either way, and leaving the flag set would make _dispatch a
        # no-op for the *next* run, which would then never start.
        self._warming = False
        self._pressure_timer.stop()
        self._close_record()
        self.run_finished.emit(not self._had_failure)
        if self._requested:
            # an edit landed while that run was in flight; now it gets its run
            self._request_timer.start()

    # ----------------------------------------------------------- recording

    def _open_record(self, targets: Iterable[str], plan: list[str]) -> None:
        rss = self._sampler.rss()
        self._record = RunRecord(rss_start=rss, rss_peak=rss,
                                 workers=self.worker_limit())
        (self._record.skipped_clean, self._record.skipped_frozen,
         self._record.skipped_inactive) = skipped_summary(
            self.graph, targets, self.cache, plan)
        self._run_started = time.perf_counter()
        if self.sampling_enabled:
            self._sample_timer.start()

    def _open_node_run(self, node_id: str) -> "Optional[NodeRun]":
        if self._record is None:
            return None
        node = self.graph.nodes.get(node_id)
        rss = self._sampler.rss()
        # Counting this node itself: "ran alongside 1" would be a confusing
        # way to say "ran on its own".
        concurrent = len(self._running)
        run = NodeRun(
            node_id=node_id,
            label=node.label if node is not None else node_id,
            started=time.perf_counter() - self._run_started,
            rss_start=rss, rss_peak=rss,
            concurrent=concurrent,
        )
        # Everything already in flight is now sharing with one more.
        for other in self._running.values():
            if other.run is not None:
                other.run.concurrent = max(other.run.concurrent, concurrent)
        if self._record is not None:
            self._record.peak_concurrency = max(
                self._record.peak_concurrency, concurrent)
        return run

    def _close_node_run(self, inflight: "Optional[_InFlight]", outcome: str,
                        wall_time: "Optional[float]") -> None:
        run = inflight.run if inflight is not None else None
        if run is None or self._record is None:
            return
        node_id = run.node_id
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
        self._sample_timer.stop()
        if record is None:
            return
        # Appended as they finish, which under concurrency is not the order
        # they started in. The timeline and the table both read as a sequence,
        # so they get one.
        record.nodes.sort(key=lambda run: run.started)
        record.wall_time = time.perf_counter() - self._run_started
        record.ok = not self._had_failure
        self.history.add(record)
        self.run_recorded.emit(record)

    def _sample(self) -> None:
        """One poll of process memory, charged to everyone running.

        The reading is process-wide, so with several nodes in flight there is
        no honest way to split it between them — each is charged the whole
        peak, and NodeRun.concurrent records how many were sharing it so the
        stats panel can say so rather than implying the growth was one node's.
        """
        rss = self._sampler.rss()
        if not rss:
            self._sample_timer.stop()   # unavailable here; stop asking
            return
        if self._record is not None:
            self._record.rss_peak = max(self._record.rss_peak, rss)
        for inflight in self._running.values():
            if inflight.run is not None:
                inflight.run.rss_peak = max(inflight.run.rss_peak, rss)

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
