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


#: The longest side a pasted icon is kept at: twice the size an icon is
#: usually drawn, so it stays sharp on a high-density screen — and a
#: screenshot pasted as an icon costs the flow a few KB, not megabytes.
ICON_PIXELS = 128

#: A copied file bigger than this is not read to find out if it is an icon.
_ICON_FILE_LIMIT = 50 * 1024 * 1024


def icon_picture(data: bytes, most: int = ICON_PIXELS) -> Optional[str]:
    """`data` as an icon-sized picture's `data:` URI, or None if it is not a
    picture.

    A still is shrunk to fit `most` pixels on its longer side (never grown)
    and re-encoded to its smallest lossless form. An SVG is kept as it is —
    it is already any size — and so is an animation, which Qt cannot write.
    """
    from flograph.core.images import is_image_mime
    mime = sniff_mime(data)
    if not is_image_mime(mime):
        return None
    if mime == "image/svg+xml" or _is_animation(data):
        return to_data_uri(data, mime)
    image = QImage.fromData(QByteArray(data))
    if image.isNull():
        return None
    if max(image.width(), image.height()) > most:
        from PySide6.QtCore import Qt
        image = image.scaled(most, most, Qt.KeepAspectRatio,
                             Qt.SmoothTransformation)
        data = _encode_png(image)
    best, kind = _smallest_lossless(data)
    return to_data_uri(best, kind)


def icon_source(mime: QMimeData) -> Optional[str]:
    """What the clipboard (or a drop) holds as an icon-sized picture, or
    None when it holds no picture — so the caller pastes it as text.

    Tried in this order: a copied **picture file**; **text that is a
    picture** (base64, a `data:` address, SVG markup — shrunk like any
    other); then, only when there is no text, a **copied picture**. The text
    comes before the picture because an office app copying a few words puts
    a rendering of them on the clipboard too, and a ✓ copied from a
    document is meant as a ✓.
    """
    if mime is None:
        return None
    from flograph.core.images import parse_data_uri, picture_uri
    try:
        if mime.hasUrls():
            for url in mime.urls():
                if not url.isLocalFile():
                    continue
                path = url.toLocalFile()
                import os
                if (os.path.isfile(path)
                        and os.path.getsize(path) <= _ICON_FILE_LIMIT):
                    with open(path, "rb") as handle:
                        found = icon_picture(handle.read())
                    if found:
                        return found
        if mime.hasText() and mime.text().strip():
            uri = picture_uri(mime.text())
            if uri is None:
                return None
            parsed = parse_data_uri(uri)
            return icon_picture(parsed[0]) if parsed else None
        found = clipboard_image_bytes(mime)
        return icon_picture(found[0]) if found else None
    except (OSError, ValueError):
        return None
