"""The grid's two mouse gestures beyond clicking: the fill handle, and
dragging rows or columns by their headers.

**Fill handle.** The selection has an outline and, at its bottom-right
corner, a small square — Excel's fill handle. Hover it for a crosshair; drag
it down, up, left or right and a dashed outline shows where the fill will
go, with a tooltip of what lands in the last cell. Let go and the cells fill
by Excel's AutoFill rules (core/sheet/fill.py), as one undo step. Hold Ctrl
to make a lone number count rather than copy. Dragging past the last row or
column grows the table; near the edge of the grid it scrolls.

**Drag to move.** Select whole rows or columns (click their numbers or
names), then drag one of the selected headers: an open hand says it can be
picked up, a line shows where they will land, and they move there on
release. A drag that starts on a header that is *not* selected still selects
a range, as it always has.

Both draw on one transparent overlay laid over the whole grid widget —
headers and frozen panes included, so the outline and the handle run across
frozen cells and the drop line crosses the header strip — and both listen
through event filters on the grid's own widgets (its viewport and each
frozen pane's), never on the application. Positions are grid coordinates:
the view widget's own (SpreadsheetView.cells_grid_rect).
"""
from __future__ import annotations

import math
from typing import Optional

from PySide6.QtCore import QEvent, QObject, QPoint, QPointF, QRect, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPen, QPolygonF, QRegion
from PySide6.QtWidgets import QApplication, QToolTip, QWidget

_OUTLINE = QColor("#60a5fa")
_HANDLE = 7          # the square's side, in px
_GRAB = 5            # how far round it still counts as on it
_EDGE = 18           # how close to the grid's edge a drag starts scrolling


class _Overlay(QWidget):
    """Draws over the whole grid — cells, frozen panes and headers — and
    lets every click through."""

    def __init__(self, view) -> None:
        super().__init__(view)
        self._view = view
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.fill_target: Optional[tuple] = None
        # ("row"|"col", pixel in grid coordinates, the header it crosses)
        self.drop_line: Optional[tuple] = None

    def paintEvent(self, _event) -> None:
        view = self._view
        if view.sheet_model() is None:
            return
        painter = QPainter(self)
        cells = view.cells_area()
        if self.drop_line is not None:
            self._paint_drop_line(painter, cells)
        painter.setClipRect(cells)
        rect = view.selection_grid_rect()
        if rect is not None and view.editable:
            painter.setPen(QPen(_OUTLINE, 2))
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(rect.adjusted(0, 0, -1, -1))
            handle = view.fill_handle_grid_rect()
            if handle is not None:
                painter.setClipping(False)     # it may overhang the edge
                painter.setPen(QPen(QColor("#1b1c20"), 1))
                painter.setBrush(_OUTLINE)
                painter.drawRect(handle)
                painter.setClipRect(cells)
        if self.fill_target is not None:
            target = view.cells_grid_rect(*self.fill_target)
            if target is not None:
                pen = QPen(QColor("#93c5fd"), 1.5, Qt.DashLine)
                painter.setPen(pen)
                painter.setBrush(Qt.NoBrush)
                painter.drawRect(target.adjusted(0, 0, -1, -1))

    def _paint_drop_line(self, painter: QPainter, cells: QRect) -> None:
        """The line where dragged rows or columns will land: through the
        header strip as well as the cells, with a marker in the header."""
        kind, at, header = self.drop_line
        strip = QRect(header.viewport().mapTo(self._view, QPoint(0, 0)),
                      header.viewport().size())
        painter.save()
        painter.setClipRegion(QRegion(cells).united(QRegion(strip)))
        painter.setPen(QPen(_OUTLINE, 3))
        if kind == "col":
            painter.drawLine(at, strip.top(), at, cells.bottom())
            tip = QPointF(at, strip.top() + 7)
            marker = QPolygonF([tip + QPointF(-5, -6), tip + QPointF(5, -6),
                                tip])
        else:
            painter.drawLine(strip.left(), at, cells.right(), at)
            tip = QPointF(strip.left() + 7, at)
            marker = QPolygonF([tip + QPointF(-6, -5), tip + QPointF(-6, 5),
                                tip])
        painter.setPen(Qt.NoPen)
        painter.setBrush(_OUTLINE)
        painter.drawPolygon(marker)
        painter.restore()


