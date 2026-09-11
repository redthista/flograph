"""Drawing a Page Links card (AB3): one button per page, in a row or a
column.

The canvas card and the dashboard tile both paint it straight onto the
item, the way the Action Button's face is painted — crisp at every zoom, and
no widget holding a copy of the page list to go stale when a page is added.
Which pages it shows is core.page_nav's to say; this only lays them out,
draws them and answers which one is under a point.
"""
from __future__ import annotations

from typing import Optional, Sequence

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen

from . import theme

PAD = 6.0
GAP = 6.0
EMPTY = "No pages yet — add one with + in the tab bar"


def link_rects(rect: QRectF, count: int, vertical: bool) -> list[QRectF]:
    """Equal buttons filling `rect`, inset by PAD with GAP between."""
    if count <= 0:
        return []
    inner = rect.adjusted(PAD, PAD, -PAD, -PAD)
    if vertical:
        height = max(0.0, (inner.height() - GAP * (count - 1)) / count)
        return [QRectF(inner.left(), inner.top() + i * (height + GAP),
                       inner.width(), height) for i in range(count)]
    width = max(0.0, (inner.width() - GAP * (count - 1)) / count)
    return [QRectF(inner.left() + i * (width + GAP), inner.top(),
                   width, inner.height()) for i in range(count)]


def page_at(rect: QRectF, pages: Sequence, pos: QPointF,
            vertical: bool) -> Optional[str]:
    """The id of the page whose button is under `pos`, or None."""
    for page, box in zip(pages, link_rects(rect, len(pages), vertical)):
        if box.contains(pos):
            return page.id
    return None


def paint_links(painter: QPainter, rect: QRectF, pages: Sequence,
                current_id: Optional[str], vertical: bool, *,
                selected: bool = False, tint: Optional[str] = None) -> None:
    """The card: a body (tinted with the node's colour, if it has one) and
    a button per page. A page's own tab colour tints its button, so the
    strip and the tab bar agree; the page the card sits on is filled with
    the accent, the way a current tab stands out."""
    painter.save()
    painter.setRenderHint(QPainter.Antialiasing)
    body = QPainterPath()
    body.addRoundedRect(rect, 8, 8)
    painter.fillPath(body, theme.tint(theme.NODE_BODY, tint, theme.TINT_SOFT)
                     if tint else theme.NODE_BODY)
    painter.setPen(QPen(theme.SELECTION_OUTLINE if selected
                        else theme.NODE_BORDER, 2.0 if selected else 1.2))
    painter.drawPath(body)

    font = painter.font()
    font.setPointSizeF(9.0)
    if not pages:
        painter.setFont(font)
        painter.setPen(QPen(theme.NODE_SUBTEXT))
        painter.drawText(rect.adjusted(8, 4, -8, -4),
                         Qt.AlignCenter | Qt.TextWordWrap, EMPTY)
        painter.restore()
        return
    for page, box in zip(pages, link_rects(rect, len(pages), vertical)):
        here = page.id == current_id
        base = theme.BUTTON_ACCENT if here else theme.NODE_HEADER
        fill = (theme.tint(base, page.color,
                           theme.TINT_STRONG if here else theme.TINT_SOFT)
                if page.color else base)
        button = QPainterPath()
        button.addRoundedRect(box, 6, 6)
        painter.fillPath(button, fill)
        font.setBold(here)
        painter.setFont(font)
        painter.setPen(QPen(QColor("#ffffff") if here else theme.NODE_TEXT))
        text = painter.fontMetrics().elidedText(
            page.title, Qt.ElideRight, int(max(0.0, box.width() - 10)))
        painter.drawText(box, Qt.AlignCenter, text)
    painter.restore()
