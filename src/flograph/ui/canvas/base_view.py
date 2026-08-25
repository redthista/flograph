"""ZoomPanGraphicsView: the infinite-feeling canvas behavior shared by the
modeling canvas and dashboard pages — zoom-to-cursor, middle/space pan,
adaptive grid, and a settle timer that re-renders figure widgets crisp once
zooming pauses."""
from __future__ import annotations

import math
import time
from collections import deque

from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QKeyEvent, QMouseEvent, QPainter, QPen, QWheelEvent
from PySide6.QtWidgets import (QAbstractScrollArea, QGraphicsProxyWidget,
                               QGraphicsView, QScrollBar, QWidget)

try:
    from PySide6.QtWebEngineWidgets import QWebEngineView
except ImportError:  # trimmed PySide6 installs ship without QtWebEngine
    QWebEngineView = None

from .. import theme

# How many recent frames the paint timer averages over. A couple of seconds
# of continuous redraw, so a figure reflects what the canvas is doing now
# rather than what it did during the last big pan.
PAINT_WINDOW = 120

ZOOM_MIN = 0.1
ZOOM_MAX = 4.0
GRID_FINE = 20.0
GRID_COARSE = 100.0
FINE_GRID_LOD = 0.4

# Edge-scroll: how close to the viewport border something must be held
# before the canvas starts gliding that way, how fast it moves at the very
# edge, and how often it moves. ~470 viewport px/s at full tilt.
EDGE_SCROLL_MARGIN = 44
EDGE_SCROLL_SPEED = 14
EDGE_SCROLL_TICK_MS = 30


def edge_scroll_delta(rect: QRect, pos: QPoint,
                      margin: float = EDGE_SCROLL_MARGIN,
                      speed: float = EDGE_SCROLL_SPEED) -> QPointF:
    """The pan to apply because `pos` sits in an edge band of `rect`, or a
    null point from the middle.

    The result is in viewport pixels, ready for scroll_by — the direction
    the *canvas content* slides, so holding at the left border yields a
    positive dx (what lay off-screen to the left comes into view). Each axis
    is decided on its own, so a corner scrolls both ways; deeper into a band
    scrolls faster, so slowing down is how you stop.
    """
    def push(depth: float) -> float:
        return speed * max(0.0, 1.0 - depth / margin)

    dx = dy = 0.0
    if pos.x() < margin:
        dx = push(pos.x())
    elif rect.width() - pos.x() < margin:
        dx = -push(rect.width() - pos.x())
    if pos.y() < margin:
        dy = push(pos.y())
    elif rect.height() - pos.y() < margin:
        dy = -push(rect.height() - pos.y())
    return QPointF(dx, dy)


class PaintStats:
    """How long this view is taking to draw itself.

    A ring of recent frame times, filled by paintEvent. The measurement costs
    two clock reads per frame, which is why it is always on rather than
    something the stats window switches: a diagnostic you have to enable
    before reproducing the problem is one you never have when you need it.

    Frames are only produced when something asks for a repaint, so a still
    canvas records nothing and `fps` is "how fast it redraws while it is
    redrawing", not a running frame rate.
    """

    def __init__(self, window: int = PAINT_WINDOW) -> None:
        self._frames: deque = deque(maxlen=window)
        self.total = 0            # frames drawn since the view opened

    def record(self, seconds: float) -> None:
        self._frames.append(seconds)
        self.total += 1

    def reset(self) -> None:
        self._frames.clear()

    def recent(self) -> list:
        """The window itself, oldest first — for anything that wants the
        shape rather than the average."""
        return list(self._frames)

    @property
    def samples(self) -> int:
        return len(self._frames)

    @property
    def avg_ms(self) -> float:
        return 1000 * sum(self._frames) / len(self._frames) if self._frames else 0.0

    @property
    def worst_ms(self) -> float:
        return 1000 * max(self._frames) if self._frames else 0.0

    @property
    def fps(self) -> float:
        """Frames a second the view could sustain at this cost — a ceiling,
        not an observed rate."""
        avg = self.avg_ms
        return 1000.0 / avg if avg > 0 else 0.0


