"""Printing a rendered report to PDF.

QPdfWriter rather than the web engine: the preview is already a
QTextDocument, and printing that same document is what makes the PDF match
what was on screen. It is also synchronous, which means an export either
worked or raised by the time the call returns — no callback to lose.
"""
from __future__ import annotations

from PySide6.QtCore import QMarginsF
from PySide6.QtGui import QPageLayout, QPageSize, QPdfWriter

# Generous enough that a printer's unprintable edge can't clip the text, and
# close to what a word processor would default to.
MARGIN_MM = 15.0

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


def page_layout(landscape: bool = False,
                page_size: QPageSize.PageSizeId = QPageSize.A4) -> QPageLayout:
    return QPageLayout(
        QPageSize(page_size),
        QPageLayout.Landscape if landscape else QPageLayout.Portrait,
        QMarginsF(MARGIN_MM, MARGIN_MM, MARGIN_MM, MARGIN_MM),
        QPageLayout.Millimeter)


def export_pdf(document, path: str, title: str = "",
               landscape: bool = False) -> str:
    """Write `document` to `path` as a PDF and return the path.

    The document is laid out to the printable rect first: a QTextDocument
    keeps whatever text width it was last given, so printing one sized for
    an on-screen preview would otherwise reflow at the wrong measure and
    push tables off the page. Setting the *page* size (not just the width)
    is also what gives Qt something to paginate against.

    A clone is printed so the live preview isn't re-flowed underneath the
    user by the act of exporting.
    """
    from PySide6.QtCore import QSizeF

    writer = QPdfWriter(path)
    writer.setResolution(RESOLUTION)
    writer.setPageLayout(page_layout(landscape))
    if title:
        writer.setTitle(title)

    printable = writer.pageLayout().paintRectPixels(RESOLUTION)
    copy = document.clone()
    copy.setPageSize(QSizeF(printable.size()))
    copy.print_(writer)
    return path
