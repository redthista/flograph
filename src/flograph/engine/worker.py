"""Executes one node on a pool thread.

The worker never touches Qt widgets or the graph: it receives plain data,
runs the node, and hands results back to the GUI thread through queued
signals. WorkerSignals must be created on the GUI thread (QRunnable itself
can't carry signals).
"""
from __future__ import annotations

import io
import time
from typing import Any, Callable

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
    ) -> None:
        super().__init__()
        self.node_id = node_id
        self.source = source
        self.params = params
        self.inputs = inputs
        self.output_ports = output_ports
        self.token = token
        self.signals = signals

    def run(self) -> None:  # executes on a pool thread
        node_id = self.node_id
        stdout = _LineWriter(lambda line: self.signals.logged.emit(node_id, line, "stdout"))
        stderr = _LineWriter(lambda line: self.signals.logged.emit(node_id, line, "stderr"))
        try:
            run_fn = compile_run(self.source, node_id)
            ctx = RunContext(
                node_id=node_id,
                params=self.params,
                token=self.token,
                log=self.signals.logged.emit,
            )
            import contextlib
            started = time.perf_counter()
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
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
            stdout.flush_remainder()
            stderr.flush_remainder()

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
