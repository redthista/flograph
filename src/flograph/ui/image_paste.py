"""Turning a clipboard image into a file an Image node can point at.

Screen grabbing is deliberately not implemented here. Every OS this runs on
already has a screenshot key that puts the result on the clipboard — and on
Wayland an application cannot grab the screen itself anyway without going
through the desktop portal — so the whole feature is "paste what the OS
already gave you", which works identically on Windows, macOS and Linux.

Files land in a content-addressed store (`paths.user_images_dir`) rather
than inside the .flograph file. See that function for why.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QMimeData
from PySide6.QtGui import QImage

from flograph.paths import user_images_dir

# Clipboard flavours worth taking verbatim, best first. Saving the bytes the
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


def save_image_bytes(data: bytes, suffix: str,
                     directory: Optional[Path] = None) -> str:
    """Write `data` into the image store under its content hash.

    Content addressing means pasting the same screenshot into five nodes
    costs one file, and re-pasting after an undo costs none.
    """
    directory = Path(directory) if directory is not None else user_images_dir()
    directory.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(data).hexdigest()[:32]
    path = directory / f"{digest}{suffix}"
    if not path.exists():
        # Write-then-rename so a crash mid-write can't leave a truncated file
        # sitting at the name its own hash promises is intact.
        temporary = path.with_suffix(path.suffix + ".part")
        temporary.write_bytes(data)
        temporary.replace(path)
    return str(path)


def save_clipboard_image(mime: QMimeData,
                         directory: Optional[Path] = None) -> Optional[str]:
    """Path to a saved copy of the clipboard's image, or None if it has none."""
    found = clipboard_image_bytes(mime)
    if found is None:
        return None
    data, suffix = found
    return save_image_bytes(data, suffix, directory)
