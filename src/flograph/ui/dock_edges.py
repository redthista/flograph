"""Edge strips: collapse or resize a whole side of the canvas.

An open edge is resized by Qt's own dock separator, styled as a thin
divider line (`[ui] divider`) round the panels -- the border *is* the
handle. Drag that border most of the way to the window's edge and let go,
and the whole edge collapses: its panels close, and in their place a thin
bar, the edge strip, appears at the window's edge. Drag the bar back out
(or double-click it) and the panels return, sized to where the drag ends.
Double-clicking an open edge's border collapses it, the same gesture.

So a strip is only on screen while its edge is collapsed. It used to sit
beside the canvas all the time with grip dots and an arrow button; those
were a second handle a few pixels from the separator, and the arrow was a
12px target for something a drag says better.

Collapsing closes the docks rather than shrinking them. A tabified dock
cannot be made narrower than its own tab bar, which is what made an
earlier custom-rail attempt bottom out at a ~26px strip of rotated
labels; closed is 0px and needs no custom layout code at all.

A strip takes its whole edge down together, because that is the unit
people want out of the way -- the right-hand side is a tab group, and
closing it a tab at a time is not collapsing. A panel's own X still
closes just that panel. What was open at collapse time is remembered, so
restoring does not resurrect something dismissed before the edge fell.

Which docks belong to a strip is asked of the dock host every time rather
than fixed when the window is built: restoreState() can put a dock back
on a different edge than the one it was created on (a layout saved before
Log moved to the right restores Log to the bottom), and dragging one
there does the same. A strip that trusted its build-time list would
collapse an edge and leave a stranger behind on it.

"Open" means "not QDockWidget.isHidden()". Verified rather than assumed,
because the obvious worry is tab groups: Qt reports a tabified dock that
is merely *behind* another tab as visible and un-hidden, so a group
counts as open while any of its tabs remain.
"""
from __future__ import annotations

import shiboken6
from PySide6.QtCore import QEvent, QObject, QPoint, QRect, Qt, QTimer
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QDockWidget, QHBoxLayout, QMainWindow, QSizePolicy, QVBoxLayout, QWidget,
)
from flograph.ui import theme as _theme  # noqa: E402

#: how thick a collapsed edge's bar is -- enough to grab, little enough
#: that a collapsed edge costs the canvas next to nothing
_STRIP_THICKNESS = 8
#: the left and right bars sit at the window's own edge, under the
#: frameless window's resize grips (window_frame.RESIZE_MARGIN, 6px), which
#: are laid over the window and take the mouse first. A bar no wider than
#: the grip could not be grabbed at all -- a drag resized the window -- so
#: those bars are the grip's width plus a grabbable strip of their own.
_UNDER_GRIP = 6


def _line() -> int:
    """How thick the divider line round the panels is: the theme's
    `[style] divider_width` (Qt's separators, and a collapsed bar's line)."""
    return int(_theme.style("divider_width"))

#: a border let go this close to the window's edge collapses that edge;
#: a collapsed bar dragged out less than this stays collapsed
_COLLAPSE_AT = 60
#: smallest an edge is sized to when a drag brings it back
_MIN_DOCK_SIZE = 80

_AREAS = {
    "left": Qt.LeftDockWidgetArea,
    "right": Qt.RightDockWidgetArea,
    "bottom": Qt.BottomDockWidgetArea,
}


