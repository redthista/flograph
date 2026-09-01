"""Turning a clipboard image into a `data:` URI an Image node can point at.

Screen grabbing is deliberately not implemented here. Every OS this runs on
already has a screenshot key that puts the result on the clipboard — and on
Wayland an application cannot grab the screen itself anyway without going
through the desktop portal — so the whole feature is "paste what the OS
already gave you", which works identically on Windows, macOS and Linux.

A pasted picture goes straight into the node's ``path`` param as a base64
``data:`` URI, so the flow carries the image with it — hand the .flograph
(or an exported .flowf) to someone else and the picture is still there. A
still is re-encoded to whichever *lossless* format is smallest (PNG or, when
the Qt build can write it, WebP); an animation is kept byte-for-byte because
Qt has no animation writer.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QMimeData
from PySide6.QtGui import QImage, QImageReader, QImageWriter

from flograph.core.images import sniff_mime, to_data_uri

# Clipboard flavours worth taking verbatim, best first. Taking the bytes the
# clipboard already holds beats re-encoding the decoded QImage: it keeps an
# animated GIF animated, and keeps a PNG's exact pixels rather than paying a
# decode/encode round trip. Anything else falls back to encoding as PNG.
_PREFERRED_FORMATS = (
    ("image/gif", ".gif"),
    ("image/webp", ".webp"),
    ("image/png", ".png"),
    ("image/jpeg", ".jpg"),
    ("image/svg+xml", ".svg"),
)


def _encode_png(image: QImage) -> bytes:
    # `store` must outlive the buffer: QBuffer keeps a reference to the
    # QByteArray rather than owning it, so passing a temporary here lets
    # Python collect it out from under the C++ side mid-write — a segfault,
    # not an exception.
    store = QByteArray()
    buffer = QBuffer(store)
    buffer.open(QIODevice.WriteOnly)
    image.save(buffer, "PNG")
    buffer.close()
    return bytes(store)


def clipboard_image_bytes(mime: QMimeData) -> Optional[tuple[bytes, str]]:
    """(encoded image, file extension) from `mime`, or None if it holds no
    picture. Never raises — a clipboard is whatever another program put there.
    """
    if mime is None:
        return None
    for fmt, suffix in _PREFERRED_FORMATS:
        if mime.hasFormat(fmt):
            data = bytes(mime.data(fmt))
            if data:
                return data, suffix
    if not mime.hasImage():
        return None
    image = mime.imageData()
    if not isinstance(image, QImage):
        image = QImage(image) if image is not None else QImage()
    if image.isNull():
        return None
    data = _encode_png(image)
    return (data, ".png") if data else None


def _is_animation(data: bytes) -> bool:
    store = QByteArray(data)
    buffer = QBuffer(store)
    buffer.open(QIODevice.ReadOnly)
    reader = QImageReader(buffer)
    return reader.supportsAnimation() and reader.imageCount() > 1


def _encode_lossless_webp(image: QImage) -> Optional[bytes]:
    """`image` as a lossless WebP, or None if this Qt build can't write one."""
    if b"webp" not in {bytes(f) for f in QImageWriter.supportedImageFormats()}:
        return None
    store = QByteArray()
    buffer = QBuffer(store)
    buffer.open(QIODevice.WriteOnly)
    writer = QImageWriter(buffer, b"webp")
    writer.setQuality(100)  # 100 selects lossless in Qt's WebP plugin
    ok = writer.write(image)
    buffer.close()
    if not ok or not store.size():
        return None
    blob = bytes(store)
    # Trust nothing: a plugin that claims WebP support but writes garbage
    # would otherwise become the "smallest" candidate and paste a broken URI.
    return blob if not QImage.fromData(QByteArray(blob)).isNull() else None


def _smallest_lossless(data: bytes) -> tuple[bytes, str]:
    """The clipboard bytes re-encoded to whichever lossless form is smallest.

    An animation is returned untouched — re-encoding it would need a writer
    Qt does not have. A still is compared against a fresh PNG and a lossless
    WebP; the original is kept if neither beats it (a clipboard PNG is often
    already about as small as it gets).
    """
    if _is_animation(data):
        return data, sniff_mime(data)
    image = QImage.fromData(QByteArray(data))
    if image.isNull():
        return data, sniff_mime(data)
    candidates: list[tuple[bytes, str]] = [(data, sniff_mime(data))]
    png = _encode_png(image)
    if png and not QImage.fromData(QByteArray(png)).isNull():
        candidates.append((png, "image/png"))
    webp = _encode_lossless_webp(image)
    if webp:
        candidates.append((webp, "image/webp"))
    return min(candidates, key=lambda pair: len(pair[0]))


def clipboard_image_source(mime: QMimeData) -> Optional[str]:
    """The clipboard's picture as a base64 `data:` URI, or None if it has none.

    This is also the whole of "screen grab": every OS screenshot key already
    puts its result on the clipboard, so there is nothing to capture here.
    """
    found = clipboard_image_bytes(mime)
    if found is None:
        return None
    data, _suffix = found
    best, mime_type = _smallest_lossless(data)
    return to_data_uri(best, mime_type)
