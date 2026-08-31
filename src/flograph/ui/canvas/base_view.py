"""ZoomPanGraphicsView: the infinite-feeling canvas behavior shared by the
modeling canvas and dashboard pages — zoom-to-cursor, middle/space pan,
adaptive grid, and a settle timer that re-renders figure widgets crisp once
zooming pauses."""
from __future__ import annotations

import math
import time
from collections import deque

from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (QKeyEvent, QMouseEvent, QPainter, QPainterPath,
                           QPen, QWheelEvent)
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

# What a drag-select has to do to an item to catch it.
#
# "touch" is Qt's own default (IntersectsItemShape): the band only has to
# graze an item. "contain" is Qt's ContainsItemShape: only what the band
# swallows whole. "frames" is the middle one and the default — nodes on a
# graze, frames only when the band goes right round them.
#
# The middle one exists because the two rules want different things. Sweeping
# a row of nodes wants a band that catches what it brushes; a band drawn
# inside a frame to pick up the nodes in it does not want the frame as well,
# since a selected frame drags its whole block along. Frames are the only
# items big enough for a band to be drawn *inside*, so they are the only ones
# that need the stricter rule.
RUBBER_BAND_MODES = ("touch", "frames", "contain")
DEFAULT_RUBBER_BAND_MODE = "frames"

#: Modifiers that can be held to get the *other* mode for the length of one
#: drag, keyed by the name the setting stores.
#:
#: Ctrl is the default: from the default mode it gives back the band that
#: catches everything it crosses, which is the behaviour anyone who has used
#: the canvas already has in their hands. It comes with a rider — Qt reads
#: Ctrl during a band as "add to the existing selection" too, so a Ctrl-drag
#: does both at once. That reads as one gesture rather than two ("add
#: everything I brush"), which is why it can carry both. Alt is the one
#: modifier with no other job here, for anyone who wants them separate.
RUBBER_BAND_INVERT_KEYS = {
    "ctrl": Qt.ControlModifier,
    "alt": Qt.AltModifier,
    "shift": Qt.ShiftModifier,
    "none": Qt.NoModifier,
}
DEFAULT_RUBBER_BAND_INVERT_KEY = "ctrl"

