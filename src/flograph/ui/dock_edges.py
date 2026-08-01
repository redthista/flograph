"""Edge strips: collapse or resize a whole side of the canvas.

Each strip is a thin always-there rail between the canvas and one edge's
docks, doing two jobs. Its arrow points outward while that edge is open
(click to collapse it) and inward once it is empty (click to bring it
back) -- the same two-way toggle, and the same reasoning, as
DashboardPage's visuals-panel button: the control has to live outside the
thing it hides. Dragging the strip anywhere else resizes that edge, which
is why Qt's own dock separators are styled to nothing: the strip replaces
them rather than sitting a few pixels away from them, and the grip dots
down its middle are what says so.

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
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import (
    QDockWidget, QHBoxLayout, QMainWindow, QToolButton, QVBoxLayout, QWidget,
)

_STRIP_THICKNESS = 12
# smallest an edge can be dragged to before it is just a nuisance; below
# this, collapsing it outright is what someone actually wants
_MIN_DOCK_SIZE = 80

_AREAS = {
    "left": Qt.LeftDockWidgetArea,
    "right": Qt.RightDockWidgetArea,
    "bottom": Qt.BottomDockWidgetArea,
}

# the arrow points the way the panels will travel: outward to collapse
# them off the edge, back inward to bring them in
_ARROWS = {
    "left": (Qt.ArrowType.LeftArrow, Qt.ArrowType.RightArrow),
    "right": (Qt.ArrowType.RightArrow, Qt.ArrowType.LeftArrow),
    "bottom": (Qt.ArrowType.DownArrow, Qt.ArrowType.UpArrow),
}


class EdgeStrip(QWidget):
    """The collapse toggle and resize handle for one edge of the canvas."""

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
        # in-flight drag: (starting mouse position, starting dock size)
        self._drag: tuple[int, int] | None = None

        self._button = QToolButton(self)
        self._button.setAutoRaise(True)
        self._button.setCursor(Qt.PointingHandCursor)
        self._button.clicked.connect(self.toggle)
        # square and pinned to the strip's own thickness: left to its size
        # hint, the button would ask for more room than a thin strip has
        # and drag the layout wider than _STRIP_THICKNESS
        self._button.setFixedSize(_STRIP_THICKNESS, _STRIP_THICKNESS)

        if side == "bottom":
            layout: QHBoxLayout | QVBoxLayout = QHBoxLayout(self)
            self.setFixedHeight(_STRIP_THICKNESS)
        else:
            layout = QVBoxLayout(self)
            self.setFixedWidth(_STRIP_THICKNESS)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._button)
        layout.addStretch(1)

        # ShowToParent/HideToParent rather than the more obvious
        # visibilityChanged: that signal only fires once the top-level
        # window is actually on screen, so an edge collapsed before then
        # would leave its arrow pointing the wrong way (and it fires a
        # spurious extra False after a show). These two arrive either way,
        # and isHidden() already reads correctly by the time they do.
        for dock in self._candidates:
            dock.installEventFilter(self)
        self.refresh()

    def eventFilter(self, watched, event) -> bool:
        if event.type() in (QEvent.Type.ShowToParent,
                            QEvent.Type.HideToParent):
            self.refresh()
        return super().eventFilter(watched, event)

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

    def is_collapsed(self) -> bool:
        members = self._members()
        return bool(members) and all(dock.isHidden() for dock in members)

    # ------------------------------------------------------ collapse/expand

    def toggle(self) -> None:
        self.expand() if self.is_collapsed() else self.collapse()

    def collapse(self) -> None:
        self._restore = [dock for dock in self._members()
                         if not dock.isHidden()]
        for dock in self._restore:
            dock.close()

    def expand(self) -> None:
        """Restore what was open when this edge came down, falling back to
        the whole edge when there is nothing remembered -- someone who
        closed every panel by hand and then clicked the arrow wants them
        back, not an arrow that does nothing."""
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
        so their edges have nothing to collapse and the arrow would only be
        noise on a page the panels don't belong to."""
        self._enabled = enabled
        self.refresh()

    def refresh(self) -> None:
        members = self._members()
        collapsed = self.is_collapsed()
        outward, inward = _ARROWS[self._side]
        self._button.setArrowType(inward if collapsed else outward)
        names = ", ".join(dock.windowTitle() for dock in members)
        self._button.setToolTip(f"{'Show' if collapsed else 'Hide'} {names}")
        # a collapsed edge has no size to drag, so drop the resize cursor
        # and the grip dots -- they would promise something it can't do
        self.setCursor(Qt.ArrowCursor if collapsed else
                       (Qt.SplitVCursor if self._side == "bottom"
                        else Qt.SplitHCursor))
        # an edge with nothing on it has neither a panel to collapse nor a
        # size to drag; the strip would just be dead chrome
        self.setVisible(self._enabled and bool(members))
        self.update()

    # -------------------------------------------------------------- drawing

    def paintEvent(self, event) -> None:
        """Grip dots down the middle: the strip took over from Qt's dock
        separator, so it has to carry the separator's "you can drag me"
        texture too."""
        if self.is_collapsed():
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(self.palette().mid())
        count, gap, radius = 5, 4.0, 1.4
        centre_x, centre_y = self.width() / 2, self.height() / 2
        span = (count - 1) * gap
        for index in range(count):
            offset = index * gap - span / 2
            point = (QPointF(centre_x + offset, centre_y)
                     if self._side == "bottom"
                     else QPointF(centre_x, centre_y + offset))
            painter.drawEllipse(point, radius, radius)
        painter.end()

    # ------------------------------------------------------------ resizing

    def _sizing_dock(self) -> QDockWidget | None:
        """The dock resizeDocks() should be pointed at. Any open member of a
        tab group will do -- they share one geometry -- but it has to be an
        open one, since a closed dock has no size to grow from."""
        for dock in self._members():
            if not dock.isHidden():
                return dock
        return None

    def _dock_size(self, dock: QDockWidget) -> int:
        return dock.height() if self._side == "bottom" else dock.width()

    def mousePressEvent(self, event) -> None:
        dock = self._sizing_dock()
        if event.button() != Qt.LeftButton or dock is None:
            super().mousePressEvent(event)
            return
        pos = event.globalPosition().toPoint()
        start = pos.y() if self._side == "bottom" else pos.x()
        self._drag = (start, self._dock_size(dock))
        event.accept()

    def mouseMoveEvent(self, event) -> None:
        dock = self._sizing_dock()
        if self._drag is None or dock is None:
            super().mouseMoveEvent(event)
            return
        start, start_size = self._drag
        pos = event.globalPosition().toPoint()
        now = pos.y() if self._side == "bottom" else pos.x()
        # the left edge grows as the mouse moves right; the right and bottom
        # edges grow as it moves the other way, towards the canvas
        delta = now - start if self._side == "left" else start - now
        size = max(_MIN_DOCK_SIZE, start_size + delta)
        self._host.resizeDocks(
            [dock], [size],
            Qt.Vertical if self._side == "bottom" else Qt.Horizontal)
        event.accept()

    def mouseReleaseEvent(self, event) -> None:
        self._drag = None
        super().mouseReleaseEvent(event)


def install(canvas: QWidget, host: QMainWindow,
            docks: list[QDockWidget]) -> tuple[QWidget, dict[str, EdgeStrip]]:
    """Wrap `canvas` in a container carrying a strip on each edge.

    The container becomes the dock host's central widget, which puts the
    strips inside the dock area ring -- so each one sits against the canvas
    at the edge it controls, rather than out at the window border.

    Every strip is handed every dock and works out its own membership, so
    moving a panel from one edge to another needs no bookkeeping here.
    Qt's own separators are flattened to nothing: the strips are the drag
    handles now, and leaving them in would put two grab targets a few
    pixels apart and spend ~5px of canvas on the redundant one.
    """
    host.setStyleSheet(
        (host.styleSheet() or "")
        + "\nQMainWindow::separator { width: 0px; height: 0px; }")
    strips = {side: EdgeStrip(side, docks, host) for side in _AREAS}

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
