"""App facts: what a report can say about the app itself.

A report embed names a node — `![[Sales]]`. One under the reserved
`flograph.` prefix names something about the app instead: the flow's state,
when it last ran, the file it is saved in, today's date.

    ![[flograph.status]]       Up to date · last run 10:42 · took 3.2 s
    ![[flograph.last_run]]     10:42
    ![[flograph.file_size]]    1.4 MB

Most of it is read off the graph, which every renderer has. The rest — the
file the project is saved in, the engine's last run — belongs to the window
that has the project open, so a window registers a provider for its graph
(`set_provider`). A render with no provider (the headless runner, a test)
still answers from the graph and says "—" for what it cannot know.

Qt-free: the strings are built here, and only the status pill's colours
are drawn by the UI.
"""
from __future__ import annotations

import os
import time
import weakref
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Optional

PREFIX = "flograph."

#: Every fact, in the order the autocomplete lists them, with the line it
#: shows beside each.
FACTS = {
    "status": "the flow's state — up to date, out of date, running, failed",
    "date": "today's date",
    "time": "the time now, when the page was drawn",
    "last_run": "when the last run finished",
    "run_time": "how long the last run took",
    "run_result": "how the last run ended — OK, failed or stopped",
    "nodes": "how many nodes the flow has",
    "out_of_date": "how many nodes are waiting to run",
    "failed": "how many nodes failed",
    "file": "the project's file name",
    "file_size": "the project file's size on disk",
    "saved": "when the project file was last saved",
    "memory": "the memory flograph is using",
    "version": "the flograph version",
}

#: What a fact says when it cannot be known here.
UNKNOWN = "—"


@dataclass
class LastRun:
    finished: float          # epoch seconds
    seconds: float
    ok: bool = True
    cancelled: bool = False


@dataclass
class AppState:
    """What the window knows that the graph does not."""
    file_path: str = ""
    running: bool = False
    last_run: Optional[LastRun] = None


_providers: "weakref.WeakKeyDictionary" = weakref.WeakKeyDictionary()


def set_provider(graph, provider: Callable[[], AppState]) -> None:
    """Have `graph`'s facts read from `provider` — the window that has it
    open. Held weakly, so a closed window's graph lets go of it."""
    _providers[graph] = provider


def state_for(graph) -> AppState:
    provider = _providers.get(graph) if graph is not None else None
    if provider is None:
        return AppState()
    try:
        return provider() or AppState()
    except Exception:       # a window part-way through closing
        return AppState()


def fact_name(ref) -> Optional[str]:
    """The fact an embed's ref names — `status` for `flograph.status` — or
    None when it is not under the prefix (an ordinary node label)."""
    ref = str(ref or "").strip()
    if not ref.casefold().startswith(PREFIX):
        return None
    return ref[len(PREFIX):].strip().casefold()


def unknown_fact(name: str) -> str:
    return (f"> **⚠ No app fact called “{PREFIX}{name}”** — try "
            f"{', '.join(PREFIX + key for key in list(FACTS)[:4])}, ….")


# ------------------------------------------------------------- the status

@dataclass(frozen=True)
class Status:
    #: ok, stale, running, failed, stopped or never — the UI colours by it
    kind: str
    text: str


def status(graph, state: Optional[AppState] = None,
           now: Optional[float] = None) -> Status:
    """The flow's state in a phrase, and the last run beside it."""
    if graph is None:
        return Status("never", UNKNOWN)
    state = state or AppState()
    run = state.last_run
    when = f"last run {_clock(run.finished, now)}" if run else ""
    if state.running:
        return Status("running", "Running…")
    failed = _failed(graph)
    if failed:
        noun = "node" if failed == 1 else "nodes"
        return Status("failed", _join(f"{failed} {noun} failed", when))
    if run is not None and run.cancelled:
        return Status("stopped", _join("Last run stopped", when))
    stale = _out_of_date(graph)
    waiting = _runnable(graph)
    if stale and stale == len(waiting) and run is None:
        return Status("never", "Not run yet")
    if stale:
        noun = "node" if stale == 1 else "nodes"
        return Status("stale", _join(f"{stale} {noun} out of date", when))
    took = f"took {duration(run.seconds)}" if run else ""
    return Status("ok", _join("Up to date", when, took))