#: The key that carries each modifier, so a press or release *during* a drag
#: can be read as the modifier going down or coming up. A key event's own
#: modifiers() is no help for the key being pressed — whether it already
#: counts itself varies — so the key is what says which way this went.
_MODIFIER_KEYS = {
    Qt.Key_Control: Qt.ControlModifier,
    Qt.Key_Alt: Qt.AltModifier,
    Qt.Key_Shift: Qt.ShiftModifier,
}

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
        self._rubber_band_mode = DEFAULT_RUBBER_BAND_MODE
        self._rubber_band_invert_key = DEFAULT_RUBBER_BAND_INVERT_KEY
        # a drag running under the held-modifier override, so the release
        # knows to put the standing mode back
        self._rubber_band_inverted = False
        # the frames a band in progress found already selected (see
        # _drop_grazed_frames); empty between drags
        self._band_held_frames: frozenset = frozenset()
        self._apply_rubber_band_mode()
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
        banding = (event.button() == Qt.LeftButton
                   and self.dragMode() == QGraphicsView.RubberBandDrag)
        if banding:
            self._sync_rubber_band_override(
                self._invert_key_held(event.modifiers()))
        super().mousePressEvent(event)
        if banding:
            # *after* the press, which is where Qt drops the old selection
            # unless a modifier says to keep it — so this holds what the band
            # is adding to, and nothing it is replacing
            self._band_held_frames = frozenset(self._selected_frames())

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._panning:
            delta = event.position() - self._pan_last
            self._pan_last = event.position()
            self.translate(delta.x() / self.zoom, delta.y() / self.zoom)
            event.accept()
            return
        # before the base class: the mode has to be right for the selection
        # it is about to build, and the modifier may have moved since the
        # press or since the last move
        if self.dragMode() == QGraphicsView.RubberBandDrag:
            self._sync_rubber_band_override(
                self._invert_key_held(event.modifiers()))
        super().mouseMoveEvent(event)
        # after it: that is the call that (re)builds the band's selection,
        # and this drops the part of it the mode does not want
        if self.effective_rubber_band_mode() == "frames":
            self._drop_grazed_frames()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MiddleButton and self._panning:
            self._panning = False
            self.unsetCursor()
            event.accept()
            return
        super().mouseReleaseEvent(event)
        # after the base class, which is the call that turns the band into a
        # selection — restoring the standing mode first would decide the drag
        # by the setting rather than by the key that was held for it
        if event.button() == Qt.LeftButton:
            self._clear_rubber_band_override()
            self._band_held_frames = frozenset()

    def cancel_pan(self) -> None:
        """Drop a middle-drag pan that never got its release — the graph
        being replaced under it, focus lost mid-drag — so the grab cursor
        doesn't stick. Safe to call when nothing is panning."""
        if self._panning:
            self._panning = False
            self.unsetCursor()

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

    def set_rubber_band_mode(self, mode: str) -> None:
        """What a drag-select has to do to an item to catch it — one of
        RUBBER_BAND_MODES. See the note there for what the three mean."""
        self._rubber_band_mode = (mode if mode in RUBBER_BAND_MODES
                                  else DEFAULT_RUBBER_BAND_MODE)
        self._apply_rubber_band_mode()

    def set_rubber_band_invert_key(self, name: str) -> None:
        """Which modifier, held as a drag-select starts, gives you the other
        mode for that one drag. "none" turns the override off."""
        self._rubber_band_invert_key = (
            name if name in RUBBER_BAND_INVERT_KEYS
            else DEFAULT_RUBBER_BAND_INVERT_KEY)

    def effective_rubber_band_mode(self) -> str:
        """The rule the band in progress is actually going by — the setting,
        or its opposite while the invert modifier is being held. Holding it
        means "everything I brush" from either of the two stricter modes, and
        "only what I go right round" from the loosest."""
        if not self._rubber_band_inverted:
            return self._rubber_band_mode
        return "contain" if self._rubber_band_mode == "touch" else "touch"

    def _apply_rubber_band_mode(self, inverted: bool = False) -> None:
        self._rubber_band_inverted = inverted
        # "frames" rides on Qt's touch rule and drops the frames the band
        # failed to swallow afterwards (see _drop_grazed_frames) — Qt itself
        # has no per-item-kind setting.
        self.setRubberBandSelectionMode(
            Qt.ContainsItemShape
            if self.effective_rubber_band_mode() == "contain"
            else Qt.IntersectsItemShape)

    def _selected_frames(self) -> list:
        scene = self.scene()
        if scene is None:
            return []
        from .frame_item import FrameItem

        return [item for item in scene.selectedItems()
                if isinstance(item, FrameItem)]

    def _drop_grazed_frames(self) -> None:
        """Take back the frames the band only grazed, leaving everything else
        Qt selected alone. Runs after each move of a band in "frames" mode:
        Qt rebuilds the whole selection on every move, so the last word is
        always this one's.

        Frames that were already selected when the band started are left
        alone — a Ctrl-drag adds to a selection, and taking back something
        the band never claimed would be a deselect nobody asked for."""
        band = self.rubberBandRect()
        if band.isNull():
            return
        scene = self.scene()
        if scene is None:
            return
        from .frame_item import FrameItem

        area = self.mapToScene(band).boundingRect()
        for item in scene.selectedItems():
            if (isinstance(item, FrameItem)
                    and item not in self._band_held_frames
                    and not area.contains(item.sceneBoundingRect())):
                item.setSelected(False)

    def _sync_rubber_band_override(self, held: bool) -> bool:
        """Point the band at the rule the modifier currently asks for, and
        say whether that changed anything.

        Tracked for as long as the band is being drawn rather than settled at
        the press: pressing the key half way through a drag is how you ask to
        see what the other rule would catch, and letting go is how you take it
        back, so the band has to answer while you hold it."""
        if held == self._rubber_band_inverted:
            return False
        self._apply_rubber_band_mode(inverted=held)
        return True

    def _invert_key_held(self, modifiers) -> bool:
        key = RUBBER_BAND_INVERT_KEYS.get(self._rubber_band_invert_key,
                                          Qt.NoModifier)
        return key != Qt.NoModifier and bool(modifiers & key)

    def _band_is_live(self) -> bool:
        return (self.dragMode() == QGraphicsView.RubberBandDrag
                and not self.rubberBandRect().isNull())

    def _rebuild_band_selection(self, modifiers) -> None:
        """Re-decide what the band currently covers, without waiting for the
        mouse to move.

        Qt only recomputes a rubber band's selection on a mouse move, so a
        key pressed while the pointer is held still would otherwise do
        nothing visible until you jiggled the mouse. This is the same call Qt
        makes from its own move handler — including its rule that Ctrl or
        Shift adds rather than replaces — so a band that is re-decided by the
        key and one that is re-decided by the next move agree."""
        band = self.rubberBandRect()
        scene = self.scene()
        if band.isNull() or scene is None:
            return
        path = QPainterPath()
        path.addPolygon(self.mapToScene(band))
        adding = bool(modifiers & (Qt.ControlModifier | Qt.ShiftModifier))
        scene.setSelectionArea(
            path,
            Qt.AddToSelection if adding else Qt.ReplaceSelection,
            self.rubberBandSelectionMode(),
            self.viewportTransform())
        if self.effective_rubber_band_mode() == "frames":
            self._drop_grazed_frames()

    def _modifier_changed_mid_band(self, event: QKeyEvent,
                                   pressed: bool) -> None:
        """A modifier went down or came up. If it is the invert key and a
        band is being drawn, flip the rule and re-decide there and then."""
        modifier = _MODIFIER_KEYS.get(event.key())
        if modifier is None or not self._band_is_live():
            return
        if not self._invert_key_held(modifier):
            return
        if self._sync_rubber_band_override(pressed):
            # the modifiers as they are *after* this key event, which is what
            # decides add-vs-replace on the rebuild
            modifiers = event.modifiers() | modifier if pressed \
                else event.modifiers() & ~modifier
            self._rebuild_band_selection(modifiers)

    def _clear_rubber_band_override(self) -> None:
        if self._rubber_band_inverted:
            self._apply_rubber_band_mode()

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
        # The span only needs fitting when there are bars to keep proportional;
        # with them off it stays world-sized so a drag pan is never walled in
        # at the edge of the flow (see ContentFittedSceneRect.set_rect_fitted).
        scene = self.scene()
        if hasattr(scene, "set_rect_fitted"):
            scene.set_rect_fitted(show)

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
        if not event.isAutoRepeat():
            self._modifier_changed_mid_band(event, pressed=True)
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key_Space and not event.isAutoRepeat():
            self._end_space_pan()
            event.accept()
            return
        if not event.isAutoRepeat():
            self._modifier_changed_mid_band(event, pressed=False)
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
        from .grid import grid_step, grid_visible
        if not grid_visible(self.scene()):
            return  # grid hidden; snapping (a scene preference) is untouched
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
