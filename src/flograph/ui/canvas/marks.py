"""The glyph inside a compact node's square.

Drawn, not typed — the same reasoning `NodeBadge` and the dashboard Visuals
list already record in their own docstrings. Colour-emoji and non-BMP glyphs
paint *nothing* through Qt's text path on a machine whose UI font lacks
coverage, and `QFontMetrics.inFont()` answers True for glyphs it then
declines to draw, so there is no way to test a candidate short of painting it
and counting the ink. A dozen lines of QPainterPath always draw, take the
theme's colour, and stay sharp at any zoom.

Every mark is a function of `(painter, rect, color)` that paints itself into
a square, working in unit coordinates via `_u`. That signature is what lets
the picker render the identical mark into a 20x20 swatch and the canvas into
a 28x28 body inset, with no second implementation of anything.

A node's mark comes from its category by default (`CATEGORY_MARKS`), which is
seven marks for the whole library — deliberately coarse, because the node's
name sits directly above the square and is the thing that actually
distinguishes a Sort from a Join. The rest of the library exists for the
per-node override (right-click > Node mark), where picking the funnel for
your filters is a choice about *your* graph rather than a fact about the node
type.
"""

from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QBrush, QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap,
)

# Stroke weight as a fraction of the square's side, so a mark drawn into a
# 20px swatch and the same mark at 28px on the canvas read identically.
_STROKE = 0.075
_MIN_STROKE = 0.9


def _pen(rect: QRectF, color: QColor, scale: float = 1.0) -> QPen:
    width = max(_MIN_STROKE, rect.width() * _STROKE * scale)
    pen = QPen(color, width)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    return pen


def _u(rect: QRectF, x: float, y: float) -> QPointF:
    """A point in unit coordinates: (0, 0) is the square's top-left, (1, 1)
    its bottom-right."""
    return QPointF(rect.left() + x * rect.width(),
                   rect.top() + y * rect.height())


def _box(rect: QRectF, x0: float, y0: float, x1: float, y1: float) -> QRectF:
    return QRectF(_u(rect, x0, y0), _u(rect, x1, y1))


def _poly(rect: QRectF, *points: tuple[float, float]) -> QPainterPath:
    path = QPainterPath(_u(rect, *points[0]))
    for point in points[1:]:
        path.lineTo(_u(rect, *point))
    return path


def _stroke(painter: QPainter, rect: QRectF, color: QColor,
            path: QPainterPath, scale: float = 1.0) -> None:
    painter.setPen(_pen(rect, color, scale))
    painter.setBrush(Qt.NoBrush)
    painter.drawPath(path)


def _fill(painter: QPainter, color: QColor, path: QPainterPath) -> None:
    painter.setPen(Qt.NoPen)
    painter.setBrush(QBrush(color))
    painter.drawPath(path)


def _arrow(painter: QPainter, rect: QRectF, color: QColor,
           x0: float, x1: float, y: float) -> None:
    """A horizontal arrow from x0 to x1 at height y, head at the x1 end."""
    _stroke(painter, rect, color, _poly(rect, (x0, y), (x1, y)))
    head = 0.13 if x1 > x0 else -0.13
    _stroke(painter, rect, color,
            _poly(rect, (x1 - head, y - 0.11), (x1, y), (x1 - head, y + 0.11)))


# --------------------------------------------------------------- the marks

def _page_body(rect: QRectF, x0: float, x1: float) -> QPainterPath:
    """A sheet with the top-right corner folded, spanning x0..x1."""
    fold = (x1 - x0) * 0.34
    return _poly(rect,
                 (x0, 0.10), (x1 - fold, 0.10), (x1, 0.10 + fold),
                 (x1, 0.90), (x0, 0.90), (x0, 0.10))


def _page(painter: QPainter, rect: QRectF, color: QColor) -> None:
    _stroke(painter, rect, color, _page_body(rect, 0.22, 0.78))
    fold = 0.56 * 0.34
    _stroke(painter, rect, color,
            _poly(rect, (0.78 - fold, 0.10), (0.78 - fold, 0.10 + fold),
                  (0.78, 0.10 + fold)), scale=0.7)
    for y in (0.55, 0.72):
        _stroke(painter, rect, color, _poly(rect, (0.34, y), (0.66, y)),
                scale=0.7)