class FillHandle(QObject):
    """The fill-handle gesture, on one SpreadsheetView's viewport."""

    def __init__(self, view) -> None:
        super().__init__(view)
        self._view = view
        self.overlay = _Overlay(view)
        self._source: Optional[tuple] = None
        self._last_pos: Optional[QPoint] = None
        self._grabbed = None        # the viewport the handle was taken on
        self._scroll = QTimer(self)
        self._scroll.setInterval(40)
        self._scroll.timeout.connect(self._auto_scroll)
        self._watched: list = []
        self.watch(view.viewport())
        view.installEventFilter(self)       # to follow the grid's size
        self.overlay.resize(view.size())
        self.overlay.show()

    def watch(self, viewport) -> None:
        """Take the handle's clicks on `viewport` too — a frozen pane's."""
        if viewport in self._watched:
            return
        self._watched.append(viewport)
        viewport.setMouseTracking(True)
        viewport.installEventFilter(self)
        viewport.destroyed.connect(
            lambda _=None, v=viewport: self._watched.remove(v)
            if v in self._watched else None)

    @property
    def dragging(self) -> bool:
        return self._source is not None

    def refresh(self) -> None:
        overlay = self.overlay
        if overlay.size() != self._view.size():
            overlay.resize(self._view.size())
        overlay.raise_()
        overlay.update()

    def _grid_pos(self, watched, event) -> QPoint:
        return watched.mapTo(self._view, event.position().toPoint())

    # ------------------------------------------------------------- events

    def eventFilter(self, watched, event) -> bool:
        kind = event.type()
        if watched is self._view:
            if kind in (QEvent.Resize, QEvent.LayoutRequest):
                self.refresh()
            return False
        if kind == QEvent.MouseButtonPress:
            pos = self._grid_pos(watched, event)
            if (event.button() == Qt.LeftButton and self._view.editable
                    and self._on_handle(pos)):
                self._source = self._view._selection_rect()
                self._last_pos = pos
                self._grabbed = watched
                watched.setCursor(Qt.CrossCursor)
                return True
            return False
        if kind == QEvent.MouseMove:
            pos = self._grid_pos(watched, event)
            if self.dragging:
                self._last_pos = pos
                self._update_target(pos)
                self._check_scroll(pos)
                return True
            if not event.buttons():
                on = self._view.editable and self._on_handle(pos)
                if on:
                    watched.setCursor(Qt.CrossCursor)
                elif watched.cursor().shape() == Qt.CrossCursor:
                    watched.unsetCursor()
            return False
        if kind == QEvent.MouseButtonRelease and self.dragging:
            series = bool(event.modifiers() & Qt.ControlModifier)
            self._finish(series)
            return True
        return False

    def _on_handle(self, pos: QPoint) -> bool:
        handle = self._view.fill_handle_grid_rect()
        return handle is not None and handle.adjusted(
            -_GRAB, -_GRAB, _GRAB, _GRAB).contains(pos)

    # -------------------------------------------------------------- drag

    def _cell_at(self, grid_pos: QPoint) -> tuple[int, int]:
        """The row and column under `grid_pos` — over a frozen pane too, and
        past the end of the grid, the rows and columns a fill there would
        add."""
        view = self._view
        model = view.sheet_model()
        n_rows, n_cols = model.rowCount(), model.columnCount()
        origin = view._viewport_origin()
        pos = grid_pos - origin
        frozen_row = frozen_col = -1
        if pos.y() < 0 and view._frozen_rows():
            pane = view._frozen_pane("rows") or view._frozen_pane("corner")
            frozen_row = pane.rowAt(
                (grid_pos - view._viewport_origin(pane)).y())
        if pos.x() < 0 and view._frozen_cols():
            pane = view._frozen_pane("cols") or view._frozen_pane("corner")
            frozen_col = pane.columnAt(
                (grid_pos - view._viewport_origin(pane)).x())
        row, col = self._main_cell_at(pos, n_rows, n_cols)
        return (frozen_row if frozen_row >= 0 else row,
                frozen_col if frozen_col >= 0 else col)

    def _main_cell_at(self, pos: QPoint, n_rows: int, n_cols: int
                      ) -> tuple[int, int]:
        view = self._view
        row = view.rowAt(pos.y())
        if row < 0:
            if pos.y() < 0:
                row = view.rowAt(0)
            else:
                last = n_rows - 1
                bottom = view.rowViewportPosition(last) + view.rowHeight(last)
                height = view.verticalHeader().defaultSectionSize() or 22
                row = last + max(1, math.ceil((pos.y() - bottom) / height))
        col = view.columnAt(pos.x())
        if col < 0:
            if pos.x() < 0:
                col = view.columnAt(0)
            else:
                last = n_cols - 1
                right = (view.columnViewportPosition(last)
                         + view.columnWidth(last))
                width = view.horizontalHeader().defaultSectionSize() or 72
                col = last + max(1, math.ceil((pos.x() - right) / width))
        return max(row, 0), max(col, 0)

    def _target_for(self, pos: QPoint) -> Optional[tuple]:
        r0, c0, r1, c1 = self._source
        row, col = self._cell_at(pos)
        down = row - r1 if row > r1 else (row - r0 if row < r0 else 0)
        across = col - c1 if col > c1 else (col - c0 if col < c0 else 0)
        if not down and not across:
            return None
        if abs(down) >= abs(across):
            return (min(r0, row), c0, max(r1, row), c1)
        return (r0, min(c0, col), r1, max(c1, col))

    def _update_target(self, pos: QPoint) -> None:
        target = self._target_for(pos)
        self.overlay.fill_target = target
        self.overlay.update()
        if target is None:
            QToolTip.hideText()
            return
        text = self._preview(target)
        if text is not None:
            from ..data_table import show_tooltip
            show_tooltip(self._view.mapToGlobal(pos + QPoint(14, 10)),
                         text or "(blank)", self._view.viewport())

    def _preview(self, target: tuple) -> Optional[str]:
        """What the last cell of the fill will hold — Excel's tooltip."""
        from flograph.core.sheet.fill import fill_values
        model = self._view.sheet_model()
        r0, c0, r1, c1 = self._source
        t0, tc0, t1, tc1 = target
        series = bool(QApplication.keyboardModifiers() & Qt.ControlModifier)
        if t1 > r1 or t0 < r0:
            down = t1 > r1
            seed = [model.cell_source(r, c0) for r in range(r0, r1 + 1)]
            count = (t1 - r1) if down else (r0 - t0)
            if not down:
                seed.reverse()
            values = fill_values(seed, count, along="row",
                                 backwards=not down, series=series)
        else:
            right = tc1 > c1
            seed = [model.cell_source(r0, c) for c in range(c0, c1 + 1)]
            count = (tc1 - c1) if right else (c0 - tc0)
            if not right:
                seed.reverse()
            values = fill_values(seed, count, along="col",
                                 backwards=not right, series=series)
        return values[-1] if values else None

    def _check_scroll(self, grid_pos: QPoint) -> None:
        viewport = self._view.viewport()
        pos = grid_pos - self._view._viewport_origin()
        near = (pos.y() > viewport.height() - _EDGE or pos.y() < _EDGE
                or pos.x() > viewport.width() - _EDGE or pos.x() < _EDGE)
        if near and not self._scroll.isActive():
            self._scroll.start()
        elif not near:
            self._scroll.stop()

    def _auto_scroll(self) -> None:
        if not self.dragging or self._last_pos is None:
            self._scroll.stop()
            return
        view = self._view
        pos = self._last_pos - view._viewport_origin()
        viewport = view.viewport()
        vbar, hbar = view.verticalScrollBar(), view.horizontalScrollBar()
        step_v = max(vbar.singleStep(), 8)
        step_h = max(hbar.singleStep(), 8)
        if pos.y() > viewport.height() - _EDGE:
            vbar.setValue(vbar.value() + step_v)
        elif pos.y() < _EDGE:
            vbar.setValue(vbar.value() - step_v)
        if pos.x() > viewport.width() - _EDGE:
            hbar.setValue(hbar.value() + step_h)
        elif pos.x() < _EDGE:
            hbar.setValue(hbar.value() - step_h)
        self._update_target(self._last_pos)

    def _finish(self, series: bool) -> None:
        self._scroll.stop()
        QToolTip.hideText()
        view = self._view
        target = self.overlay.fill_target
        source = self._source
        self._source = None
        self.overlay.fill_target = None
        self._release_cursor()
        if target is not None and source is not None:
            model = view.sheet_model()
            model.fill_range(source, target, series=series)
            view._select_block(*target)
            view.scrollTo(model.index(target[2], target[3]))
        self.refresh()

    def cancel(self) -> None:
        if self.dragging:
            self._source = None
            self._scroll.stop()
            self.overlay.fill_target = None
            QToolTip.hideText()
            self._release_cursor()
            self.refresh()

    def _release_cursor(self) -> None:
        grabbed = getattr(self, "_grabbed", None)
        self._grabbed = None
        for widget in (grabbed, self._view.viewport()):
            if widget is not None:
                widget.unsetCursor()


