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

# How far past the outermost item the scrollable span reaches, per side.
# The scroll bars map the whole span onto their length, so this — not a
# world-sized rect — is what decides how fast they scroll: fitted to the
# flow, one pixel of bar is one pixel of canvas. (Kept here rather than in
# scene.py because center_on_scene needs it and scene.py imports this
# module's neighbours.)
SCENE_MARGIN = 1200.0


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
        # The view frozen where it stands — no zoom, no pan, no rubber band,
        # no scroll bars (a locked dashboard page sets this; see
        # set_navigation_locked). The scene underneath is untouched, so
        # everything embedded in it still takes input.
        self.navigation_locked = False
        self._scrollbars_enabled = False
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
        if self.navigation_locked:
            return
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
        if self.navigation_locked:
            # Swallowed rather than passed up: QGraphicsView's own handler
            # would scroll the view instead, which is the same accident by a
            # different route. Note the branch above it, which runs first —
            # a table or a web view under the cursor still gets its wheel,
            # because a locked page is one being *used*.
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
        if not items or self.navigation_locked:
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
        if event.button() == Qt.MiddleButton and not self.navigation_locked:
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

    def center_on_scene(self, pos) -> None:
        """Centre the view on a point or an item (centreOn accepts both),
        first stretching the scrollable span to reach if it must — the view
        cannot scroll outside its sceneRect, so a jump aimed past it would
        land short of centre. The debounced refit keeps whatever the views
        are looking at inside the span, so this stretch holds."""
        scene = self.scene()
        if hasattr(scene, "flush_rect_fit"):
            rect_fn = getattr(pos, "sceneBoundingRect", None)
            if callable(rect_fn):
                target = rect_fn().center()
            else:
                target = QPointF(pos.x(), pos.y())
            span = scene.sceneRect()
            if not span.contains(target):
                # room to actually centre it — the target plus what the
                # viewport shows around it, plus a margin's slack so the
                # exact edge isn't sitting on an integer scroll step
                pad = SCENE_MARGIN + max(
                    self.viewport().width(),
                    self.viewport().height()) / (2 * self.zoom)
                grown = span.united(QRectF(
                    target.x() - pad, target.y() - pad, 2 * pad, 2 * pad))
                scene.setSceneRect(grown)
        self.centerOn(pos)
        # refit right away rather than after the debounce: the fit keeps
        # whatever the views are looking at, and we are looking somewhere
        # new — this makes the reach above permanent instead of something
        # a racing refit could clamp back mid-gesture
        if hasattr(scene, "flush_rect_fit"):
            scene.flush_rect_fit()

    def set_scrollbars_enabled(self, enabled: bool) -> None:
        """Show the horizontal and vertical scroll bars. The canvas pans
        freely by drag and wheel either way; the bars are a where-am-I and
        a drag handle for people who want one, not the mechanism."""
        self._scrollbars_enabled = bool(enabled)
        self._apply_scrollbar_policy()

    def _apply_scrollbar_policy(self) -> None:
        """The setting, minus anything the lock overrules — kept in one
        place because the two arrive independently: the window pushes the
        preference at every view whenever it changes, and would otherwise
        put the bars back on a page that has none to offer."""
        show = self._scrollbars_enabled and not self.navigation_locked
        policy = Qt.ScrollBarAsNeeded if show else Qt.ScrollBarAlwaysOff
        self.setHorizontalScrollBarPolicy(policy)
        self.setVerticalScrollBarPolicy(policy)

    def _restore_drag_mode(self) -> None:
        self.setDragMode(QGraphicsView.NoDrag if self.navigation_locked
                         else QGraphicsView.RubberBandDrag)

    def set_navigation_locked(self, locked: bool) -> None:
        """Freeze the view: no zoom, no pan, no rubber band, no scroll bars.

        Not a read-only mode — the *scene* is untouched, so every widget in
        it still takes input. This is only about the viewport: the surface
        stops behaving like an infinite canvas and starts behaving like a
        page, which is what a finished dashboard is. Everything a canvas
        offers here — zoom to cursor, middle-drag, space-drag, the rubber
        band, the bars — is a way of rearranging your view of something you
        are still building, and there is nothing left to build.
        """
        self.navigation_locked = bool(locked)
        if self.navigation_locked:
            self._space_held = False
            self._panning = False
            self.unsetCursor()
            # And take the viewport's cursor back, which is not the same
            # thing. An item with a cursor sets it *on the viewport*, and
            # the viewport only gets it back when the mouse moves off that
            # item — so locking a page from the tab menu, with the pointer
            # nowhere near it, leaves whatever the last tile asked for
            # painted on for good. That was a four-way move cursor over
            # every card of a locked dashboard, on every part of it that
            # had no widget of its own to say otherwise.
            self.viewport().setCursor(Qt.ArrowCursor)
        else:
            self.viewport().unsetCursor()
        self._restore_drag_mode()
        self._apply_scrollbar_policy()

    # ------------------------------------------------------------ keyboard

    def _proxy_widget_has_focus(self) -> bool:
        """True when an embedded widget (note editor, table cell) is focused
        and should receive keys instead of the canvas shortcuts."""
        return isinstance(self.scene().focusItem(), QGraphicsProxyWidget)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if (not self._proxy_widget_has_focus()
                and not self.navigation_locked
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
        self._restore_drag_mode()
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
