"""Rendering and painting for the PDF card.

The sibling of `image_card`, and deliberately shaped like it: a NodeItem
holds one of these, calls `set_source` when its params change and `paint`
when it draws, and the class does the rest. The two are close enough that
NodeItem drives them through the same call sites — see `_card_image` — and
different enough to be separate classes, because a picture decodes and a
page renders.

The same three rules keep a canvas full of PDF cards as cheap as a canvas
full of ordinary nodes:

1. **Render at display size, never at page size.** pdfium rasterises to
   whatever QSize it is handed, so an A4 page on a 320x240 card costs a
   320x240 buffer rather than a print-resolution one. The result is cached
   and re-rendered only when the target size actually changes.
2. **No proxy widget.** The page is painted straight onto the item, exactly
   as the image card paints artwork. Qt ships a real PDF *viewer* widget
   (QPdfView) and using it here would put a QWidget with its own backing
   store on every card; a rendered page is a QImage and costs what one
   costs.
3. **One page at a time.** A card shows the page it was asked for. A
   400-page document on the canvas is one page of pixels, and the document
   itself is read from disk as pdfium needs it.

The document is held open between paints — reopening it per frame would
re-parse the file on every repaint — and closed as soon as the source
changes or the card goes away.
"""
from __future__ import annotations

import hashlib
from typing import Callable, Optional

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QImage, QPainter, QPixmap

from flograph.core.pdfsource import resolve_source
from flograph.pdfdoc import MAX_RENDER_PIXELS, PdfDocument, PdfError, budgeted

from .image_card import DEFAULT_FIT, FIT_MODES, SCALE_MAX, SCALE_MIN, target_size

# What a card shows before anything has been picked.
EMPTY_HINT = ("Drop a PDF here, or pick a file in the properties panel.")


def pdf_source(node, payload=None) -> str:
    """What a PDF node's card or tile should draw.

    Normally the node's own param, so a dropped document shows up without
    the graph being run at all. `payload` is the node's cached output when
    there is one: a source that arrived on a *wire* only exists once the
    node has run, so it wins while it lasts. A `document` dict from Read PDF
    counts — its `path` is exactly what the card needs. Shared by the canvas
    card and the dashboard tile so one node cannot show two different
    documents.
    """
    if isinstance(payload, dict):
        wired = payload.get("source") or payload.get("path")
        if wired:
            return str(wired)
    return str(node.params.get("path", "") or "")


def on_paper(page: QImage) -> QImage:
    """A rendered page composited onto white.

    pdfium renders a page onto transparency — it draws the marks, not the
    paper — so a page dropped straight onto a dark card is black text on a
    dark body, which is to say invisible. Every PDF reader shows paper as
    white whatever the surrounding chrome is doing, and so does this. It
    also drops the alpha channel, so the cached pixmap is three bytes a
    pixel rather than four.
    """
    paper = QImage(page.size(), QImage.Format_RGB32)
    paper.fill(Qt.white)
    painter = QPainter(paper)
    painter.drawImage(0, 0, page)
    painter.end()
    return paper


