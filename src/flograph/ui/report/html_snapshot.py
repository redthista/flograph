"""Static pictures of a webview card's HTML, for paper.

A webview node returns HTML — a hand-written dashboard, a folium map, an
Altair chart, a mermaid diagram — and its card shows that HTML in a real
Chromium page. A report used to receive the same string and inline it *as
markdown*, so Qt's rich text engine kept the words and threw away the
layout: the card and the page showed two different things. This module is
how they are made to agree. The picture is taken by the browser the card
itself draws in, at the card's own pixel size, so the report shows the
visual as the card shows it.

The picture is taken through **print-to-PDF, not a screen grab**. Two
reasons, and the second is the important one:

  • `QWidget.grab()` on a QWebEngineView comes back blank — the page is
    painted on a GPU surface the widget never holds pixels for.
  • A PDF is vector, so the page is laid out *once* at the card's CSS size
    and can then be rasterised at any resolution. The report gets text and
    lines that are sharp at 300dpi while the layout is identical to the
    card's — which a screen grab of a 420px card, stretched across a page,
    could never be.

Everything fails soft, exactly as plotly_snapshot does: no Qt WebEngine, no
QtPdf, a page that will not load, a print that will not come back — all
return None, and the caller falls back to what it did before. A report
never disappears because a picture could not be taken.
"""
from __future__ import annotations

import hashlib

from PySide6.QtCore import (QBuffer, QEventLoop, QMarginsF, QSize, QSizeF,
                            QTimer, QUrl)
from PySide6.QtGui import QPageLayout, QPageSize

# Long enough for a slow first paint on a loaded machine (a page carrying
# plotly.js has ~5 MB of JavaScript to parse), short enough that a wedged
# page cannot hang the app.
LOAD_TIMEOUT_MS = 20000
PRINT_TIMEOUT_MS = 20000

# After the load event, before the print. A page whose chart is drawn by
# JavaScript has its content one frame *after* "loaded", and printing into
# that gap would catch an empty div. Deliberately generous: this is paid
# once per distinct picture (the cache below sees to the rest) and a blank
# chart on paper costs far more than a quarter second here.
SETTLE_MS = 350

# CSS pixels are 1/96in and PDF points 1/72in, so a page this many points
# across lays the HTML out at the pixel width the card used. Getting this
# wrong doesn't fail — it silently reflows the visual to a different width,
# which is the whole bug this module exists to fix.
PX_TO_POINT = 72.0 / 96.0

# Finished PNGs, keyed by page content and size. The report preview
# re-renders on a debounce whenever the body is edited, and pushing an
# unchanged visual back through Chromium on every keystroke would make
# typing unusable.
CACHE_LIMIT = 32
_CACHE: "dict[tuple, bytes]" = {}


def _wait(loop: QEventLoop, timeout_ms: int) -> None:
    """Run `loop` until it is quit or the timeout fires.

    User input is excluded so a keystroke in the report editor cannot kick
    off a second render inside this one — the same guard plotly_snapshot
    uses, and for the same reason.
    """
    deadline = QTimer()
    deadline.setSingleShot(True)
    deadline.timeout.connect(loop.quit)
    deadline.start(timeout_ms)
    loop.exec(QEventLoop.ExcludeUserInputEvents)
    deadline.stop()


