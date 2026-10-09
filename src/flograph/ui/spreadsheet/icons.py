"""The spreadsheet's ribbon and menu glyphs, drawn rather than shipped.

Same reasons as the title bar's (see ui/toolbar.py): a file has to survive
the one-file build, and a glyph from a font may silently paint nothing on a
machine without it. Most are built on one motif, a little grid, with the
part a command acts on lit — the row it inserts, the column it deletes —
and a badge in the canvas's status colours: green adds, red takes away,
blue is the selection, amber is something held back (an edit not yet
submitted). Read the way the nodes are read.
"""
from __future__ import annotations

from functools import lru_cache

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (QColor, QFont, QIcon, QPainter, QPainterPath, QPen,
                           QPixmap)

FG = QColor("#c8cbd2")
DIM = QColor("#8b909c")
BLUE = QColor("#60a5fa")
GREEN = QColor("#22c55e")
RED = QColor("#ef4444")
AMBER = QColor("#eab308")
VIOLET = QColor("#a78bfa")

_PT = 20.0   # the box every glyph is drawn in; shown at 16-24 px


def _pen(color: QColor, width: float = 1.4) -> QPen:
    pen = QPen(color, width)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    return pen


def _fill(color: QColor, alpha: int) -> QColor:
    out = QColor(color)
    out.setAlpha(alpha)
    return out


def _grid(p: QPainter, r: QRectF, rows: int = 3, cols: int = 3,
          lit=(), lit_color: QColor = BLUE, color: QColor = FG) -> None:
    """A small table. `lit` holds ("row", i), ("col", i) or ("cell", r, c)
    entries to fill in `lit_color`."""
    cw, rh = r.width() / cols, r.height() / rows
    for entry in lit:
        if entry[0] == "row":
            cell = QRectF(r.left(), r.top() + entry[1] * rh, r.width(), rh)
        elif entry[0] == "col":
            cell = QRectF(r.left() + entry[1] * cw, r.top(), cw, r.height())
        else:
            cell = QRectF(r.left() + entry[2] * cw, r.top() + entry[1] * rh,
                          cw, rh)
        p.fillRect(cell, _fill(lit_color, 150))
    p.setPen(_pen(color, 1.1))
    p.setBrush(Qt.NoBrush)
    p.drawRoundedRect(r, 1.5, 1.5)
    for i in range(1, rows):
        y = r.top() + i * rh
        p.drawLine(QPointF(r.left(), y), QPointF(r.right(), y))
    for i in range(1, cols):
        x = r.left() + i * cw
        p.drawLine(QPointF(x, r.top()), QPointF(x, r.bottom()))


def _badge(p: QPainter, center: QPointF, kind: str, color: QColor,
           radius: float = 4.4) -> None:
    """A filled disc with + (add), − (remove) or × (delete/discard)."""
    p.setPen(Qt.NoPen)
    p.setBrush(color)
    p.drawEllipse(center, radius, radius)
    p.setPen(_pen(QColor("#111318"), 1.5))
    d = radius * 0.55
    if kind in ("+", "-"):
        p.drawLine(center + QPointF(-d, 0), center + QPointF(d, 0))
    if kind == "+":
        p.drawLine(center + QPointF(0, -d), center + QPointF(0, d))
    if kind == "x":
        p.drawLine(center + QPointF(-d, -d), center + QPointF(d, d))
        p.drawLine(center + QPointF(-d, d), center + QPointF(d, -d))


def _arrow(p: QPainter, start: QPointF, end: QPointF, color: QColor,
           width: float = 1.5, head: float = 3.2) -> None:
    p.setPen(_pen(color, width))
    p.drawLine(start, end)
    direction = end - start
    length = max((direction.x() ** 2 + direction.y() ** 2) ** 0.5, 0.001)
    ux, uy = direction.x() / length, direction.y() / length
    left = QPointF(end.x() - head * ux + head * 0.7 * uy,
                   end.y() - head * uy - head * 0.7 * ux)
    right = QPointF(end.x() - head * ux - head * 0.7 * uy,
                    end.y() - head * uy + head * 0.7 * ux)
    p.drawLine(end, left)
    p.drawLine(end, right)


def _text(p: QPainter, r: QRectF, text: str, color: QColor, size: float,
          bold: bool = True, italic: bool = False,
          align=Qt.AlignCenter) -> None:
    font = QFont()
    font.setPixelSize(max(1, int(round(size))))
    font.setBold(bold)
    font.setItalic(italic)
    p.setFont(font)
    p.setPen(color)
    p.drawText(r, int(align), text)


_BOX = QRectF(2.5, 3.5, 13, 13)        # the grid, leaving room for a badge
_BADGE = QPointF(15.5, 15.5)


# ------------------------------------------------------------- clipboard

def _paste(p, r, c):
    p.setPen(_pen(c))
    p.setBrush(Qt.NoBrush)
    p.drawRoundedRect(QRectF(3.5, 4, 11, 13.5), 1.5, 1.5)
    p.setBrush(c)
    p.drawRoundedRect(QRectF(6.5, 2.5, 5, 3), 1, 1)
    p.setBrush(QColor("#2a2c33"))
    p.setPen(_pen(BLUE, 1.2))
    p.drawRoundedRect(QRectF(9, 9, 8.5, 9), 1, 1)