def _join(*parts) -> str:
    return " · ".join(part for part in parts if part)


def _nodes(graph) -> list:
    return list(graph.nodes.values()) if graph is not None else []


def _runnable(graph) -> list:
    """The nodes a run is about: active ones that make something. A button
    or a note never produces a value, so it is never "out of date"."""
    return [node for node in _nodes(graph)
            if getattr(node, "active", True) and node.spec.outputs]


def _out_of_date(graph) -> int:
    return sum(1 for node in _runnable(graph) if node.dirty)


def _failed(graph) -> int:
    return sum(1 for node in _nodes(graph)
               if getattr(node.status, "value", node.status) == "error")


# ------------------------------------------------------------- the values

def value(name: str, graph, state: Optional[AppState] = None,
          now: Optional[float] = None) -> Optional[str]:
    """The fact as words, or None when there is no fact of that name."""
    if name not in FACTS:
        return None
    state = state or AppState()
    now = time.time() if now is None else now
    run = state.last_run
    path = state.file_path
    if name == "status":
        return status(graph, state, now).text
    if name == "date":
        return datetime.fromtimestamp(now).strftime("%d %B %Y").lstrip("0")
    if name == "time":
        return datetime.fromtimestamp(now).strftime("%H:%M")
    if name == "last_run":
        return _clock(run.finished, now) if run else "not run yet"
    if name == "run_time":
        return duration(run.seconds) if run else UNKNOWN
    if name == "run_result":
        if state.running:
            return "running"
        if run is None:
            return "not run yet"
        return "stopped" if run.cancelled else ("OK" if run.ok else "failed")
    if graph is None and name in ("nodes", "out_of_date", "failed"):
        return UNKNOWN
    if name == "nodes":
        return str(len(graph.nodes))
    if name == "out_of_date":
        return str(_out_of_date(graph))
    if name == "failed":
        return str(_failed(graph))
    if name == "file":
        return os.path.basename(path) if path else "not saved yet"
    if name == "file_size":
        size = _stat(path, "st_size")
        return file_size(size) if size is not None else UNKNOWN
    if name == "saved":
        saved = _stat(path, "st_mtime")
        return _clock(saved, now) if saved is not None else "not saved yet"
    if name == "memory":
        rss = _rss()
        return file_size(rss) if rss else UNKNOWN
    if name == "version":
        from flograph.version import running_version
        return running_version(UNKNOWN) or UNKNOWN
    return None


def _stat(path: str, field: str):
    if not path:
        return None
    try:
        return getattr(os.stat(path), field)
    except OSError:
        return None


def _rss() -> Optional[int]:
    try:
        import psutil
        return psutil.Process().memory_info().rss
    except Exception:
        return None


def _clock(stamp: float, now: Optional[float] = None) -> str:
    """10:42 today, `4 Oct 10:42` another day, with the year if not this
    one."""
    when = datetime.fromtimestamp(stamp)
    today = datetime.fromtimestamp(time.time() if now is None else now)
    if when.date() == today.date():
        return when.strftime("%H:%M")
    if when.year == today.year:
        return f"{when.day} {when.strftime('%b %H:%M')}"
    return f"{when.day} {when.strftime('%b %Y %H:%M')}"


def duration(seconds: float) -> str:
    if seconds < 10:
        return f"{seconds:.1f} s"
    if seconds < 60:
        return f"{seconds:.0f} s"
    minutes, rest = divmod(int(round(seconds)), 60)
    if minutes < 60:
        return f"{minutes} min {rest} s" if rest else f"{minutes} min"
    hours, minutes = divmod(minutes, 60)
    return f"{hours} h {minutes} min" if minutes else f"{hours} h"


def file_size(size: float) -> str:
    for unit in ("bytes", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return (f"{int(size)} {unit}" if unit == "bytes"
                    else f"{size:.1f} {unit}")
        size /= 1024
    return f"{size:.1f} GB"
