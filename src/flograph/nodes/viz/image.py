"""Image

Show a picture on the canvas: PNG, JPEG, GIF (animated), WebP (animated),
SVG, BMP, ICO, TIFF, PPM/PGM/PBM, XPM and more — whatever the installed Qt
image plugins can read, with no extra Python packages needed.

Four ways to get one:

  • drag an image file from the file manager onto the canvas,
  • copy an image to the clipboard (your OS screenshot key does this) and
    paste it onto the canvas with Ctrl+V,
  • drop this node and pick a file in "Image file",
  • wire something into the "source" port — see below.

**"Image file" and the "source" port both take three forms**: a path to a
file, a `data:image/png;base64,...` URI, or a bare base64 string. So an
image that arrives as base64 out of a REST call, a database blob column or
a Python Script node can be plugged straight in without being written to
disk first. A wired source wins over the typed one.

**Sharing the flow.** A pasted picture is stored inside the project
automatically — it is held as base64 in "Image file", so the image travels
with the .flograph (or an exported .flowf). A picture chosen from or dragged
in as a *file* stays a link to that file; to carry a copy inside the project
instead, right-click the node and pick **Embed Image in the File**.

The card draws straight from the source, so a picture set here appears
without running the graph. Running the node emits it on the "image" port so
it can feed other nodes — `data_uri` slots directly into Plotly, HTML or a
report:

    fig.add_layout_image(source=image["data_uri"], ...)

The emitted dict carries `bytes`, `mime`, `data_uri`, and `path` (the file
it came from, or None when it came from a string).

Animated GIF/WebP play on the card when "Animate" is on. Playback stops by
itself whenever the card isn't really being looked at — zoomed out past the
detail threshold, or with the canvas preview switched off — so a canvas
full of animations costs nothing while you work elsewhere on it.
"""

NODE = {
    "label": "Image",
    "category": "Viz",
    "version": "1.0",
    "card": "image",
    # The optional input lets an upstream node supply the picture: a path it
    # built, or base64 straight out of an API or a blob column.
    "inputs": [("source", "string", {"optional": True})],
    "outputs": [("image", "object")],
}
PARAMS = [
    {"name": "path", "type": "file_open", "label": "Image file",
     "default": "", "placeholder": "file path, data: URI, or base64"},
    {"name": "fit", "type": "choice", "label": "Fit",
     "options": ["Fit", "Fill", "Stretch", "Original size"], "default": "Fit"},
    # Cosmetic: run() never reads it — the zoom happens as the card decodes
    # the picture, which it redraws on a param change without a run.
    {"name": "scale", "type": "int", "label": "Scale %",
     "default": 100, "min": 25, "max": 400, "cosmetic": True},
    {"name": "animate", "type": "bool", "label": "Animate", "default": True},
    {"name": "background", "type": "bool", "label": "Card background",
     "default": True},
    {"name": "width", "type": "int", "label": "Width",
     "default": 320, "min": 60, "max": 1600, "cosmetic": True},
    {"name": "height", "type": "int", "label": "Height",
     "default": 240, "min": 60, "max": 1600, "cosmetic": True},
]


def run(ctx, source=None):
    # Imported here, not at the top: the canvas card resolves sources with
    # this same module, so a path, a data: URI and a base64 blob can never
    # mean one thing to the node and another to the picture on screen.
    from flograph.core.images import resolve_source, to_data_uri

    raw = str(source if source else ctx.params.get("path", "") or "")
    data, mime, path = resolve_source(raw)

    origin = path if path else f"{len(raw):,} characters of encoded image"
    ctx.log(f"loaded {len(data):,} bytes of {mime} from {origin}")
    return {"image": {
        "path": path,
        "mime": mime,
        "bytes": data,
        "data_uri": to_data_uri(data, mime),
        # What the card should draw. Echoed back so a *wired* source reaches
        # the canvas, which otherwise only ever sees the node's own param.
        "source": raw,
    }}