class ZoomPanGraphicsView(QGraphicsView):
    zoom_changed = Signal(float)   # the new zoom factor (1.0 = 100%)

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
        self.paint_stats = PaintStats()
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

    def _apply_lod(self) -> None:
        """Push the new zoom to the scene right away (not gated by the zoom
        settle timer) so nodes hide their ports/widgets and flatten as soon
        as they cross the scene's lod_threshold, keeping large graphs
        responsive mid-zoom (see NodeGraphScene.lod_enabled/lod_threshold,
        user-configurable via Settings > Canvas)."""
        scene = self.scene()
        if scene is not None and hasattr(scene, "set_lod"):
            scene.set_lod(self.zoom)

    # ----------------------------------------------------------------- zoom

    @property
    def zoom(self) -> float:
        return self.transform().m11()

    def _zoom_updated(self) -> None:
        self._apply_lod()
        self._zoom_settle.start()
        self.zoom_changed.emit(self.zoom)

    def set_zoom(self, value: float) -> None:
        """Jump to an absolute zoom factor, keeping the view centre put."""
        value = max(ZOOM_MIN, min(ZOOM_MAX, value))
        factor = value / self.zoom
        if math.isclose(factor, 1.0):
            return
        center = self.mapToScene(self.viewport().rect().center())
        self.scale(factor, factor)
        self.centerOn(center)
        self._zoom_updated()

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
        self._zoom_updated()

    def _scrollable_widget_at(self, pos) -> QWidget | None:
        """The embedded widget under the viewport point that could consume a
        wheel tick — a scroll area with actual scroll range, a scrollbar
        itself, or a web view (folium/Leaflet and friends handle their own
        wheel-zoom/pan internally, regardless of Qt scroll range). Painted
        cards and widgets whose content fits return None so the canvas keeps
        zoom-to-cursor."""
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
                if QWebEngineView is not None and isinstance(
                        child, QWebEngineView):
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
        self._zoom_updated()

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

    def scroll_by(self, dx: float, dy: float) -> None:
        """Pan by viewport pixels — the same motion as a middle-drag pan,
        without needing a mouse move to carry it (edge-scroll ticks)."""
        self.translate(dx / self.zoom, dy / self.zoom)

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
            self._end_space_pan()
            event.accept()
            return
        super().keyReleaseEvent(event)

    def _end_space_pan(self) -> None:
        """Leave space-pan and restore the normal cursor. Space's key-release
        can be swallowed when a popup steals focus or the window deactivates
        mid-pan; without this the open-hand ScrollHandDrag cursor sticks."""
        if not self._space_held:
            return
        self._space_held = False
        self.setDragMode(QGraphicsView.RubberBandDrag)
        self.unsetCursor()

    def focusOutEvent(self, event) -> None:
        self._end_space_pan()
        super().focusOutEvent(event)

    def leaveEvent(self, event) -> None:
        self._end_space_pan()
        super().leaveEvent(event)

    def changeEvent(self, event) -> None:
        if event.type() == QEvent.ActivationChange and not self.isActiveWindow():
            self._end_space_pan()
        super().changeEvent(event)

    # --------------------------------------------------------------- paint

    def paintEvent(self, event) -> None:
        started = time.perf_counter()
        super().paintEvent(event)
        self.paint_stats.record(time.perf_counter() - started)

    # ------------------------------------------------------------------ bg

    def drawBackground(self, painter: QPainter, rect: QRectF) -> None:
        painter.fillRect(rect, theme.CANVAS_BG)
        from .grid import grid_step
        fine = grid_step(self.scene())  # follows the chosen snap resolution
        if self.zoom >= FINE_GRID_LOD:
            self._draw_grid(painter, rect, fine, theme.GRID_FINE)
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
