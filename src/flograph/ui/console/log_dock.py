"""Log console: per-node stdout/stderr/ctx.log lines plus engine errors,
color-coded and capped. Each line also carries a severity mark, so the kind
of line does not rest on colour alone, and its node's name is a link that
selects the node (`node_requested`)."""
from __future__ import annotations

import html
import time

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtGui import QFontDatabase, QIcon
from PySide6.QtWidgets import (
    QHBoxLayout, QPlainTextEdit, QStyle, QToolButton, QVBoxLayout, QWidget,
)

from flograph.core import Graph
from flograph.engine import ExecutionEngine, NodeError
from flograph.ui import theme

MAX_BLOCKS = 5000

_STREAM_COLORS = {
    "stdout": "#d1d5db",
    "log": "#93c5fd",
    "stderr": "#fb923c",
    "error": "#ef4444",
}


#: a mark per kind of line: errors and warnings are told apart by shape as
#: well as colour (a colour-blind reader, a grey-scale print-out)
_STREAM_MARKS = {
    "stdout": "\u00a0",
    "log": "\u2022",
    "stderr": "!",
    "error": "\u2715",
}

_LINK = "node:"


class LogConsole(QWidget):
    #: a node's name was clicked in the log -- go to that node
    node_requested = Signal(str)

    def __init__(self, graph: Graph, engine: ExecutionEngine, parent=None) -> None:
        super().__init__(parent)
        self._graph = graph

        self._text = QPlainTextEdit()
        self._text.setReadOnly(True)
        self._text.setMaximumBlockCount(MAX_BLOCKS)
        font = QFontDatabase.systemFont(QFontDatabase.FixedFont)
        font.setPointSizeF(9.0)
        self._text.setFont(font)
        self._text.viewport().installEventFilter(self)
        self._text.viewport().setMouseTracking(True)

        # the log runs the full height; Clear is a small icon in a narrow
        # column to its right rather than a row of its own above it
        clear_btn = QToolButton()
        clear_btn.setIcon(QIcon.fromTheme(
            "edit-clear-all",
            self.style().standardIcon(QStyle.SP_LineEditClearButton)))
        clear_btn.setToolTip("Clear the log")
        clear_btn.setAutoRaise(True)
        clear_btn.clicked.connect(self._text.clear)
        side = QVBoxLayout()
        side.setContentsMargins(0, 0, 0, 0)
        side.addWidget(clear_btn)
        side.addStretch(1)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(2)
        layout.addWidget(self._text, 1)
        layout.addLayout(side)

        engine.node_log.connect(self._on_log)
        engine.node_failed.connect(self._on_failed)
        engine.run_started.connect(
            lambda: self._append_raw("run started", "#6b7280"))
        engine.run_finished.connect(
            lambda ok: self._append_raw(
                "run finished" if ok else "\u2715 run finished with errors",
                "#6b7280" if ok else _STREAM_COLORS["error"]))

    def _anchor_at(self, pos) -> str:
        cursor = self._text.cursorForPosition(pos)
        href = cursor.charFormat().anchorHref()
        return href[len(_LINK):] if href.startswith(_LINK) else ""

    def eventFilter(self, watched, event) -> bool:
        """A click on a node's name selects that node; the pointer turns to
        a hand over one, so the link is discoverable."""
        if watched is self._text.viewport():
            kind = event.type()
            if kind == QEvent.MouseMove:
                watched.setCursor(Qt.PointingHandCursor
                                  if self._anchor_at(event.position().toPoint())
                                  else Qt.IBeamCursor)
            elif (kind == QEvent.MouseButtonRelease
                  and event.button() == Qt.LeftButton
                  and not self._text.textCursor().hasSelection()):
                node_id = self._anchor_at(event.position().toPoint())
                if node_id and node_id in self._graph.nodes:
                    self.node_requested.emit(node_id)
        return super().eventFilter(watched, event)

    def _node_label(self, node_id: str) -> str:
        node = self._graph.nodes.get(node_id)
        return node.label if node is not None else node_id[:8]

    def _on_log(self, node_id: str, line: str, stream: str) -> None:
        color = _STREAM_COLORS.get(stream, "#d1d5db")
        mark = _STREAM_MARKS.get(stream, "\u00a0")
        stamp = time.strftime("%H:%M:%S")
        label = html.escape(self._node_label(node_id))
        self._text.appendHtml(theme.skin(
            f'<span style="color:#4b5563">[{stamp}]</span> '
            f'<span style="color:{color}">{mark}</span> '
            f'<a href="{_LINK}{html.escape(node_id)}" '
            f'style="color:#9ca3af; text-decoration:none">[{label}]</a> '
            f'<span style="color:{color}">{html.escape(line)}</span>'))

    def _on_failed(self, node_id: str, error: NodeError) -> None:
        self._on_log(node_id, error.message, "error")
        if error.formatted_tb and error.formatted_tb != error.message:
            for tb_line in error.formatted_tb.splitlines():
                self._on_log(node_id, tb_line, "error")

    def _append_raw(self, text: str, color: str) -> None:
        stamp = time.strftime("%H:%M:%S")
        self._text.appendHtml(theme.skin(
            f'<span style="color:#4b5563">[{stamp}]</span> '
            f'<span style="color:{color}">— {html.escape(text)} —</span>'))