def _page_out(painter: QPainter, rect: QRectF, color: QColor) -> None:
    _stroke(painter, rect, color, _page_body(rect, 0.06, 0.46))
    _arrow(painter, rect, color, 0.56, 0.94, 0.50)


def _page_in(painter: QPainter, rect: QRectF, color: QColor) -> None:
    _stroke(painter, rect, color, _page_body(rect, 0.54, 0.94))
    _arrow(painter, rect, color, 0.06, 0.44, 0.50)


def _grid(painter: QPainter, rect: QRectF, color: QColor) -> None:
    outer = QPainterPath()
    outer.addRect(_box(rect, 0.12, 0.16, 0.88, 0.84))
    _stroke(painter, rect, color, outer)
    # a filled header row, the way a table reads
    header = QPainterPath()
    header.addRect(_box(rect, 0.12, 0.16, 0.88, 0.36))
    _fill(painter, color, header)
    for x in (0.37, 0.63):
        _stroke(painter, rect, color, _poly(rect, (x, 0.36), (x, 0.84)),
                scale=0.7)
    _stroke(painter, rect, color, _poly(rect, (0.12, 0.60), (0.88, 0.60)),
            scale=0.7)


def _cylinder(painter: QPainter, rect: QRectF, color: QColor) -> None:
    painter.setPen(_pen(rect, color))
    painter.setBrush(Qt.NoBrush)
    painter.drawEllipse(_box(rect, 0.16, 0.10, 0.84, 0.32))
    _stroke(painter, rect, color, _poly(rect, (0.16, 0.21), (0.16, 0.79)))
    _stroke(painter, rect, color, _poly(rect, (0.84, 0.21), (0.84, 0.79)))
    bottom = QPainterPath()
    bottom.arcMoveTo(_box(rect, 0.16, 0.68, 0.84, 0.90), 180)
    bottom.arcTo(_box(rect, 0.16, 0.68, 0.84, 0.90), 180, 180)
    _stroke(painter, rect, color, bottom)
    middle = QPainterPath()
    middle.arcMoveTo(_box(rect, 0.16, 0.39, 0.84, 0.61), 180)
    middle.arcTo(_box(rect, 0.16, 0.39, 0.84, 0.61), 180, 180)
    _stroke(painter, rect, color, middle, scale=0.7)


def _arrows(painter: QPainter, rect: QRectF, color: QColor) -> None:
    _arrow(painter, rect, color, 0.10, 0.90, 0.32)
    _arrow(painter, rect, color, 0.90, 0.10, 0.68)


def _funnel(painter: QPainter, rect: QRectF, color: QColor) -> None:
    _fill(painter, color, _poly(
        rect, (0.10, 0.14), (0.90, 0.14), (0.58, 0.52), (0.58, 0.90),
        (0.42, 0.80), (0.42, 0.52), (0.10, 0.14)))


def _overlap(painter: QPainter, rect: QRectF, color: QColor) -> None:
    painter.setPen(_pen(rect, color))
    painter.setBrush(Qt.NoBrush)
    painter.drawEllipse(_box(rect, 0.06, 0.24, 0.62, 0.80))
    painter.drawEllipse(_box(rect, 0.38, 0.24, 0.94, 0.80))


def _collapse(painter: QPainter, rect: QRectF, color: QColor) -> None:
    for y in (0.20, 0.50, 0.80):
        _stroke(painter, rect, color, _poly(rect, (0.08, y), (0.36, y)))
        if y != 0.50:
            _stroke(painter, rect, color,
                    _poly(rect, (0.40, y), (0.52, 0.50)), scale=0.6)
    _arrow(painter, rect, color, 0.52, 0.92, 0.50)


def _sort_bars(painter: QPainter, rect: QRectF, color: QColor) -> None:
    for y, x1 in ((0.20, 0.42), (0.50, 0.64), (0.80, 0.88)):
        _stroke(painter, rect, color, _poly(rect, (0.12, y), (x1, y)),
                scale=1.4)


def _reshape(painter: QPainter, rect: QRectF, color: QColor) -> None:
    square = QPainterPath()
    square.addRect(_box(rect, 0.36, 0.36, 0.64, 0.64))
    _stroke(painter, rect, color, square, scale=0.9)
    arc = QPainterPath()
    box = _box(rect, 0.08, 0.08, 0.92, 0.92)
    arc.arcMoveTo(box, 55)
    arc.arcTo(box, 55, 265)
    _stroke(painter, rect, color, arc, scale=0.8)
    _stroke(painter, rect, color,
            _poly(rect, (0.54, 0.04), (0.76, 0.16), (0.66, 0.36)), scale=0.8)


