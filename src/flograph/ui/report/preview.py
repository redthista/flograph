"""The report preview, drawn as sheets of paper.

It used to be a QTextBrowser: one continuous scroll of rich text, which
made the preview honest about the *content* and silent about the *page*.
Everything page setup added — the cover, the running header and footer,
where a page actually ends — was invisible until the PDF came out, which
is the one moment it is least useful to find out.

So this draws paper. Each page is a white sheet with a shadow, the margins
are where the margins are, and the document is drawn a page at a time
through the same routines the PDF writer uses (`export.paint_body`,
`paint_furniture`, `paint_cover`) — deliberately, because a preview that
reimplements the page loop is a preview that will eventually disagree with
the export, and disagreeing is the only thing a preview must never do.

Text selection is what this costs, and it is the reason the widget keeps a
`document()` accessor: what is on screen is still one QTextDocument, and
everything else in the report code goes on treating it as one.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QRectF, QSizeF, Qt
from PySide6.QtGui import QColor, QPainter, QTextDocument
from PySide6.QtWidgets import QAbstractScrollArea

from flograph.core.page_setup import PageSetup, today

from .export import (body_rect, paint_body, paint_context, paint_cover,
                     paint_furniture, printable_points, sheet_points)

#: Space around and between the sheets, in device pixels — not points, so
#: the gap stays the same however far the paper is zoomed.
MARGIN_PX = 14
GAP_PX = 14

#: How far the paper may be scaled to fit the pane. The ceiling stops a
#: narrow report being blown up into something the export will not match;
#: the floor stops a very narrow pane rendering a stamp.
MIN_SCALE = 0.15
MAX_SCALE = 1.6

#: What Ctrl+wheel may reach. Wider than the fit range on both sides: the
#: point of zooming out is to see several pages at once, and of zooming in
#: to read something at full size in a narrow pane.
MIN_ZOOM = 0.1
MAX_ZOOM = 4.0
ZOOM_STEP = 1.15

#: The desk the paper sits on. Deliberately not a theme colour: the sheet
#: is white because paper is white, so the surround has to be dark enough
#: to read as *not paper* in either theme.
DESK = QColor("#4a4a4f")
SHADOW = QColor(0, 0, 0, 60)
PAPER = QColor("#ffffff")


class PagedPreview(QAbstractScrollArea):
    """A rendered report shown as the pages it will print as."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("report_preview")
        self._document: Optional[QTextDocument] = None
        self._setup = PageSetup()
        self._title = ""
        self._date = today()
        self._pages = 1
        self._scale = 1.0
        #: a zoom the user set with Ctrl+wheel, or None for fit-to-width.
        #: Paper cannot reflow to a narrow pane the way the old continuous
        #: preview did, so without a zoom a narrow editor/preview split
        #: would leave the text too small to proofread — this is what pays
        #: for showing real pages.
        self._user_scale: Optional[float] = None
        #: sheets left-to-right and wrapping, rather than in one column
        self._flow = False
        self.viewport().setAutoFillBackground(False)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)

    # ------------------------------------------------------------- contents

    def set_report(self, document: QTextDocument, setup: PageSetup,
                   title: str = "") -> None:
        """Show `document` laid out onto `setup`'s paper.

        The document is paginated by giving it the body size — a
        QTextDocument has no page count until it has been told how tall a
        page is.
        """
        self._document = document
        self._setup = setup or PageSetup()
        self._title = title
        self._date = today()
        if document is not None:
            body = body_rect(printable_points(self._setup), self._setup)
            document.setPageSize(QSizeF(body.width(), body.height()))
            self._pages = max(1, document.pageCount())
        else:
            self._pages = 1
        self._relayout()
        self.viewport().update()

    def document(self) -> Optional[QTextDocument]:
        """The document on screen. Kept because the rest of the report code
        — the animator, the tests that check the preview and the PDF are the
        same thing — reasonably treats a preview as having one."""
        return self._document

    def page_count(self) -> int:
        """Body pages, not counting a cover."""
        return self._pages

    def sheet_count(self) -> int:
        return self._pages + (1 if self._setup.cover else 0)

    # -------------------------------------------------------------- layout

    def _sheet_size(self) -> QSizeF:
        return sheet_points(self._setup)

    def _fit_scale(self) -> float:
        sheet = self._sheet_size()
        available = max(1, self.viewport().width() - 2 * MARGIN_PX)
        return max(MIN_SCALE, min(MAX_SCALE, available / sheet.width()))

    def zoom(self) -> float:
        return self._scale

    def set_zoom(self, scale: Optional[float]) -> None:
        """Set an explicit zoom, or None to go back to fitting the width."""
        self._user_scale = (None if scale is None
                            else max(MIN_ZOOM, min(MAX_ZOOM, scale)))
        self._relayout()
        self.viewport().update()

    def columns(self) -> int:
        """How many sheets fit across the pane, at the current scale.

        1 in single-column mode whatever the room, because "one page at a
        time, as big as it goes" is a different way of reading and not
        something the window width should take away.
        """
        if not self._flow:
            return 1
        width = self._sheet_size().width() * self._scale
        room = self.viewport().width() - 2 * MARGIN_PX + GAP_PX
        return max(1, int(room // (width + GAP_PX)))

    def flow(self) -> bool:
        return self._flow

    def set_flow(self, flow: bool) -> None:
        """Lay the sheets out left-to-right and wrapping, rather than in one
        column — the contact sheet view, for seeing where everything falls
        at once."""
        self._flow = bool(flow)
        # Fitting the *width* to one sheet makes no sense once several sit
        # side by side, so a flowed view starts from whatever zoom is in
        # force and stays there until told otherwise.
        if self._flow and self._user_scale is None:
            self._user_scale = self._scale
        self._relayout()
        self.viewport().update()

    def _rows(self) -> int:
        columns = self.columns()
        return (self.sheet_count() + columns - 1) // columns

    def _relayout(self) -> None:
        """Size the scrollbars to the stack of sheets."""
        self._scale = (self._fit_scale() if self._user_scale is None
                       else self._user_scale)
        sheet = self._sheet_size()
        height = int(sheet.height() * self._scale)
        rows = self._rows()
        total = (MARGIN_PX * 2 + rows * height + max(0, rows - 1) * GAP_PX)
        bar = self.verticalScrollBar()
        bar.setPageStep(max(1, self.viewport().height()))
        bar.setSingleStep(max(1, self.viewport().height() // 12))
        bar.setRange(0, max(0, total - self.viewport().height()))
        # Only ever needed when zoomed in past the pane; fit-to-width never
        # produces one, which is why the policy is AsNeeded.
        columns = self.columns()
        width = (int(sheet.width() * self._scale) * columns
                 + max(0, columns - 1) * GAP_PX + 2 * MARGIN_PX)
        side = self.horizontalScrollBar()
        side.setPageStep(max(1, self.viewport().width()))
        side.setSingleStep(max(1, self.viewport().width() // 12))
        side.setRange(0, max(0, width - self.viewport().width()))

    def scrollContentsBy(self, dx: int, dy: int) -> None:
        """Repaint rather than blit. Sheet positions are computed from the
        scrollbars at paint time, so a full repaint is always right — and
        the default blit leaves the drop shadows smeared behind it."""
        self.viewport().update()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        # The scroll position is kept as a fraction rather than a pixel
        # count: resizing rescales the paper, so the same pixel offset would
        # land somewhere else entirely.
        bar = self.verticalScrollBar()
        fraction = (bar.value() / bar.maximum()) if bar.maximum() else 0.0
        self._relayout()
        bar.setValue(int(fraction * bar.maximum()))

    def _sheet_rect(self, index: int) -> QRectF:
        """Where sheet `index` sits in viewport coordinates."""
        sheet = self._sheet_size()
        width = sheet.width() * self._scale
        height = sheet.height() * self._scale
        columns = self.columns()
        column, row = index % columns, index // columns
        block = columns * width + max(0, columns - 1) * GAP_PX
        left = max(MARGIN_PX, (self.viewport().width() - block) / 2.0)
        x = (left + column * (width + GAP_PX)
             - self.horizontalScrollBar().value())
        y = (MARGIN_PX + row * (height + GAP_PX)
             - self.verticalScrollBar().value())
        return QRectF(x, y, width, height)

    # ------------------------------------------------------------ painting

    def paintEvent(self, event) -> None:
        painter = QPainter(self.viewport())
        painter.fillRect(self.viewport().rect(), DESK)
        if self._document is None:
            return
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)

        layout = self._document.documentLayout()
        context = paint_context()
        printable = printable_points(self._setup)
        body = body_rect(printable, self._setup)
        cover = 1 if self._setup.cover else 0
        visible = QRectF(self.viewport().rect())

        for index in range(self.sheet_count()):
            rect = self._sheet_rect(index)
            if not rect.intersects(visible):
                continue      # scrolled past — the whole point of the loop
            painter.fillRect(rect.translated(2, 2), SHADOW)
            painter.fillRect(rect, PAPER)

            painter.save()
            painter.translate(rect.topLeft())
            painter.scale(self._scale, self._scale)
            painter.setClipRect(QRectF(0, 0, self._sheet_size().width(),
                                       self._sheet_size().height()))
            if cover and index == 0:
                paint_cover(painter, printable, self._setup, self._title,
                            self._date)
            else:
                page = index - cover
                paint_body(painter, layout, context, body, page)
                if page or self._setup.bands_on_first_page:
                    paint_furniture(
                        painter, printable, self._setup,
                        self._setup.first_page_number + page, self._pages,
                        self._title, self._date)
            painter.restore()

    def wheelEvent(self, event) -> None:
        delta = event.angleDelta().y()
        if delta and event.modifiers() & Qt.ControlModifier:
            # Zoom about the pointer, so the thing under the cursor stays
            # under it — zooming about the top-left sends whatever you were
            # looking at off the screen.
            bar = self.verticalScrollBar()
            anchor = event.position().y() if hasattr(event, "position") else 0
            before = (bar.value() + anchor) / max(1e-6, self._scale)
            self.set_zoom(self._scale * (ZOOM_STEP if delta > 0
                                         else 1 / ZOOM_STEP))
            bar.setValue(int(before * self._scale - anchor))
            event.accept()
            return
        if delta:
            # QAbstractScrollArea scrolls by lines; a page of paper wants
            # more than three lines a notch or a long report is a chore.
            bar = self.verticalScrollBar()
            bar.setValue(bar.value() - delta)
            event.accept()
            return
        super().wheelEvent(event)
