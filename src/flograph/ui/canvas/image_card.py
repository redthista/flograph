"""Decoding and painting for the Image card.

Split out of node_item because the interesting part is not the chrome (that
is `_paint_widget_card`, shared with every other card) but the decode, and
the decode is where all the cost lives.

Three rules keep an image card cheap enough that a canvas full of them
behaves like a canvas full of ordinary nodes:

1. **Decode at display size, never at source size.** `QImageReader`'s
   `setScaledSize` scales *during* decode, so a 6000x4000 JPEG on a 320x240
   card costs a 320x240 buffer, not a 96 MB one. The scaled result is cached
   and only re-decoded when the target size actually changes.
2. **No proxy widget.** The artwork is painted straight onto the item, the
   way the KPI card paints its value. A `QGraphicsProxyWidget` is a real
   QWidget with its own backing store; not having one is why image cards are
   exempt from the canvas-preview toggle that figure/webview cards need.
3. **Animation only while it's being watched.** A paused `QMovie` costs
   nothing, so playback stops whenever the card isn't really visible — see
   `set_playing`, driven from the item's LOD/preview state.

A source is a path, a `data:` URI or a base64 blob; `flograph.core.images`
decides which, so the picture on the canvas and the bytes the node emits can
never disagree. Sources that aren't files are decoded once, on assignment,
and held as bytes — Qt reads them through a QBuffer exactly as it would a
file.

Formats come from whatever Qt image plugins are installed (PNG, JPEG, GIF,
WebP, BMP, ICO, TIFF, PPM, XPM, ... ) plus SVG, which is rendered as vectors
rather than decoded, so it stays sharp at every zoom.
"""
from __future__ import annotations

import hashlib
from typing import Callable, Optional

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QRectF, QSize, Qt
from PySide6.QtGui import QImageReader, QMovie, QPainter, QPixmap

from flograph.core.images import resolve_source

# Ceiling on the decoded buffer for one card, in pixels (~16 MB at RGBA).
# Only "Original size" and a hard-zoomed-in "Fill" can push past a card-sized
# target; without a cap, "Original size" on a 100-megapixel scan would try to
# allocate 400 MB the moment the node is dropped.
MAX_DECODE_PIXELS = 4_000_000

# How the artwork is sized inside the card's content area:
#   Fit           shrink/grow until it's wholly inside, aspect kept
#   Fill          grow until it covers, aspect kept, overflow clipped
#   Stretch       exactly the content area, aspect ignored
#   Original size one image pixel per canvas pixel, overflow clipped
# "Scale %" then multiplies whichever of those was chosen.
FIT_MODES = ("Fit", "Fill", "Stretch", "Original size")
DEFAULT_FIT = "Fit"
SCALE_MIN, SCALE_MAX = 0.1, 4.0

SVG_MIME = "image/svg+xml"

# Extensions Qt renders as vectors instead of decoding to a raster.
_SVG_EXTENSIONS = (".svg", ".svgz")


def is_svg(path: str) -> bool:
    """Whether a *filename* names an SVG. Sources without a filename are
    identified by their sniffed mime type instead — see CardImage."""
    return path.lower().endswith(_SVG_EXTENSIONS)


def target_size(natural: QSize, box: QSize, fit: str,
                scale: float = 1.0) -> QSize:
    """The size the artwork should occupy in a `box`-sized content area."""
    if natural.isEmpty() or box.isEmpty():
        return box
    scale = min(SCALE_MAX, max(SCALE_MIN, scale))
    if fit == "Stretch":
        base = box
    elif fit == "Original size":
        base = natural
    else:
        scale_x = box.width() / natural.width()
        scale_y = box.height() / natural.height()
        # Fit shrinks until it's wholly inside; Fill grows until it covers.
        factor = (min(scale_x, scale_y) if fit != "Fill"
                  else max(scale_x, scale_y))
        base = QSize(max(1, round(natural.width() * factor)),
                     max(1, round(natural.height() * factor)))
    if scale == 1.0:
        return base
    return QSize(max(1, round(base.width() * scale)),
                 max(1, round(base.height() * scale)))


def _budgeted(size: QSize) -> QSize:
    """`size` shrunk, in proportion, to fit inside MAX_DECODE_PIXELS."""
    pixels = size.width() * size.height()
    if pixels <= MAX_DECODE_PIXELS or pixels <= 0:
        return size
    scale = (MAX_DECODE_PIXELS / pixels) ** 0.5
    return QSize(max(1, int(size.width() * scale)),
                 max(1, int(size.height() * scale)))