class PanelRule(QWidget):
    """A straight line across the window in the divider's colour and
    thickness: the one under the page tabs, so the strip of tabs is told from
    the canvas by the same line that tells panels apart. Drawn here rather
    than borrowed from a neighbour's frame, which `theme._app_stylesheet`
    removes. It re-reads the theme, so a switch (or a changed
    `divider_width`) reaches it with no re-wiring."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("panel_rule")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        _theme.on_change(self._restyle)
        self._restyle()

    def _restyle(self) -> None:
        try:
            self.setFixedHeight(max(0, _line()))
            self.update()
        except RuntimeError:
            pass                     # deleted with a replaced layout

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), _theme.color("ui", "divider"))
        painter.end()


class EdgeStrip(QWidget):
    """The way back for one collapsed edge, and that edge's collapse and
    restore logic. Hidden while the edge is open."""

    def __init__(self, side: str, docks: list[QDockWidget],
                 host: QMainWindow, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._side = side
        self._area = _AREAS[side]
        # every dock that could live on any edge -- membership of *this*
        # edge is worked out live, see _members()
        self._candidates = list(docks)
        self._host = host
        self._enabled = True
        # what to put back: the docks open when this edge was collapsed, so
        # restoring doesn't resurrect one closed by its own X before that
        self._restore: list[QDockWidget] = []
        # in-flight drag out of the collapsed bar: the starting mouse
        # position along the drag axis
        self._drag: int | None = None

        if side == "bottom":
            self.setFixedHeight(_STRIP_THICKNESS)
            self.setCursor(Qt.SplitVCursor)
        else:
            self.setFixedWidth(_STRIP_THICKNESS + _UNDER_GRIP)
            self.setCursor(Qt.SplitHCursor)
        # lit while the mouse is over it: a collapsed edge is a thin line,
        # and this says "this is the handle" before anyone has to guess
        self._hover = False
        self.setAttribute(Qt.WA_Hover, True)

        # ShowToParent/HideToParent rather than the more obvious
        # visibilityChanged: that signal only fires once the top-level
        # window is actually on screen, so an edge collapsed before then
        # would leave its strip in the wrong state (and it fires a spurious
        # extra False after a show). These two arrive either way, and
        # isHidden() already reads correctly by the time they do.
        for dock in self._candidates:
            dock.installEventFilter(self)
        self.refresh()

    def eventFilter(self, watched, event) -> bool:
        if event.type() in (QEvent.Type.ShowToParent,
                            QEvent.Type.HideToParent):
            self.refresh()
        return super().eventFilter(watched, event)

    @property
    def side(self) -> str:
        return self._side

    # ---------------------------------------------------------- membership

    def _members(self) -> list[QDockWidget]:
        """The docks sitting on this edge right now. Floating ones are
        excluded even though dockWidgetArea() still reports the area they
        came from -- a torn-off panel is its own window and collapsing an
        edge has no business closing it.

        isValid() guards the teardown window: closing the app deletes the
        docks while events are still in flight, and a filter that fires
        after that would touch freed C++ objects.
        """
        if not shiboken6.isValid(self._host):
            return []
        return [dock for dock in self._candidates
                if shiboken6.isValid(dock)
                and not dock.isFloating()
                and self._host.dockWidgetArea(dock) == self._area]

    def docks(self) -> list[QDockWidget]:
        return self._members()

    def open_docks(self) -> list[QDockWidget]:
        return [dock for dock in self._members() if not dock.isHidden()]

    def is_collapsed(self) -> bool:
        members = self._members()
        return bool(members) and all(dock.isHidden() for dock in members)

    # ------------------------------------------------------ collapse/expand

    def toggle(self) -> None:
        self.expand() if self.is_collapsed() else self.collapse()

    def collapse(self) -> None:
        self._restore = self.open_docks()
        for dock in self._restore:
            dock.close()

    def expand(self) -> None:
        """Restore what was open when this edge came down, falling back to
        the whole edge when there is nothing remembered -- someone who
        closed every panel by hand and then dragged the bar out wants them
        back, not a bar that does nothing."""
        targets = [dock for dock in (self._restore or self._members())
                   if dock in self._members()]
        if not targets:
            return
        for dock in targets:
            dock.show()
        targets[0].raise_()
        self._restore = []

    def set_enabled(self, enabled: bool) -> None:
        """Dashboard and report pages hide every model-only dock on purpose,
        so their edges have nothing to bring back and a bar would only be
        noise on a page the panels don't belong to."""
        self._enabled = enabled
        self.refresh()

    def refresh(self) -> None:
        members = self._members()
        names = ", ".join(dock.windowTitle() for dock in members)
        self.setToolTip(f"Drag out or double-click to show {names}")
        # on screen only while there is a collapsed edge to bring back --
        # and for the rest of a drag that has already brought it back, or
        # hiding it would drop the mouse grab mid-gesture
        self.setVisible(self._enabled and bool(members)
                        and (self.is_collapsed() or self._drag is not None))
        self.update()

    # -------------------------------------------------------------- drawing

    def paintEvent(self, event) -> None:
        """The divider line on the canvas side, on the window colour: the
        same border the open edge had, left behind where it folded away."""
        painter = QPainter(self)
        painter.fillRect(self.rect(), _theme.color("ui", "window"))
        if self._hover or self._drag is not None:
            glow = QColor(_theme.color("ui", "divider"))
            glow.setAlpha(110)
            painter.fillRect(self.rect(), glow)
        line = _theme.color("ui", "divider")
        w, h = self.width(), self.height()
        if self._side == "left":
            painter.fillRect(QRect(w - _line(), 0, _line(), h), line)
        elif self._side == "right":
            painter.fillRect(QRect(0, 0, _line(), h), line)
        else:
            painter.fillRect(QRect(0, 0, w, _line()), line)
        painter.end()

    # ------------------------------------------------------------ resizing

    def _sizing_dock(self) -> QDockWidget | None:
        """The dock resizeDocks() should be pointed at. Any open member of a
        tab group will do -- they share one geometry -- but it has to be an
        open one, since a closed dock has no size to grow from."""
        open_docks = self.open_docks()
        return open_docks[0] if open_docks else None

    def enterEvent(self, event) -> None:
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hover = False
        self.update()
        super().leaveEvent(event)

    def _along(self, event) -> int:
        pos = event.globalPosition().toPoint()
        return pos.y() if self._side == "bottom" else pos.x()

    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.LeftButton or not self.is_collapsed():
            super().mousePressEvent(event)
            return
        self._drag = self._along(event)
        event.accept()

    def mouseMoveEvent(self, event) -> None:
        if self._drag is None:
            super().mouseMoveEvent(event)
            return
        now = self._along(event)
        # the left edge comes out as the mouse moves right; the right and
        # bottom edges as it moves the other way, towards the canvas
        out = now - self._drag if self._side == "left" else self._drag - now
        if out < _COLLAPSE_AT:
            if not self.is_collapsed():
                self.collapse()          # pushed back in: fold it again
        else:
            if self.is_collapsed():
                self.expand()
            dock = self._sizing_dock()
            if dock is not None:
                self._host.resizeDocks(
                    [dock], [max(_MIN_DOCK_SIZE, out)],
                    Qt.Vertical if self._side == "bottom" else Qt.Horizontal)
        event.accept()

    def mouseReleaseEvent(self, event) -> None:
        self._drag = None
        self.refresh()
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        """Double-clicking the bar brings the edge back -- a gesture for
        someone who would rather not drag."""
        if event.button() != Qt.LeftButton:
            super().mouseDoubleClickEvent(event)
            return
        # the press that opened this double-click armed a drag; drop it, or
        # the next stray move would resize from a stale origin
        self._drag = None
        self.expand()
        self.refresh()
        event.accept()


