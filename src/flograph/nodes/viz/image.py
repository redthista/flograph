"""Image

Show a picture on the canvas: PNG, JPEG, GIF (animated), WebP (animated),
SVG, BMP, ICO, TIFF, PPM/PGM/PBM, XPM and more — whatever the installed Qt
image plugins can read, with no extra Python packages needed.

Three ways to get one:

  • drag an image file from the file manager onto the canvas,
  • copy an image to the clipboard (your OS screenshot key does this) and
    paste it onto the canvas with Ctrl+V,
  • drop this node and pick a file in "Image file".

The card draws straight from the file, so the picture appears without
running the graph. Running it emits the image on the "image" port so it can
feed other nodes — `data_uri` slots directly into Plotly, HTML or a report:

    fig.add_layout_image(source=image["data_uri"], ...)

Animated GIF/WebP play on the card when "Animate" is on. Playback stops by
itself whenever the card isn't really being looked at — zoomed out past the
detail threshold, or with the canvas preview switched off — so a canvas
full of animations costs nothing while you work elsewhere on it.
"""
import base64
import os

NODE = {
    "label": "Image",
    "category": "Viz",
    "card": "image",
    # The optional input lets an upstream node choose the file (a path built
    # by an Expression, a filename from a table); it wins over the param.
    "inputs": [("path", "string", {"optional": True})],
    "outputs": [("image", "object")],
}
PARAMS = [
    {"name": "path", "type": "file_open", "label": "Image file", "default": ""},
    {"name": "fit", "type": "choice", "label": "Fit",
     "options": ["Fit", "Fill", "Stretch", "Original size"], "default": "Fit"},
    {"name": "scale", "type": "int", "label": "Scale %",
     "default": 100, "min": 25, "max": 400},
    {"name": "animate", "type": "bool", "label": "Animate", "default": True},
    {"name": "background", "type": "bool", "label": "Card background",
     "default": True},
    {"name": "width", "type": "int", "label": "Width",
     "default": 320, "min": 60, "max": 1600},
    {"name": "height", "type": "int", "label": "Height",
     "default": 240, "min": 60, "max": 1600},
]

# Magic-byte sniffing rather than trusting the extension: a screenshot saved
# by the paste path is always .png, but a file dragged in may be named
# anything at all, and the mime type is what a data URI needs to be right.
_MAGIC = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
    (b"BM", "image/bmp"),
    (b"II*\x00", "image/tiff"),
    (b"MM\x00*", "image/tiff"),
    (b"\x00\x00\x01\x00", "image/x-icon"),
)

_EXT_MIME = {
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".jfif": "image/jpeg", ".gif": "image/gif", ".webp": "image/webp",
    ".bmp": "image/bmp", ".svg": "image/svg+xml", ".svgz": "image/svg+xml",
    ".ico": "image/x-icon", ".tif": "image/tiff", ".tiff": "image/tiff",
}


def _sniff_mime(data: bytes, path: str) -> str:
    for prefix, mime in _MAGIC:
        if data.startswith(prefix):
            return mime
    # RIFF....WEBP — the marker is at byte 8, not the start
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data.lstrip()[:5] in (b"<?xml", b"<svg"):
        return "image/svg+xml"
    return _EXT_MIME.get(os.path.splitext(path)[1].lower(),
                         "application/octet-stream")


def run(ctx, path=None):
    source = str(path if path else ctx.params.get("path", "") or "").strip()
    if not source:
        raise ValueError(
            "no image selected — set 'Image file', drag an image file onto "
            "the canvas, or paste one from the clipboard")
    source = os.path.expanduser(source)
    if not os.path.isfile(source):
        raise FileNotFoundError(f"image file not found: {source}")

    with open(source, "rb") as handle:
        data = handle.read()
    if not data:
        raise ValueError(f"image file is empty: {source}")

    mime = _sniff_mime(data, source)
    ctx.log(f"loaded {len(data):,} bytes of {mime} from {source}")
    # `data_uri` is the form nearly every consumer wants (Plotly, HTML, a
    # report embed), so it is built once here rather than in each of them.
    return {"image": {
        "path": source,
        "mime": mime,
        "bytes": data,
        "data_uri": f"data:{mime};base64,{base64.b64encode(data).decode()}",
    }}
