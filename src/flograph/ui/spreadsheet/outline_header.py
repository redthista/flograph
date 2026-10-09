"""The row header with Excel's outline gutter.

When the table has grouped rows, the row-number header grows a margin on
its left, one narrow column per level of grouping. Each group draws a
bracket down its rows and a −/+ button on the row just after it (just
before, when the group runs to the end). Click the button — or anywhere on
the bracket — to fold the group away or bring it back. Without groups the
header is the plain one.
"""
from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, QSize, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QHeaderView, QToolTip

from flograph.core.sheet.outline import button_row, depth, level_of

_LEVEL = 12          # px per level of grouping
_PAD = 4             # px before the first level
_BOX = 9             # the −/+ button
_LINE = QColor("#8b909c")
_BUTTON_BG = QColor("#2f323b")
_GUTTER_BG = QColor("#23252c")


class OutlineHeader(QHeaderView):
    def __init__(self, view) -> None:
        super().__init__(Qt.Vertical, view)
        self._view = view
        self._gutter = 0

    # ---------------------------------------------------------- geometry

    def _groups(self) -> list:
        model = self.model()
        return list(getattr(model, "groups", None) or [])

    def gutter_width(self) -> int:
        return self._gutter

    def outline_changed(self) -> None:
        """Called by the view when the groups or their folds change."""
        levels = depth(self._groups())
        gutter = _PAD + levels * _LEVEL + 2 if levels else 0
        if gutter != self._gutter:
            self._gutter = gutter
            self.updateGeometry()
            view = self._view
            if hasattr(view, "updateGeometries"):
                view.updateGeometries()
        self.viewport().update()

    def sizeHint(self) -> QSize:
        hint = super().sizeHint()
        return QSize(hint.width() + self._gutter, hint.height())

    def _column_x(self, level: int) -> int:
        """The centre of a level's column."""
        return _PAD + (level - 1) * _LEVEL + _LEVEL // 2

    # ----------------------------------------------------------- painting

    def paintSection(self, painter: QPainter, rect: QRect,
                     logical: int) -> None:
        if not self._gutter:
            super().paintSection(painter, rect, logical)
            return
        painter.save()
        super().paintSection(painter, rect.adjusted(self._gutter, 0, 0, 0),
                             logical)
        painter.restore()
        painter.save()
        painter.fillRect(QRect(rect.left(), rect.top(), self._gutter,
                               rect.height()), _GUTTER_BG)
        self._paint_outline(painter, rect, logical)
        painter.restore()

    def _paint_outline(self, painter: QPainter, rect: QRect,
                       row: int) -> None:
        groups = self._groups()
        n_rows = self.model().rowCount() if self.model() else 0
        painter.setRenderHint(QPainter.Antialiasing, False)
        top, bottom = rect.top(), rect.bottom()
        mid = rect.center().y()
        for group in groups:
            x = rect.left() + self._column_x(level_of(groups, group))
            anchor = button_row(group, n_rows)
            painter.setPen(QPen(_LINE, 1))
            if not group.collapsed and group.covers(row):
                y0 = top + 3 if row == group.start and anchor > group.end \
                    else top
                y1 = bottom - 3 if row == group.end and anchor < group.start \
                    else bottom
                painter.drawLine(x, y0, x, y1)
                if row == group.start and anchor > group.end:
                    painter.drawLine(x, y0, x + 4, y0)
                if row == group.end and anchor < group.start:
                    painter.drawLine(x, y1, x + 4, y1)
            if row == anchor:
                box = QRect(x - _BOX // 2, mid - _BOX // 2, _BOX, _BOX)
                if not group.collapsed:
                    # the bracket runs on into the button
                    if anchor > group.end:
                        painter.drawLine(x, top, x, box.top())
                    else:
                        painter.drawLine(x, box.bottom(), x, bottom)
                painter.fillRect(box, _BUTTON_BG)
                painter.drawRect(box)
                painter.setPen(QPen(QColor("#e5e7eb"), 1))
                c = box.center()
                painter.drawLine(c.x() - 2, c.y(), c.x() + 2, c.y())
                if group.collapsed:
                    painter.drawLine(c.x(), c.y() - 2, c.x(), c.y() + 2)

    # ------------------------------------------------------------- mouse

    def group_at(self, pos: QPoint):
        """The group whose button or bracket is under `pos`, or None."""
        if not self._gutter or pos.x() >= self._gutter:
            return None
        row = self.logicalIndexAt(pos)
        if row < 0:
            return None
        groups = self._groups()
        n_rows = self.model().rowCount()
        for group in groups:
            x = self._column_x(level_of(groups, group))
            if abs(pos.x() - x) > _LEVEL // 2:
                continue
            if button_row(group, n_rows) == row or (
                    not group.collapsed and group.covers(row)):
                return group
        return None

    def mousePressEvent(self, event) -> None:
        pos = event.position().toPoint()
        if self._gutter and pos.x() < self._gutter:
            group = self.group_at(pos)
            if group is not None and event.button() == Qt.LeftButton:
                self._view.toggle_group(group)
            event.accept()          # the margin never selects rows
            return
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        if self._gutter and event.position().x() < self._gutter:
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def viewportEvent(self, event) -> bool:
        if event.type() == event.Type.ToolTip and self._gutter \
                and event.pos().x() < self._gutter:
            group = self.group_at(event.pos())
            if group is None:
                QToolTip.hideText()
            else:
                rows = f"rows {group.start + 1}–{group.end + 1}"
                QToolTip.showText(
                    event.globalPos(),
                    (f"Show {rows} (Show Detail)" if group.collapsed
                     else f"Fold away {rows} (Hide Detail)"), self)
            return True
        return super().viewportEvent(event)
