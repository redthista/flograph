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
import functools
import os
import re
import struct
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


def embed_source(value: str) -> str:
    """A file path -> its `data:` URI, so the picture travels inside the flow.

    A `data:` URI, a bare base64 blob, an empty string, or a path that does
    not resolve to a readable file all come back unchanged — the caller can
    tell nothing happened by the result still not starting with ``data:``.
    """
    if not value or value.lstrip()[:5].lower() == "data:":
        return value
    try:
        data, mime, path = resolve_source(value)
    except (ValueError, FileNotFoundError, OSError):
        return value
    return to_data_uri(data, mime) if path else value


# ------------------------------------------------------ pictures in a table

#: A picture's `data:` prefix, which a rules line is stripped of before it
#: is read: the prefix carries a comma, and a rules line is split on commas.
#: The type is sniffed back out of the bytes, so nothing is lost.
DATA_PREFIX = re.compile(r"data:image/[\w.+-]+;base64,", re.IGNORECASE)

#: How much of a base64 string is decoded to decide what it is — enough for
#: an SVG's `<?xml …?>` and a comment or two ahead of its `<svg`.
_SNIFF_CHARS = 1024


@functools.lru_cache(maxsize=4096)
def _picture_uri(text: str) -> Optional[str]:
    prefix = DATA_PREFIX.match(text)
    body = text[prefix.end():] if prefix else text
    if len(body) < _MIN_BASE64_LEN or not _BASE64_ONLY.match(body):
        return None
    head = decode_base64(body[:_SNIFF_CHARS])
    mime = sniff_mime(head) if head else UNKNOWN_MIME
    if not is_image_mime(mime):
        return None
    # the standard alphabet, padded — what a browser and Qt both expect of
    # a data: address, whatever alphabet the string arrived in
    packed = body.replace("-", "+").replace("_", "/").rstrip("=")
    packed += "=" * (-len(packed) % 4)
    return f"data:{mime};base64,{packed}"


def picture_uri(value) -> Optional[str]:
    """`value` as an image `data:` address when it *is* a picture — a
    `data:image/…;base64,` URI, a bare base64 string of a PNG, JPEG, GIF,
    WebP, BMP, ICO or SVG, or the raw bytes of one — else None.

    Cheap for everything that is not one: a number, a short word or a
    sentence with a space in it is turned away before anything is decoded.
    A string that is one is remembered, so a column of logos repainted on
    every scroll is sniffed once per logo, not once per paint.
    """
    if isinstance(value, (bytes, bytearray, memoryview)):
        data = bytes(value)
        mime = sniff_mime(data)
        return to_data_uri(data, mime) if is_image_mime(mime) else None
    if not isinstance(value, str) or len(value) < _MIN_BASE64_LEN:
        return None
    text = value.strip()
    if text[:1] == "<":
        # SVG markup as it is, not encoded — what a design tool copies
        return _svg_markup_uri(text)
    if any(ch.isspace() for ch in text[:256]):
        # a paste wrapped at 76 columns — rare enough to pay for the join
        text = "".join(text.split())
    return _picture_uri(text)


@functools.lru_cache(maxsize=1024)
def _svg_markup_uri(text: str) -> Optional[str]:
    head = text[:4096].lower()
    if "<svg" not in head or "</svg>" not in text[-64:].lower():
        return None
    return to_data_uri(text.encode("utf-8"), "image/svg+xml")


#: A picture on a tile sits this far in from the tile's edge, as a share of
#: its shorter side — room for the colour to read as a ground.
TILE_INSET = 0.14


def tile_radius(shape: Optional[str], width: float, height: float) -> float:
    """The corner radius a picture's `shape` gives a box this size:
    square 0, rounded a fifth of the shorter side, circle half of it."""
    side = min(width, height)
    return {"circle": side / 2, "rounded": side * 0.22}.get(shape or "", 0.0)


def _svg_length(value: "str | None") -> Optional[float]:
    match = re.fullmatch(r"\s*([0-9]*\.?[0-9]+)\s*(px)?\s*", value or "")
    return float(match.group(1)) if match else None


@functools.lru_cache(maxsize=4096)
def picture_dimensions(uri: str) -> Optional[tuple]:
    """(width, height) of the picture in a `data:` address, read from its
    header — None when the format hides it or the header is broken.

    Header-deep on purpose: a table needs a picture's *shape* to lay out a
    row, on paper as on the card, and neither should decode a column of
    logos to find it.
    """
    parsed = parse_data_uri(uri)
    if parsed is None:
        return None
    data, mime = parsed
    try:
        if data.startswith(b"\x89PNG") and data[12:16] == b"IHDR":
            return struct.unpack(">II", data[16:24])
        if data[:3] == b"GIF":
            return struct.unpack("<HH", data[6:10])
        if data[:2] == b"BM":
            w, h = struct.unpack("<ii", data[18:26])
            return abs(w), abs(h)
        if data[:4] in (b"\x00\x00\x01\x00", b"\x00\x00\x02\x00"):
            return data[6] or 256, data[7] or 256
        if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
            chunk = data[12:16]
            if chunk == b"VP8 ":
                w, h = struct.unpack("<HH", data[26:30])
                return w & 0x3FFF, h & 0x3FFF
            if chunk == b"VP8L":
                bits = int.from_bytes(data[21:25], "little")
                return (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
            if chunk == b"VP8X":
                return (int.from_bytes(data[24:27], "little") + 1,
                        int.from_bytes(data[27:30], "little") + 1)
            return None
        if data[:2] == b"\xff\xd8":
            i = 2
            while i + 9 < len(data):
                if data[i] != 0xFF:
                    i += 1
                    continue
                marker = data[i + 1]
                if marker in (0xD8, 0x01, 0xFF) or 0xD0 <= marker <= 0xD7:
                    i += 1 if marker == 0xFF else 2
                    continue
                if (0xC0 <= marker <= 0xCF
                        and marker not in (0xC4, 0xC8, 0xCC)):
                    h, w = struct.unpack(">HH", data[i + 5:i + 9])
                    return w, h
                i += 2 + struct.unpack(">H", data[i + 2:i + 4])[0]
            return None
        if mime == "image/svg+xml":
            head = data[:4096].decode("utf-8", "replace")
            tag = re.search(r"<svg\b[^>]*>", head, re.S)
            if tag is None:
                return None
            attrs = dict(re.findall(r'([\w:-]+)\s*=\s*["\']([^"\']*)["\']',
                                    tag.group(0)))
            w = _svg_length(attrs.get("width"))
            h = _svg_length(attrs.get("height"))
            if w and h:
                return w, h
            box = (attrs.get("viewBox") or "").replace(",", " ").split()
            if len(box) == 4:
                return float(box[2]), float(box[3])
    except (struct.error, IndexError, ValueError):
        return None
    return None


def picture_aspect(uri: str) -> float:
    """Width over height — 1 when the header will not say — held to
    between 1:5 and 5:1, so one banner-shaped logo cannot take a column."""
    size = picture_dimensions(uri)
    if not size or not size[0] or not size[1]:
        return 1.0
    return max(0.2, min(5.0, float(size[0]) / float(size[1])))