def _paste_values(p, r, c):
    p.setPen(_pen(c))
    p.setBrush(Qt.NoBrush)
    p.drawRoundedRect(QRectF(3.5, 4, 11, 13.5), 1.5, 1.5)
    p.setBrush(c)
    p.drawRoundedRect(QRectF(6.5, 2.5, 5, 3), 1, 1)
    p.setBrush(QColor("#2a2c33"))
    p.setPen(_pen(BLUE, 1.2))
    p.drawRoundedRect(QRectF(8, 9.5, 10.5, 8.5), 1, 1)
    _text(p, QRectF(8, 9.5, 10.5, 8.5), "12", BLUE, 6.5)


def _clipboard(p, c):
    p.setPen(_pen(c))
    p.setBrush(Qt.NoBrush)
    p.drawRoundedRect(QRectF(3.5, 4, 11, 13.5), 1.5, 1.5)
    p.setBrush(c)
    p.drawRoundedRect(QRectF(6.5, 2.5, 5, 3), 1, 1)


def _paste_special(p, r, c):
    """The clipboard with a badge holding the four sums."""
    _clipboard(p, c)
    p.setBrush(QColor("#2a2c33"))
    p.setPen(_pen(VIOLET, 1.2))
    p.drawRoundedRect(QRectF(8, 8.5, 10.5, 10), 1, 1)
    _text(p, QRectF(8, 8.2, 10.5, 5.6), "+\u2212", VIOLET, 5.5)
    _text(p, QRectF(8, 13, 10.5, 5.6), "\u00d7\u00f7", VIOLET, 5.5)


def _paste_transpose(p, r, c):
    """The clipboard with a row bending round into a column."""
    _clipboard(p, c)
    p.setBrush(QColor("#2a2c33"))
    p.setPen(_pen(BLUE, 1.2))
    p.drawRoundedRect(QRectF(8, 8.5, 10.5, 10), 1, 1)
    p.setBrush(BLUE)
    p.setPen(Qt.NoPen)
    p.drawRect(QRectF(9.5, 10, 6.5, 2))          # the row ...
    p.setBrush(Qt.NoBrush)
    _arrow(p, QPointF(16.6, 12.6), QPointF(16.6, 17.2), BLUE, 1.2, 2.2)
    p.setBrush(BLUE)
    p.setPen(Qt.NoPen)
    p.drawRect(QRectF(9.5, 12.5, 2, 5))          # ... and the column


def _cut(p, r, c):
    p.setPen(_pen(c, 1.4))
    p.setBrush(Qt.NoBrush)
    p.drawEllipse(QPointF(6, 15), 2.6, 2.6)
    p.drawEllipse(QPointF(14, 15), 2.6, 2.6)
    p.drawLine(QPointF(7.6, 13), QPointF(13.5, 3))
    p.drawLine(QPointF(12.4, 13), QPointF(6.5, 3))


def _copy(p, r, c):
    p.setPen(_pen(c))
    p.setBrush(Qt.NoBrush)
    p.drawRoundedRect(QRectF(3, 3, 9.5, 11), 1.5, 1.5)
    p.setBrush(QColor("#2a2c33"))
    p.drawRoundedRect(QRectF(7.5, 7, 9.5, 11), 1.5, 1.5)


def _copy_headers(p, r, c):
    p.setPen(_pen(c))
    p.setBrush(Qt.NoBrush)
    p.drawRoundedRect(QRectF(3, 3, 9.5, 11), 1.5, 1.5)
    box = QRectF(7.5, 7, 9.5, 11)
    p.setBrush(QColor("#2a2c33"))
    p.drawRoundedRect(box, 1.5, 1.5)
    p.fillRect(QRectF(box.left() + 0.7, box.top() + 0.7,
                      box.width() - 1.4, 3), _fill(BLUE, 200))


def _undo(p, r, c, flip=False):
    path = QPainterPath()
    path.moveTo(5, 9)
    path.cubicTo(8, 4.5, 16, 5, 16, 11)
    path.cubicTo(16, 14, 13, 16, 10, 16)
    p.save()
    if flip:
        p.translate(20, 0)
        p.scale(-1, 1)
    p.setPen(_pen(c, 1.5))
    p.setBrush(Qt.NoBrush)
    p.drawPath(path)
    p.drawLine(QPointF(5, 9), QPointF(4.5, 4.5))
    p.drawLine(QPointF(5, 9), QPointF(9.5, 9.3))
    p.restore()


def _redo(p, r, c):
    _undo(p, r, c, flip=True)


# ------------------------------------------------------- rows and columns

def _row_above(p, r, c):
    _grid(p, _BOX, lit=[("row", 0)], lit_color=GREEN, color=c)
    _badge(p, _BADGE, "+", GREEN)


def _row_below(p, r, c):
    _grid(p, _BOX, lit=[("row", 2)], lit_color=GREEN, color=c)
    _badge(p, _BADGE, "+", GREEN)


def _row_delete(p, r, c):
    _grid(p, _BOX, lit=[("row", 1)], lit_color=RED, color=c)
    _badge(p, _BADGE, "x", RED)


def _col_left(p, r, c):
    _grid(p, _BOX, lit=[("col", 0)], lit_color=GREEN, color=c)
    _badge(p, _BADGE, "+", GREEN)


def _col_right(p, r, c):
    _grid(p, _BOX, lit=[("col", 2)], lit_color=GREEN, color=c)
    _badge(p, _BADGE, "+", GREEN)


