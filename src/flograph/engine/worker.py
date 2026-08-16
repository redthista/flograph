"""Executes one node on a pool thread.

The worker never touches Qt widgets or the graph: it receives plain data,
runs the node, and hands results back to the GUI thread through queued
signals. WorkerSignals must be created on the GUI thread (QRunnable itself
can't carry signals).

Several nodes may be in flight at once (see scheduler._dispatch), so anything
process-wide a node touches has to be routed back to the node that touched
it. `print()` is the one that matters: see _StreamRouter.
"""
from __future__ import annotations

import io
import sys
import threading
import time
from typing import Any, Callable, Mapping, Optional

from PySide6.QtCore import QObject, QRunnable, Signal

from flograph.core.datatypes import validate_value
from flograph.core.ports import PortSpec
from flograph.core.script import NodeScriptError, compile_run

from .context import CancellationToken, NodeCancelled, RunContext
from .errors import NodeError, build_node_error


class WorkerSignals(QObject):
    finished = Signal(str, object, float)  # node_id, outputs: dict, wall_time
    failed = Signal(str, object)           # node_id, NodeError
    logged = Signal(str, str, str)         # node_id, line, stream
    progressed = Signal(str, float)        # node_id, fraction 0..1


class _LineWriter(io.TextIOBase):
    """Buffers writes and hands off complete lines."""

    def __init__(self, emit: Callable[[str], None]) -> None:
        super().__init__()
        self._emit = emit
        self._buffer = ""

    def writable(self) -> bool:
        return True

    def write(self, text: str) -> int:
        self._buffer += str(text)
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            self._emit(line)
        return len(text)

    def flush_remainder(self) -> None:
        if self._buffer:
            self._emit(self._buffer)
            self._buffer = ""


class _StreamRouter(io.TextIOBase):
    """One process-wide stdout (or stderr) that hands each thread its own sink.

    `contextlib.redirect_stdout` rebinds `sys.stdout` for the whole process,
    which was exactly right while one node ran at a time and is exactly wrong
    now that several can: two nodes printing at once would each land wherever
    the other most recently pointed the global, so a line would surface under
    a node that never wrote it. Interleaved output is bad; misattributed
    output is worse, because it reads as a bug in the wrong node.

    Routing by thread id fixes it at the only place that knows the answer.
    A thread with no sink registered — the GUI thread, a thread some library
    spawned inside a node — writes to whatever `sys.stdout` was when the
    router was installed, so output nobody claims still goes where it always
    went, pytest's capture included.
    """

    def __init__(self, fallback) -> None:
        super().__init__()
        self._fallback = fallback
        self._sinks: dict[int, Any] = {}

    def register(self, sink) -> None:
        self._sinks[threading.get_ident()] = sink

    def unregister(self) -> None:
        self._sinks.pop(threading.get_ident(), None)

    def writable(self) -> bool:
        return True

    def write(self, text: str) -> int:
        sink = self._sinks.get(threading.get_ident(), self._fallback)
        if sink is None:
            return len(text)
        return sink.write(text) or len(text)

    def flush(self) -> None:
        # Only the fallback: a _LineWriter buffers a partial line on purpose
        # and flushes it once, when its node finishes.
        if self._fallback is not None:
            try:
                self._fallback.flush()
            except Exception:
                pass


# Installed on first use and removed when the last node finishes, rather than
# at import: this module is imported to be read as much as to be run — the
# registry loads it, tests import it — and a module that rebinds sys.stdout on
# import would be capturing output from processes that never execute a node.
_stream_lock = threading.Lock()
_routers: Optional[tuple[_StreamRouter, _StreamRouter]] = None
_saved_streams: Optional[tuple[Any, Any]] = None
_router_users = 0


def _acquire_streams(stdout, stderr) -> None:
    """Point this thread's `print()` at `stdout`/`stderr`, installing the
    process-wide routers if this is the first node in flight."""
    global _routers, _saved_streams, _router_users
    with _stream_lock:
        if _routers is None:
            _saved_streams = (sys.stdout, sys.stderr)
            _routers = (_StreamRouter(sys.stdout), _StreamRouter(sys.stderr))
            sys.stdout, sys.stderr = _routers
        _router_users += 1
        out_router, err_router = _routers
    out_router.register(stdout)
    err_router.register(stderr)


