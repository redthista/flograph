"""All colors and the application-wide dark theme live here — the single
place where core's hex strings become QColors."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

from flopy.core import WIRE_COLORS, PortType
from flopy.core.node import NodeStatus

# ------------------------------------------------------------------ canvas

CANVAS_BG = QColor("#1b1c20")
GRID_FINE = QColor("#232429")
GRID_COARSE = QColor("#2c2d34")

NODE_BODY = QColor("#2a2c33")
NODE_HEADER = QColor("#363943")
NODE_HEADER_BROKEN = QColor("#4c2626")
NODE_BORDER = QColor("#17181c")
NODE_BORDER_BROKEN = QColor("#7f1d1d")
NODE_TEXT = QColor("#e5e7eb")
NODE_SUBTEXT = QColor("#9ca3af")
SELECTION_OUTLINE = QColor("#60a5fa")

FRAME_TITLE = QColor("#d1d5db")
BUTTON_ACCENT = QColor("#7c6cf6")

STATUS_COLORS: dict[NodeStatus, QColor] = {
    NodeStatus.IDLE: QColor("#6b7280"),
    NodeStatus.QUEUED: QColor("#eab308"),
    NodeStatus.RUNNING: QColor("#3b82f6"),
    NodeStatus.DONE: QColor("#22c55e"),
    NodeStatus.ERROR: QColor("#ef4444"),
}

WIRE_VALID = QColor("#4ade80")
WIRE_INVALID = QColor("#ef4444")
WIRE_PENDING = QColor("#93c5fd")


def wire_color(port_type: PortType) -> QColor:
    return QColor(WIRE_COLORS[port_type])


def status_color(status: NodeStatus) -> QColor:
    return STATUS_COLORS[status]


# ------------------------------------------------------------------- app

def apply_theme(app: QApplication) -> None:
    app.setStyle("Fusion")
    palette = QPalette()
    window = QColor("#24262b")
    base = QColor("#1e2024")
    text = QColor("#e5e7eb")
    disabled = QColor("#6b7280")
    highlight = QColor("#3b82f6")

    palette.setColor(QPalette.Window, window)
    palette.setColor(QPalette.WindowText, text)
    palette.setColor(QPalette.Base, base)
    palette.setColor(QPalette.AlternateBase, window)
    palette.setColor(QPalette.ToolTipBase, base)
    palette.setColor(QPalette.ToolTipText, text)
    palette.setColor(QPalette.Text, text)
    palette.setColor(QPalette.Button, window)
    palette.setColor(QPalette.ButtonText, text)
    palette.setColor(QPalette.BrightText, QColor("#f87171"))
    palette.setColor(QPalette.Link, highlight)
    palette.setColor(QPalette.Highlight, highlight)
    palette.setColor(QPalette.HighlightedText, QColor("#ffffff"))
    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
        palette.setColor(QPalette.Disabled, role, disabled)
    app.setPalette(palette)

    app.setStyleSheet("""
        QToolTip { background: #1e2024; color: #e5e7eb; border: 1px solid #3a3d46; }
        QDockWidget::title { background: #2a2c33; padding: 4px 8px; }
        QTabBar::tab { background: #24262b; padding: 5px 12px; border: none; }
        QTabBar::tab:selected { background: #33363e; }
        QStatusBar { background: #202226; }
    """)