def _col_delete(p, r, c):
    _grid(p, _BOX, lit=[("col", 1)], lit_color=RED, color=c)
    _badge(p, _BADGE, "x", RED)


def _row_up(p, r, c):
    _grid(p, QRectF(2.5, 3.5, 10, 13), cols=2, lit=[("row", 1)], color=c)
    _arrow(p, QPointF(16, 15), QPointF(16, 4), BLUE)


def _row_down(p, r, c):
    _grid(p, QRectF(2.5, 3.5, 10, 13), cols=2, lit=[("row", 1)], color=c)
    _arrow(p, QPointF(16, 5), QPointF(16, 16), BLUE)


def _col_move_left(p, r, c):
    _grid(p, QRectF(3.5, 7, 13, 10), rows=2, lit=[("col", 1)], color=c)
    _arrow(p, QPointF(15, 3.5), QPointF(4, 3.5), BLUE)


def _col_move_right(p, r, c):
    _grid(p, QRectF(3.5, 7, 13, 10), rows=2, lit=[("col", 1)], color=c)
    _arrow(p, QPointF(5, 3.5), QPointF(16, 3.5), BLUE)


def _select_row(p, r, c):
    _grid(p, QRectF(2.5, 3.5, 15, 13), lit=[("row", 1)], color=c)


def _select_col(p, r, c):
    _grid(p, QRectF(2.5, 3.5, 15, 13), lit=[("col", 1)], color=c)


def _header(p, r, c):
    _grid(p, _BOX, lit=[("row", 0)], color=c)
    _arrow(p, QPointF(16.5, 17), QPointF(16.5, 7.5), BLUE)


# ---------------------------------------------------------------- editing

def _clear(p, r, c):
    p.save()
    p.translate(10, 10)
    p.rotate(-40)
    p.setPen(_pen(c, 1.3))
    p.setBrush(Qt.NoBrush)
    p.drawRoundedRect(QRectF(-7, -3.5, 14, 7), 1.5, 1.5)
    p.fillRect(QRectF(-6.4, -2.9, 5, 5.8), _fill(RED, 190))
    p.restore()
    p.setPen(_pen(DIM, 1.2))
    p.drawLine(QPointF(9, 17.5), QPointF(17.5, 17.5))


def _fill_down(p, r, c):
    _grid(p, QRectF(2.5, 3, 8, 14.5), rows=3, cols=1, lit=[("row", 0)],
          color=c)
    _arrow(p, QPointF(15, 4), QPointF(15, 16.5), BLUE)


def _fill_right(p, r, c):
    _grid(p, QRectF(2.5, 2.5, 14.5, 7), rows=1, cols=3, lit=[("col", 0)],
          color=c)
    _arrow(p, QPointF(3.5, 15), QPointF(16.5, 15), BLUE)


def _find(p, r, c):
    p.setPen(_pen(c, 1.6))
    p.setBrush(Qt.NoBrush)
    p.drawEllipse(QPointF(8.5, 8.5), 5, 5)
    p.drawLine(QPointF(12.2, 12.2), QPointF(17, 17))


def _replace(p, r, c):
    p.setPen(_pen(c, 1.3))
    p.setBrush(Qt.NoBrush)
    p.drawEllipse(QPointF(6.5, 6.5), 3.6, 3.6)
    p.drawLine(QPointF(9.2, 9.2), QPointF(11.5, 11.5))
    _arrow(p, QPointF(9, 16.5), QPointF(17.5, 16.5), BLUE, 1.4, 2.6)
    _arrow(p, QPointF(17.5, 12), QPointF(13, 12), DIM, 1.2, 2.2)



def _goto(p, r, c):
    """An arrow landing in a lit cell."""
    _grid(p, QRectF(6.5, 6.5, 11, 11), rows=2, cols=2,
          lit=[("cell", 1, 1)], color=c)
    _arrow(p, QPointF(2, 2), QPointF(10.5, 10.5), BLUE, 1.4, 2.6)


def _goto_special(p, r, c):
    """Scattered lit cells — a pick of one kind."""
    _grid(p, QRectF(2.5, 2.5, 15, 15), rows=3, cols=3,
          lit=[("cell", 0, 1), ("cell", 1, 2), ("cell", 2, 0)],
          lit_color=VIOLET, color=c)


def _pick(p, c, lit_color, mark, mark_color):
    _grid(p, QRectF(2.5, 2.5, 12, 12), rows=2, cols=2,
          lit=[("cell", 0, 1), ("cell", 1, 0)], lit_color=lit_color,
          color=c)
    _text(p, QRectF(9.5, 9.5, 10, 10), mark, mark_color, 7)


def _select_formulas(p, r, c):
    _pick(p, c, BLUE, "fx", BLUE)


def _select_constants(p, r, c):
    _pick(p, c, GREEN, "12", GREEN)


def _select_blanks(p, r, c):
    p.setPen(QPen(c, 1.1, Qt.DashLine))
    p.setBrush(Qt.NoBrush)
    p.drawRoundedRect(QRectF(2.5, 2.5, 15, 15), 1.5, 1.5)
    p.drawLine(QPointF(10, 2.5), QPointF(10, 17.5))
    p.drawLine(QPointF(2.5, 10), QPointF(17.5, 10))


