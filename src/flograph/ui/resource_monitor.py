"""Status bar resource monitor: system memory usage, the memory footprint of
all cached outputs in the open project, and of the currently selected node."""
from __future__ import annotations

from typing import Optional

import psutil
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget

from flograph.engine import ExecutionEngine

REFRESH_MS = 2000
_LABEL_STYLE = "color: #9ca3af; font-size: 8pt; padding: 0 4px;"


def format_bytes(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if abs(n) < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"


class ResourceMonitorWidget(QWidget):
    """Permanent status bar widget showing system RAM, the open file's total
    cache size, and the selected node's cache size."""

    def __init__(self, engine: ExecutionEngine, parent=None) -> None:
        super().__init__(parent)
        self._engine = engine
        self._node_id: Optional[str] = None

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 8, 0)
        layout.setSpacing(4)

        self._system_label = QLabel()
        self._file_label = QLabel()
        self._node_label = QLabel()
        for label in (self._system_label, self._file_label, self._node_label):
            label.setStyleSheet(_LABEL_STYLE)
        layout.addWidget(self._system_label)
        layout.addWidget(self._file_label)
        layout.addWidget(self._node_label)

        self._timer = QTimer(self)
        self._timer.setInterval(REFRESH_MS)
        self._timer.timeout.connect(self._refresh)
        self._timer.start()
        self._refresh()

    def set_node(self, node_id: Optional[str]) -> None:
        self._node_id = node_id
        self._refresh()

    def _refresh(self) -> None:
        vm = psutil.virtual_memory()
        self._system_label.setText(
            f"Sys mem: {format_bytes(vm.used)} / {format_bytes(vm.total)} ({vm.percent:.0f}%)"
        )

        self._file_label.setText(f"File mem: {format_bytes(self._engine.cache.total_bytes())}")

        entry = self._engine.cache.get(self._node_id) if self._node_id else None
        if entry is None:
            self._node_label.setText("Node mem: —")
        else:
            self._node_label.setText(f"Node mem: {format_bytes(entry.memory_bytes)}")
