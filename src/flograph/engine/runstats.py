"""What a run cost: per-node timings, output sizes and process memory.

The engine already knew how long each node took — `CacheEntry.wall_time` —
but only for nodes that finished *and* cached, only for the most recent run,
and with no record of what was skipped or what failed. That is enough for a
tooltip and not enough to answer "why did that take ninety seconds".

A RunRecord is the missing account: one NodeRun per node the plan actually
started, in the order they ran, plus what the run left out and why. Records
are kept in memory for the session and, since runs.json arrived, written
beside the project in its side-car so reopening shows the flow's previous
runs instead of a blank window. They are still bounded and still honest
about what they are — timings describe the machine as much as the flow —
which is why they live in the *cache* side-car rather than the project
file: derived, regenerable by running again, and not worth polluting a
diffable JSON document over.

Nothing here imports Qt. The engine owns the timer that drives sampling;
this module only holds the numbers and the arithmetic over them.
"""
from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from typing import Optional

HISTORY_LIMIT = 20

# How often the process is polled for its resident size while a node runs.
# Fast enough to catch a load that builds a large intermediate and drops it,
# slow enough to be free: reading /proc costs microseconds.
SAMPLE_MS = 100


@dataclass
class NodeRun:
    """One node's turn in one run."""
    node_id: str
    label: str
    outcome: str = "ok"          # ok | failed | cancelled
    started: float = 0.0         # seconds from the start of the run
    wall_time: float = 0.0
    output_bytes: int = 0
    summary: str = ""            # "12,345 rows × 8 cols", "DataFrame", ...
    rss_start: int = 0
    rss_peak: int = 0            # highest process RSS seen while it ran
    # How many nodes were in flight at once while this one ran, counting
    # itself: 1 means it had the process to itself. Above that, rss_peak is a
    # reading several nodes share and cannot be read as this node's own
    # appetite — see ProcessSampler.
    concurrent: int = 1

    @property
    def finished(self) -> float:
        return self.started + self.wall_time

    @property
    def rss_growth(self) -> int:
        """How much the process grew across this node.

        Can be negative, and legitimately so: a node that releases a large
        intermediate ends smaller than it started. Shown as a signed number
        rather than clamped, because "this step gave 2 GB back" is worth
        knowing too.
        """
        return self.rss_peak - self.rss_start if self.rss_peak else 0