def _select_errors(p, r, c):
    _pick(p, c, RED, "!", RED)


def _select_problems(p, r, c):
    _pick(p, c, AMBER, "?", AMBER)


def _dedupe(p, r, c):
    """Two matching rows, the second struck through."""
    _grid(p, QRectF(2.5, 2.5, 15, 15), rows=3, cols=1,
          lit=[("row", 0), ("row", 2)], color=c)
    p.setPen(_pen(RED, 1.5))
    p.drawLine(QPointF(4, 14.5), QPointF(16, 14.5))


def _split(p, r, c):
    """One cell of text, an arrow, two cells."""
    p.setPen(_pen(c, 1.1))
    p.setBrush(Qt.NoBrush)
    p.drawRoundedRect(QRectF(2.5, 2.5, 15, 5.5), 1, 1)
    _text(p, QRectF(2.5, 2.3, 15, 5.5), "a,b", c, 5)
    _arrow(p, QPointF(10, 8.5), QPointF(10, 12), BLUE, 1.2, 1.8)
    p.setPen(_pen(BLUE, 1.1))
    p.drawRoundedRect(QRectF(2.5, 12.5, 7, 5.5), 1, 1)
    p.drawRoundedRect(QRectF(10.5, 12.5, 7, 5.5), 1, 1)


def _letter(p, c, text, *, bold=False, italic=False, underline=False):
    font = QFont()
    font.setPixelSize(14)
    font.setBold(bold)
    font.setItalic(italic)
    font.setUnderline(underline)
    font.setFamily("serif" if italic else font.family())
    p.setFont(font)
    p.setPen(c)
    p.drawText(QRectF(1, 0, 18, 18), Qt.AlignCenter, text)


def _fmt_b(p, r, c):
    _letter(p, c, "B", bold=True)


def _fmt_i(p, r, c):
    _letter(p, c, "I", italic=True)


def _fmt_u(p, r, c):
    _letter(p, c, "U", underline=True)


def _align(p, c, side):
    p.setPen(_pen(c, 1.5))
    for y, width in ((4.5, 14), (8.5, 9), (12.5, 14), (16.5, 9)):
        if side == "left":
            x0 = 3
        elif side == "right":
            x0 = 17 - width
        else:
            x0 = 10 - width / 2
        p.drawLine(QPointF(x0, y), QPointF(x0 + width, y))


def _align_left(p, r, c):
    _align(p, c, "left")


def _align_center(p, r, c):
    _align(p, c, "center")


def _align_right(p, r, c):
    _align(p, c, "right")


def _fill_color(p, r, c):
    """A paint bucket over a yellow bar."""
    path = QPainterPath()
    path.moveTo(4, 8)
    path.lineTo(9, 3)
    path.lineTo(14.5, 8.5)
    path.lineTo(9.5, 13.5)
    path.closeSubpath()
    p.setPen(_pen(c, 1.2))
    p.setBrush(Qt.NoBrush)
    p.drawPath(path)
    p.setPen(Qt.NoPen)
    p.setBrush(c)
    p.drawEllipse(QPointF(16, 11), 1.4, 1.8)
    p.setBrush(QColor("#fde68a"))
    p.drawRect(QRectF(2.5, 15.5, 15, 3))


def _font_color(p, r, c):
    """An A over a red bar."""
    _letter(p, c, "A", bold=True)
    p.setPen(Qt.NoPen)
    p.setBrush(RED)
    p.drawRect(QRectF(2.5, 16, 15, 2.5))


def _clear_formats(p, r, c):
    _letter(p, c, "A")
    _badge(p, _BADGE, "x", RED)


def _outline(p, c, sign, *, lines=True, color=None):
    """Rows with an outline bracket and a −/+ box."""
    if lines:
        p.setPen(_pen(DIM, 1.2))
        for y in (4.5, 8.5, 12.5):
            p.drawLine(QPointF(9, y), QPointF(17.5, y))
    p.setPen(_pen(color or BLUE, 1.2))
    p.drawLine(QPointF(4.5, 3.5), QPointF(4.5, 12))
    p.drawLine(QPointF(4.5, 3.5), QPointF(6.5, 3.5))
    box = QRectF(1.5, 13, 6, 5.5)
    p.setBrush(QColor("#2a2c33"))
    p.drawRect(box)
    p.drawLine(QPointF(3, 15.75), QPointF(6, 15.75))
    if sign == "+":
        p.drawLine(QPointF(4.5, 14.25), QPointF(4.5, 17.25))


def _group(p, r, c):
    _outline(p, c, "-")
    _badge(p, _BADGE, "+", GREEN)


def _ungroup(p, r, c):
    _outline(p, c, "-")
    _badge(p, _BADGE, "-", RED)


def _hide_detail(p, r, c):
    _outline(p, c, "-")


def _show_detail(p, r, c):
    _outline(p, c, "+")


def _collapse_all(p, r, c):
    _outline(p, c, "+", lines=False)
    p.setPen(_pen(DIM, 1.2))
    p.drawLine(QPointF(9, 15.75), QPointF(17.5, 15.75))


def _expand_all(p, r, c):
    _outline(p, c, "-")
    p.setPen(_pen(DIM, 1.2))
    p.drawLine(QPointF(9, 16.5), QPointF(17.5, 16.5))


