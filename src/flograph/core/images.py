"""Resolving an image source: a file path, a `data:` URI, or bare base64.

Qt-free and stdlib-only, like the rest of `flograph.core` — imported both by
the Image node's `run()` (which executes in an engine worker) and by the
canvas card (which paints on the GUI thread), so the two can never disagree
about what a given source string means.

The three accepted forms, in the order they are tried:

  1. a `data:` URI — `data:image/png;base64,iVBOR...`, definitive
  2. a path to a file that exists
  3. a bare base64 blob, accepted only if what it decodes to actually looks
     like an image

Order matters: a path is checked before bare base64 because a filename made
purely of base64-legal characters ("logo") is a perfectly ordinary path, and
the file existing is the stronger signal.
"""
from __future__ import annotations

import base64
import binascii
import os
import re
from typing import Optional

# Leading bytes that identify a format. Sniffing beats trusting the
# extension: a base64 blob has no filename at all, and a dragged-in file may
# be named anything. The mime type is what a data URI has to get right.
_MAGIC: tuple[tuple[bytes, str], ...] = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
    (b"BM", "image/bmp"),
    (b"II*\x00", "image/tiff"),
    (b"MM\x00*", "image/tiff"),
    (b"\x00\x00\x01\x00", "image/x-icon"),
    (b"\x00\x00\x02\x00", "image/x-icon"),
)

_EXT_MIME = {
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".jfif": "image/jpeg", ".gif": "image/gif", ".webp": "image/webp",
    ".bmp": "image/bmp", ".svg": "image/svg+xml", ".svgz": "image/svg+xml",
    ".ico": "image/x-icon", ".tif": "image/tiff", ".tiff": "image/tiff",
    ".ppm": "image/x-portable-pixmap", ".pgm": "image/x-portable-graymap",
    ".pbm": "image/x-portable-bitmap", ".xpm": "image/x-xpixmap",
    ".tga": "image/x-tga", ".icns": "image/x-icns",
}

UNKNOWN_MIME = "application/octet-stream"

_DATA_URI = re.compile(r"^data:([^;,]*)((?:;[^;,]*)*),", re.IGNORECASE)
_BASE64_ONLY = re.compile(r"^[A-Za-z0-9+/_-]+={0,2}$")

# Below this, a string is far too short to be an image and is much more
# likely to be a stray filename.
_MIN_BASE64_LEN = 24


def sniff_mime(data: bytes, path: str = "") -> str:
    """The mime type of `data`, falling back to `path`'s extension."""
    for prefix, mime in _MAGIC:
        if data.startswith(prefix):
            return mime
    # RIFF....WEBP — the marker sits at byte 8, not at the start
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data[:1] == b"\x1f" and data[1:2] == b"\x8b":
        return "image/svg+xml"  # .svgz is gzipped SVG
    head = data[:512].lstrip()
    if head[:5] == b"<?xml" or head[:4] == b"<svg":
        return "image/svg+xml"
    return _EXT_MIME.get(os.path.splitext(path)[1].lower(), UNKNOWN_MIME)


def is_image_mime(mime: str) -> bool:
    return mime.startswith("image/")


def looks_like_base64(text: str) -> bool:
    """Whether `text` could plausibly be a bare base64 image blob.

    Cheap structural checks only — the real proof is that it decodes to
    something with an image's magic bytes, which `decode_base64` does.
    """
    if len(text) < _MIN_BASE64_LEN:
        return False
    return bool(_BASE64_ONLY.match("".join(text.split())))


def decode_base64(text: str) -> Optional[bytes]:
    """`text` decoded, or None if it isn't valid base64."""
    packed = "".join(text.split())
    # urlsafe alphabet too: base64 that has been through a URL or a JSON API
    # often comes back with - and _ in place of + and /.
    packed = packed.replace("-", "+").replace("_", "/")
    padding = (-len(packed)) % 4
    try:
        return base64.b64decode(packed + "=" * padding, validate=True)
    except (binascii.Error, ValueError):
        return None


def parse_data_uri(source: str) -> Optional[tuple[bytes, str]]:
    """(bytes, mime) from a `data:` URI, or None if it isn't one/is broken."""
    match = _DATA_URI.match(source)
    if match is None:
        return None
    mime = (match.group(1) or "").strip().lower()
    parameters = (match.group(2) or "").lower()
    payload = source[match.end():]
    if ";base64" in parameters:
        data = decode_base64(payload)
        if data is None:
            return None
    else:
        from urllib.parse import unquote_to_bytes
        data = unquote_to_bytes(payload)
    if not data:
        return None
    return data, (mime or sniff_mime(data))


def resolve_source(source: str) -> tuple[bytes, str, Optional[str]]:
    """Turn an image source string into (bytes, mime, path-or-None).

    `path` is None whenever the image came from a string rather than a file,
    which is how callers tell "this lives on disk" from "these bytes are all
    there is". Raises ValueError/FileNotFoundError with a message meant for
    the user, since both callers surface it directly.
    """
    source = str(source or "").strip()
    if not source:
        raise ValueError(
            "no image given — set 'Image file', drag an image onto the "
            "canvas, paste one from the clipboard, or wire in a path, a "
            "data: URI or a base64 string")

    if source[:5].lower() == "data:":
        parsed = parse_data_uri(source)
        if parsed is None:
            raise ValueError("that data: URI could not be decoded as an image")
        data, mime = parsed
        return data, mime, None

    expanded = os.path.expanduser(source)
    try:
        on_disk = os.path.isfile(expanded)
    except (OSError, ValueError):
        # A multi-megabyte base64 blob is not a path any OS will look at.
        on_disk = False
    if on_disk:
        with open(expanded, "rb") as handle:
            data = handle.read()
        if not data:
            raise ValueError(f"image file is empty: {expanded}")
        return data, sniff_mime(data, expanded), expanded

    if looks_like_base64(source):
        data = decode_base64(source)
        if data:
            mime = sniff_mime(data)
            if is_image_mime(mime):
                return data, mime, None
            raise ValueError(
                "that base64 string decoded, but not into a recognised image "
                "format")

    # Looks like a path, so complain like one — that is the far commoner case.
    if len(source) < 260 and not looks_like_base64(source):
        raise FileNotFoundError(f"image file not found: {expanded}")
    raise ValueError(
        "could not read that image: it is not a file that exists, a data: "
        "URI, or a base64-encoded image")


def to_data_uri(data: bytes, mime: str) -> str:
    """The form nearly every consumer wants — Plotly, HTML, a report embed."""
    return f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"
