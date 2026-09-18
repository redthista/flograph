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

from collections import OrderedDict

from PySide6.QtCore import (
    QBuffer, QByteArray, QIODevice, QPointF, QRect, QRectF, QSize, Qt,
)
from PySide6.QtGui import (
    QColor, QFontMetrics, QImageReader, QPainter, QPainterPath, QPalette,
    QPen, QPixmap,
)
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
#: -> the height this cell's row should be, in pixels, or None — a `height`
#: line for every row, or a highlight's `height` for the rows it picks
HEIGHT_ROLE = int(Qt.UserRole) + 4

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


#: How wide a sparkline beside a value is when its rule named no width —
#: the least it gets; a wider cell gives it what the value leaves over,
#: up to the most.
_SPARK_BESIDE_W = 64
_SPARK_BESIDE_MAX_W = 240
#: Kept clear beside the value's text, so a spark grown into the spare room
#: never sits hard against the last letter.
_TEXT_SLACK = 8
#: Breathing room above and below a spark, so a line through its high
#: point does not touch the grid line of the row above.
_SPARK_PAD_Y = 2


def _spark(d):
    return getattr(d, "spark", None)


def _picture(d):
    return getattr(d, "image", None)


#: Kept clear above and below a picture, so a logo as tall as its row does
#: not sit on the grid lines.
_PICTURE_PAD_Y = 1
#: Decoded pictures, by (address, width, height, pixel ratio). A column of
#: logos is repainted on every scroll; decoding each one per paint is the
#: cost this saves, and the bound keeps a long session's scrolling from
#: holding every size it ever drew.
_PIXMAPS: "OrderedDict" = OrderedDict()
_PIXMAP_CACHE = 512


def picture_pixmap(uri: str, width: int, height: int,
                   ratio: float = 1.0) -> "QPixmap | None":
    """The picture at `uri`, scaled to fit `width` × `height` with its shape
    kept, for a screen at `ratio` — or None when it will not decode.

    Scaled by the reader rather than after it, so an SVG is drawn at the
    size it is shown rather than blown up from its own.
    """
    key = (uri, int(width), int(height), round(float(ratio), 2))
    if key in _PIXMAPS:
        _PIXMAPS.move_to_end(key)
        return _PIXMAPS[key]
    from flograph.core.images import parse_data_uri
    pixmap = None
    parsed = parse_data_uri(uri) if width > 0 and height > 0 else None
    if parsed is not None:
        buffer = QBuffer()
        buffer.setData(QByteArray(parsed[0]))
        buffer.open(QIODevice.ReadOnly)
        reader = QImageReader(buffer)
        reader.setAutoTransform(True)
        target = QSize(max(1, round(width * ratio)),
                       max(1, round(height * ratio)))
        native = reader.size()
        if native.isValid() and not native.isEmpty():
            reader.setScaledSize(native.scaled(target, Qt.KeepAspectRatio))
        image = reader.read()
        if not image.isNull():
            if not native.isValid() or native.isEmpty():
                image = image.scaled(target, Qt.KeepAspectRatio,
                                     Qt.SmoothTransformation)
            pixmap = QPixmap.fromImage(image)
            pixmap.setDevicePixelRatio(ratio)
    _PIXMAPS[key] = pixmap
    while len(_PIXMAPS) > _PIXMAP_CACHE:
        _PIXMAPS.popitem(last=False)
    return pixmap


def paint_picture(painter, rect: QRectF, uri: str, tile=None, shape=None,
                  ratio: float = 1.0) -> None:
    """Draw the picture at `uri` fitted into `rect`: on a tile of colour
    `tile` when there is one, both cut to `shape`.

    Shared by the card and a report page, which composites a tile into a
    picture because its rich text cannot draw one — so the two agree on
    the radius, the inset and where the picture sits.
    """
    from flograph.core.images import TILE_INSET, tile_radius
    rect = QRectF(rect)
    painter.save()
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
    clip = None
    if tile or shape:
        radius = tile_radius(shape, rect.width(), rect.height())
        clip = QPainterPath()
        clip.addRoundedRect(rect, radius, radius)
    inner = rect
    if tile:
        painter.fillPath(clip, QColor(tile))
        pad = min(rect.width(), rect.height()) * TILE_INSET
        inner = rect.adjusted(pad, pad, -pad, -pad)
    pixmap = picture_pixmap(uri, max(1, round(inner.width())),
                            max(1, round(inner.height())), ratio)
    if pixmap is not None:
        if clip is not None:
            painter.setClipPath(clip, Qt.IntersectClip)
        shown_w = pixmap.width() / pixmap.devicePixelRatio()
        shown_h = pixmap.height() / pixmap.devicePixelRatio()
        painter.drawPixmap(QPointF(inner.center().x() - shown_w / 2,
                                   inner.center().y() - shown_h / 2), pixmap)
    painter.restore()