def _clear_outline(p, r, c):
    _outline(p, c, "-", color=DIM)
    _badge(p, _BADGE, "x", RED)


def _fill_series(p, r, c):
    """A column counting 1, 2, 3 with a downward arrow."""
    p.setPen(_pen(c, 1.1))
    p.setBrush(Qt.NoBrush)
    p.drawRoundedRect(QRectF(2.5, 2.5, 9, 15), 1.5, 1.5)
    for i, digit in enumerate("123"):
        _text(p, QRectF(2.5, 2.5 + i * 5, 9, 5), digit, c, 5)
    _arrow(p, QPointF(15, 3.5), QPointF(15, 17), BLUE, 1.4, 2.6)


def _note_mark(p, r, c, badge=None):
    """A cell with Excel's red note corner, and an optional badge."""
    cell = QRectF(2.5, 4.5, 15, 11)
    p.setPen(_pen(c, 1.1))
    p.setBrush(Qt.NoBrush)
    p.drawRoundedRect(cell, 1.5, 1.5)
    p.setPen(Qt.NoPen)
    p.setBrush(RED)
    path = QPainterPath()
    path.moveTo(12, 4.5)
    path.lineTo(17.5, 4.5)
    path.lineTo(17.5, 10)
    path.closeSubpath()
    p.drawPath(path)
    p.setPen(_pen(DIM, 1.1))
    p.drawLine(QPointF(5, 8.5), QPointF(10.5, 8.5))
    p.drawLine(QPointF(5, 11.5), QPointF(13, 11.5))


def _note(p, r, c):
    _note_mark(p, r, c)


def _note_delete(p, r, c):
    _note_mark(p, r, c)
    _badge(p, _BADGE, "x", RED)


def _note_next(p, r, c):
    _note_mark(p, r, c)
    _arrow(p, QPointF(9, 18), QPointF(17.5, 18), c, 1.3, 2.2)

# ------------------------------------------------------- sort and filter

def _sort(p, c, ascending: bool):
    p.setPen(_pen(c, 1.6))
    widths = (4, 7, 10) if ascending else (10, 7, 4)
    for i, w in enumerate(widths):
        y = 5 + i * 5
        p.drawLine(QPointF(3, y), QPointF(3 + w, y))
    if ascending:
        _arrow(p, QPointF(16.5, 3.5), QPointF(16.5, 16.5), BLUE)
    else:
        _arrow(p, QPointF(16.5, 16.5), QPointF(16.5, 3.5), BLUE)


def _sort_asc(p, r, c):
    _sort(p, c, True)


def _sort_desc(p, r, c):
    _sort(p, c, False)


def _sort_custom(p, r, c):
    p.setPen(_pen(c, 1.5))
    for i, w in enumerate((9, 6, 9, 6)):
        y = 3.5 + i * 4.3
        p.drawLine(QPointF(2.5, y), QPointF(2.5 + w, y))
    _arrow(p, QPointF(14, 3), QPointF(14, 16.5), BLUE, 1.3, 2.4)
    _arrow(p, QPointF(18, 16.5), QPointF(18, 3), AMBER, 1.3, 2.4)


def _validation(p, r, c):
    p.setPen(_pen(c, 1.0))
    p.setBrush(Qt.NoBrush)
    p.drawRoundedRect(QRectF(2.5, 4.5, 15, 11), 1.5, 1.5)
    p.setPen(_pen(GREEN, 1.8))
    path = QPainterPath()
    path.moveTo(6, 10.2)
    path.lineTo(8.8, 13)
    path.lineTo(14.5, 7)
    p.drawPath(path)


def _next_problem(p, r, c):
    _grid(p, QRectF(2.5, 2.5, 12, 12), rows=2, cols=2,
          lit=[("cell", 1, 1)], lit_color=RED, color=c)
    _arrow(p, QPointF(12, 17.5), QPointF(18, 17.5), c, 1.3, 2.2)


def _funnel_path() -> QPainterPath:
    path = QPainterPath()
    path.moveTo(2.5, 3.5)
    path.lineTo(16.5, 3.5)
    path.lineTo(11, 10.5)
    path.lineTo(11, 16)
    path.lineTo(8, 17.5)
    path.lineTo(8, 10.5)
    path.closeSubpath()
    return path


def _filter(p, r, c):
    p.setPen(_pen(c, 1.3))
    p.setBrush(_fill(BLUE, 90))
    p.drawPath(_funnel_path())


def _filter_clear(p, r, c):
    p.setPen(_pen(c, 1.3))
    p.setBrush(Qt.NoBrush)
    p.drawPath(_funnel_path())
    _badge(p, _BADGE, "x", RED, 3.9)


# ---------------------------------------------------------------- columns

def _col_type(p, r, c):
    p.setPen(_pen(c, 1.2))
    p.setBrush(Qt.NoBrush)
    p.drawRoundedRect(QRectF(2.5, 4, 15, 12), 2, 2)
    _text(p, QRectF(2.5, 4, 15, 12), "1A", BLUE, 8.5)


def _dropdown(p, r, c):
    p.setPen(_pen(c, 1.2))
    p.setBrush(Qt.NoBrush)
    p.drawRoundedRect(QRectF(2, 2.5, 16, 6), 1.5, 1.5)
    p.setPen(_pen(BLUE, 1.4))
    p.drawLine(QPointF(12.5, 4.6), QPointF(14, 6.2))
    p.drawLine(QPointF(14, 6.2), QPointF(15.5, 4.6))
    p.setPen(_pen(DIM, 1.2))
    for i, w in enumerate((10, 7, 9)):
        y = 11 + i * 3
        p.drawLine(QPointF(4, y), QPointF(4 + w, y))


