"""Printing a rendered report to PDF: the page, the cover, the furniture.

QPdfWriter rather than the web engine: the preview is already a
QTextDocument, and printing that same document is what makes the PDF match
what was on screen. It is also synchronous, which means an export either
worked or raised by the time the call returns — no callback to lose.

The document is painted page by page rather than handed to
`QTextDocument.print_`, because print_ owns the whole sheet and leaves no
room in the margins for anything else. Running headers and footers *are*
that room, so the page loop has to be here. What print_ does invisibly and
is easy to lose in the transcription is called out below — the black text
colour especially.

Geometry comes from core.page_setup, which is deliberately not expressed in
Qt's vocabulary; the conversion happens here and nowhere else.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QMarginsF, QRectF, QSizeF, Qt
from PySide6.QtGui import (QFont, QPageLayout, QPageSize, QPainter, QPalette,
                           QPdfWriter, QTextDocument)

from flograph.core.page_setup import (BAND_FONT_SIZE, BAND_HEIGHT,
                                      MM_PER_POINT, PAGE_SIZES, PageSetup,
                                      expand, today)

# 72, i.e. one device unit per point — NOT a quality setting.
#
# A QTextDocument sizes its fonts in points and resolves them against the
# *application's* DPI, so the page it is laid out into has to be measured in
# the same units or the two disagree. Setting the page to A4 in 300dpi
# device pixels (2480 wide) while 11pt text stays ~15 units tall is what
# made exported reports come out as a tiny block in the corner of the sheet.
# At 72 the page is 595 units wide, 11pt text is 11 units, and the margins
# below land where they were asked to.
#
# Print quality is unaffected: text is vector, and embedded images are
# carried at their own pixel size (see IMAGE_SCALE in render.py), not
# resampled to this resolution.
RESOLUTION = 72

#: Kept for the one caller that predates page setup and for anything that
#: wants the old default without constructing a PageSetup.
MARGIN_MM = PageSetup().margin_top

#: Point sizes on the cover. Big, then smaller, then quiet — the whole
#: design of a cover page is that hierarchy and nothing else.
COVER_TITLE_PT = 26.0
COVER_SUBTITLE_PT = 14.0
COVER_DATE_PT = 11.0

#: Where the title sits down the page, as a fraction of the printable
#: height. Slightly above centre, which is where a title looks centred.
COVER_TITLE_AT = 0.38


def _page_size(setup: PageSetup) -> QPageSize:
    """The sheet, portrait — orientation is QPageLayout's job.

    A named QPageSize where the name is one Qt knows, so the PDF reports
    itself as A4 rather than as an anonymous 595x842 box, and a custom size
    built from millimetres otherwise.
    """
    standard = {
        "A3": QPageSize.A3, "A4": QPageSize.A4, "A5": QPageSize.A5,
        "Letter": QPageSize.Letter, "Legal": QPageSize.Legal,
        "Tabloid": QPageSize.Tabloid,
    }.get(setup.size)
    if standard is not None:
        return QPageSize(standard)
    width, height = PAGE_SIZES.get(setup.size, PAGE_SIZES["A4"])
    return QPageSize(QSizeF(width, height), QPageSize.Millimeter)


def page_layout(setup: Optional[PageSetup] = None,
                landscape: Optional[bool] = None) -> QPageLayout:
    """`setup` as a Qt page layout.

    `landscape` overrides the setup's own orientation; it is what the
    pre-page-setup callers passed and it stays because "print this one
    sideways" is a reasonable thing to ask without editing the page.
    """
    setup = setup or PageSetup()
    sideways = setup.landscape if landscape is None else bool(landscape)
    return QPageLayout(
        _page_size(setup),
        QPageLayout.Landscape if sideways else QPageLayout.Portrait,
        # QMarginsF is left, top, right, bottom — not the CSS order
        QMarginsF(setup.margin_left, setup.margin_top,
                  setup.margin_right, setup.margin_bottom),
        QPageLayout.Millimeter)


def sheet_points(setup: PageSetup) -> QSizeF:
    """The whole sheet in points, orientation applied.

    The PDF writer never needs this — its painter starts inside the margins
    — but a preview that draws paper has to draw the paper.
    """
    width, height = setup.page_mm()
    return QSizeF(width / MM_PER_POINT, height / MM_PER_POINT)


def printable_points(setup: PageSetup) -> QRectF:
    """The printable area *positioned within the sheet*, in points.

    The one place the two renderers legitimately differ: painting a PDF
    starts at this rect's top-left, so export passes an equivalent rect at
    the origin; painting a preview starts at the corner of the paper, so it
    passes this one. Everything downstream takes the rect and asks no
    questions.
    """
    sheet = sheet_points(setup)
    left = setup.margin_left / MM_PER_POINT
    top = setup.margin_top / MM_PER_POINT
    return QRectF(
        left, top,
        max(1.0, sheet.width() - left - setup.margin_right / MM_PER_POINT),
        max(1.0, sheet.height() - top - setup.margin_bottom / MM_PER_POINT))


def body_rect(printable: QRectF, setup: PageSetup) -> QRectF:
    """The printable area with the header and footer bands taken out.

    A band is only subtracted when it has something in it, so a report with
    no running elements gets the whole page — which is what makes the
    defaults print exactly as they did before any of this existed.
    """
    top = BAND_HEIGHT if setup.has_header() else 0.0
    bottom = BAND_HEIGHT if setup.has_footer() else 0.0
    return QRectF(printable.left(), printable.top() + top,
                  printable.width(),
                  max(1.0, printable.height() - top - bottom))


def _draw_band(painter: QPainter, rect: QRectF, fields: tuple,
               page: int, pages: int, title: str, date: str) -> None:
    """One running header or footer: left, centre and right in one line."""
    left, center, right = (expand(f, page, pages, title, date)
                           for f in fields)
    if not any((left, center, right)):
        return
    font = QFont(painter.font())
    font.setPointSizeF(BAND_FONT_SIZE)
    painter.save()
    painter.setFont(font)
    painter.setPen(Qt.black)
    for text, align in ((left, Qt.AlignLeft), (center, Qt.AlignHCenter),
                        (right, Qt.AlignRight)):
        if text:
            painter.drawText(rect, int(align | Qt.AlignVCenter), text)
    painter.restore()


def _draw_cover(painter: QPainter, printable: QRectF, setup: PageSetup,
                title: str, date: str) -> None:
    """The cover: a title, an optional line under it, an optional date.

    Not part of the markdown, on purpose — a cover written into the body
    would have to be deleted to turn the cover off, and would be the first
    thing every embed-resolution error pointed at.
    """
    painter.save()
    painter.setPen(Qt.black)
    y = printable.top() + printable.height() * COVER_TITLE_AT

    font = QFont(painter.font())
    font.setPointSizeF(COVER_TITLE_PT)
    font.setBold(True)
    painter.setFont(font)
    heading = expand(setup.cover_title, 0, 0, title, date) or title
    box = QRectF(printable.left(), y, printable.width(), COVER_TITLE_PT * 2.2)
    painter.drawText(box, int(Qt.AlignHCenter | Qt.AlignTop), heading)
    y += COVER_TITLE_PT * 2.2

    if setup.cover_subtitle:
        font = QFont(painter.font())
        font.setPointSizeF(COVER_SUBTITLE_PT)
        font.setBold(False)
        painter.setFont(font)
        box = QRectF(printable.left(), y, printable.width(),
                     COVER_SUBTITLE_PT * 2.2)
        painter.drawText(
            box, int(Qt.AlignHCenter | Qt.AlignTop),
            expand(setup.cover_subtitle, 0, 0, title, date))
        y += COVER_SUBTITLE_PT * 2.2

    if setup.cover_date:
        font = QFont(painter.font())
        font.setPointSizeF(COVER_DATE_PT)
        font.setBold(False)
        painter.setFont(font)
        box = QRectF(printable.left(), y + COVER_DATE_PT, printable.width(),
                     COVER_DATE_PT * 2.2)
        painter.drawText(box, int(Qt.AlignHCenter | Qt.AlignTop), date)
    painter.restore()


def paint_context():
    """A paint context with black text.

    What QTextDocument.print_ does and a hand-rolled page loop forgets:
    without it the text is drawn in the *application palette's* text
    colour, so a report exported — or previewed — under a dark theme is
    near-white on a white sheet.
    """
    from PySide6.QtGui import QAbstractTextDocumentLayout
    context = QAbstractTextDocumentLayout.PaintContext()
    context.palette.setColor(QPalette.Text, Qt.black)
    return context


def paint_body(painter: QPainter, layout, context, body: QRectF,
               index: int) -> None:
    """One page's worth of the document, drawn into `body`.

    Clip before translating: the clip is taken in the coordinates in force
    when it is set, and those are the page's. Without it a tall image on
    the last page bleeds down into the footer.
    """
    painter.save()
    painter.setClipRect(body)
    painter.translate(body.left(), body.top() - index * body.height())
    context.clip = QRectF(0, index * body.height(),
                          body.width(), body.height())
    layout.draw(painter, context)
    painter.restore()


def paint_furniture(painter: QPainter, printable: QRectF, setup: PageSetup,
                    number: int, pages: int, title: str, date: str) -> None:
    """The running header and footer for one page."""
    if setup.has_header():
        _draw_band(painter,
                   QRectF(printable.left(), printable.top(),
                          printable.width(), BAND_HEIGHT),
                   setup.header_fields(), number, pages, title, date)
    if setup.has_footer():
        _draw_band(painter,
                   QRectF(printable.left(), printable.bottom() - BAND_HEIGHT,
                          printable.width(), BAND_HEIGHT),
                   setup.footer_fields(), number, pages, title, date)


def paint_cover(painter: QPainter, printable: QRectF, setup: PageSetup,
                title: str, date: str) -> None:
    _draw_cover(painter, printable, setup, title, date)


def page_count(document: QTextDocument, setup: PageSetup) -> int:
    """How many *body* pages this document makes on this paper — a cover,
    if there is one, is not one of them."""
    body = body_rect(printable_points(setup), setup)
    copy = document.clone()
    copy.setPageSize(QSizeF(body.width(), body.height()))
    return max(1, copy.pageCount())


def export_pdf(document: QTextDocument, path: str, title: str = "",
               landscape: Optional[bool] = None,
               setup: Optional[PageSetup] = None) -> str:
    """Write `document` to `path` as a PDF and return the path.

    The document is laid out to the *body* rect first: a QTextDocument
    keeps whatever text width it was last given, so printing one sized for
    an on-screen preview would otherwise reflow at the wrong measure and
    push tables off the page. Setting the page size is also what gives Qt
    something to paginate against — `pageCount()` is meaningless until it
    knows how tall a page is.

    A clone is printed so the live preview isn't re-flowed underneath the
    user by the act of exporting.
    """
    setup = setup or PageSetup()
    writer = QPdfWriter(path)
    writer.setResolution(RESOLUTION)
    writer.setPageLayout(page_layout(setup, landscape))
    if title:
        writer.setTitle(title)

    # Origin at (0, 0), *not* at the margin: a QPdfWriter's painter already
    # starts at the top-left of the printable area, so a rect positioned at
    # the margins would apply them a second time — content shifted down and
    # right by exactly one margin, and clipped off the far edges.
    printable = QRectF(
        0.0, 0.0,
        writer.pageLayout().paintRectPixels(RESOLUTION).width(),
        writer.pageLayout().paintRectPixels(RESOLUTION).height())
    body = body_rect(printable, setup)
    copy = document.clone()
    copy.setPageSize(QSizeF(body.width(), body.height()))

    date = today()
    layout = copy.documentLayout()
    context = paint_context()

    painter = QPainter()
    if not painter.begin(writer):
        raise OSError(f"could not open {path} for writing")
    try:
        pages = max(1, copy.pageCount())
        if setup.cover:
            paint_cover(painter, printable, setup, title, date)
            writer.newPage()
        for index in range(pages):
            if index:
                writer.newPage()
            paint_body(painter, layout, context, body, index)
            if index == 0 and not setup.bands_on_first_page:
                continue
            paint_furniture(painter, printable, setup,
                            setup.first_page_number + index, pages,
                            title, date)
    finally:
        painter.end()
    return path