class _Snapshotter:
    """The hidden page: built on first use, kept for the session.

    One view, reloaded per picture. Chromium's start-up cost is what makes
    a report of forty visuals worth caching a view for, and a page that has
    been navigated away from holds nothing of the last one.
    """

    def __init__(self) -> None:
        self._view = None
        self._tmp = None
        self._broken = False    # a structural failure — stop retrying
        self._busy = False      # re-entrancy guard for the nested loops

    def _page_path(self, suffix: str):
        import tempfile
        from pathlib import Path

        if self._tmp is None:
            self._tmp = tempfile.TemporaryDirectory(prefix="flograph-html-")
        return Path(self._tmp.name) / f"page{suffix}"

    def _ready_view(self):
        if self._broken:
            return None
        if self._view is not None:
            return self._view
        try:
            from PySide6.QtWidgets import QApplication
            if QApplication.instance() is None:
                return None      # no app yet; try again later, not broken
            from PySide6.QtWebEngineCore import QWebEngineSettings
            from PySide6.QtWebEngineWidgets import QWebEngineView

            view = QWebEngineView()
            # The same two settings the card's view is given (see
            # inspector/plotly_view.py): the page is loaded from a local
            # file, and without this a Leaflet map or any library pulling a
            # script from a CDN would load but never run it. The picture has
            # to be of the page the card shows, CDN and all.
            settings = view.settings()
            settings.setAttribute(
                QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls,
                True)
            # Chromium's print path drops element backgrounds unless asked;
            # a dashboard card is mostly background.
            settings.setAttribute(
                QWebEngineSettings.WebAttribute.PrintElementBackgrounds, True)
            view.hide()
        except Exception:
            self._broken = True
            return None
        self._view = view
        return view

    def _load(self, view, html: str, width: int, height: int) -> bool:
        """Put `html` in front of the view and wait for it to settle.

        Loaded from a temp file rather than `setHtml`, which caps content at
        2 MB — a self-contained Plotly page is over that on its own.
        """
        path = self._page_path(".html")
        path.write_text(html, encoding="utf-8")
        # A viewport at the card's size, so anything that measures the
        # window (a `vh` unit, a responsive library) sees the card's shape.
        # It is not what decides the picture's size — the page layout is.
        view.resize(max(1, int(width)), max(1, int(height)))
        loop = QEventLoop()
        state = {"ok": False}

        def finished(ok: bool) -> None:
            state["ok"] = bool(ok)
            loop.quit()

        view.loadFinished.connect(finished)
        try:
            view.load(QUrl.fromLocalFile(str(path)))
            _wait(loop, LOAD_TIMEOUT_MS)
        finally:
            view.loadFinished.disconnect(finished)
        if not state["ok"]:
            return False
        settle = QEventLoop()
        QTimer.singleShot(SETTLE_MS, settle.quit)
        _wait(settle, SETTLE_MS * 4)
        return True

    def _pdf(self, view, width: int, height: int) -> "bytes | None":
        """The page as a one-page PDF the size of the card."""
        layout = QPageLayout(
            QPageSize(QSizeF(width * PX_TO_POINT, height * PX_TO_POINT),
                      QPageSize.Point, "flograph-card", QPageSize.ExactMatch),
            QPageLayout.Portrait, QMarginsF(0, 0, 0, 0))
        loop = QEventLoop()
        got: dict = {}

        def done(data) -> None:
            got["data"] = bytes(data)
            loop.quit()

        view.page().printToPdf(done, layout)
        _wait(loop, PRINT_TIMEOUT_MS)
        data = got.get("data")
        return data or None

    def png(self, html: str, width: int, height: int,
            scale: float = 1.0) -> "bytes | None":
        if self._busy:
            return None          # already inside a snapshot; do not nest
        view = self._ready_view()
        if view is None:
            return None
        self._busy = True
        try:
            if not self._load(view, html, width, height):
                return None
            pdf = self._pdf(view, width, height)
        except Exception:
            return None
        finally:
            self._busy = False
        if not pdf:
            return None
        return self._raster(pdf, width, height, scale)

    def _raster(self, pdf: bytes, width: int, height: int,
                scale: float) -> "bytes | None":
        """The PDF's first page as PNG bytes, `scale` times the card's size.

        The *first* page only: content taller than the card is what the card
        itself clips, so a report page showing the same crop is the honest
        answer — and a visual that silently grew to nine pages of paper
        would be a worse surprise than one that matches the card.
        """
        try:
            from PySide6.QtPdf import QPdfDocument
        except ImportError:
            return None
        path = self._page_path(".pdf")
        try:
            path.write_bytes(pdf)
            document = QPdfDocument()
            document.load(str(path))
            if document.pageCount() < 1:
                return None
            image = document.render(
                0, QSize(max(1, round(width * scale)),
                         max(1, round(height * scale))))
        except Exception:
            return None
        if image is None or image.isNull():
            return None
        return _encode(image)


def _encode(image) -> "bytes | None":
    """A QImage as PNG bytes. The buffer owns its own byte array — one
    passed to the constructor is a Python temporary the buffer keeps
    pointing at after it is collected, which segfaults rather than
    failing (the same trap ui/report/html.py documents)."""
    buffer = QBuffer()
    buffer.open(QBuffer.WriteOnly)
    try:
        if not image.save(buffer, "PNG"):
            return None
        return bytes(buffer.data())
    finally:
        buffer.close()


_SNAPSHOTTER = _Snapshotter()


def snapshot(html: str, width: int, height: int,
             scale: float = 1.0) -> "bytes | None":
    """PNG bytes for an HTML page, or None.

    `width`/`height` are the CSS pixel size to lay the page out at — the
    card's own size, so the picture is the card — and `scale` the pixel
    density on top of it, so the image comes out width*scale across.

    None means "no picture available here" — no Qt WebEngine, no QtPdf, or
    a page that would not load — and is always the caller's cue to fall
    back, never an error to show.
    """
    if not html:
        return None
    width, height = max(1, int(width)), max(1, int(height))
    scale = max(0.1, float(scale))
    key = (hashlib.sha1(html.encode("utf-8")).hexdigest(),
           width, height, round(scale, 3))
    if key in _CACHE:
        return _CACHE[key]
    data = _SNAPSHOTTER.png(html, width, height, scale)
    if data:
        if len(_CACHE) >= CACHE_LIMIT:
            # plain FIFO: a report renders its visuals in a stable order, so
            # the oldest entry is the one least likely to be wanted again
            del _CACHE[next(iter(_CACHE))]
        _CACHE[key] = data
    return data


def clear_cache() -> None:
    _CACHE.clear()
