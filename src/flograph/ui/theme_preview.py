"""A page of labelled examples of the theme in force, for the Theme
Customiser: the controls in their states, and a small canvas with nodes in
each of theirs, so a change can be judged on a representative sample rather
than hunted for in the main window.

The controls are real widgets, so the app stylesheet styles them exactly as
it does anywhere. The canvas is painted here from the same theme constants
the real canvas reads (`theme.NODE_BODY`, `canvas.node_item.NODE_RADIUS` …),
so the two cannot drift.
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor, QFont, QPainter, QPainterPath, QPen,
)
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFormLayout, QFrame, QGroupBox, QHBoxLayout,
    QLabel, QLineEdit, QListWidget, QPushButton, QScrollArea, QSpinBox,
    QTabBar, QVBoxLayout, QWidget,
)

from flograph.core.ports import PortType
from flograph.core.node import NodeStatus

from . import theme


class MiniCanvas(QWidget):
    """Frames, nodes in five states, ports in every data colour, and the
    three wire states, on the canvas background."""

    def __init__(self) -> None:
        super().__init__()
        self.setMinimumSize(620, 250)
        theme.on_change(self.update)

    # one node: header strip, body, outline, title, one input + one output
    def _node(self, p: QPainter, x: float, y: float, title: str, *,
              selected=False, broken=False, bypassed=False,
              status=NodeStatus.IDLE, colour: QColor | None = None) -> tuple:
        from .canvas import node_item as ni
        w, h = ni.NODE_WIDTH * 0.62, ni.HEADER_H + ni.ROW_H + ni.PAD_BOTTOM
        rect = QRectF(x, y, w, h)
        radius = ni.NODE_RADIUS
        body = QPainterPath()
        body.addRoundedRect(rect, radius, radius)
        p.fillPath(body, colour or theme.NODE_BODY)
        header = QPainterPath()
        top = QRectF(x, y, w, ni.HEADER_H)
        header.addRoundedRect(top, radius, radius)
        header.addRect(QRectF(x, y + ni.HEADER_H / 2, w, ni.HEADER_H / 2))
        if broken:
            fill = theme.NODE_HEADER_BROKEN
        elif theme.style("one_tone_header"):
            fill = theme.NODE_BODY
        else:
            fill = theme.NODE_HEADER
        p.fillPath(header.simplified(), fill)
        if selected:
            pen = QPen(theme.SELECTION_OUTLINE, 2.0)
        elif broken:
            pen = QPen(theme.NODE_BORDER_BROKEN, 1.4)
        else:
            pen = QPen(theme.NODE_BORDER, 1.3)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(rect, radius, radius)
        font = QFont(p.font())
        font.setPointSizeF(8.5)
        font.setBold(True)
        p.setFont(font)
        p.setPen(theme.NODE_TEXT)
        p.drawText(QRectF(x + 8, y, w - 24, ni.HEADER_H),
                   Qt.AlignVCenter | Qt.AlignLeft,
                   ("⚠ " if broken else "") + title)
        font.setBold(False)
        font.setPointSizeF(7.5)
        p.setFont(font)
        p.setPen(theme.NODE_SUBTEXT)
        row = QRectF(x + 12, y + ni.HEADER_H, w - 24, ni.ROW_H)
        p.drawText(row, Qt.AlignVCenter | Qt.AlignLeft, "in")
        p.drawText(row, Qt.AlignVCenter | Qt.AlignRight, "out")
        # status light
        light = theme.STATUS_COLORS[status]
        p.setPen(Qt.NoPen)
        p.setBrush(light)
        p.drawEllipse(QPointF(x + w - 10, y + ni.HEADER_H / 2), 4.5, 4.5)
        if bypassed:
            p.setPen(QPen(theme.BYPASS, 1.6, Qt.DashLine))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(rect.adjusted(-3, -3, 3, 3), radius, radius)
        y_port = y + ni.HEADER_H + ni.ROW_H / 2
        return QPointF(x, y_port), QPointF(x + w, y_port)

    def _port(self, p: QPainter, at: QPointF, kind: str) -> None:
        p.setPen(QPen(theme.NODE_BORDER, 1.0))
        p.setBrush(theme.wire_color(PortType(kind)))
        p.drawEllipse(at, 5.0, 5.0)

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), theme.CANVAS_BG)
        # grid
        step = 20
        for i, x in enumerate(range(0, self.width(), step)):
            p.setPen(QPen(theme.GRID_COARSE if i % 5 == 0 else theme.GRID_FINE,
                          1))
            p.drawLine(x, 0, x, self.height())
        for i, y in enumerate(range(0, self.height(), step)):
            p.setPen(QPen(theme.GRID_COARSE if i % 5 == 0 else theme.GRID_FINE,
                          1))
            p.drawLine(0, y, self.width(), y)
        # two frames, one on a pale colour and one on a dark one
        for x, colour, label in ((8, QColor("#fde68a"), "Frame (light)"),
                                 (268, QColor("#1e3a8a"), "Frame (dark)")):
            rect = QRectF(x, 8, 244, 112)
            fill = QColor(colour)
            fill.setAlphaF(theme.FRAME_FILL)
            p.setPen(Qt.NoPen)
            p.setBrush(fill)
            p.drawRoundedRect(rect, 8, 8)
            bar = QColor(colour)
            bar.setAlphaF(theme.FRAME_TITLE_BAR)
            p.setBrush(bar)
            p.drawRoundedRect(QRectF(x, 8, 244, 20), 8, 8)
            p.setPen(theme.FRAME_TITLE)
            font = QFont(p.font())
            font.setPointSizeF(8)
            p.setFont(font)
            p.drawText(QRectF(x + 8, 8, 200, 20), Qt.AlignVCenter, label)
        # nodes, one per state
        a_in, a_out = self._node(p, 20, 40, "Normal", status=NodeStatus.DONE)
        b_in, b_out = self._node(p, 140, 40, "Selected", selected=True,
                                 status=NodeStatus.RUNNING)
        c_in, c_out = self._node(p, 280, 40, "Broken", broken=True,
                                 status=NodeStatus.ERROR)
        d_in, d_out = self._node(p, 400, 40, "Bypassed", bypassed=True,
                                 status=NodeStatus.QUEUED)
        e_in, e_out = self._node(p, 20, 160, "Idle")
        # wires: a data wire, a valid drop, an invalid drop, a pending drag
        def wire(a: QPointF, b: QPointF, colour: QColor, width=2.0, dash=False):
            path = QPainterPath(a)
            dx = max(30.0, abs(b.x() - a.x()) / 2)
            path.cubicTo(a.x() + dx, a.y(), b.x() - dx, b.y(), b.x(), b.y())
            pen = QPen(colour, width)
            if dash:
                pen.setStyle(Qt.DashLine)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            p.drawPath(path)
        wire(a_out, b_in, theme.wire_color(PortType("dataframe")))
        wire(b_out, c_in, theme.WIRE_VALID, dash=True)
        wire(c_out, d_in, theme.WIRE_INVALID, dash=True)
        wire(e_out, QPointF(e_out.x() + 110, e_out.y() - 8),
             theme.WIRE_PENDING, dash=True)
        # ports in every data colour, as a legend along the bottom
        font = QFont(p.font())
        font.setPointSizeF(7.5)
        p.setFont(font)
        x = 128.0
        for kind in ("any", "dataframe", "series", "number", "string",
                     "bool", "object", "figure", "flow"):
            self._port(p, QPointF(x, 214), kind)
            p.setPen(theme.NODE_SUBTEXT)
            p.drawText(QRectF(x - 26, 222, 52, 14), Qt.AlignCenter, kind)
            x += 54
        p.end()


class ThemePreview(QScrollArea):
    """The whole Preview tab."""

    def __init__(self) -> None:
        super().__init__()
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        page = QWidget()
        root = QVBoxLayout(page)

        controls = QGroupBox("Controls")
        form = QFormLayout(controls)
        row = QHBoxLayout()
        normal = QPushButton("Normal")
        default = QPushButton("Default")
        default.setDefault(True)
        off = QPushButton("Disabled")
        off.setEnabled(False)
        for b in (normal, default, off):
            row.addWidget(b)
        row.addStretch(1)
        form.addRow("Buttons", row)

        row = QHBoxLayout()
        self.focused = QLineEdit("Has keyboard focus")
        plain = QLineEdit("Plain input")
        empty = QLineEdit()
        empty.setPlaceholderText("Placeholder")
        gone = QLineEdit("Disabled")
        gone.setEnabled(False)
        bad = QLineEdit("Error")
        bad.setStyleSheet(
            f"QLineEdit {{ border: 1px solid {theme.status_color(NodeStatus.ERROR).name()}; }}")
        for w in (self.focused, plain, empty, gone, bad):
            row.addWidget(w)
        form.addRow("Inputs", row)

        row = QHBoxLayout()
        on = QCheckBox("On")
        on.setChecked(True)
        off_box = QCheckBox("Off")
        dis = QCheckBox("Disabled")
        dis.setEnabled(False)
        combo = QComboBox()
        combo.addItems(["Combo", "Second"])
        spin = QSpinBox()
        spin.setValue(7)
        for w in (on, off_box, dis, combo, spin):
            row.addWidget(w)
        row.addStretch(1)
        form.addRow("Choices", row)

        tabs = QTabBar()
        tabs.addTab("Selected")
        tabs.addTab("Other")
        tabs.addTab("Another")
        form.addRow("Tabs", tabs)

        lst = QListWidget()
        lst.addItems(["Row", "Selected row", "Row", "Row"])
        lst.setCurrentRow(1)
        lst.setAlternatingRowColors(True)
        lst.setMaximumHeight(86)
        form.addRow("List", lst)

        links = QLabel('Text, <a href="#">a link</a>, and dim text follow '
                       "the palette.")
        links.setTextFormat(Qt.RichText)
        form.addRow("Text", links)
        root.addWidget(controls)

        canvas = QGroupBox("Canvas — nodes, ports, wires, frames")
        box = QVBoxLayout(canvas)
        box.addWidget(MiniCanvas())
        legend = QLabel("Left to right: normal · selected · broken · "
                        "bypassed · idle. Dashed wires: valid drop · invalid "
                        "drop · pending drag.")
        legend.setWordWrap(True)
        box.addWidget(legend)
        root.addWidget(canvas)
        root.addStretch(1)
        self.setWidget(page)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.focused.setFocus()            # so one input shows its focus ring
