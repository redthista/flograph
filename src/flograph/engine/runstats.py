"""What a run cost: per-node timings, output sizes and process memory.

The engine already knew how long each node took — `CacheEntry.wall_time` —
but only for nodes that finished *and* cached, only for the most recent run,
and with no record of what was skipped or what failed. That is enough for a
tooltip and not enough to answer "why did that take ninety seconds".

A RunRecord is the missing account: one NodeRun per node the plan actually
started, in the order they ran, plus what the run left out and why. Records
are kept in memory for the session and nothing is written beside the project
— run timings age badly (they describe the machine as much as the flow) and
are not worth carrying between sittings.

Nothing here imports Qt. The engine owns the timer that drives sampling; this
module only holds the numbers and the arithmetic over them.
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
    rss_start: int = 0
    rss_peak: int = 0

    @property
    def node_time(self) -> float:
        """Time inside nodes, as against the run's wall clock.

        The two differ by the scheduling overhead: dispatch, the queued
        signals that carry each result back to the GUI thread, and the cache
        writes. A wide gap is itself a finding — it means the flow is losing
        time between the steps rather than in them.
        """
        return sum(n.wall_time for n in self.nodes)

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

    def __len__(self) -> int:
        return len(self._runs)


class ProcessSampler:
    """The flograph process's resident size, polled.

    Deliberately approximate and labelled as such wherever it is shown. The
    interpreter, Qt, the loaded libraries and any other thread all live in
    the same process, so a node's attributed growth is "what the process did
    while this node held the floor", not "what this node allocated". Runs are
    serial — one NodeRunnable in flight at a time — which is what makes the
    attribution meaningful at all.

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
