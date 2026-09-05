"""The item delegate that draws a data table's conditional formatting.

Flat cell colours and the bold/italic font come straight off the model
through the standard Qt roles (`BackgroundRole`, `ForegroundRole`,
`FontRole`) and need no delegate. The two things a plain view cannot paint
do:

* an in-cell **data bar** — a partial-width fill proportional to the value;
* an **icon** glyph sitting in the cell's left margin, beside the value.

`PandasModel` answers `BAR_ROLE` with `(fraction, colour)` and `ICON_ROLE`
with a glyph string; for every other cell this delegate is a pure
pass-through to `QStyledItemDelegate`, so the same `DataTableView` still
serves the inspector and dashboard tiles that carry no style.
"""
from __future__ import annotations

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import (
    QApplication, QStyle, QStyledItemDelegate, QStyleOptionViewItem,
)

from .emoji_font import with_emoji

# Read by ConditionalFormatDelegate off the model. Kept here (not in
# pandas_model) so data_table.py can install the delegate without dragging
# pandas into its import graph.
BAR_ROLE = int(Qt.UserRole) + 1      # -> (fraction 0..1, colour hex) | None
ICON_ROLE = int(Qt.UserRole) + 2     # -> (glyph str, colour hex | None) | None

_ICON_CELL_W = 18
_ICON_GAP = 4


class ConditionalFormatDelegate(QStyledItemDelegate):
    def paint(self, painter, option, index) -> None:
        bar = index.data(BAR_ROLE)
        icon = index.data(ICON_ROLE)
        if bar is None and not icon:
            super().paint(painter, option, index)
            return

        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        text = opt.text
        opt.text = ""
        style = opt.widget.style() if opt.widget else QApplication.style()
        # background fill + selection, without the text
        style.drawControl(QStyle.CE_ItemViewItem, opt, painter, opt.widget)

        painter.save()
        inner = opt.rect.adjusted(3, 2, -3, -2)

        if bar is not None:
            try:
                frac, color, mode = bar
                frac = max(-1.0, min(1.0, float(frac)))
            except (TypeError, ValueError):
                frac, color, mode = 0.0, None, "left"
            if color and frac:
                if mode == "center":
                    mid = inner.left() + inner.width() // 2
                    span = int(round(inner.width() / 2 * abs(frac)))
                    left = mid if frac > 0 else mid - span
                else:
                    left, span = inner.left(), int(round(inner.width() * abs(frac)))
                painter.fillRect(
                    QRect(left, inner.top(), span, inner.height()),
                    QColor(color))
                if mode == "center":
                    painter.fillRect(
                        QRect(inner.left() + inner.width() // 2, inner.top(),
                              1, inner.height()),
                        QColor("#5b5f68"))

        selected = bool(opt.state & QStyle.State_Selected)
        text_pen = opt.palette.color(
            QPalette.HighlightedText if selected else QPalette.Text)

        # a cell/row highlight has painted a fill; a semantic icon colour
        # (a red breach glyph on a red row) would vanish into it, so on a
        # filled cell the icon takes the already-contrasted text colour
        filled = index.data(Qt.BackgroundRole) is not None

        text_rect = inner
        if icon:
            try:
                glyph, icon_color = icon
            except (TypeError, ValueError):
                glyph, icon_color = str(icon), None
            painter.setPen(QColor(icon_color)
                           if icon_color and not selected and not filled
                           else text_pen)
            # the glyph is whatever the rule typed — an emoji needs a font
            # the UI one falls back to, or it paints an empty cell
            painter.setFont(with_emoji(opt.font))
            glyph = str(glyph)
            # an emoji is squarer and wider than the ✓ this cell was sized
            # for, and drawText clips to its rect, so measure rather than
            # assume — and give it the row's full height, not the inset
            cell_w = max(_ICON_CELL_W,
                         painter.fontMetrics().horizontalAdvance(glyph))
            # with no value beside it — an `only` rule — the icon *is* the
            # column, so it sits in the middle of the cell rather than in a
            # left margin holding nothing open
            box = (opt.rect if not text
                   else QRect(inner.left(), opt.rect.top(),
                              cell_w, opt.rect.height()))
            painter.drawText(box, Qt.AlignVCenter | Qt.AlignHCenter, glyph)
            painter.setFont(opt.font)
            text_rect = inner.adjusted(cell_w + _ICON_GAP, 0, 0, 0)

        painter.setPen(text_pen)
        align = int(opt.displayAlignment) or int(Qt.AlignVCenter | Qt.AlignLeft)
        metrics = painter.fontMetrics()
        painter.drawText(
            text_rect, align,
            metrics.elidedText(text, Qt.ElideRight, text_rect.width()))
        painter.restore()