class CardPdf:
    """The page behind one PDF card: opens, renders, paints.

    Owned by a NodeItem, which supplies `on_frame` — unused today (a page
    does not animate) but kept so the two card classes are interchangeable
    from the item's side. Everything here runs on the GUI thread; nothing
    here touches the graph.
    """

    def __init__(self, on_frame: Callable[[], None]) -> None:
        self._on_frame = on_frame
        self._source = ""
        self._password = ""
        self._key = ""
        self._fit = DEFAULT_FIT
        self._scale = 1.0
        self._page = 0            # 0-based; the param is 1-based
        self._doc: Optional[PdfDocument] = None
        self._pixmap: Optional[QPixmap] = None
        self._rendered_key: tuple = ()
        self._ratio = 1.0
        self.error = ""

    # ------------------------------------------------------------- source

    def set_source(self, source: str, fit: str = DEFAULT_FIT,
                   scale: float = 1.0, page: int = 1,
                   password: str = "") -> None:
        """Point the card at a path, a `data:` URI or a base64 blob.

        Cheap and idempotent: an unchanged source does nothing at all, and
        re-rendering is deferred to the next paint. Opening happens here
        rather than in paint() so a document is parsed once when it is set,
        not once per frame.
        """
        source = str(source or "").strip()
        password = str(password or "")
        scale = min(SCALE_MAX, max(SCALE_MIN, scale))
        page = max(1, int(page or 1)) - 1
        if (source == self._source and password == self._password
                and fit == self._fit and scale == self._scale
                and page == self._page):
            return
        if source != self._source or password != self._password:
            self._release()
            self._source = source
            self._password = password
            self._open()
        self._fit = fit if fit in FIT_MODES else DEFAULT_FIT
        self._scale = scale
        self._page = page
        self._rendered_key = ()  # force a re-render at the next paint

    def _open(self) -> None:
        """Open whatever the current source string points at."""
        self.error = ""
        self._key = ""
        if not self._source:
            return
        try:
            data, path = resolve_source(self._source, need_bytes=False)
            self._doc = PdfDocument.open(data, path, self._password)
        except (ValueError, FileNotFoundError, OSError, PdfError) as exc:
            self.error = str(exc)
            return
        self._key = (f"file:{path}" if path
                     else "blob:" + hashlib.sha256(data).hexdigest()[:16])

    def reload(self) -> None:
        """Re-read the document from disk (a re-run may have rewritten it)."""
        source, password = self._source, self._password
        self._release()
        self._source, self._password = source, password
        self._open()
        self._rendered_key = ()

    def _release(self) -> None:
        if self._doc is not None:
            self._doc.close()
            self._doc = None
        self._source = ""
        self._password = ""
        self._pixmap = None
        self._rendered_key = ()
        self.error = ""

    # --------------------------------------------------------------- shape

    def page_count(self) -> int:
        return self._doc.page_count if self._doc is not None else 0

    def _clamped_page(self) -> int:
        """The page actually shown. A page number past the end of the
        document shows the last page rather than an error: the number is a
        parameter someone is dragging, and a document that got shorter
        should not turn the card into a message."""
        return max(0, min(self._page, self.page_count() - 1))

    def natural_size(self) -> QSize:
        """The page's own size, one PDF point per logical pixel."""
        if self._doc is None or not self.page_count():
            return QSize()
        width, height = self._doc.page_size(self._clamped_page())
        return QSize(max(1, round(width)), max(1, round(height)))

    def is_animated(self) -> bool:
        return False

    def has_content(self) -> bool:
        return self._doc is not None and self.page_count() > 0 and not self.error

    # ------------------------------------------------------------ playback

    def set_playing(self, playing: bool) -> None:
        """Nothing to play — a page is still. Present so a NodeItem can hold
        either card class without asking which it has."""

    # -------------------------------------------------------------- render

    def _ensure(self, box: QSize, ratio: float) -> None:
        """Render (or re-render) the page for a `box`-sized content area.

        `ratio` is device pixels per logical pixel — screen DPR times canvas
        zoom — so a card inspected close up is sharp rather than upscaled
        from a card-sized buffer. Quantised to halves so panning and small
        zoom nudges don't each trigger a fresh render.
        """
        if self._doc is None or box.isEmpty():
            return
        natural = self.natural_size()
        if natural.isEmpty():
            return
        ratio = min(4.0, max(1.0, round(ratio * 2) / 2))
        logical = target_size(natural, box, self._fit, self._scale)
        wanted = budgeted(QSize(max(1, round(logical.width() * ratio)),
                                max(1, round(logical.height() * ratio))))
        page = self._clamped_page()
        key = (self._key, page, self._fit, self._scale,
               wanted.width(), wanted.height())
        if key == self._rendered_key:
            return
        self._rendered_key = key
        # The painted size is derived back from the buffer, so a budget-
        # clamped render still lands in the right place on the card.
        self._ratio = (wanted.width() / logical.width()
                       if logical.width() else 1.0)
        image = self._doc.render(page, wanted)
        if image.isNull():
            self.error = f"page {page + 1} could not be rendered"
            self._pixmap = None
            return
        self.error = ""
        self._pixmap = QPixmap.fromImage(on_paper(image))

    # --------------------------------------------------------------- paint

    def paint(self, painter: QPainter, rect: QRectF, ratio: float = 1.0) -> None:
        """Draw the page centred in `rect`, clipped to it."""
        box = QSize(max(1, int(rect.width())), max(1, int(rect.height())))
        self._ensure(box, ratio)
        pixmap = self._pixmap
        if pixmap is None or pixmap.isNull():
            return
        width = pixmap.width() / self._ratio
        height = pixmap.height() / self._ratio
        painter.save()
        # Intersect, never replace: the card sets a rounded-corner clip
        # before calling in, and a Fill/Stretch page would otherwise paint
        # square corners over the card's round ones.
        painter.setClipRect(rect, Qt.IntersectClip)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        painter.drawPixmap(self._centred(rect, width, height), pixmap,
                           QRectF(pixmap.rect()))
        painter.restore()

    def page_caption(self) -> str:
        """"3 / 12" for the card's pager, or "" with no document."""
        total = self.page_count()
        if not total:
            return ""
        return f"{self.shown_page()} / {total}"

    def shown_page(self) -> int:
        """The 1-based page actually on screen, which is not always the page
        that was asked for — see `_clamped_page`. The card's chevrons step
        from here rather than from the param, so a page number left past the
        end of a shorter document steps back into it instead of counting up
        through pages that aren't there."""
        return self._clamped_page() + 1

    @staticmethod
    def _centred(rect: QRectF, width: float, height: float) -> QRectF:
        return QRectF(rect.x() + (rect.width() - width) / 2.0,
                      rect.y() + (rect.height() - height) / 2.0,
                      width, height)


__all__ = ["CardPdf", "EMPTY_HINT", "MAX_RENDER_PIXELS", "pdf_source"]