def _picture_height(d, room: int) -> int:
    """How tall a picture is drawn in `room` pixels of height: the size its
    rule named, else all of the room — never more than the room has."""
    most = max(1, room - 2 * _PICTURE_PAD_Y)
    return min(d.size, most) if d.size else most


def _units(decorations) -> int:
    """How many text lines a stacked line of decorations takes: two when
    it holds a `tall` spark, one otherwise."""
    return 2 if any(_spark(d) is not None and _spark(d).tall
                    for d in decorations) else 1


def _line_px(decorations, line_h: int) -> int:
    """How tall a stacked line of decorations is, in pixels: a line of text
    (two for a tall spark), or a sized picture's height if that is more."""
    sized = [d.size + 2 * _PICTURE_PAD_Y for d in decorations
             if _picture(d) and d.size]
    return max([line_h * _units(decorations)] + sized)


def _grown_px(decorations, line_h: int) -> int:
    """How much taller the value's own line gets: a line for a `tall`
    spark beside or in place of it, or what a sized picture there needs
    beyond a line."""
    extra = 0
    for d in decorations:
        if d.where not in ("left", "right", "in"):
            continue
        if _spark(d) is not None and _spark(d).tall:
            extra = max(extra, line_h)
        elif _picture(d) and d.size:
            extra = max(extra, d.size + 2 * _PICTURE_PAD_Y - line_h)
    return extra


def _grows_the_row(decorations) -> bool:
    """A `tall` spark on the value's own line makes that line taller."""
    return any(_spark(d) is not None and _spark(d).tall
               and d.where in ("left", "right", "in") for d in decorations)


def _qpath(points, smooth: bool) -> QPainterPath:
    from flograph.core.sparkline import curve
    path = QPainterPath(QPointF(*points[0]))
    if smooth:
        for c1, c2, end in curve(points):
            path.cubicTo(QPointF(*c1), QPointF(*c2), QPointF(*end))
    else:
        for x, y in points[1:]:
            path.lineTo(x, y)
    return path