class _BorderWatcher(QObject):
    """Watches drags on the dock host's own separators -- the borders round
    the panels -- and collapses an edge whose border is let go close to the
    window's edge. Qt clamps the dock at its minimum size while the mouse
    goes on past it, so the *mouse* position is what says how far the drag
    meant to go. Never consumes an event: Qt's own resize carries on."""

    def __init__(self, host: QMainWindow, strips: dict[str, EdgeStrip]):
        super().__init__(host)
        self._host = host
        self._strips = strips
        self._side: str | None = None

    def side_at(self, pos: QPoint) -> str | None:
        """Which edge's border is under `pos` (host coordinates), if any."""
        slack = _line() + 3
        inside = self._host.rect()
        for side, strip in self._strips.items():
            # a tab parked behind another reports a stale geometry off in
            # negative space; only the docks actually laid out count
            docks = [dock for dock in strip.open_docks()
                     if inside.contains(dock.geometry())]
            if not docks:
                continue
            area = QRect(docks[0].geometry())
            for dock in docks[1:]:
                area = area.united(dock.geometry())
            if side == "left":
                edge = area.x() + area.width()
                hit = (edge - 1 <= pos.x() <= edge + slack
                       and area.top() <= pos.y() <= area.bottom())
            elif side == "right":
                hit = (area.x() - slack <= pos.x() <= area.x()
                       and area.top() <= pos.y() <= area.bottom())
            else:
                hit = (area.y() - slack <= pos.y() <= area.y()
                       and area.left() <= pos.x() <= area.right())
            if hit:
                return side
        return None

    def near_edge(self, side: str, pos: QPoint) -> bool:
        """Whether `pos` is close enough to `side`'s window edge that a
        border let go there means "put this edge away"."""
        if side == "left":
            return pos.x() < _COLLAPSE_AT
        if side == "right":
            return self._host.width() - pos.x() < _COLLAPSE_AT
        return self._host.height() - pos.y() < _COLLAPSE_AT

    def eventFilter(self, watched, event) -> bool:
        kind = event.type()
        if kind == QEvent.Type.MouseButtonPress:
            self._side = (self.side_at(event.position().toPoint())
                          if event.button() == Qt.LeftButton else None)
        elif kind == QEvent.Type.MouseButtonRelease and self._side:
            side, self._side = self._side, None
            if self.near_edge(side, event.position().toPoint()):
                # after Qt has finished its own separator move
                QTimer.singleShot(0, self._strips[side].collapse)
        elif kind == QEvent.Type.MouseButtonDblClick \
                and event.button() == Qt.LeftButton:
            side = self.side_at(event.position().toPoint())
            self._side = None
            if side:
                QTimer.singleShot(0, self._strips[side].collapse)
        return False