def _release_streams() -> None:
    """Give up this thread's sinks, restoring the real streams once no node
    is running."""
    global _routers, _saved_streams, _router_users
    with _stream_lock:
        if _routers is None:
            return
        out_router, err_router = _routers
        out_router.unregister()
        err_router.unregister()
        _router_users -= 1
        if _router_users > 0:
            return
        # Only if nothing has been swapped in over us meanwhile — a debugger
        # or a test's capture is entitled to the global, and stamping our
        # saved value back over theirs would be the same bug one level up.
        if _saved_streams is not None:
            if sys.stdout is out_router:
                sys.stdout = _saved_streams[0]
            if sys.stderr is err_router:
                sys.stderr = _saved_streams[1]
        _routers = None
        _saved_streams = None


class NodeRunnable(QRunnable):
    def __init__(
        self,
        node_id: str,
        source: str,
        params: dict[str, Any],
        inputs: dict[str, Any],
        output_ports: list[PortSpec],
        token: CancellationToken,
        signals: WorkerSignals,
        variables: Optional[Mapping[str, Any]] = None,
    ) -> None:
        super().__init__()
        self.node_id = node_id
        self.source = source
        self.params = params
        self.variables = variables
        self.inputs = inputs
        self.output_ports = output_ports
        self.token = token
        self.signals = signals

    def run(self) -> None:  # executes on a pool thread
        node_id = self.node_id
        stdout = _LineWriter(lambda line: self.signals.logged.emit(node_id, line, "stdout"))
        stderr = _LineWriter(lambda line: self.signals.logged.emit(node_id, line, "stderr"))
        _acquire_streams(stdout, stderr)
        try:
            run_fn = compile_run(self.source, node_id)
            ctx = RunContext(
                node_id=node_id,
                params=self.params,
                variables=self.variables,
                token=self.token,
                log=self.signals.logged.emit,
                progress=self.signals.progressed.emit,
            )
            started = time.perf_counter()
            result = run_fn(ctx, **self.inputs)
            wall_time = time.perf_counter() - started
            outputs = self._normalize(result)
            self.signals.finished.emit(node_id, outputs, wall_time)
        except NodeCancelled as exc:
            self.signals.failed.emit(node_id, NodeError(
                node_id=node_id, message="cancelled",
                exc_type="NodeCancelled", formatted_tb="", script_line=None,
            ))
        except NodeScriptError as exc:
            self.signals.failed.emit(node_id, NodeError(
                node_id=node_id, message=str(exc),
                exc_type="NodeScriptError", formatted_tb=str(exc), script_line=None,
            ))
        except BaseException as exc:
            self.signals.failed.emit(node_id, build_node_error(node_id, self.source, exc))
        finally:
            # Order matters: the buffered partial lines are flushed while this
            # thread still owns its sinks, or the last line of a node that did
            # not end in a newline would be routed to the fallback instead.
            stdout.flush_remainder()
            stderr.flush_remainder()
            _release_streams()

    def _normalize(self, result: Any) -> dict[str, Any]:
        """Map run()'s return value onto the declared output ports, validating
        types. Raises ValueError (caught above as a node failure)."""
        names = [p.name for p in self.output_ports]
        if not names:
            return {}
        if len(names) == 1 and not (isinstance(result, dict) and set(result) == set(names)):
            outputs = {names[0]: result}
        elif isinstance(result, dict):
            missing = set(names) - set(result)
            extra = set(result) - set(names)
            if missing or extra:
                raise ValueError(
                    f"run() must return a dict keyed by the output ports "
                    f"{names}; missing {sorted(missing)}, unexpected {sorted(extra)}"
                )
            outputs = dict(result)
        else:
            raise ValueError(
                f"run() must return a dict keyed by the output ports {names}, "
                f"got {type(result).__name__}"
            )
        for port in self.output_ports:
            problem = validate_value(outputs[port.name], port.type)
            if problem:
                raise ValueError(f"output {port.name!r}: {problem}")
        return outputs