class HeaderMove(QObject):
    """Drag selected rows (or columns) by their header to move them."""

    def __init__(self, view, header, kind: str) -> None:
        super().__init__(header)
        self._view = view
        self._header = header
        self._kind = kind              # "row" or "col"
        self._press: Optional[QPoint] = None
        self._picked: list[int] = []
        self._gap: Optional[int] = None
        header.viewport().setMouseTracking(True)
        header.viewport().installEventFilter(self)

    def _selected(self) -> list[int]:
        view = self._view
        if self._kind == "row":
            return view.selected_rows() if view.whole_rows_selected() else []
        return (view.selected_columns() if view.whole_columns_selected()
                else [])

    def _pos(self, event) -> QPoint:
        return event.position().toPoint()

    def _along(self, pos: QPoint) -> int:
        return pos.y() if self._kind == "row" else pos.x()

    def eventFilter(self, watched, event) -> bool:
        kind = event.type()
        view = self._view
        if kind == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
            section = self._header.logicalIndexAt(self._pos(event))
            picked = self._selected()
            if (view.editable and section >= 0 and section in picked
                    and not self._on_button(self._pos(event))
                    and not event.modifiers() & (Qt.ShiftModifier
                                                 | Qt.ControlModifier)):
                self._press = self._pos(event)
                self._picked = picked
                return True        # held: a move or a plain click, not yet known
            return False
        if kind == QEvent.MouseMove:
            pos = self._pos(event)
            if self._press is not None:
                if (self._gap is None and (pos - self._press).manhattanLength()
                        < QApplication.startDragDistance()):
                    return True
                self._gap = self._gap_at(pos)
                watched.setCursor(Qt.ClosedHandCursor)
                self._show_line()
                return True
            if not event.buttons():
                section = self._header.logicalIndexAt(pos)
                if (view.editable and section >= 0
                        and section in self._selected()
                        and not self._on_button(pos)):
                    watched.setCursor(Qt.OpenHandCursor)
                elif watched.cursor().shape() in (Qt.OpenHandCursor,
                                                  Qt.ClosedHandCursor):
                    watched.unsetCursor()
            return False
        if kind == QEvent.MouseButtonRelease and self._press is not None:
            gap, picked = self._gap, self._picked
            section = self._header.logicalIndexAt(self._pos(event))
            self._press, self._gap, self._picked = None, None, []
            watched.unsetCursor()
            view.drop_line(None)
            if gap is None:
                # a plain click on a selected header: just that one, as a
                # click on any header does
                if section >= 0:
                    (view.select_rows if self._kind == "row"
                     else view.select_columns)([section])
                return True
            self._move(picked, gap)
            return True
        return False

    def _on_button(self, pos: QPoint) -> bool:
        button_at = getattr(self._header, "_button_at", None)
        return bool(button_at and button_at(pos) >= 0)

    def _gap_at(self, pos: QPoint) -> int:
        """The gap between sections the pointer is nearest: 0 is before the
        first, n after the last."""
        header = self._header
        along = self._along(pos)
        section = header.logicalIndexAt(pos)
        count = header.count()
        if section < 0:
            if along <= 0:
                return next((i for i in range(count)
                             if not header.isSectionHidden(i)), 0)
            return count
        start = header.sectionViewportPosition(section)
        middle = start + header.sectionSize(section) / 2
        return section if along < middle else section + 1

    def _show_line(self) -> None:
        view, header, gap = self._view, self._header, self._gap
        count = header.count()
        if gap >= count:
            last = max((i for i in range(count)
                        if not header.isSectionHidden(i)), default=0)
            at = header.sectionViewportPosition(last) + header.sectionSize(
                last)
        else:
            at = header.sectionViewportPosition(gap)
        origin = header.viewport().mapTo(view, QPoint(0, 0))
        at += origin.y() if self._kind == "row" else origin.x()
        view.drop_line((self._kind, at, header))

    def _move(self, picked: list[int], gap: int) -> None:
        view = self._view
        before = sum(1 for i in picked if i < gap)
        to = gap - before
        if picked == list(range(picked[0], picked[0] + len(picked))) and \
                to == picked[0]:
            return                 # dropped where they already are
        model = view.sheet_model()
        moved = list(range(to, to + len(picked)))
        if self._kind == "row":
            model.move_rows(picked, to)
            view.select_rows(moved)
        else:
            model.move_columns(picked, to)
            view.select_columns(moved)