def install(canvas: QWidget, host: QMainWindow,
            docks: list[QDockWidget]) -> tuple[QWidget, dict[str, EdgeStrip]]:
    """Wrap `canvas` in a container carrying a strip on each edge.

    The container becomes the dock host's central widget, which puts the
    strips inside the dock area ring -- so a collapsed edge's bar sits at
    the window's edge, where its panels were.

    Every strip is handed every dock and works out its own membership, so
    moving a panel from one edge to another needs no bookkeeping here.
    Qt's own separators are the resize handles, drawn as the divider line
    round the panels, in the theme's colour and re-read on a theme switch.
    """
    base = host.styleSheet() or ""

    def host_qss() -> str:
        return (base + "\nQMainWindow::separator {"
                f" width: {_line()}px; height: {_line()}px;"
                f" background: {_theme.color('ui', 'divider').name()}; }}")

    _theme.set_qss(host, host_qss)
    strips = {side: EdgeStrip(side, docks, host) for side in _AREAS}
    host.installEventFilter(_BorderWatcher(host, strips))

    def resync() -> None:
        for strip in strips.values():
            strip.refresh()

    for dock in docks:
        # bound-ish: a dock outliving the strips would only ever call
        # refresh() on them, and they are owned by the same window
        dock.dockLocationChanged.connect(lambda _area: resync())
        dock.topLevelChanged.connect(lambda _floating: resync())

    middle = QWidget()
    middle_layout = QVBoxLayout(middle)
    middle_layout.setContentsMargins(0, 0, 0, 0)
    middle_layout.setSpacing(0)
    middle_layout.addWidget(canvas, 1)
    middle_layout.addWidget(strips["bottom"])

    container = QWidget()
    layout = QHBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(0)
    layout.addWidget(strips["left"])
    layout.addWidget(middle, 1)
    layout.addWidget(strips["right"])
    return container, strips
