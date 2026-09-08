"""The item delegate that draws a data table's conditional formatting.

Flat cell colours and the bold/italic font come straight off the model
through the standard Qt roles (`BackgroundRole`, `ForegroundRole`,
`FontRole`) and need no delegate. The things a plain view cannot paint do:

* an in-cell **data bar** — a partial-width fill proportional to the value;
* the cell's **decorations** — glyphs, labels and pills, any number of
  them, each sitting where its rule asked: left of the value, right of it,
  on a line above or below, or in place of it.

`PandasModel` answers `BAR_ROLE` with `(fraction, colour, mode)` and
`DECOR_ROLE` with `(decorations, pill fill, pill ink)`; for every other
cell this delegate is a pure pass-through to `QStyledItemDelegate`, so the
same `DataTableView` still serves the inspector and dashboard tiles that
carry no style.

A cell used to hold exactly one icon, always on the left. The arrangement
here is what that became: `above` and `below` take a line of their own and
so decide the row's height, which is why this class grows a `sizeHint`
where before it needed none.
"""
from __future__ import annotations

from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPalette
from PySide6.QtWidgets import (
    QApplication, QStyle, QStyledItemDelegate, QStyleOptionViewItem,
)

from .emoji_font import with_emoji

# Read by ConditionalFormatDelegate off the model. Kept here (not in
# pandas_model) so data_table.py can install the delegate without dragging
# pandas into its import graph.
BAR_ROLE = int(Qt.UserRole) + 1      # -> (fraction 0..1, colour hex) | None
ICON_ROLE = int(Qt.UserRole) + 2     # -> (glyph str, colour hex | None) | None
#: -> (list[Decoration], pill fill | None, pill ink | None) | None
#:
#: ICON_ROLE is the first decoration and nothing else, which is all a
#: caller sizing a column needs to know. This is the whole arrangement: a
#: cell may carry a mark on each side, a line above and below, and a
#: lozenge around its value, all at once.
DECOR_ROLE = int(Qt.UserRole) + 3

_ICON_CELL_W = 18
_ICON_GAP = 4
#: Padding inside a lozenge, and the radius of its ends. The card can draw
#: a real rounded rectangle; paper cannot (Qt's rich text drops
#: border-radius), which is the one place the two surfaces differ.
_PILL_PAD_X = 7
_PILL_PAD_Y = 1
_PILL_RADIUS = 7


def _stacked(decorations) -> tuple:
    """The decorations that take a line of their own, (above, below)."""
    return ([d for d in decorations if d.where == "above"],
            [d for d in decorations if d.where == "below"])


def _line_height(opt) -> int:
    """One stacked decoration's line, measured in the font that will draw
    it — the emoji-capable one, which is the taller of the two."""
    return QFontMetrics(with_emoji(opt.font)).height()