@dataclass
class RunRecord:
    """One press of Run: what ran, what did not, and what it cost."""
    when: float = field(default_factory=time.time)
    wall_time: float = 0.0
    ok: bool = True
    cancelled: bool = False
    nodes: list[NodeRun] = field(default_factory=list)
    # What the plan left out, and on whose authority. Counted rather than
    # listed: the interesting part is the proportion, and the names are on
    # the canvas.
    skipped_clean: int = 0
    skipped_frozen: int = 0
    skipped_inactive: int = 0
    skipped_manual: int = 0
    rss_start: int = 0
    rss_peak: int = 0
    # The worker limit this run was given, and the most nodes actually in
    # flight at once. The second is the interesting one: a limit of eight on
    # a flow that never got past two says the graph is a chain, not that the
    # machine is busy.
    workers: int = 1
    peak_concurrency: int = 1

    def to_dict(self) -> dict:
        return {
            "when": self.when,
            "wall_time": self.wall_time,
            "ok": self.ok,
            "cancelled": self.cancelled,
            "skipped_clean": self.skipped_clean,
            "skipped_frozen": self.skipped_frozen,
            "skipped_inactive": self.skipped_inactive,
            "skipped_manual": self.skipped_manual,
            "rss_start": self.rss_start,
            "rss_peak": self.rss_peak,
            "workers": self.workers,
            "peak_concurrency": self.peak_concurrency,
            "nodes": [{
                "node_id": n.node_id,
                "label": n.label,
                "outcome": n.outcome,
                "started": n.started,
                "wall_time": n.wall_time,
                "output_bytes": n.output_bytes,
                "summary": n.summary,
                "rss_start": n.rss_start,
                "rss_peak": n.rss_peak,
                "concurrent": n.concurrent,
            } for n in self.nodes],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "RunRecord":
        record = cls(
            when=float(data.get("when") or 0.0),
            wall_time=float(data.get("wall_time") or 0.0),
            ok=bool(data.get("ok", True)),
            cancelled=bool(data.get("cancelled", False)),
            skipped_clean=int(data.get("skipped_clean") or 0),
            skipped_frozen=int(data.get("skipped_frozen") or 0),
            skipped_inactive=int(data.get("skipped_inactive") or 0),
            skipped_manual=int(data.get("skipped_manual") or 0),
            rss_start=int(data.get("rss_start") or 0),
            rss_peak=int(data.get("rss_peak") or 0),
            workers=int(data.get("workers") or 1),
            peak_concurrency=int(data.get("peak_concurrency") or 1),
        )
        for node in data.get("nodes") or []:
            if not isinstance(node, dict):
                continue
            record.nodes.append(NodeRun(
                node_id=str(node.get("node_id") or ""),
                label=str(node.get("label") or ""),
                outcome=str(node.get("outcome") or "ok"),
                started=float(node.get("started") or 0.0),
                wall_time=float(node.get("wall_time") or 0.0),
                output_bytes=int(node.get("output_bytes") or 0),
                summary=str(node.get("summary") or ""),
                rss_start=int(node.get("rss_start") or 0),
                rss_peak=int(node.get("rss_peak") or 0),
                concurrent=int(node.get("concurrent") or 1),
            ))
        return record

    @property
    def node_time(self) -> float:
        """Time inside nodes, as against the run's wall clock.

        The two differ by two things now. One is the scheduling overhead —
        dispatch, the queued signals that carry each result back to the GUI
        thread, the cache writes — which makes node time the *smaller*
        number. The other is overlap: nodes running side by side each charge
        their own seconds to a clock that only ran once, so node time can
        exceed wall time, and by how much is roughly how much the run got out
        of running wide. Read the gap with peak_concurrency beside it.
        """
        return sum(n.wall_time for n in self.nodes)

    @property
    def overlap(self) -> float:
        """Seconds saved by running nodes side by side, as far as the numbers
        can say: the node time that did not cost wall time. Zero on a run
        that never overlapped."""
        return max(0.0, self.node_time - self.wall_time)

    @property
    def failed(self) -> list[NodeRun]:
        return [n for n in self.nodes if n.outcome == "failed"]

    @property
    def peak_growth(self) -> int:
        return max(0, self.rss_peak - self.rss_start)

    def slowest(self, limit: int = 5) -> list[NodeRun]:
        return sorted(self.nodes, key=lambda n: n.wall_time, reverse=True)[:limit]

    def share(self, node: NodeRun) -> float:
        """This node's fraction of the time spent in nodes, 0.0 to 1.0."""
        total = self.node_time
        return node.wall_time / total if total > 0 else 0.0

    def heaviest(self, limit: int = 5) -> list[NodeRun]:
        return sorted(self.nodes, key=lambda n: n.output_bytes,
                      reverse=True)[:limit]


class RunHistory:
    """The last few runs, newest last. Session-only and bounded."""

    def __init__(self, limit: int = HISTORY_LIMIT) -> None:
        self._runs: deque = deque(maxlen=limit)

    def add(self, record: RunRecord) -> None:
        self._runs.append(record)

    def set_limit(self, limit: int) -> None:
        """Resize the window, keeping the newest runs if it shrinks."""
        limit = max(1, int(limit))
        if limit == self._runs.maxlen:
            return
        self._runs = deque(self._runs, maxlen=limit)

    def clear(self) -> None:
        self._runs.clear()

    @property
    def latest(self) -> Optional[RunRecord]:
        return self._runs[-1] if self._runs else None

    def all(self) -> list[RunRecord]:
        """Newest first — the order a run picker wants to offer them in."""
        return list(reversed(self._runs))

    def last_wall_time(self, node_id: str) -> Optional[float]:
        """How long this node took the last time it ran to completion.

        For telling someone watching a run roughly how long the step in
        front of them should take. Only successful runs count — a node that
        failed or was cancelled stopped early, so its time says nothing
        about how long the work takes. None when it has never finished this
        session, which is the honest answer on a first run.
        """
        for record in reversed(self._runs):
            for node in record.nodes:
                if node.node_id == node_id and node.outcome == "ok":
                    return node.wall_time
        return None

    def __len__(self) -> int:
        return len(self._runs)


class ProcessSampler:
    """The flograph process's resident size, polled.

    Deliberately approximate and labelled as such wherever it is shown. The
    interpreter, Qt, the loaded libraries and any other thread all live in
    the same process, so a node's attributed growth is "what the process did
    while this node held the floor", not "what this node allocated".

    Nodes can share that floor: when several run at once the same reading is
    charged to each of them, because a process-wide number cannot be split
    between its causes. NodeRun.concurrent records how many were sharing, and
    anything showing a peak should say so — a figure that reads as one node's
    appetite when it is really four nodes' is worse than no figure. A run
    that never overlapped (concurrent == 1) is attributed exactly as it
    always was.

    Degrades to zeroes rather than failing if psutil is unavailable or the
    platform refuses the read; a stats panel is never worth an exception.
    """

    def __init__(self) -> None:
        self._proc = None
        self._broken = False

    def rss(self) -> int:
        if self._broken:
            return 0
        try:
            if self._proc is None:
                import os
                import psutil
                self._proc = psutil.Process(os.getpid())
            return int(self._proc.memory_info().rss)
        except Exception:
            self._broken = True
            return 0