class CardImage:
    """The artwork behind one Image card: loads, scales, animates, paints.

    Owned by a NodeItem, which supplies `on_frame` — called once per frame of
    an animation so the item can repaint itself. Everything here runs on the
    GUI thread; nothing here touches the graph.
    """

    def __init__(self, on_frame: Callable[[], None]) -> None:
        self._on_frame = on_frame
        self._source = ""          # the raw string, as given
        self._path = ""            # set only when the source is a real file
        self._data: Optional[bytes] = None  # set only when it is not
        self._key = ""             # identifies the artwork in the decode cache
        self._is_svg = False
        self._fit = DEFAULT_FIT
        self._scale = 1.0
        self._animate = True
        self._playing = True
        self._natural = QSize()
        self._pixmap: Optional[QPixmap] = None
        self._movie: Optional[QMovie] = None
        self._movie_buffer: Optional[QBuffer] = None
        self._movie_bytes: Optional[QByteArray] = None
        self._svg = None  # QSvgRenderer, kept as vectors
        self._decoded_key: tuple = ()
        self._ratio = 1.0
        self.error = ""

    # ------------------------------------------------------------- source

    def set_source(self, source: str, fit: str, animate: bool,
                   scale: float = 1.0) -> None:
        """Point the card at a path, a `data:` URI or a base64 blob.

        Cheap and idempotent: an unchanged source does nothing at all, and
        re-decoding is deferred to the next paint. Resolving happens here
        rather than in paint() so a multi-megabyte base64 string is decoded
        once when it is set, not once per frame.
        """
        source = str(source or "").strip()
        scale = min(SCALE_MAX, max(SCALE_MIN, scale))
        if (source == self._source and fit == self._fit
                and animate == self._animate and scale == self._scale):
            return
        if source != self._source:
            self._release()
            self._source = source
            self._resolve()
        self._fit = fit if fit in FIT_MODES else DEFAULT_FIT
        self._animate = animate
        self._scale = scale
        self._decoded_key = ()  # force a re-decode at the next paint

    def _resolve(self) -> None:
        """Work out what the current source string actually points at."""
        self._path = ""
        self._data = None
        self._natural = QSize()
        self._is_svg = False
        self.error = ""
        self._key = ""
        if not self._source:
            return
        try:
            data, mime, path = resolve_source(self._source)
        except (ValueError, FileNotFoundError, OSError) as exc:
            self.error = str(exc)
            return
        self._is_svg = (mime == SVG_MIME)
        if path:
            # Keep reading from the file: Qt can decode it scaled straight off
            # disk, so holding the bytes as well would double the cost for
            # nothing.
            self._path = path
            self._key = f"file:{path}"
        else:
            self._data = data
            self._key = "blob:" + hashlib.sha256(data).hexdigest()[:16]

    def reload(self) -> None:
        """Forget everything decoded and read the source again."""
        self._release()
        self._resolve()
        self._decoded_key = ()

    def _release(self) -> None:
        if self._movie is not None:
            self._movie.stop()
            try:
                self._movie.frameChanged.disconnect()
            except (RuntimeError, TypeError):
                pass
            self._movie = None
        # Outlive the movie they fed, never the other way round.
        self._movie_buffer = None
        self._movie_bytes = None
        self._pixmap = None
        self._svg = None

    # ------------------------------------------------------------ metadata

    def _open_buffer(self) -> Optional[QBuffer]:
        """A read-only QBuffer over the held bytes, or None if there are none.

        The QByteArray is parented to the buffer so that returning the buffer
        alone keeps its storage alive — passing a temporary QByteArray to
        QBuffer is a segfault, not an exception.
        """
        if self._data is None:
            return None
        store = QByteArray(self._data)
        buffer = QBuffer()
        buffer.setData(store)
        buffer.open(QIODevice.ReadOnly)
        return buffer

    def _reader(self) -> Optional[QImageReader]:
        """A QImageReader over the current source, file or bytes."""
        if self._path:
            return QImageReader(self._path)
        buffer = self._open_buffer()
        if buffer is None:
            return None
        reader = QImageReader(buffer)
        # The reader borrows the device, so pin the buffer to its lifetime.
        reader._flograph_buffer = buffer
        return reader

    def natural_size(self) -> QSize:
        """Source dimensions, read from the header without decoding pixels."""
        if not self._natural.isEmpty() or not self.has_content():
            return self._natural
        if self._is_svg:
            from PySide6.QtSvg import QSvgRenderer
            renderer = (QSvgRenderer(self._path) if self._path
                        else QSvgRenderer(QByteArray(self._data)))
            if renderer.isValid():
                self._natural = renderer.defaultSize()
                self._svg = renderer
            else:
                self.error = "not a readable SVG"
            return self._natural
        reader = self._reader()
        if reader is None:
            return self._natural
        size = reader.size()  # header only — no pixels decoded
        if size.isValid() and not size.isEmpty():
            self._natural = size
        else:
            self.error = reader.errorString() or "unreadable image"
        return self._natural

    def is_animated(self) -> bool:
        if not self.has_content() or self._is_svg:
            return False
        reader = self._reader()
        if reader is None:
            return False
        return reader.supportsAnimation() and reader.imageCount() > 1

    def has_content(self) -> bool:
        return bool(self._path or self._data) and not self.error

    # ------------------------------------------------------------ playback

    def set_playing(self, playing: bool) -> None:
        """Run or freeze an animation. The card calls this whenever its
        visibility changes, so animations off-screen or zoomed past the LOD
        threshold cost nothing at all."""
        self._playing = playing
        if self._movie is None:
            return
        want = playing and self._animate
        if want and self._movie.state() != QMovie.Running:
            self._movie.setPaused(False)
            if self._movie.state() == QMovie.NotRunning:
                self._movie.start()
        elif not want and self._movie.state() == QMovie.Running:
            self._movie.setPaused(True)

    # -------------------------------------------------------------- decode

    def _ensure(self, box: QSize, ratio: float) -> None:
        """Decode (or re-decode) the artwork for a `box`-sized content area.

        `ratio` is device pixels per logical pixel — screen DPR times canvas
        zoom — so a card inspected close up decodes sharp instead of being
        upscaled from a card-sized buffer. It is quantised to halves so that
        panning and small zoom nudges don't each trigger a fresh decode.
        """
        natural = self.natural_size()
        if natural.isEmpty() or box.isEmpty():
            return
        ratio = min(4.0, max(1.0, round(ratio * 2) / 2))
        logical = target_size(natural, box, self._fit, self._scale)
        wanted = _budgeted(QSize(max(1, round(logical.width() * ratio)),
                                 max(1, round(logical.height() * ratio))))
        key = (self._key, self._fit, self._scale, self._animate,
               wanted.width(), wanted.height())
        if key == self._decoded_key:
            return
        self._decoded_key = key
        # The painted size is derived back from the buffer, so a budget-
        # clamped decode still lands in the right place on the card.
        self._ratio = (wanted.width() / logical.width()
                       if logical.width() else 1.0)

        if self._is_svg:
            return  # vectors: nothing to decode, painted from the renderer

        if self._animate and self.is_animated():
            self._decode_movie(wanted)
        else:
            self._decode_still(wanted)

    def _decode_still(self, wanted: QSize) -> None:
        self._release()
        reader = self._reader()
        if reader is None:
            return
        reader.setAutoTransform(True)  # honour EXIF orientation on phone photos
        if wanted != reader.size():
            reader.setScaledSize(wanted)  # scales during decode, not after
        image = reader.read()
        if image.isNull():
            self.error = reader.errorString() or "unreadable image"
            self._pixmap = None
            return
        self.error = ""
        self._pixmap = QPixmap.fromImage(image)

    def _decode_movie(self, wanted: QSize) -> None:
        was_frame = self._movie.currentFrameNumber() if self._movie else 0
        self._release()
        if self._path:
            movie = QMovie(self._path)
        else:
            # Both the buffer and its storage must outlive the movie, which
            # reads from them for as long as it plays.
            self._movie_bytes = QByteArray(self._data)
            self._movie_buffer = QBuffer()
            self._movie_buffer.setData(self._movie_bytes)
            self._movie_buffer.open(QIODevice.ReadOnly)
            movie = QMovie(self._movie_buffer)
        if not movie.isValid():
            self.error = "unreadable animation"
            return
        # CacheNone: hold one frame at a time rather than every frame of the
        # animation, which is the difference between a few hundred KB and
        # tens of MB for a long GIF.
        movie.setCacheMode(QMovie.CacheNone)
        movie.setScaledSize(wanted)
        movie.frameChanged.connect(lambda _n: self._on_frame())
        self._movie = movie
        self.error = ""
        movie.jumpToFrame(0)  # a frame to show even if playback never starts
        if was_frame:
            movie.jumpToFrame(min(was_frame, max(0, movie.frameCount() - 1)))
        self.set_playing(self._playing)

    # --------------------------------------------------------------- paint

    def paint(self, painter: QPainter, rect: QRectF, ratio: float = 1.0) -> None:
        """Draw the artwork centred in `rect`, clipped to it."""
        box = QSize(max(1, int(rect.width())), max(1, int(rect.height())))
        self._ensure(box, ratio)

        if self._is_svg and self._svg is not None:
            natural = self.natural_size()
            size = target_size(natural, box, self._fit, self._scale)
            painter.save()
            # Intersect, never replace: the card sets a rounded-corner clip
            # before calling in, and a Fill/Stretch/Original-size picture
            # would otherwise paint square corners over the card's round ones.
            painter.setClipRect(rect, Qt.IntersectClip)
            painter.setRenderHint(QPainter.Antialiasing, True)
            self._svg.render(painter, self._centred(rect, size.width(),
                                                    size.height()))
            painter.restore()
            return

        pixmap = (self._movie.currentPixmap() if self._movie is not None
                  else self._pixmap)
        if pixmap is None or pixmap.isNull():
            return
        width = pixmap.width() / self._ratio
        height = pixmap.height() / self._ratio
        painter.save()
        painter.setClipRect(rect, Qt.IntersectClip)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        painter.drawPixmap(self._centred(rect, width, height), pixmap,
                           QRectF(pixmap.rect()))
        painter.restore()

    @staticmethod
    def _centred(rect: QRectF, width: float, height: float) -> QRectF:
        return QRectF(rect.x() + (rect.width() - width) / 2.0,
                      rect.y() + (rect.height() - height) / 2.0,
                      width, height)
