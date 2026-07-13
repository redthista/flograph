from __future__ import annotations

import threading
from typing import Any, Callable, Optional


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

    def log(self, message: str) -> None:
        self._log(self.node_id, str(message), "log")

    def check_cancelled(self) -> None:
        if self._token.cancelled:
            raise NodeCancelled()

    def progress(self, fraction: float) -> None:
        if self._progress is not None:
            self._progress(self.node_id, max(0.0, min(1.0, float(fraction))))