def _slider(painter: QPainter, rect: QRectF, color: QColor) -> None:
    _stroke(painter, rect, color, _poly(rect, (0.08, 0.50), (0.92, 0.50)))
    knob = QPainterPath()
    knob.addEllipse(_box(rect, 0.52, 0.32, 0.88, 0.68))
    _fill(painter, color, knob)


def _bars(painter: QPainter, rect: QRectF, color: QColor) -> None:
    for x0, top in ((0.14, 0.56), (0.42, 0.24), (0.70, 0.42)):
        bar = QPainterPath()
        bar.addRect(_box(rect, x0, top, x0 + 0.16, 0.86))
        _fill(painter, color, bar)
    _stroke(painter, rect, color, _poly(rect, (0.08, 0.86), (0.92, 0.86)),
            scale=0.7)


def _dot(painter: QPainter, rect: QRectF, color: QColor) -> None:
    path = QPainterPath()
    path.addEllipse(_box(rect, 0.28, 0.28, 0.72, 0.72))
    _fill(painter, color, path)


def _brackets(painter: QPainter, rect: QRectF, color: QColor) -> None:
    _stroke(painter, rect, color,
            _poly(rect, (0.36, 0.20), (0.12, 0.50), (0.36, 0.80)))
    _stroke(painter, rect, color,
            _poly(rect, (0.64, 0.20), (0.88, 0.50), (0.64, 0.80)))
    _stroke(painter, rect, color, _poly(rect, (0.56, 0.14), (0.44, 0.86)),
            scale=0.8)


def _outline_square(painter: QPainter, rect: QRectF, color: QColor) -> None:
    path = QPainterPath()
    path.addRoundedRect(_box(rect, 0.18, 0.18, 0.82, 0.82),
                        rect.width() * 0.08, rect.height() * 0.08)
    _stroke(painter, rect, color, path)


_PAINTERS: dict[str, Callable[[QPainter, QRectF, QColor], None]] = {
    "page": _page,
    "page_out": _page_out,
    "page_in": _page_in,
    "grid": _grid,
    "cylinder": _cylinder,
    "arrows": _arrows,
    "funnel": _funnel,
    "overlap": _overlap,
    "collapse": _collapse,
    "sort_bars": _sort_bars,
    "reshape": _reshape,
    "slider": _slider,
    "bars": _bars,
    "dot": _dot,
    "brackets": _brackets,
    "outline_square": _outline_square,
}

# Picker order — grouped by what they mean, not alphabetically, so the grid
# reads as rows of related shapes.
MARK_NAMES: tuple[str, ...] = (
    "page", "page_out", "page_in", "grid", "cylinder", "dot",
    "arrows", "funnel", "overlap", "collapse", "sort_bars", "reshape",
    "slider", "bars", "brackets", "outline_square",
)

MARK_LABELS: dict[str, str] = {
    "page": "Sheet",
    "page_out": "Read",
    "page_in": "Write",
    "grid": "Table",
    "cylinder": "Database",
    "dot": "Dot",
    "arrows": "Transform",
    "funnel": "Filter",
    "overlap": "Join",
    "collapse": "Aggregate",
    "sort_bars": "Sort",
    "reshape": "Reshape",
    "slider": "Input",
    "bars": "Chart",
    "brackets": "Script",
    "outline_square": "Blank",
}

# The default mark for each library category, keyed lowercase — `category` is
# a free string on NODE, so a user node that calls itself "Transform" gets
# the transform mark for free, and anything unrecognised falls back.
CATEGORY_MARKS: dict[str, str] = {
    "io": "page",
    "transform": "arrows",
    "input": "slider",
    "viz": "bars",
    "util": "dot",
    "scripting": "brackets",
}

FALLBACK_MARK = "outline_square"


# A mark image is stored *in* the project file, so it has to stay small
# enough that a graph full of them is still a text file you can open. 128px
# covers zooming a 56px square to about 2x before it softens, and a PNG that
# size is a few kilobytes.
MARK_IMAGE_MAX_PX = 128
# An animation cannot be re-encoded smaller with Qt alone (QMovie reads, it
# does not write), so its original bytes go in as they are — capped, because
# "as they are" could be a 40 MB screen recording.
MARK_IMAGE_MAX_BYTES = 2_000_000


