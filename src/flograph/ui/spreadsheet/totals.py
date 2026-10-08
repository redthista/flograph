"""The Total Row — Excel's, under the grid.

A strip under the grid holding one total per column: Sum, Average, Count
and the rest of Show Table's totals (core/table_totals.AGGREGATIONS), each
column's own choice. Click a total to change it. Like Excel's SUBTOTAL, a
total counts only the rows a filter leaves showing — the strip says so when
a filter is on. It is a view of the table: never part of what the node
sends on.

It is drawn rather than built from cells, and every column is placed by
the grid's own header geometry, so it follows scrolling, resizing,
moving and frozen panes with nothing of its own to keep in step. Hosts lay
it out directly under the grid (`SpreadsheetView.totals_bar()`).
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QPoint, QRect, QSize, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QToolTip, QWidget

from .. import theme

_HEIGHT = 24
_LINE = QColor("#60a5fa")
_TEXT = QColor("#e5e7eb")
_DIM = QColor("#8b909c")


class TotalsBar(QWidget):
    def __init__(self, view, parent=None) -> None:
        super().__init__(parent)
        self._view = view
        self.setFixedHeight(_HEIGHT)
        self.setMouseTracking(True)
        self.setAttribute(Qt.WA_OpaquePaintEvent, True)
        header = view.horizontalHeader()
        header.sectionResized.connect(self._changed)
        header.sectionMoved.connect(self._changed)
        header.geometriesChanged.connect(self._changed)
        view.horizontalScrollBar().valueChanged.connect(self._changed)
        view.filter_changed.connect(self._changed)
        self._bind(view.sheet_model())
        self._sync_visibility()

    def _bind(self, model) -> None:
        if model is None:
            return
        for signal in (model.dataChanged, model.modelReset,
                       model.totals_changed, model.freeze_changed):
            signal.connect(self._changed)
        model.totals_changed.connect(self._sync_visibility)
        model.modelReset.connect(self._sync_visibility)

    def sizeHint(self) -> QSize:
        return QSize(200, _HEIGHT)

    def _changed(self, *_args) -> None:
        import shiboken6
        if shiboken6.isValid(self):
            self.update()

    def _sync_visibility(self, *_args) -> None:
        import shiboken6
        model = self._view.sheet_model()
        if shiboken6.isValid(self):
            self.setVisible(bool(model is not None and model.show_totals))

    # ----------------------------------------------------------- geometry

    def _label_width(self) -> int:
        view = self._view
        frozen = view.frozen_panes
        if frozen is not None and frozen.active:
            return view.frameWidth() + frozen.base_sizes[0]
        header = view.verticalHeader()
        return view.frameWidth() + (header.width() if header.isVisible()
                                    else 0)

    def column_rects(self) -> list[tuple[int, QRect]]:
        """(column, where its total goes) for every column in view."""
        view, model = self._view, self._view.sheet_model()
        if model is None:
            return []
        out = []
        header = view.horizontalHeader()
        frozen = view.frozen_panes
        left = self._label_width()
        pane = (frozen.panes().get("cols") if frozen is not None
                and frozen.cols else None)
        frozen_width = 0
        if pane is not None:
            for col in range(frozen.cols):
                x = pane.columnViewportPosition(col)
                w = pane.columnWidth(col)
                out.append((col, QRect(left + x, 0, w, self.height())))
                frozen_width = max(frozen_width, x + w)
        start = view.viewport().geometry().left()
        for col in range(model.columnCount()):
            if header.isSectionHidden(col):
                continue
            x = header.sectionViewportPosition(col)
            w = header.sectionSize(col)
            rect = QRect(start + x, 0, w, self.height())
            if rect.right() < start or rect.left() > self.width():
                continue
            out.append((col, rect))
        return out

    def column_at(self, pos: QPoint) -> int:
        for col, rect in self.column_rects():
            if rect.contains(pos):
                return col
        return -1

    def _visible_rows(self) -> Optional[list[int]]:
        view, model = self._view, self._view.sheet_model()
        if model is None or not view.filtered:
            return None
        return [r for r in range(model.rowCount()) if not view.row_filtered(r)]

    # ------------------------------------------------------------- paint

    def paintEvent(self, _event) -> None:
        view, model = self._view, self._view.sheet_model()
        painter = QPainter(self)
        painter.fillRect(self.rect(), theme.NODE_HEADER)
        painter.setPen(QPen(_LINE, 2))
        painter.drawLine(0, 1, self.width(), 1)
        if model is None:
            return
        font = QFont(self.font())
        font.setBold(True)
        painter.setFont(font)
        label = QRect(0, 0, self._label_width(), self.height())
        painter.setPen(_DIM)
        painter.drawText(label.adjusted(4, 2, -2, 0),
                         int(Qt.AlignLeft | Qt.AlignVCenter),
                         "Σ" if label.width() < 40 else "Total")
        rows = self._visible_rows()
        painter.setClipRect(QRect(label.right() + 1, 0, self.width(),
                                  self.height()))
        grid_pen = QPen(theme.NODE_BORDER, 1)
        for col, rect in self.column_rects():
            painter.setPen(grid_pen)
            painter.drawLine(rect.right(), 3, rect.right(), self.height())
            text = model.total_text(col, rows)
            if not text:
                continue
            painter.setPen(_TEXT)
            how = model.column_total(col)
            align = Qt.AlignRight if how not in ("first", "last", "mode") \
                else Qt.AlignLeft
            painter.drawText(rect.adjusted(4, 2, -5, 0),
                             int(align | Qt.AlignVCenter), text)

    # ------------------------------------------------------------- mouse

    def mousePressEvent(self, event) -> None:
        col = self.column_at(event.position().toPoint())
        if col < 0 or event.button() not in (Qt.LeftButton, Qt.RightButton):
            return super().mousePressEvent(event)
        event.accept()
        self.open_menu(col, event.position().toPoint())

    def open_menu(self, col: int, pos: QPoint) -> None:
        from .menus import exec_menu, new_menu
        menu = new_menu(self)
        fill_total_menu(menu, self._view, [col])
        exec_menu(menu, self, QPoint(pos.x(), self.height()))

    def event(self, event) -> bool:
        if event.type() == event.Type.ToolTip:
            from ..data_table import show_tooltip
            col = self.column_at(event.pos())
            model = self._view.sheet_model()
            if col >= 0 and model is not None:
                how = model.column_total(col)
                name = model.sheet.columns[col].name
                if how:
                    from flograph.core.table_totals import AGGREGATION_HELP
                    text = (f"{how.capitalize()} of {name} — "
                            f"{AGGREGATION_HELP.get(how, how)}")
                    if self._view.filtered:
                        text += ", over the rows the filter shows"
                    text += ". Click to change it."
                else:
                    text = f"Click to total {name}."
                show_tooltip(event.globalPos(), text, self)
            else:
                QToolTip.hideText()
            return True
        return super().event(event)


def fill_total_menu(menu, view, cols) -> None:
    """The totals a column can show, its current one ticked."""
    from flograph.core.table_totals import AGGREGATION_HELP, AGGREGATIONS
    from .menus import heading
    model = view.sheet_model()
    if model is None or not cols:
        return
    current = model.column_total(cols[0])
    heading(menu, "Total")
    none = menu.addAction("None")
    none.setCheckable(True)
    none.setChecked(current is None)
    none.triggered.connect(lambda: model.set_column_total(cols, None))
    for how in AGGREGATIONS:
        action = menu.addAction(how.capitalize())
        action.setCheckable(True)
        action.setChecked(current == how)
        action.setToolTip(AGGREGATION_HELP.get(how, how).capitalize() + ".")
        action.triggered.connect(
            lambda _=False, h=how: model.set_column_total(cols, h))