class ConditionalFormatDelegate(QStyledItemDelegate):

    # ------------------------------------------------------------ sizing

    def sizeHint(self, option, index) -> QSize:
        """A row is as tall as its tallest cell, and a cell asking for a
        line above or below is asking for a taller row.

        Per-cell by decision: a rule fires on the rows that match it, so
        only those rows pay. That is the opposite of `wrap`, which is
        table-wide precisely because one cell's second line would
        otherwise spend every row's height.
        """
        size = super().sizeHint(option, index)
        decor = index.data(DECOR_ROLE)
        if decor is None:
            return size
        above, below = _stacked(decor[0])
        lines = bool(above) + bool(below)
        if not lines:
            return size
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        # measured with the *same* font paint() will use. A glyph falls
        # back to an emoji face that is taller than the UI one, and
        # reserving the shorter of the two clips the mark it reserved for.
        return QSize(size.width(), size.height() + lines * _line_height(opt))

    # ------------------------------------------------------------ chips

    def _chip_width(self, metrics, d) -> int:
        """How much room one decoration needs beside the value."""
        advance = metrics.horizontalAdvance(str(d.text))
        if d.pill:
            return advance + 2 * _PILL_PAD_X
        # an emoji is squarer and wider than the ✓ a cell was sized for,
        # and drawText clips to its rect, so measure rather than assume
        return max(_ICON_CELL_W, advance)

    def _draw_chip(self, painter, x, band, d, metrics, pen) -> int:
        """One decoration at `x` within `band`. Returns the width used."""
        width = self._chip_width(metrics, d)
        if d.pill:
            height = min(band.height(), metrics.height() + 2 * _PILL_PAD_Y)
            top = band.top() + (band.height() - height) // 2
            painter.save()
            painter.setRenderHint(QPainter.Antialiasing, True)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(d.pill))
            painter.drawRoundedRect(QRect(x, top, width, height),
                                    _PILL_RADIUS, _PILL_RADIUS)
            painter.restore()
        # a lozenge brings its own ground, so its ink is safe whatever the
        # cell is filled with; a bare glyph is the one that has to defer
        painter.setPen(QColor(d.color) if d.color else pen)
        painter.drawText(QRect(x, band.top(), width, band.height()),
                         Qt.AlignVCenter | Qt.AlignHCenter, str(d.text))
        return width

    def _draw_line(self, painter, band, decorations, metrics, pen) -> None:
        """A whole line of decorations, centred in `band`."""
        if not decorations:
            return
        widths = [self._chip_width(metrics, d) for d in decorations]
        total = sum(widths) + _ICON_GAP * (len(widths) - 1)
        x = band.left() + max(0, (band.width() - total) // 2)
        for d, width in zip(decorations, widths):
            self._draw_chip(painter, x, band, d, metrics, pen)
            x += width + _ICON_GAP

    # --------------------------------------------------------- the value

    def _value_band(self, opt, decorations, metrics) -> QRect:
        """The room left for the value once the decorations have taken
        theirs — a line above or below costs height, a mark to either side
        costs width."""
        inner = opt.rect.adjusted(3, 2, -3, -2)
        above, below = _stacked(decorations)
        line_h = metrics.height()
        band = QRect(inner)
        if above:
            band.setTop(band.top() + line_h)
        if below:
            band.setBottom(band.bottom() - line_h)
        # each chip costs its own width and the gap after it, which is
        # exactly the step paint() walks below
        left = sum(self._chip_width(metrics, d) + _ICON_GAP
                   for d in decorations if d.where == "left")
        right = sum(self._chip_width(metrics, d) + _ICON_GAP
                    for d in decorations if d.where == "right")
        x, end = band.left() + left, band.right() - right
        return QRect(x, band.top(), max(0, end - x), band.height())

    def value_area(self, option, index) -> "QRect | None":
        """Where this cell's value is drawn, or None when it is not drawn
        at all — something placed `in` stands in for it, so nothing was cut
        short and there is nothing left to explain.

        Public because the *view* is the only thing that knows how wide the
        column ended up, the *model* is the only thing that knows the whole
        value, and neither knows how much of the cell the decorations took.
        This does, so the tooltip can ask instead of guessing.
        """
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        decor = index.data(DECOR_ROLE)
        decorations, pill, _ink = (decor if decor is not None
                                   else ([], None, None))
        if any(d.where == "in" for d in decorations):
            return None
        if not decorations:
            # nothing beside the value: Qt laid the text out itself, so ask
            # the style where it put it rather than re-guessing its margin
            style = opt.widget.style() if opt.widget else QApplication.style()
            rect = style.subElementRect(QStyle.SE_ItemViewItemText, opt,
                                        opt.widget)
            # SE_ItemViewItemText gives the cell's text *area*; the margin
            # inside it is applied when the text is drawn, not before, so
            # without this the last few pixels of a cell read as room the
            # value never actually had
            margin = style.pixelMetric(QStyle.PM_FocusFrameHMargin, opt,
                                       opt.widget) + 1
            rect = rect.adjusted(margin, 0, -margin, 0)
        else:
            rect = self._value_band(opt, decorations,
                                    QFontMetrics(with_emoji(opt.font)))
        if pill:
            # a lozenge pays for its own padding out of the value's room
            rect = rect.adjusted(_PILL_PAD_X, 0, -_PILL_PAD_X, 0)
        return rect

    # ------------------------------------------------------------ paint

    def paint(self, painter, option, index) -> None:
        bar = index.data(BAR_ROLE)
        decor = index.data(DECOR_ROLE)
        if bar is None and decor is None:
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
            self._paint_bar(painter, inner, bar)

        selected = bool(opt.state & QStyle.State_Selected)
        text_pen = opt.palette.color(
            QPalette.HighlightedText if selected else QPalette.Text)
        # a cell/row highlight has painted a fill; a semantic icon colour
        # (a red breach glyph on a red row) would vanish into it, so on a
        # filled cell a bare glyph takes the already-contrasted text colour
        filled = index.data(Qt.BackgroundRole) is not None
        glyph_pen = text_pen if (selected or filled) else None

        decorations, pill, pill_ink = decor if decor is not None else ([], None, None)
        # the glyph font has to cover an emoji or it paints an empty cell
        painter.setFont(with_emoji(opt.font))
        metrics = painter.fontMetrics()

        above, below = _stacked(decorations)
        line_h = metrics.height()
        band = QRect(inner)
        if above:
            self._draw_line(painter, QRect(inner.left(), inner.top(),
                                           inner.width(), line_h),
                            above, metrics, glyph_pen or text_pen)
            band.setTop(band.top() + line_h)
        if below:
            self._draw_line(painter, QRect(inner.left(), inner.bottom() - line_h,
                                           inner.width(), line_h),
                            below, metrics, glyph_pen or text_pen)
            band.setBottom(band.bottom() - line_h)

        left = [d for d in decorations if d.where == "left"]
        right = [d for d in decorations if d.where == "right"]
        inside = [d for d in decorations if d.where == "in"]
        pen = glyph_pen or text_pen

        x = band.left()
        for d in left:
            x += self._draw_chip(painter, x, band, d, metrics, pen) + _ICON_GAP
        end = band.right()
        for d in reversed(right):
            width = self._chip_width(metrics, d)
            end -= width
            self._draw_chip(painter, end, band, d, metrics, pen)
            end -= _ICON_GAP

        # what is left between the two margins belongs to the value —
        # unless something was placed `in`, which stands in for it. The
        # margins are drawn either way: a cell can hold a mark in place of
        # its value *and* one beside that, and dropping the second is the
        # exact failure the decoration list exists to prevent.
        # the same arithmetic the chips were just walked by, from the
        # one method that owns it
        middle = self._value_band(opt, decorations, metrics)
        if inside:
            self._draw_line(painter, middle, inside, metrics, pen)
        else:
            painter.setFont(opt.font)
            self._draw_value(painter, middle, text, opt, text_pen,
                             pill, pill_ink)
        painter.restore()

    def _draw_value(self, painter, rect, text, opt, pen, pill, ink) -> None:
        if not text:
            return
        metrics = painter.fontMetrics()
        align = int(opt.displayAlignment) or int(Qt.AlignVCenter | Qt.AlignLeft)
        shown = metrics.elidedText(text, Qt.ElideRight,
                                   rect.width() - (2 * _PILL_PAD_X if pill else 0))
        if pill:
            width = min(rect.width(),
                        metrics.horizontalAdvance(shown) + 2 * _PILL_PAD_X)
            height = min(rect.height(), metrics.height() + 2 * _PILL_PAD_Y)
            top = rect.top() + (rect.height() - height) // 2
            left = rect.left()
            if align & int(Qt.AlignRight):
                left = rect.right() - width
            elif align & int(Qt.AlignHCenter):
                left = rect.left() + (rect.width() - width) // 2
            painter.save()
            painter.setRenderHint(QPainter.Antialiasing, True)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(pill))
            painter.drawRoundedRect(QRect(left, top, width, height),
                                    _PILL_RADIUS, _PILL_RADIUS)
            painter.restore()
            painter.setPen(QColor(ink) if ink else pen)
            painter.drawText(QRect(left, top, width, height),
                             Qt.AlignVCenter | Qt.AlignHCenter, shown)
            return
        painter.setPen(pen)
        painter.drawText(rect, align, shown)

    def _paint_bar(self, painter, inner, bar) -> None:
        try:
            frac, color, mode = bar
            frac = max(-1.0, min(1.0, float(frac)))
        except (TypeError, ValueError):
            frac, color, mode = 0.0, None, "left"
        if not (color and frac):
            return
        if mode == "center":
            mid = inner.left() + inner.width() // 2
            span = int(round(inner.width() / 2 * abs(frac)))
            left = mid if frac > 0 else mid - span
        else:
            left, span = inner.left(), int(round(inner.width() * abs(frac)))
        painter.fillRect(QRect(left, inner.top(), span, inner.height()),
                         QColor(color))
        if mode == "center":
            painter.fillRect(
                QRect(inner.left() + inner.width() // 2, inner.top(),
                      1, inner.height()),
                QColor("#5b5f68"))
