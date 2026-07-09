"""Minimap: a painted overlay in the view's corner — node rects plus the
current viewport, click/drag to navigate. No second QGraphicsView."""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget

from .. import theme

WIDTH, HEIGHT = 200, 140
MARGIN = 12
REFRESH_MS = 200


class Minimap(QWidget):
    def __init__(self, view) -> None:
        super().__init__(view)
        self._view = view
        self.setFixedSize(WIDTH, HEIGHT)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, False)
        self._timer = QTimer(self)
        self._timer.setInterval(REFRESH_MS)
        self._timer.timeout.connect(self.update)
        self._timer.start()

    # ------------------------------------------------------------- mapping

    def _content_rect(self) -> QRectF:
        scene = self._view.scene()
        rect = QRectF()
        for item in scene.node_items.values():
            rect = rect.united(item.sceneBoundingRect())
        for item in scene.frame_items.values():
            rect = rect.united(item.scene_rect())
        viewport = self._view.mapToScene(
            self._view.viewport().rect()).boundingRect()
        rect = rect.united(viewport)
        if rect.isEmpty():
            rect = QRectF(-500, -400, 1000, 800)
        pad_x = rect.width() * 0.08
        pad_y = rect.height() * 0.08
        return rect.adjusted(-pad_x, -pad_y, pad_x, pad_y)

    def _scale(self, content: QRectF) -> float:
        return min(WIDTH / content.width(), HEIGHT / content.height())

    def _to_mini(self, point: QPointF, content: QRectF, s: float) -> QPointF:
        offset_x = (WIDTH - content.width() * s) / 2
        offset_y = (HEIGHT - content.height() * s) / 2
        return QPointF((point.x() - content.x()) * s + offset_x,
                       (point.y() - content.y()) * s + offset_y)

    def _to_scene(self, point: QPointF) -> QPointF:
        content = self._content_rect()
        s = self._scale(content)
        offset_x = (WIDTH - content.width() * s) / 2
        offset_y = (HEIGHT - content.height() * s) / 2
        return QPointF((point.x() - offset_x) / s + content.x(),
                       (point.y() - offset_y) / s + content.y())

    # ------------------------------------------------------------- painting

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        bg = QColor(theme.CANVAS_BG)
        bg.setAlphaF(0.85)
        painter.setBrush(bg)
        painter.setPen(QPen(theme.GRID_COARSE, 1))
        painter.drawRoundedRect(self.rect().adjusted(0, 0, -1, -1), 4, 4)

        scene = self._view.scene()
        content = self._content_rect()
        s = self._scale(content)

        for item in scene.frame_items.values():
            rect = item.scene_rect()
            top_left = self._to_mini(rect.topLeft(), content, s)
            color = QColor(item.frame.color)
            color.setAlphaF(0.35)
            painter.setPen(Qt.NoPen)
            painter.setBrush(color)
            painter.drawRect(QRectF(top_left,
                                    rect.size() * s).toRect())

        for item in scene.node_items.values():
            rect = item.sceneBoundingRect()
            top_left = self._to_mini(rect.topLeft(), content, s)
            painter.setPen(Qt.NoPen)
            painter.setBrush(theme.status_color(item.node.status)
                             if item.node.status.value != "idle"
                             else theme.NODE_HEADER.lighter(150))
            painter.drawRect(QRectF(top_left, rect.size() * s).toRect())

        viewport = self._view.mapToScene(
            self._view.viewport().rect()).boundingRect()
        top_left = self._to_mini(viewport.topLeft(), content, s)
        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(theme.SELECTION_OUTLINE, 1.5))
        painter.drawRect(QRectF(top_left, viewport.size() * s))

    # ---------------------------------------------------------- interaction

    def mousePressEvent(self, event) -> None:
        self._view.centerOn(self._to_scene(event.position()))
        event.accept()

    def mouseMoveEvent(self, event) -> None:
        if event.buttons() & Qt.LeftButton:
            self._view.centerOn(self._to_scene(event.position()))
            event.accept()

    def reposition(self) -> None:
        self.move(self._view.viewport().width() - WIDTH - MARGIN, MARGIN)
