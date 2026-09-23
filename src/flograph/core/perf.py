"""Where the GUI thread's time goes — a few labelled stopwatches.

A hang is almost always one long piece of work on the GUI thread, and the
question after one is always "which?". `timed(label)` wraps the handful of
places that can take long (rendering a card, rebuilding a report, caching a
result) and keeps a running total per label, so a benchmark can ask where a
run's time went and the stall watchdog (`ui/perf.py`) can name the work it
just waited on.

It costs two clock reads and a dict update, so it stays on. Printing each
slow block is opt-in: set `FLOGRAPH_PERF=1` and anything over
`LOG_THRESHOLD` seconds goes to stderr as it finishes.

Qt-free on purpose — the engine uses it too.
"""
from __future__ import annotations

import functools
import inspect
import os
import sys
import threading
import time
from dataclasses import dataclass

LOG_THRESHOLD = 0.05


@dataclass
class Tally:
    count: int = 0
    total: float = 0.0
    longest: float = 0.0


_tallies: dict[str, Tally] = {}
# The slowest block since the watchdog last asked — what it names when a
# tick arrives late. Only GUI-thread blocks are kept: a worker's slow block
# is not what froze the window.
_slowest: "tuple[str, float] | None" = None
_logging = os.environ.get("FLOGRAPH_PERF", "") not in ("", "0")


class timed:
    """`with timed("label"):` or `@timed("label")` on a method.

    As a decorator it trims surplus positional arguments before the call,
    the way PySide does for a plain slot: a signal that emits more than a
    method takes (`run_finished(bool)` into a `refresh()`) hands the wrapper
    all of them, and a bare `*args` pass-through would then raise."""

    __slots__ = ("label", "_start")

    def __init__(self, label: str):
        self.label = label

    def __enter__(self):
        self._start = time.perf_counter()
        return self

    def __exit__(self, *exc):
        record(self.label, time.perf_counter() - self._start)
        return False

    def __call__(self, fn):
        label = self.label
        code = fn.__code__
        limit = None if code.co_flags & inspect.CO_VARARGS else code.co_argcount

        @functools.wraps(fn)
        def inner(*args, **kwargs):
            if limit is not None and len(args) > limit:
                args = args[:limit]
            start = time.perf_counter()
            try:
                return fn(*args, **kwargs)
            finally:
                record(label, time.perf_counter() - start)
        return inner


def record(label: str, seconds: float) -> None:
    global _slowest
    tally = _tallies.get(label)
    if tally is None:
        tally = _tallies[label] = Tally()
    tally.count += 1
    tally.total += seconds
    if seconds > tally.longest:
        tally.longest = seconds
    if threading.current_thread() is threading.main_thread():
        if _slowest is None or seconds > _slowest[1]:
            _slowest = (label, seconds)
    if _logging and seconds >= LOG_THRESHOLD:
        print(f"[perf] {label}: {seconds * 1000:.0f} ms", file=sys.stderr)


def tallies() -> dict[str, Tally]:
    return dict(_tallies)


def reset() -> None:
    global _slowest
    _tallies.clear()
    _slowest = None


def take_slowest() -> "tuple[str, float] | None":
    """The slowest GUI-thread block since the last call, and forget it."""
    global _slowest
    found, _slowest = _slowest, None
    return found