class MarkImageError(ValueError):
    """A picture that can't become a mark, with a reason worth showing."""


def encode_mark_image(source: str) -> str:
    """Turn a file path (or data: URI, or bare base64) into the data: URI a
    node stores as its mark.

    A still is decoded, scaled to fit MARK_IMAGE_MAX_PX and re-encoded as
    PNG — so a 6000px photo becomes a few KB rather than bloating the project
    file with pixels no 56px square will ever show. An animation is kept
    byte-for-byte, because scaling it down would mean re-encoding it and Qt
    has no GIF writer; it is size-capped instead.
    """
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice
    from PySide6.QtGui import QImageReader

    from flograph.core.images import resolve_source, to_data_uri

    try:
        data, mime, _path = resolve_source(source)
    except (ValueError, FileNotFoundError, OSError) as exc:
        raise MarkImageError(str(exc)) from exc

    buffer = QBuffer()
    buffer.setData(QByteArray(data))
    buffer.open(QIODevice.ReadOnly)
    reader = QImageReader(buffer)
    reader.setAutoTransform(True)
    animated = reader.supportsAnimation() and reader.imageCount() > 1

    if animated:
        if len(data) > MARK_IMAGE_MAX_BYTES:
            raise MarkImageError(
                f"That animation is {len(data) // 1000} KB. An animated mark "
                f"is stored inside the project file as-is, so keep it under "
                f"{MARK_IMAGE_MAX_BYTES // 1000} KB — or use a still, which "
                f"is scaled down for you.")
        return to_data_uri(data, mime)

    natural = reader.size()
    if natural.isValid() and max(natural.width(), natural.height()) > MARK_IMAGE_MAX_PX:
        reader.setScaledSize(natural.scaled(
            MARK_IMAGE_MAX_PX, MARK_IMAGE_MAX_PX, Qt.KeepAspectRatio))
    image = reader.read()
    if image.isNull():
        raise MarkImageError(reader.errorString() or "unreadable image")

    out = QBuffer()
    out.open(QIODevice.WriteOnly)
    if not image.save(out, "PNG"):
        raise MarkImageError("could not re-encode that image")
    return to_data_uri(bytes(out.data()), "image/png")


def mark_for_category(category: str) -> str:
    """The default mark for a library category. Split out from mark_for
    because the library lists *specs*, which have a category but no instance
    to carry an override."""
    return CATEGORY_MARKS.get(str(category or "").strip().lower(),
                              FALLBACK_MARK)


def mark_pixmap(name: str, size: int, color: QColor,
                ratio: float = 1.0) -> QPixmap:
    """A mark rendered to a transparent pixmap — for the places that want an
    icon rather than a paint call: library rows, the palette popup.

    Device-pixel-ratio aware, so a 16px icon is drawn at 32px on a HiDPI
    screen and stays as crisp as the canvas version.
    """
    pixels = max(1, int(round(size * ratio)))
    pixmap = QPixmap(pixels, pixels)
    pixmap.fill(Qt.transparent)
    pixmap.setDevicePixelRatio(ratio)
    painter = QPainter(pixmap)
    draw(name, painter, QRectF(0, 0, size, size), color)
    painter.end()
    return pixmap


def mark_icon(name: str, size: int, color: QColor,
              ratio: float = 1.0) -> QIcon:
    return QIcon(mark_pixmap(name, size, color, ratio))


def mark_for(node) -> str:
    """The mark name a node draws: its own override when that names a mark
    this build still ships, else its category's, else the fallback. An
    override naming a mark that has since been removed degrades to the
    category default rather than painting nothing."""
    if node.mark in _PAINTERS:
        return node.mark
    return mark_for_category(getattr(node.spec, "category", ""))


def draw(name: str, painter: QPainter, rect: QRectF,
         color: QColor) -> bool:
    """Paint a mark into `rect`. Returns False for an unknown name, having
    drawn nothing. Saves and restores the painter: marks set their own pen
    and brush and callers should not have to undo that."""
    paint: Optional[Callable] = _PAINTERS.get(name)
    if paint is None:
        return False
    painter.save()
    painter.setRenderHint(QPainter.Antialiasing, True)
    paint(painter, rect, QColor(color))
    painter.restore()
    return True