def _rename(p, r, c):
    p.setPen(_pen(c, 1.2))
    p.setBrush(Qt.NoBrush)
    p.drawRoundedRect(QRectF(2, 6, 16, 8), 1.5, 1.5)
    _text(p, QRectF(3.5, 6, 8, 8), "ab", DIM, 6.5, align=Qt.AlignLeft
          | Qt.AlignVCenter)
    p.setPen(_pen(BLUE, 1.3))
    p.drawLine(QPointF(13.5, 3.5), QPointF(13.5, 16.5))
    p.drawLine(QPointF(11.8, 3.5), QPointF(15.2, 3.5))
    p.drawLine(QPointF(11.8, 16.5), QPointF(15.2, 16.5))


def _fit(p, r, c):
    p.setPen(_pen(c, 1.2))
    p.drawLine(QPointF(3, 3), QPointF(3, 17))
    p.drawLine(QPointF(17, 3), QPointF(17, 17))
    _arrow(p, QPointF(10, 10), QPointF(5, 10), BLUE, 1.4, 2.6)
    _arrow(p, QPointF(10, 10), QPointF(15, 10), BLUE, 1.4, 2.6)


# --------------------------------------------------------------- freezing

def _freeze_grid(p, c, rows: bool, cols: bool):
    box = QRectF(2.5, 2.5, 15, 15)
    lit = []
    if rows:
        lit.append(("row", 0))
    if cols:
        lit.append(("col", 0))
    _grid(p, box, lit=lit, color=c)
    p.setPen(_pen(BLUE, 1.9))
    if rows:
        p.drawLine(QPointF(box.left(), box.top() + 5),
                   QPointF(box.right(), box.top() + 5))
    if cols:
        p.drawLine(QPointF(box.left() + 5, box.top()),
                   QPointF(box.left() + 5, box.bottom()))


def _freeze(p, r, c):
    _freeze_grid(p, c, True, True)


def _freeze_row(p, r, c):
    _freeze_grid(p, c, True, False)


def _freeze_col(p, r, c):
    _freeze_grid(p, c, False, True)


def _unfreeze(p, r, c):
    _grid(p, QRectF(2.5, 2.5, 15, 15), color=c)
    _badge(p, _BADGE, "x", RED, 3.9)


# --------------------------------------------------------------- formulas

def _fx(p, r, c):
    _text(p, QRectF(0, 0, 20, 20), "fx", c, 12, bold=True, italic=True)


def _show_formulas(p, r, c):
    p.setPen(_pen(c, 1.2))
    p.setBrush(Qt.NoBrush)
    p.drawRoundedRect(QRectF(2, 4, 16, 12), 2, 2)
    _text(p, QRectF(2, 4, 16, 12), "=A1", BLUE, 6.8)


def _reference(p, r, c):
    p.setPen(_pen(c, 1.2))
    p.setBrush(Qt.NoBrush)
    path = QPainterPath()
    path.moveTo(10, 5)
    path.cubicTo(7, 3, 4, 3, 2.5, 4)
    path.lineTo(2.5, 16)
    path.cubicTo(4, 15, 7, 15, 10, 17)
    path.cubicTo(13, 15, 16, 15, 17.5, 16)
    path.lineTo(17.5, 4)
    path.cubicTo(16, 3, 13, 3, 10, 5)
    p.drawPath(path)
    p.drawLine(QPointF(10, 5), QPointF(10, 17))
    _text(p, QRectF(10, 5, 7.5, 9), "fx", BLUE, 5.5, italic=True)


# ----------------------------------------------------------- applying

def _submit(p, r, c):
    p.setPen(_pen(c, 2.0))
    p.setBrush(Qt.NoBrush)
    p.drawLine(QPointF(4, 10.5), QPointF(8, 14.5))
    p.drawLine(QPointF(8, 14.5), QPointF(16, 5.5))


def _discard(p, r, c):
    p.setPen(_pen(c, 1.8))
    p.drawLine(QPointF(5, 5), QPointF(15, 15))
    p.drawLine(QPointF(5, 15), QPointF(15, 5))


def _auto(p, r, c):
    path = QPainterPath()
    path.moveTo(11.5, 2)
    path.lineTo(4.5, 11)
    path.lineTo(9.5, 11)
    path.lineTo(8, 18)
    path.lineTo(15.5, 8.5)
    path.lineTo(10.5, 8.5)
    path.closeSubpath()
    p.setPen(_pen(c, 1.1))
    p.setBrush(_fill(c, 110))
    p.drawPath(path)


def _expand(p, r, c):
    p.setPen(_pen(c, 1.3))
    p.setBrush(Qt.NoBrush)
    p.drawRoundedRect(QRectF(3, 5, 12, 12), 1.5, 1.5)
    _arrow(p, QPointF(10, 10), QPointF(17, 3), BLUE, 1.4, 3)


