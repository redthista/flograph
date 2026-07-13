"""Log console: per-node stdout/stderr/ctx.log lines plus engine errors,
color-coded and capped."""
from __future__ import annotations

import html
import time

from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import (
    QHBoxLayout, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget,
)

from flograph.core import Graph
from flograph.engine import ExecutionEngine, NodeError

MAX_BLOCKS = 5000

_STREAM_COLORS = {
    "stdout": "#d1d5db",
    "log": "#93c5fd",
    "stderr": "#fb923c",
    "error": "#ef4444",
}


class LogConsole(QWidget):
    def __init__(self, graph: Graph, engine: ExecutionEngine, parent=None) -> None:
        super().__init__(parent)
        self._graph = graph

        self._text = QPlainTextEdit()
        self._text.setReadOnly(True)
        self._text.setMaximumBlockCount(MAX_BLOCKS)
        font = QFontDatabase.systemFont(QFontDatabase.FixedFont)
        font.setPointSizeF(9.0)
        self._text.setFont(font)

        clear_btn = QPushButton("Clear")
        clear_btn.clicked.connect(self._text.clear)
        top = QHBoxLayout()
        top.addStretch(1)
        top.addWidget(clear_btn)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 2, 6, 6)
        layout.addLayout(top)
        layout.addWidget(self._text, 1)

        engine.node_log.connect(self._on_log)
        engine.node_failed.connect(self._on_failed)
        engine.run_started.connect(
            lambda: self._append_raw("run started", "#6b7280"))
        engine.run_finished.connect(
            lambda ok: self._append_raw(
                "run finished" if ok else "run finished with errors",
                "#6b7280" if ok else _STREAM_COLORS["error"]))

    def _node_label(self, node_id: str) -> str:
        node = self._graph.nodes.get(node_id)
        return node.label if node is not None else node_id[:8]

    def _on_log(self, node_id: str, line: str, stream: str) -> None:
        color = _STREAM_COLORS.get(stream, "#d1d5db")
        stamp = time.strftime("%H:%M:%S")
        self._text.appendHtml(
            f'<span style="color:#4b5563">[{stamp}]</span> '
            f'<span style="color:#9ca3af">[{html.escape(self._node_label(node_id))}]</span> '
            f'<span style="color:{color}">{html.escape(line)}</span>')

    def _on_failed(self, node_id: str, error: NodeError) -> None:
        self._on_log(node_id, error.message, "error")
        if error.formatted_tb and error.formatted_tb != error.message:
            for tb_line in error.formatted_tb.splitlines():
                self._on_log(node_id, tb_line, "error")

    def _append_raw(self, text: str, color: str) -> None:
        stamp = time.strftime("%H:%M:%S")
        self._text.appendHtml(
            f'<span style="color:#4b5563">[{stamp}]</span> '
            f'<span style="color:{color}">— {html.escape(text)} —</span>')
