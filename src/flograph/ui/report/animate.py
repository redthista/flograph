"""Playing animated images inside a rendered report.

A QTextDocument holds images as *resources*: static QImages, registered
under a URL that the HTML points at. There is no animated image type. So an
animated GIF or WebP in a report is played by swapping the resource behind
its URL, frame by frame, and telling the document that one character — the
image fragment itself — changed.

Marking just that fragment rather than the whole document is the whole
performance story. `markContentsDirty(0, characterCount())` re-lays-out
every block: on a 120-block report that measured 4.03 ms a frame, which at
25fps is a tenth of a core per picture. Marking the image's own position
costs 0.089 ms — 45x less — because nothing else has to be re-flowed. The
positions are found once, by walking the document for image fragments, and
that walk is ~1 ms.

Only the on-screen preview and the canvas card animate. Paper cannot, so
the print path never builds one of these — see `RenderedReport.animations`,
which the resolver leaves empty when rendering for print.
"""
from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import (QBuffer, QByteArray, QIODevice, QObject, QSize,
                            QUrl, Qt)
from PySide6.QtGui import QImageReader, QMovie, QTextDocument

from flograph.core.report import IMAGE_TOKEN_URL


def image_positions(document: QTextDocument) -> dict[str, int]:
    """Character position of every embedded image, keyed by resource name.

    Walked once per render. A fragment's position is stable for the life of
    the document, which is what lets a frame swap touch one character.
    """
    found: dict[str, int] = {}
    block = document.begin()
    while block.isValid():
        iterator = block.begin()
        while not iterator.atEnd():
            fragment = iterator.fragment()
            if fragment.isValid():
                fmt = fragment.charFormat()
                if fmt.isImageFormat():
                    name = fmt.toImageFormat().name()
                    # first wins: the same picture embedded twice animates at
                    # the first site, and the second stays on its poster frame
                    found.setdefault(name, fragment.position())
            iterator += 1
        block = block.next()
    return found


class ReportAnimator(QObject):
    """Drives every animated image in one rendered document.

    Owned by whatever is showing the document (a report page's preview, a
    report card's browser). It must be `dispose()`d before the document goes
    away — a running QMovie writing into a deleted document is a crash, not
    a stale frame.
    """

    def __init__(self, document: QTextDocument, animations: dict[int, bytes],
                 widths: Optional[dict[int, int]] = None,
                 on_frame: Optional[Callable[[], None]] = None,
                 parent=None) -> None:
        super().__init__(parent)
        self._document = document
        self._on_frame = on_frame
        self._movies: list[QMovie] = []
        # QMovie reads from its device for as long as it plays, so both the
        # buffer and its storage are pinned here rather than left to scope.
        self._buffers: list[QBuffer] = []
        self._stores: list[QByteArray] = []
        self._playing = False

        positions = image_positions(document) if animations else {}
        widths = widths or {}
        for index, data in animations.items():
            name = IMAGE_TOKEN_URL.format(index)
            position = positions.get(name)
            if position is None:
                continue  # the embed didn't survive into the document
            movie = self._build(data, widths.get(index))
            if movie is None:
                continue
            movie.frameChanged.connect(
                lambda _n, m=movie, u=QUrl(name), p=position:
                self._on_movie_frame(m, u, p))
            self._movies.append(movie)

    @staticmethod
    def _natural_size(data: bytes) -> QSize:
        """Header-only read, on its own throwaway buffer: the movie's device
        must be left untouched at position zero for QMovie to decode it."""
        store = QByteArray(data)
        buffer = QBuffer()
        buffer.setData(store)
        buffer.open(QIODevice.ReadOnly)
        return QImageReader(buffer).size()

    def _build(self, data: bytes, width: Optional[int]) -> Optional[QMovie]:
        natural = self._natural_size(data)
        store = QByteArray(data)
        buffer = QBuffer()
        buffer.setData(store)
        buffer.open(QIODevice.ReadOnly)
        movie = QMovie(buffer)
        if not movie.isValid():
            return None
        # one frame in memory at a time, and decoded at the size it is drawn
        # at rather than the size it was authored at
        movie.setCacheMode(QMovie.CacheNone)
        if width and natural.isValid() and natural.width() > 0:
            movie.setScaledSize(
                natural.scaled(width, natural.height(), Qt.KeepAspectRatio))
        self._stores.append(store)
        self._buffers.append(buffer)
        return movie

    def _on_movie_frame(self, movie: QMovie, url: QUrl, position: int) -> None:
        self._document.addResource(QTextDocument.ImageResource, url,
                                   movie.currentPixmap().toImage())
        # one character, not the document: see the module docstring
        self._document.markContentsDirty(position, 1)
        if self._on_frame is not None:
            self._on_frame()

    def has_animations(self) -> bool:
        return bool(self._movies)

    def start(self) -> None:
        self._playing = True
        for movie in self._movies:
            if movie.state() != QMovie.Running:
                movie.setPaused(False)
                if movie.state() == QMovie.NotRunning:
                    movie.start()

    def set_playing(self, playing: bool) -> None:
        """Pause while nothing can see the document — a report on a tab that
        isn't showing should not be spending frames."""
        if playing:
            self.start()
            return
        self._playing = False
        for movie in self._movies:
            if movie.state() == QMovie.Running:
                movie.setPaused(True)

    def dispose(self) -> None:
        for movie in self._movies:
            movie.stop()
            try:
                movie.frameChanged.disconnect()
            except (RuntimeError, TypeError):
                pass
        self._movies = []
        self._buffers = []
        self._stores = []
        self._document = None