def _collapse(p, r, c, up=True):
    p.setPen(_pen(c, 1.6))
    if up:
        p.drawLine(QPointF(5, 12.5), QPointF(10, 7.5))
        p.drawLine(QPointF(10, 7.5), QPointF(15, 12.5))
    else:
        p.drawLine(QPointF(5, 7.5), QPointF(10, 12.5))
        p.drawLine(QPointF(10, 12.5), QPointF(15, 7.5))


def _chevron_up(p, r, c):
    _collapse(p, r, c, True)


def _chevron_down(p, r, c):
    _collapse(p, r, c, False)


def _select_all(p, r, c):
    _grid(p, QRectF(2.5, 2.5, 15, 15), lit=[("row", 0), ("row", 1),
                                            ("row", 2)], color=c)


# ------------------------------------------------------------ number formats

def _currency_symbol() -> str:
    from PySide6.QtCore import QLocale
    symbol = QLocale().currencySymbol(QLocale.CurrencySymbol)
    return symbol if symbol and len(symbol) <= 2 else "$"


def _fmt_currency(p, r, c):
    p.setPen(_pen(c, 1.2))
    p.setBrush(Qt.NoBrush)
    p.drawRoundedRect(QRectF(2, 4, 16, 12), 2, 2)
    _text(p, QRectF(2, 4, 16, 12), _currency_symbol(), GREEN, 10)


def _fmt_percent(p, r, c):
    _text(p, QRectF(0, 0, 20, 20), "%", c, 14)


def _fmt_thousands(p, r, c):
    _text(p, QRectF(0, 2, 20, 16), ",000", c, 8)


def _decimals(p, c, more: bool):
    _text(p, QRectF(0, 1, 20, 9), ".0" if more else ".00", c, 7.5)
    _text(p, QRectF(0, 10, 20, 9), ".00" if more else ".0", BLUE, 7.5)
    _arrow(p, QPointF(3, 13), QPointF(3, 18) if more else QPointF(3, 8),
           DIM, 1.1, 2)


def _dec_more(p, r, c):
    _decimals(p, c, True)


def _dec_less(p, r, c):
    _decimals(p, c, False)


def _format(p, r, c):
    p.setPen(_pen(c, 1.2))
    p.setBrush(Qt.NoBrush)
    p.drawRoundedRect(QRectF(2, 4, 16, 12), 2, 2)
    _text(p, QRectF(2, 4, 16, 12), "1.2", BLUE, 8)


# ----------------------------------------------- conditional formatting

def _cf_scale(p, r, c):
    for i, colour in enumerate(("#a4373a", "#b0902f", "#2e7d46")):
        p.fillRect(QRectF(3, 3 + i * 5, 14, 4.5), QColor(colour))
    p.setPen(_pen(c, 1.0))
    p.setBrush(Qt.NoBrush)
    p.drawRoundedRect(QRectF(2.5, 2.5, 15, 15.5), 1.5, 1.5)


def _cf_bar(p, r, c):
    p.setPen(_pen(c, 1.0))
    p.setBrush(Qt.NoBrush)
    p.drawRoundedRect(QRectF(2.5, 2.5, 15, 15), 1.5, 1.5)
    for i, width in enumerate((11, 6, 8.5)):
        p.fillRect(QRectF(4, 4.5 + i * 4.3, width, 3), BLUE)


def _cf_icons(p, r, c):
    for i, colour in enumerate((RED, AMBER, GREEN)):
        p.setPen(Qt.NoPen)
        p.setBrush(colour)
        p.drawEllipse(QPointF(5 + i * 5, 10), 2.3, 2.3)


def _cf_highlight(p, r, c):
    _grid(p, QRectF(2.5, 2.5, 15, 15), lit=[("cell", 1, 1)],
          lit_color=AMBER, color=c)


def _cf_manage(p, r, c):
    p.setPen(_pen(c, 1.3))
    for i in range(3):
        y = 5 + i * 5
        p.drawLine(QPointF(8, y), QPointF(17, y))
    for i, colour in enumerate((RED, AMBER, GREEN)):
        p.fillRect(QRectF(2.5, 3 + i * 5, 4, 4), colour)


def _cond_format(p, r, c):
    _cf_scale(p, r, c)


def _totals(p, r, c):
    _grid(p, QRectF(2.5, 2.5, 15, 15), lit=[("row", 2)], lit_color=BLUE,
          color=c)
    _text(p, QRectF(2.5, 12.5, 15, 5), "Σ", QColor("#f3f4f6"), 5.5)


