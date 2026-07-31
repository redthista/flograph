from __future__ import annotations

import threading
import time
from typing import Any, Callable, Optional

# ctx.progress() is called from inside a node's own loop, so the node that
# most wants it is also the one most able to drown the GUI: the callback ends
# in a queued cross-thread signal, and one emit per row of a 200k-row frame
# would bury the event loop and take cancellation down with it. Throttling
# here rather than at the far end keeps it in one place and out of the reach
# of node authors, who cannot then get it wrong.
PROGRESS_MIN_STEP = 0.01    # a percentage point — finer than any LED can show
PROGRESS_MIN_INTERVAL = 0.25  # seconds; lets a slow drip still tick


class NodeCancelled(Exception):
    """Raised inside a node's run() by ctx.check_cancelled()."""


class CancellationToken:
    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        self._event.set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()


class RunContext:
    """What a node's run(ctx, ...) receives. The public node-facing API —
    keep it small and stable: params, log, check_cancelled, progress,
    node_id."""

    def __init__(
        self,
        node_id: str,
        params: dict[str, Any],
        token: CancellationToken,
        log: Callable[[str, str, str], None],
        progress: Optional[Callable[[str, float], None]] = None,
    ) -> None:
        self.node_id = node_id
        self.params = dict(params)
        self._token = token
        self._log = log
        self._progress = progress
        self._last_fraction = -1.0
        self._last_emit = 0.0

    def log(self, message: str) -> None:
        self._log(self.node_id, str(message), "log")

    def check_cancelled(self) -> None:
        if self._token.cancelled:
            raise NodeCancelled()

    def progress(self, fraction: float) -> None:
        """Report how far through this node's own work you are, 0..1.

        Safe to call as often as you like — see PROGRESS_MIN_STEP. A node
        that never calls it shows an indeterminate pulse instead.
        """
        if self._progress is None:
            return
        fraction = max(0.0, min(1.0, float(fraction)))
        now = time.monotonic()
        # A full 1.0 always lands, so the last thing seen is a finished ring
        # rather than whatever the throttle happened to let through last.
        if fraction < 1.0:
            # Distance, not advance: a loop that restarts its count reads as a
            # backwards step, and a ring frozen until it climbed past the old
            # high-water mark would look hung.
            if (abs(fraction - self._last_fraction) < PROGRESS_MIN_STEP
                    and now - self._last_emit < PROGRESS_MIN_INTERVAL):
                return
        elif self._last_fraction >= 1.0:
            return
        self._last_fraction = fraction
        self._last_emit = now
        self._progress(self.node_id, fraction)