def paint_spark(painter, rect: QRect, spark) -> None:
    """Draw `spark` into `rect` — the shapes `core.sparkline.geometry`
    laid out, which are the same ones a printed page gets as SVG."""
    from flograph.core.sparkline import geometry
    box = rect.adjusted(0, _SPARK_PAD_Y, 0, -_SPARK_PAD_Y)
    shapes = geometry(spark, box.width(), box.height())
    if shapes is None:
        return
    painter.save()
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.translate(box.left(), box.top())
    for y, colour, dashed in shapes.guides:
        pen = QPen(QColor(colour))
        pen.setWidthF(0.8)
        if dashed:
            pen.setDashPattern([2.5, 2.5])
        painter.setPen(pen)
        painter.drawLine(QPointF(0, y), QPointF(box.width(), y))
    painter.setPen(Qt.NoPen)
    for points, base, colour, opacity in shapes.areas:
        path = _qpath(points, shapes.smooth)
        path.lineTo(points[-1][0], base)
        path.lineTo(points[0][0], base)
        path.closeSubpath()
        fill = QColor(colour)
        fill.setAlphaF(opacity)
        painter.fillPath(path, fill)
    for x, y, w, h, colour in shapes.rects:
        painter.fillRect(QRectF(x, y, w, h), QColor(colour))
    painter.setBrush(Qt.NoBrush)
    for points, colour, stroke in shapes.lines:
        painter.setPen(QPen(QColor(colour), stroke, Qt.SolidLine,
                            Qt.RoundCap, Qt.RoundJoin))
        painter.drawPath(_qpath(points, shapes.smooth))
    painter.setPen(Qt.NoPen)
    for x, y, r, colour in shapes.dots:
        painter.setBrush(QColor(colour))
        painter.drawEllipse(QPointF(x, y), r, r)
    painter.restore()


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
        wanted = index.data(HEIGHT_ROLE)
        decor = index.data(DECOR_ROLE)
        lines = 0
        if decor is not None and decor[0]:
            opt = QStyleOptionViewItem(option)
            self.initStyleOption(opt, index)
            # measured with the *same* font paint() will use. A glyph falls
            # back to an emoji face that is taller than the UI one, and
            # reserving the shorter of the two clips the mark it reserved for.
            line_h = _line_height(opt)
            above, below = _stacked(decor[0])
            # in pixels, not lines: a picture asked for at 40px is as tall
            # as it was asked to be, whatever the font
            lines = ((_line_px(above, line_h) if above else 0)
                     + (_line_px(below, line_h) if below else 0)
                     + _grown_px(decor[0], line_h))
        if not lines and not wanted:
            return size
        height = size.height() + lines
        if wanted:
            # The row is as tall as it was asked to be — shorter than the
            # font's own height too, for a compact table. What it cannot be
            # is shorter than a mark on a line of its own needs: cutting
            # that off would be a rule quietly undoing another one.
            #
            # Less the grid line: a view sizing rows to their contents adds
            # it on top of this (QTableView::sizeHintForRow), where a row
            # at the default section size already includes it. Without
            # this, `height 40` was 40 on one table and 41 on the next.
            view = option.widget
            grid = 1 if (view is not None and hasattr(view, "showGrid")
                         and view.showGrid()) else 0
            asked = int(wanted) - grid
            height = max(asked, height) if lines else asked
        return QSize(size.width(), height)

    # ------------------------------------------------------------ chips

    def _chip_width(self, metrics, d, height: "int | None" = None) -> int:
        """How much room one decoration needs beside the value. `height` is
        the band it sits in, which a picture is drawn to fit."""
        if _spark(d) is not None:
            return _spark(d).width or _SPARK_BESIDE_W
        if _picture(d):
            from flograph.core.images import picture_aspect
            tall = _picture_height(d, height or metrics.height())
            return max(1, round(tall * picture_aspect(_picture(d))))
        advance = metrics.horizontalAdvance(str(d.text))
        if d.pill:
            return advance + 2 * _PILL_PAD_X
        # an emoji is squarer and wider than the ✓ a cell was sized for,
        # and drawText clips to its rect, so measure rather than assume
        return max(_ICON_CELL_W, advance)

    def _side_widths(self, opt, band_width, decorations, metrics, text,
                     pill, band_height: "int | None" = None) -> dict:
        """id(decoration) -> the width each mark beside the value takes.

        Every mark takes its own fixed width, except a spark nobody gave a
        width: those share whatever the cell has left once the other marks
        and the value's own text are paid for — never less than the default
        and never more than the most. So a spark in a column that ended up
        wide (a long header, a dragged edge) fills it rather than sitting as
        a stub at one end of an empty cell.
        """
        side = [d for d in decorations if d.where in ("left", "right")]
        widths = {id(d): self._chip_width(metrics, d, band_height)
                  for d in side}
        flexible = [d for d in side
                    if _spark(d) is not None and not _spark(d).width]
        if not flexible:
            return widths
        grown = {id(d) for d in flexible}
        taken = (sum(w for key, w in widths.items() if key not in grown)
                 + _ICON_GAP * len(side))
        words = (QFontMetrics(opt.font).horizontalAdvance(text) if text
                 else 0) + _TEXT_SLACK + (2 * _PILL_PAD_X if pill else 0)
        each = (band_width - taken - words) // len(flexible)
        each = max(_SPARK_BESIDE_W, min(_SPARK_BESIDE_MAX_W, each))
        for d in flexible:
            widths[id(d)] = each
        return widths

    def _draw_chip(self, painter, x, band, d, metrics, pen,
                   width: "int | None" = None) -> int:
        """One decoration at `x` within `band`. Returns the width used."""
        width = width or self._chip_width(metrics, d, band.height())
        if _spark(d) is not None:
            paint_spark(painter, QRect(x, band.top(), width, band.height()),
                        _spark(d))
            return width
        if _picture(d):
            from flograph.core.images import picture_aspect
            device = painter.device()
            ratio = device.devicePixelRatioF() if device is not None else 1.0
            aspect = picture_aspect(_picture(d))
            tall = _picture_height(d, band.height())
            # the picture's own box, so a tile is the picture's shape and
            # not the width a narrow column squeezed it into
            box_w = min(float(width), tall * aspect)
            box_h = box_w / aspect
            paint_picture(painter,
                          QRectF(x + (width - box_w) / 2,
                                 band.top() + (band.height() - box_h) / 2,
                                 box_w, box_h),
                          _picture(d), getattr(d, "tile", None),
                          getattr(d, "shape", None), ratio)
            return width
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

    def _draw_line(self, painter, band, decorations, metrics, pen,
                   align=None) -> None:
        """A whole line of decorations in `band`.

        Centred unless the column asked for a side. An icon standing in for
        the value is the cell's whole content, so it follows the column's
        `align` rule the way the value it replaced would have — which is
        already what the printed table does (`core/table_html._cell`), and
        for a while was the one place the two disagreed.
        """
        if not decorations:
            return
        if (len(decorations) == 1 and _spark(decorations[0]) is not None
                and not _spark(decorations[0]).width):
            # a spark with a line to itself, or the whole cell, takes all
            # of it: the column's width is what decides how long it reads
            paint_spark(painter, band.adjusted(2, 0, -2, 0),
                        _spark(decorations[0]))
            return
        # no wider than the band: a picture in place of the value is drawn
        # to the row's height, and a narrow column shrinks it to fit instead
        widths = [min(band.width(),
                      self._chip_width(metrics, d, band.height()))
                  for d in decorations]
        total = sum(widths) + _ICON_GAP * (len(widths) - 1)
        spare = max(0, band.width() - total)
        if align is not None and align & int(Qt.AlignLeft):
            x = band.left()
        elif align is not None and align & int(Qt.AlignRight):
            x = band.left() + spare
        else:
            x = band.left() + spare // 2
        for d, width in zip(decorations, widths):
            self._draw_chip(painter, x, band, d, metrics, pen, width)
            x += width + _ICON_GAP

    # --------------------------------------------------------- the value

    def _value_band(self, opt, decorations, metrics, text: str = "",
                    pill=None) -> QRect:
        """The room left for the value once the decorations have taken
        theirs — a line above or below costs height, a mark to either side
        costs width. `text` is the value, which a spark beside it grows
        round (see `_side_widths`)."""
        inner = opt.rect.adjusted(3, 2, -3, -2)
        above, below = _stacked(decorations)
        line_h = metrics.height()
        band = QRect(inner)
        if above:
            band.setTop(band.top() + _line_px(above, line_h))
        if below:
            band.setBottom(band.bottom() - _line_px(below, line_h))
        # each chip costs its own width and the gap after it, which is
        # exactly the step paint() walks below
        widths = self._side_widths(opt, band.width(), decorations, metrics,
                                   text, pill, band.height())
        left = sum(widths[id(d)] + _ICON_GAP
                   for d in decorations if d.where == "left")
        right = sum(widths[id(d)] + _ICON_GAP
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
            shown = index.data(Qt.DisplayRole)
            rect = self._value_band(opt, decorations,
                                    QFontMetrics(with_emoji(opt.font)),
                                    "" if shown is None else str(shown),
                                    pill)
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
            high = _line_px(above, line_h)
            self._draw_line(painter, QRect(inner.left(), inner.top(),
                                           inner.width(), high),
                            above, metrics, glyph_pen or text_pen)
            band.setTop(band.top() + high)
        if below:
            low = _line_px(below, line_h)
            self._draw_line(painter, QRect(inner.left(), inner.bottom() - low,
                                           inner.width(), low),
                            below, metrics, glyph_pen or text_pen)
            band.setBottom(band.bottom() - low)

        left = [d for d in decorations if d.where == "left"]
        right = [d for d in decorations if d.where == "right"]
        inside = [d for d in decorations if d.where == "in"]
        pen = glyph_pen or text_pen

        # one set of widths for the walk below and for the value's band, so
        # a spark grown into spare room and the text beside it cannot overlap
        widths = self._side_widths(opt, band.width(), decorations, metrics,
                                   text, pill, band.height())
        x = band.left()
        for d in left:
            x += self._draw_chip(painter, x, band, d, metrics, pen,
                                 widths[id(d)]) + _ICON_GAP
        end = band.right()
        for d in reversed(right):
            width = widths[id(d)]
            end -= width
            self._draw_chip(painter, end, band, d, metrics, pen, width)
            end -= _ICON_GAP

        # what is left between the two margins belongs to the value —
        # unless something was placed `in`, which stands in for it. The
        # margins are drawn either way: a cell can hold a mark in place of
        # its value *and* one beside that, and dropping the second is the
        # exact failure the decoration list exists to prevent.
        # the same arithmetic the chips were just walked by, from the
        # one method that owns it
        middle = self._value_band(opt, decorations, metrics, text, pill)
        if inside:
            self._draw_line(painter, middle, inside, metrics, pen,
                            self._column_align(index))
        else:
            painter.setFont(opt.font)
            self._draw_value(painter, middle, text, opt, text_pen,
                             pill, pill_ink)
        painter.restore()

    @staticmethod
    def _column_align(index):
        """What an `align` rule asked of this column, or None.

        Read off the **header**, not the cell: a cell's own alignment role
        also carries the right-alignment numbers get by their dtype, and an
        icon in a number column has always been centred. An icon moves
        because somebody wrote `align`, not because the column holds
        numbers — which is the same distinction the printed table draws.
        """
        model = index.model()
        if model is None:
            return None
        asked = model.headerData(index.column(), Qt.Horizontal,
                                 Qt.TextAlignmentRole)
        return None if asked is None else int(asked)

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