GLYPHS = {
    "totals": (_totals, FG),
    "cf_scale": (_cf_scale, FG), "cf_bar": (_cf_bar, FG),
    "cf_icons": (_cf_icons, FG), "cf_highlight": (_cf_highlight, FG),
    "cf_manage": (_cf_manage, FG), "cond_format": (_cond_format, FG),
    "fmt_currency": (_fmt_currency, FG), "fmt_percent": (_fmt_percent, FG),
    "fmt_thousands": (_fmt_thousands, FG), "dec_more": (_dec_more, FG),
    "dec_less": (_dec_less, FG), "format": (_format, FG),
    "paste": (_paste, FG), "paste_values": (_paste_values, FG),
    "paste_special": (_paste_special, FG),
    "goto": (_goto, FG), "goto_special": (_goto_special, FG),
    "dedupe": (_dedupe, FG), "split": (_split, FG),
    "fill_series": (_fill_series, FG),
    "group": (_group, FG), "ungroup": (_ungroup, FG),
    "hide_detail": (_hide_detail, FG), "show_detail": (_show_detail, FG),
    "collapse_all": (_collapse_all, FG), "expand_all": (_expand_all, FG),
    "clear_outline": (_clear_outline, FG),
    "fmt_b": (_fmt_b, FG), "fmt_i": (_fmt_i, FG), "fmt_u": (_fmt_u, FG),
    "align_left": (_align_left, FG), "align_center": (_align_center, FG),
    "align_right": (_align_right, FG), "fill_color": (_fill_color, FG),
    "font_color": (_font_color, FG), "clear_formats": (_clear_formats, FG),
    "note": (_note, FG), "note_delete": (_note_delete, FG),
    "note_next": (_note_next, FG), "select_notes": (_note, FG),
    "select_formulas": (_select_formulas, FG),
    "select_constants": (_select_constants, FG),
    "select_blanks": (_select_blanks, FG),
    "select_errors": (_select_errors, FG),
    "select_problems": (_select_problems, FG),
    "paste_transpose": (_paste_transpose, FG),
    "cut": (_cut, FG), "copy": (_copy, FG),
    "copy_headers": (_copy_headers, FG),
    "undo": (_undo, FG), "redo": (_redo, FG),
    "row_above": (_row_above, FG), "row_below": (_row_below, FG),
    "row_delete": (_row_delete, FG),
    "col_left": (_col_left, FG), "col_right": (_col_right, FG),
    "col_delete": (_col_delete, FG),
    "row_up": (_row_up, FG), "row_down": (_row_down, FG),
    "col_move_left": (_col_move_left, FG),
    "col_move_right": (_col_move_right, FG),
    "select_row": (_select_row, FG), "select_col": (_select_col, FG),
    "select_all": (_select_all, FG),
    "header": (_header, FG),
    "clear": (_clear, FG), "fill_down": (_fill_down, FG),
    "fill_right": (_fill_right, FG),
    "find": (_find, FG), "replace": (_replace, FG),
    "sort_asc": (_sort_asc, FG), "sort_desc": (_sort_desc, FG),
    "sort_custom": (_sort_custom, FG),
    "validation": (_validation, FG), "next_problem": (_next_problem, FG),
    "filter": (_filter, FG), "filter_clear": (_filter_clear, FG),
    "col_type": (_col_type, FG), "dropdown": (_dropdown, FG),
    "rename": (_rename, FG), "fit": (_fit, FG),
    "freeze": (_freeze, FG), "freeze_row": (_freeze_row, FG),
    "freeze_col": (_freeze_col, FG), "unfreeze": (_unfreeze, FG),
    "fx": (_fx, FG), "show_formulas": (_show_formulas, FG),
    "reference": (_reference, FG),
    "submit": (_submit, GREEN), "discard": (_discard, RED),
    "auto": (_auto, AMBER), "expand": (_expand, FG),
    "chevron_up": (_chevron_up, FG), "chevron_down": (_chevron_down, FG),
}


#: logical sizes the grid shows its icons at (menus and small buttons 20,
#: large buttons 24, the odd 16) and the screen scales they are drawn for
_SIZES = (16, 20, 24)
_RATIOS = (1.0, 1.25, 1.5, 2.0)


def _render(name: str, size: int, ratio: float, disabled: bool) -> QPixmap:
    """The glyph drawn as vectors straight onto a pixmap of `size` logical
    pixels at `ratio`.

    The glyphs sit on a 20-point grid (lines on half points): drawn at a
    whole multiple of 20 device pixels they land on pixels and stay sharp,
    so a 24 px slot gets the 20 px glyph centred rather than a blurred 1.2x
    one; below 20 there is no whole multiple and the glyph is scaled down
    as well as it can be."""
    painter_fn, color = GLYPHS[name]
    device = max(1, round(size * ratio))
    pixmap = QPixmap(device, device)
    pixmap.fill(Qt.transparent)
    pixmap.setDevicePixelRatio(ratio)
    p = QPainter(pixmap)
    p.setRenderHint(QPainter.Antialiasing, True)
    p.setRenderHint(QPainter.TextAntialiasing, True)
    if disabled:
        # a greyed-out command should look greyed out, not merely refuse
        # the click
        p.setOpacity(0.38)
    whole = int(device // _PT)
    drawn = whole * _PT if whole >= 1 else device
    offset = round((device - drawn) / 2) / ratio
    p.translate(offset, offset)
    p.scale(drawn / ratio / _PT, drawn / ratio / _PT)
    painter_fn(p, QRectF(0, 0, _PT, _PT), color)
    p.end()
    return pixmap


@lru_cache(maxsize=None)
def sheet_icon(name: str) -> QIcon:
    """The glyph called `name` as an icon holding a pixmap drawn at every
    size and screen scale it is shown at, so Qt picks an exact one and never
    resamples (a 20 px drawing shrunk to 16 or stretched to 24 smeared every
    line). Plain pixmaps, not a Python QIconEngine: Qt clones an icon's
    engine when a copy is changed, and a clone made in Python is freed
    under it."""
    if name not in GLYPHS:
        raise KeyError(name)
    icon = QIcon()
    for mode, disabled in ((QIcon.Normal, False), (QIcon.Disabled, True)):
        for size in _SIZES:
            for ratio in _RATIOS:
                icon.addPixmap(_render(name, size, ratio, disabled), mode)
    return icon
