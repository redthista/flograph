"""ZoomPanGraphicsView: the infinite-feeling canvas behavior shared by the
modeling canvas and dashboard pages — zoom-to-cursor, middle/space pan,
adaptive grid, and a settle timer that re-renders figure widgets crisp once
zooming pauses."""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QKeyEvent, QMouseEvent, QPainter, QPen, QWheelEvent
from PySide6.QtWidgets import (QAbstractScrollArea, QGraphicsProxyWidget,
                               QGraphicsView, QScrollBar, QWidget)

from .. import theme

ZOOM_MIN = 0.1
ZOOM_MAX = 4.0
GRID_FINE = 20.0
GRID_COARSE = 100.0
FINE_GRID_LOD = 0.4


class ZoomPanGraphicsView(QGraphicsView):
    def __init__(self, scene, parent=None) -> None:
        super().__init__(scene, parent)
        # SmoothPixmapTransform matters for the embedded figure/webview
        # cards: without it any zoomed raster is scaled nearest-neighbor
        # and reads as pixelated instead of merely soft
        self.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing
                            | QPainter.SmoothPixmapTransform)
        self.setTransformationAnchor(QGraphicsView.NoAnchor)
        self.setResizeAnchor(QGraphicsView.NoAnchor)
        self.setDragMode(QGraphicsView.RubberBandDrag)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setViewportUpdateMode(QGraphicsView.BoundingRectViewportUpdate)
        self._panning = False
        self._pan_last = QPointF()
        self._space_held = False
        self.centerOn(0, 0)

        # figure cards re-render at the new resolution once zooming pauses —
        # not per wheel tick, which would redraw every figure continuously
        self._zoom_settle = QTimer(self)
        self._zoom_settle.setSingleShot(True)
        self._zoom_settle.setInterval(150)
        self._zoom_settle.timeout.connect(self._on_zoom_settled)

    def _on_zoom_settled(self) -> None:
        scene = self.scene()
        if scene is not None and hasattr(scene, "refresh_render_ratios"):
            scene.refresh_render_ratios()

    # ----------------------------------------------------------------- zoom

    @property
    def zoom(self) -> float:
        return self.transform().m11()

    def wheelEvent(self, event: QWheelEvent) -> None:
        if self._scrollable_widget_at(event.position().toPoint()) is not None:
            # a table/list card under the cursor can scroll — let the scene
            # deliver the wheel to its proxy widget instead of zooming. When
            # the widget is already at the end of its range it ignores the
            # tick and QGraphicsView falls back to scrolling the view's own
            # (hidden) scrollbars, panning the canvas out from under the
            # cursor; pin them so the card swallows the tick instead.
            hbar, vbar = self.horizontalScrollBar(), self.verticalScrollBar()
            h, v = hbar.value(), vbar.value()
            super().wheelEvent(event)
            hbar.setValue(h)
            vbar.setValue(v)
            event.accept()
            return
        factor = 1.15 ** (event.angleDelta().y() / 120.0)
        new_zoom = max(ZOOM_MIN, min(ZOOM_MAX, self.zoom * factor))
        factor = new_zoom / self.zoom
        if math.isclose(factor, 1.0):
            return
        pos = event.position().toPoint()
        before = self.mapToScene(pos)
        self.scale(factor, factor)
        after = self.mapToScene(pos)
        delta = after - before
        self.translate(delta.x(), delta.y())
        self._zoom_settle.start()

    def _scrollable_widget_at(self, pos) -> QWidget | None:
        """The embedded widget under the viewport point that could consume a
        wheel tick — a scroll area with actual scroll range, or a scrollbar
        itself. Painted cards and widgets whose content fits return None so
        the canvas keeps zoom-to-cursor."""
        scene_pos = self.mapToScene(pos)
        for item in self.items(pos):
            if not isinstance(item, QGraphicsProxyWidget):
                continue
            widget = item.widget()
            if widget is None:
                continue
            # proxy-local coordinates are widget coordinates; mapFromScene
            # already folds in any proxy.setScale card-fitting transform
            local = item.mapFromScene(scene_pos).toPoint()
            child = widget.childAt(local) or widget
            while child is not None:
                if isinstance(child, QScrollBar):
                    return child
                if (isinstance(child, QAbstractScrollArea)
                        and self._has_scroll_range(child)):
                    return child
                child = child.parentWidget()
        return None

    @staticmethod
    def _has_scroll_range(area: QAbstractScrollArea) -> bool:
        return any(bar.maximum() > bar.minimum()
                   for bar in (area.verticalScrollBar(),
                               area.horizontalScrollBar())
                   if bar is not None)

    def fit_items(self, items) -> None:
        """Fit the given graphics items in view with a margin."""
        if not items:
            return
        rect = QRectF()
        for item in items:
            rect = rect.united(item.sceneBoundingRect())
        rect.adjust(-60, -60, 60, 60)
        self.fitInView(rect, Qt.KeepAspectRatio)
        if self.zoom > 1.5:  # don't over-zoom on a single item
            factor = 1.5 / self.zoom
            self.scale(factor, factor)
        self._zoom_settle.start()

    # ------------------------------------------------------------------ pan

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MiddleButton:
            self._panning = True
            self._pan_last = event.position()
            self.setCursor(Qt.ClosedHandCursor)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._panning:
            delta = event.position() - self._pan_last
            self._pan_last = event.position()
            self.translate(delta.x() / self.zoom, delta.y() / self.zoom)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MiddleButton and self._panning:
            self._panning = False
            self.unsetCursor()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    # ------------------------------------------------------------ keyboard

    def _proxy_widget_has_focus(self) -> bool:
        """True when an embedded widget (note editor, table cell) is focused
        and should receive keys instead of the canvas shortcuts."""
        return isinstance(self.scene().focusItem(), QGraphicsProxyWidget)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if (not self._proxy_widget_has_focus()
                and event.key() == Qt.Key_Space and not event.isAutoRepeat()):
            self._space_held = True
            self.setDragMode(QGraphicsView.ScrollHandDrag)
            event.accept()
            return
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key_Space and not event.isAutoRepeat():
            self._space_held = False
            self.setDragMode(QGraphicsView.RubberBandDrag)
            event.accept()
            return
        super().keyReleaseEvent(event)

    # ------------------------------------------------------------------ bg

    def drawBackground(self, painter: QPainter, rect: QRectF) -> None:
        painter.fillRect(rect, theme.CANVAS_BG)
        if self.zoom >= FINE_GRID_LOD:
            self._draw_grid(painter, rect, GRID_FINE, theme.GRID_FINE)
        self._draw_grid(painter, rect, GRID_COARSE, theme.GRID_COARSE)

    @staticmethod
    def _draw_grid(painter: QPainter, rect: QRectF, step: float, color) -> None:
        painter.setPen(QPen(color, 0))
        x = math.floor(rect.left() / step) * step
        while x < rect.right():
            painter.drawLine(QPointF(x, rect.top()), QPointF(x, rect.bottom()))
            x += step
        y = math.floor(rect.top() / step) * step
        while y < rect.bottom():
            painter.drawLine(QPointF(rect.left(), y), QPointF(rect.right(), y))
            y += step
