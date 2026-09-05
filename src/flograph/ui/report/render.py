"""Turning a report body into a laid-out Qt document.

The pipeline, and why it has the shape it does:

    body markdown
      -> embeds resolved (core.report), images left as tokens
      -> QTextDocument.setMarkdown  (Qt does headings, tables, lists…)
      -> toHtml
      -> tokens swapped for <img src="embed:N">
      -> QTextDocument.setHtml, with the QImages registered as resources

The detour through HTML is not decoration: Qt's markdown reader silently
drops image syntax, so an embedded chart written as markdown would vanish
without a trace. Rendering the text with Qt (which handles far more of
CommonMark than anything worth hand-writing) and splicing the pictures into
the HTML afterwards keeps both halves.

The same document is what the preview shows and what is printed to PDF, so
what you see really is what you get.
"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from typing import Optional

from PySide6.QtCore import QUrl
from PySide6.QtGui import QImage, QImageReader, QTextDocument

from flograph.core.report import (IMAGE_TOKEN, IMAGE_TOKEN_URL,
                                  PAGEBREAK_TOKEN, format_scalar,
                                  frame_to_markdown, inline_markdown,
                                  mark_page_breaks, missing_embed,
                                  replace_columns, replace_embeds,
                                  unrun_embed)
from flograph.ui.emoji_font import with_emoji

# Default rendered width of an embedded figure, in points: the printable
# width of A4 portrait at the margins export.py uses (210mm - 2x15mm).
# Report pages render at this whatever the preview pane's width, so the
# preview shows the proportions the PDF will actually have. Cards pass
# their own width instead — see render_card.
FIGURE_WIDTH = 510

# Enough of a stylesheet to make a printed report look like a document
# rather than a text dump. Qt's rich text engine supports a small CSS
# subset — everything here is inside it.
REPORT_CSS = """
    body { font-family: sans-serif; font-size: 11pt; }
    h1 { font-size: 20pt; }
    h2 { font-size: 15pt; }
    h3 { font-size: 12.5pt; }
    table { border-collapse: collapse; }
    td, th { border: 1px solid #999; padding: 3px 7px; }
    th { background-color: #eeeeee; }
    blockquote { color: #b45309; }
"""


def _document() -> QTextDocument:
    """A report document whose font can draw an emoji.

    A rule can put one in a cell (`breach=🔥`) and a page can type one in
    its prose, and Qt paints an emoji the document font cannot rasterise as
    empty space — a blank column in the PDF. `ui/emoji_font` finds a family
    that does draw it and hangs it off the back of the font, which changes
    nothing about how the text itself sets. Both documents need it: the
    staged one writes its font-family into the HTML it hands on, and that
    declaration would otherwise outrank the final document's default.
    """
    document = QTextDocument()
    document.setDefaultFont(with_emoji(document.defaultFont()))
    return document


@dataclass
class _TablePlacement:
    """One embedded table that has to be measured once the page exists.

    `height=` needs the real height of a row, and `fit` needs the room left
    on the page the table landed on — neither is knowable while the HTML is
    being written. So the table goes out at its asked-for size carrying an
    invisible marker, and `fit_tables` comes back afterwards, finds it,
    measures it and rebuilds it if it has to.
    """
    ref: str
    marker: str
    build: object              # (rows, font_pt) -> html
    rows: int
    font_pt: "float | None"
    height: "float | None"     # the `height=` budget, in points
    fit: bool


@dataclass
class RenderedReport:
    document: QTextDocument
    #: embed refs that resolved to nothing — the page shows them inline, and
    #: the export warns rather than quietly shipping a report full of holes
    problems: list[str] = field(default_factory=list)
    #: image index -> the encoded bytes of an animation, for whoever is
    #: showing this on screen to play (see ui/report/animate.py). Empty when
    #: rendering for print, paper having no way to animate.
    animations: dict = field(default_factory=dict)
    #: image index -> the width it is drawn at, so a frame can be decoded at
    #: the size it will actually appear
    image_widths: dict = field(default_factory=dict)
    #: the embedded images themselves, in token order. The document holds
    #: them as resources under an "embed:N" URL, which is meaningless to
    #: anything outside this process — a report written out as HTML has to
    #: inline them instead, and this is what it inlines. See html.py.
    images: list = field(default_factory=list)


#: Space between charts in a multi-column stack, in points.
GRID_GAP = 8


# Target resolution for charts on paper. A *target*, not a multiplier: a
# fixed 2x put a 7in figure at 198dpi however big it was drawn, which is
# visibly soft on anything with thin lines. Scaling to a DPI instead makes
# every chart come out the same on paper whatever size it was authored at,
# and stops small figures being over-rendered for nothing.
PRINT_DPI = 300

# Ceiling on the up-scale, because the cost is quadratic and a report can
# hold a stack of forty charts. A 7in figure at 100dpi hits 300 on paper at
# about 3x, so this only bites on unusually small figures — where the
# quality gain would be least visible anyway.
MAX_IMAGE_SCALE = 4.0


def print_scale(figure, image_width: int) -> float:
    """How much to up-scale `figure` so it lands at PRINT_DPI when drawn
    `image_width` points wide."""
    try:
        natural = figure.get_size_inches()[0] * figure.get_dpi()
    except Exception:
        return 1.0
    if natural <= 0:
        return 1.0
    wanted = image_width / 72.0 * PRINT_DPI
    return max(1.0, min(MAX_IMAGE_SCALE, wanted / natural))


def _as_image(value, scale: float = 1.0) -> "QImage | None":
    """A matplotlib Figure rendered to a QImage, or None for anything else.

    Imported lazily and defensively: matplotlib is an optional extra, and a
    report that mentions a chart must not fail to open on a machine without
    it — the embed just reports itself unrenderable instead.
    """
    if not hasattr(value, "canvas") or not hasattr(value, "savefig"):
        return None
    try:
        from matplotlib.backends.backend_agg import FigureCanvasAgg
        # The figure is the cached object the canvas card is also showing,
        # so its dpi is borrowed and put back rather than changed. Inches
        # are untouched, so the layout is identical — only denser.
        original = value.get_dpi()
        try:
            if scale != 1.0:
                value.set_dpi(original * scale)
            canvas = FigureCanvasAgg(value)
            canvas.draw()
            width, height = canvas.get_width_height()
            # copy(): the buffer belongs to the canvas, which is about to go
            return QImage(bytes(canvas.buffer_rgba()), width, height,
                          QImage.Format_RGBA8888).copy()
        finally:
            value.set_dpi(original)
    except Exception:
        return None


def _as_payload_image(value) -> "QImage | None":
    """An Image node's output rendered, or None for anything else.

    Without this an `![[logo]]` embed reaches format_scalar and the reader
    gets the payload dict printed as text. Accepts what an Image node emits
    (`bytes` + an image mime type), the `data_uri` field on its own — so
    `![[logo|image]]` piped through a script still works — and a bare
    `data:image/...` string, which would otherwise be inlined as markdown
    and land on the page as a wall of base64.

    Qt decodes PNG/JPEG/GIF/WebP/BMP/SVG from memory here; an animation
    contributes its first frame, paper having no other option.
    """
    data = None
    if isinstance(value, dict):
        raw = value.get("bytes")
        if isinstance(raw, (bytes, bytearray)) and \
                str(value.get("mime", "")).startswith("image/"):
            data = bytes(raw)
        elif isinstance(value.get("data_uri"), str):
            value = value["data_uri"]
    if data is None and isinstance(value, str) \
            and value[:11].lower().startswith("data:image/"):
        from flograph.core.images import parse_data_uri
        parsed = parse_data_uri(value)
        if parsed is None:
            return None
        data = parsed[0]
    if not data:
        return None
    image = QImage()
    if not image.loadFromData(data) or image.isNull():
        return None
    return image


def _payload_bytes(value) -> "bytes | None":
    """The encoded image behind whatever `_as_payload_image` just accepted."""
    if isinstance(value, dict):
        raw = value.get("bytes")
        if isinstance(raw, (bytes, bytearray)) and \
                str(value.get("mime", "")).startswith("image/"):
            return bytes(raw)
        value = value.get("data_uri")
    if isinstance(value, str) and value[:11].lower().startswith("data:image/"):
        from flograph.core.images import parse_data_uri
        parsed = parse_data_uri(value)
        if parsed is not None:
            return parsed[0]
    return None


def _animation_bytes(value) -> "bytes | None":
    """The encoded image, but only if it actually moves.

    A single-frame GIF is a picture, not an animation, and giving one a
    QMovie would cost a timer for nothing — so the frame count decides,
    not the format.
    """
    data = _payload_bytes(value)
    if not data:
        return None
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice
    store = QByteArray(data)
    buffer = QBuffer()
    buffer.setData(store)
    buffer.open(QIODevice.ReadOnly)
    reader = QImageReader(buffer)
    if reader.supportsAnimation() and reader.imageCount() > 1:
        return data
    return None


# What a Plotly figure is drawn at when its layout does not say. Plotly's
# own defaults, so a figure that never had a size set comes out shaped the
# way it looks on a card.
PLOTLY_SIZE = (700, 450)

#: Ceiling on the `scale=` density multiplier, on top of the resolution the
#: placement already asks for. Same reasoning as MAX_IMAGE_SCALE: the cost
#: is quadratic and a report can hold a stack of charts.
MAX_SCALE_MULTIPLIER = 4.0

#: Rows of a table an embed shows before it is cut with a note, and the
#: most `rows=` may ask for. The ceiling is not arithmetic like the ones
#: above — it is that a table is laid out cell by cell by Qt, so a report
#: asking for a hundred thousand rows would appear to hang.
TABLE_ROWS = 30
MAX_TABLE_ROWS = 2000

#: The body text size REPORT_CSS sets, in points. A table's `scale=` is a
#: multiple of it, so `scale=0.8` is 8.8pt rather than a guess.
REPORT_FONT_PT = 11.0
#: What `scale=` may do to a table. Unlike a chart's density — which only
#: ever sharpens — a table's text is worth shrinking, which is the whole
#: reason to ask; but past these it is either unreadable or a headline.
MIN_TABLE_SCALE, MAX_TABLE_SCALE = 0.4, 3.0
#: The fewest rows `fit` will cut a table down to. Under this it is not a
#: table any more, it is a tease — and a whole table broken over a page
#: boundary reads better than two rows and a promise.
FIT_MIN_ROWS = 3
#: The invisible marker that finds one table in the laid-out document: a
#: word joiner around a run of zero-width spaces. Both print as nothing and
#: neither is a space. Bracketed so that no marker is a prefix of another —
#: searching for the first table's mark must not land inside the fourth's.
TABLE_MARK = "\u2060"
TABLE_MARK_FILL = "\u200b"


def table_marker(index: int) -> str:
    return TABLE_MARK + TABLE_MARK_FILL * (index + 1) + TABLE_MARK


def parse_aspect(raw: str) -> "float | None":
    """A `ratio=` value as the single number width / height.

    `16:9`, `4x3` and `3/2` all mean the same thing; a bare `1.5` is taken
    as that ratio directly. None for anything unparseable or non-positive —
    the caller reports it rather than drawing a nonsense shape.
    """
    text = (raw or "").strip().lower().replace("x", ":").replace("/", ":")
    if not text:
        return None
    try:
        if ":" in text:
            left, _, right = text.partition(":")
            width, height = float(left), float(right)
            if width <= 0 or height <= 0:
                return None
            return width / height
        value = float(text)
        return value if value > 0 else None
    except ValueError:
        return None

# On screen there is no paper to match, so charts are drawn at twice the
# width they are placed at — enough to stay sharp on a HiDPI display
# without paying print resolution for a preview.
PREVIEW_OVERSAMPLE = 2


def plotly_geometry(value, image_width: int, for_print: bool,
                    aspect: "float | None" = None,
                    scale_mult: float = 1.0) -> tuple:
    """(width, height, scale) to draw a Plotly figure at.

    The split matters. Plotly lays out in CSS pixels and sizes its fonts in
    them, so asking for a *wider* figure makes the text proportionally
    smaller rather than the picture sharper — a chart exported at 2000px
    comes out with unreadable labels. Resolution is the `scale` factor's
    job, which multiplies the pixel density and leaves the layout alone.
    Kaleido draws the same distinction; so does this.

    So the figure keeps the *width* it was designed at, and only the
    density follows the placement: on paper, enough to land at PRINT_DPI for
    the width the picture is actually placed at. Capped, because the cost is
    quadratic and a stack can hold forty charts.

    `aspect` (from `ratio=`) is the one thing that does change the layout —
    the height, at that same design width, so a `16:9` figure comes out
    letterbox and a `2:3` one tall. Only the height moves, so the fonts
    keep their size against the axis. `scale_mult` (from `scale=`) pushes
    the density past what the placement asked for, for a fine-detail chart.
    """
    layout = getattr(value, "layout", None)
    width = int(getattr(layout, "width", None) or PLOTLY_SIZE[0])
    height = int(getattr(layout, "height", None) or PLOTLY_SIZE[1])
    if aspect:
        height = max(1, round(width / aspect))
    if for_print:
        wanted = image_width / 72.0 * PRINT_DPI
    else:
        wanted = image_width * PREVIEW_OVERSAMPLE
    scale = max(1.0, min(MAX_IMAGE_SCALE, wanted / width))
    if scale_mult != 1.0:
        scale = max(1.0, min(MAX_IMAGE_SCALE, scale * scale_mult))
    return width, height, round(scale, 3)


def plotly_image(value, image_width: int, for_print: bool,
                 aspect: "float | None" = None, scale_mult: float = 1.0):
    """A Plotly figure as PNG bytes, or a warning block if it cannot be.

    Plotly figures are interactive HTML, not pictures, so a report has to
    have one taken. The app's own Qt WebEngine does that (see
    plotly_snapshot) and needs nothing installed; kaleido is tried second
    for the case where WebEngine is missing but kaleido is not, since a
    trimmed PySide6 build is exactly when it would be.
    """
    module = type(value).__module__ or ""
    if not module.startswith("plotly"):
        return None
    width, height, scale = plotly_geometry(value, image_width, for_print,
                                           aspect, scale_mult)
    try:
        from .plotly_snapshot import snapshot
        image = snapshot(value, width, height, scale)
    except Exception:
        image = None
    if image:
        return image
    try:
        return value.to_image(format="png", width=width, height=height,
                              scale=scale)
    except Exception:
        return ("> **⚠ This Plotly chart could not be drawn** — Qt "
                "WebEngine is not available to take a picture of it. Install "
                "the full PySide6 package from Manage Packages…, then run "
                "again.")


# The size a webview card is when nothing says otherwise — the default
# width/height every stock webview node ships with. Only reached for a card
# whose params have been stripped; a real node always says.
HTML_CARD_SIZE = (420, 320)


def html_geometry(params, image_width: int, for_print: bool,
                  aspect: "float | None" = None,
                  scale_mult: float = 1.0) -> tuple:
    """(width, height, scale) to draw a webview card's HTML at.

    The same split as plotly_geometry, for the same reason: HTML lays out
    in CSS pixels, so a *wider* page is a different layout — text wraps
    elsewhere, a flex row breaks differently — not a sharper picture. So
    the page keeps the pixel size its card is set to, which is the size its
    author was looking at while building it, and only the density follows
    the placement on the page.

    That the density is free is the gift of printing the page rather than
    grabbing it: the snapshot is vector, so 4x costs nothing but pixels.

    `aspect` (from `ratio=`/`height=`) changes the height the page is laid
    out at, exactly as dragging the card taller would.
    """
    params = params or {}
    width = _card_dimension(params.get("width"), HTML_CARD_SIZE[0])
    height = _card_dimension(params.get("height"), HTML_CARD_SIZE[1])
    if aspect:
        height = max(1, round(width / aspect))
    if for_print:
        wanted = image_width / 72.0 * PRINT_DPI
    else:
        wanted = image_width * PREVIEW_OVERSAMPLE
    scale = max(1.0, min(MAX_IMAGE_SCALE, wanted / width))
    if scale_mult != 1.0:
        scale = max(1.0, min(MAX_IMAGE_SCALE, scale * scale_mult))
    return width, height, round(scale, 3)


def _card_dimension(value, fallback: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return fallback
    return number if number > 0 else fallback


def html_image(value, params, image_width: int, for_print: bool,
               aspect: "float | None" = None, scale_mult: float = 1.0,
               grid: tuple = ()):
    """A webview card's output as PNG bytes, or None.

    The HTML is built by the *same* function the card and Open in Browser
    use (core.html.to_html), so the three cannot drift, and photographed by
    the app's own Chromium (see html_snapshot). None means "nothing to
    show here" — the value wasn't HTML at all, or no browser was available
    to take the picture — and leaves the caller to fall back.
    """
    from flograph.core import html as core_html
    try:
        page = (core_html.to_html(value, *grid) if grid
                else core_html.to_html(value))
    except Exception:
        return None
    if not page:
        return None
    width, height, scale = html_geometry(params, image_width, for_print,
                                         aspect, scale_mult)
    try:
        from .html_snapshot import snapshot
        return snapshot(page, width, height, scale)
    except Exception:
        return None


def _labelled(graph, ref: str) -> list:
    """Every node whose label matches `ref`, case-insensitively."""
    wanted = ref.strip().casefold()
    return [n for n in graph.nodes.values() if n.label.casefold() == wanted]


def embeddable_nodes(graph, cache) -> list:
    """Nodes worth offering in an insert menu: everything that has produced
    something, by label.

    Read from the cache rather than the graph, because an embed of a node
    that has never run renders as a warning — offering those would be
    offering to write a hole into the report.
    """
    if cache is None:
        return []
    # `ports()`, not `outputs`: a cached result that has not been loaded off
    # disk yet is still a result. Testing the outputs dict would drop every
    # node in a freshly-opened project from the list of things that can be
    # embedded, which is the opposite of what this function is for.
    return sorted((node for node in graph.nodes.values()
                   if cache.get(node.id) is not None
                   and cache.get(node.id).ports()),
                  key=lambda n: n.label.casefold())


def duplicate_labels(graph) -> set:
    """Casefolded labels that more than one node carries.

    Embeds resolve by label, so such a name is a question with no answer —
    nothing but a rename can settle it. Insert menus grey those out and the
    renderer refuses to guess.
    """
    seen: dict[str, int] = {}
    for node in graph.nodes.values():
        key = node.label.casefold()
        seen[key] = seen.get(key, 0) + 1
    return {label for label, count in seen.items() if count > 1}


def embed_line(label: str, at_block_start: bool) -> str:
    """The text an insert menu drops in: an embed on a line of its own.

    Sharing a line with a paragraph renders it inline, which is almost
    never what someone picking a chart from a menu means.
    """
    return ("" if at_block_start else "\n\n") + f"![[{label}]]\n"


def report_body(node) -> "str | None":
    """A report card's markdown body, or None if `node` isn't one.

    Checked off the card marker in the node's own source, which travels
    with a fork, rather than the legacy type_id map — the report card
    postdates the marker, so there is no old id to fall back to.
    """
    if node is None or getattr(node.spec, "card", None) != "report":
        return None
    return str(node.params.get("text", "") or "")


def nested_by_label(graph, cache):
    """For a page: when an embed names a report *card*, hand back what it
    takes to render that card here — its body, and the lookups that resolve
    the card's own `![[a]]` against its own wired inputs.

    Without this a page embedding a report node showed the card's raw
    markdown, `![[a]]` and all: the page resolved one embed, got a string
    back, and a substituted string is not re-scanned (nor should it be —
    that would let any node inject embeds into a page it isn't part of).
    Going through the card's own lookup is what keeps the page honest: the
    nested embeds still name *the card's* inputs, not the page's labels.
    """
    def find(ref: str, port: str):
        matches = _labelled(graph, ref)
        if len(matches) != 1:
            return None            # missing or ambiguous: by_label complains
        body = report_body(matches[0])
        if body is None:
            return None
        node_id = matches[0].id
        return (body, by_wired_input(graph, cache, node_id),
                source_by_wired_input(graph, node_id))
    return find


def nested_by_wired_input(graph, cache, node_id: str):
    """The same, one level in: a report card that names another report card
    renders its contents rather than its source.

    Follows the same order as by_wired_input — a wired input first, then a
    node of that label — so both ways of naming a card nest identically.
    """
    def find(ref: str, port: str):
        name = (port or ref).strip()
        node = graph.nodes.get(node_id)
        source = None
        if node is not None and name in {p.name for p in node.spec.inputs}:
            conn = graph.input_connection(node_id, name)
            source = graph.nodes.get(conn.src_node) if conn else None
        else:
            matches = _labelled(graph, ref)
            source = matches[0] if len(matches) == 1 else None
        body = report_body(source)
        if body is None:
            return None
        return (body, by_wired_input(graph, cache, source.id),
                source_by_wired_input(graph, source.id))
    return find


def by_label(graph, cache):
    """Lookup for a report *page*: embeds name a node by its label.

    Labels, not ids, because a page is written by hand and has to keep
    working when the node is moved, recoloured or re-forked. Renaming the
    node does break the embed — which is why an unresolved one shouts.

    A page sits outside the flow, so reaching across the graph for a cached
    output is honest here. It is *not* honest inside a node — see
    by_wired_input.
    """
    def lookup(ref: str, port: str):
        matches = _labelled(graph, ref)
        if not matches:
            return None, missing_embed(ref), f"no node called “{ref}”"
        if len(matches) > 1:
            # Silently taking the first would make the report depend on
            # which node happened to be created first — invisible from the
            # page, and it would change under an innocent edit. Nothing but
            # a rename can disambiguate, so say that.
            return None, (
                f"> **⚠ {len(matches)} nodes are called “{ref}”** — rename "
                "one so this embed knows which you mean."), \
                f"{len(matches)} nodes are called “{ref}”"
        node = matches[0]
        entry = cache.get(node.id) if cache is not None else None
        name = port or (node.spec.outputs[0].name if node.spec.outputs else "")
        if entry is None or name not in entry.ports():
            return None, unrun_embed(ref), f"“{ref}” hasn’t run"
        # outputs_for, not entry.outputs: rendering is the point at which the
        # value has to be real. Writing a report is an export, not a preview,
        # so a blob that has not been loaded is worth reading now — the
        # alternative is a report with a hole where the table should be.
        outputs = cache.outputs_for(node.id)
        if name not in outputs:
            return None, unrun_embed(ref), f"“{ref}” hasn’t run"
        return outputs[name], "", ""
    return lookup


def by_wired_input(graph, cache, node_id: str):
    """Lookup for a report *card*: embeds name one of the node's own inputs,
    falling back to naming any node on the canvas by its label.

    Wired inputs come first, and a name that is an input port always
    resolves as one — even when unwired, where it reports that rather than
    quietly finding a node of the same name. Unplugging a wire must not
    silently swap the source of a paragraph.

    The label fallback is a convenience with a real cost, and it is worth
    knowing which you are using. An input is a dependency the scheduler can
    see: it orders the card after its source and shows the relationship on
    the canvas as a wire. A label is neither — a partial run (Run To This
    Node) can leave a label embed with nothing to show, and nothing on the
    canvas says where the value came from. The card's display refreshes
    after every full run, so in ordinary use the difference is invisible,
    which is exactly why it is written down here.
    """
    def lookup(ref: str, port: str):
        name = (port or ref).strip()
        node = graph.nodes.get(node_id)
        if node is None:
            return None, missing_embed(ref), f"no node for “{ref}”"
        if name not in {p.name for p in node.spec.inputs}:
            return by_label(graph, cache)(ref, port)
        conn = graph.input_connection(node_id, name)
        if conn is None:
            return None, (f"> **⚠ Nothing wired into “{name}”** — connect "
                          "something to that input."), \
                f"nothing wired into “{name}”"
        entry = cache.get(conn.src_node) if cache is not None else None
        if entry is None or conn.src_port not in entry.ports():
            return None, unrun_embed(name), f"“{name}” hasn’t run"
        outputs = cache.outputs_for(conn.src_node)   # an export: load it
        if conn.src_port not in outputs:
            return None, unrun_embed(name), f"“{name}” hasn’t run"
        return outputs[conn.src_port], "", ""
    return lookup


class _Resolver:
    """Turns each embed into report markdown, collecting images to be
    spliced in afterwards. How an embed finds its value is the `lookup`
    passed in — see by_label and by_wired_input."""

    def __init__(self, lookup, image_scale: float = 1.0,
                 image_width: int = FIGURE_WIDTH, source=None,
                 nested=None, page_height: "float | None" = None,
                 cache=None) -> None:
        self._lookup = lookup
        # Read for one thing only: the `style` a table card publishes, so
        # an embedded table arrives on the page with the conditional
        # formatting it is showing on the canvas. Everything else about a
        # value still comes through `lookup`.
        self._cache = cache
        # (ref, port) -> (body, lookup, source) when the embed names a report
        # card, so its contents are rendered here instead of its source text.
        self._nested = nested
        self._depth = 0
        # (ref) -> the node that produced the value, so an embed can be
        # rendered the way that node's own card renders it: the grid a list
        # is laid out on, and the size a webview card's HTML was built for.
        # None = nothing known about the source.
        self._source = source
        from flograph.core.chart_grid import DEFAULT_DIRECTION
        self._grid = (0, 0, DEFAULT_DIRECTION)
        # 1.0 = leave figures at their own resolution (the on-screen
        # preview); "print" = scale each so it lands at PRINT_DPI on paper
        self._for_print = image_scale != 1.0
        self._image_width = image_width
        # The shape and density asked of the embed being rendered right now,
        # set for its duration only — see `render`. None/1.0 = leave it be.
        self._aspect: "float | None" = None
        self._scale_mult = 1.0
        # How many rows of a table this embed shows, from `rows=`.
        self._max_rows = TABLE_ROWS
        # A table's own reading of `scale=` and `height=`: text size, and a
        # budget of vertical space. Charts read the same two words as
        # density and shape, which is why they are held apart.
        self._table_scale = 1.0
        self._table_height: "float | None" = None
        self._table_fit = False
        # `ratio=` is the one option a table cannot take; remembered so the
        # message names it exactly rather than guessing from the aspect
        self._table_ratio = False
        # tables that asked to be measured after layout — `height=` needs
        # the real row height, `fit` needs the room left on the page
        self.tables: list = []
        # The body height of one page, in points — only a report *page* has
        # one. Needed by the `fit` pass; None makes `fit` a no-op.
        self._page_height = page_height
        self.images: list[QImage] = []
        # the width each image should be drawn at — per image, because a
        # multi-column grid renders its cells narrower than the page
        self.widths: list[int] = []
        # image indices tagged `fit`, for the post-layout shrink pass
        self.fit_marks: list[int] = []
        self.problems: list[str] = []
        # image index -> encoded bytes, for the ones that move. Never
        # collected for print: a PDF gets the poster frame and nothing else.
        self.animations: dict[int, bytes] = {}

    def _token(self, image: QImage, width: Optional[int] = None) -> str:
        self.images.append(image)
        self.widths.append(self._image_width if width is None else width)
        return IMAGE_TOKEN.format(len(self.images) - 1)

    def render(self, embed) -> str:
        for segment in getattr(embed, "unknown", ()):
            # Reported rather than ignored: "widht=50%" silently doing
            # nothing leaves someone staring at an unchanged chart, which is
            # the worst way to find out a name was wrong.
            self.problems.append(
                f"“{embed.ref}”: don't know what “{segment}” means")
        nested = self._nested(embed.ref, embed.port) if self._nested else None
        if nested is not None:
            return self._render_nested(embed.ref, *nested)
        value, failure, problem = self._lookup(embed.ref, embed.port)
        if failure:
            self.problems.append(problem)
            return failure
        # the grid settings belong to the node that produced the list, so
        # its charts are arranged the same on paper as on its own card
        self._grid = self._grid_for(embed)
        # A per-embed width, shape and density are applied for the duration
        # of this embed only, so `![[a|width=50%]]` narrows that one chart
        # and leaves the next at the page width.
        was = (self._image_width, self._aspect, self._scale_mult,
               self._max_rows, self._table_scale, self._table_height,
               self._table_fit, self._table_ratio)
        self._image_width = self._width_for(embed)
        self._aspect = self._aspect_for(embed)
        self._scale_mult = self._scale_for(embed)
        self._max_rows = self._rows_for(embed)
        self._table_scale = self._table_scale_for(embed)
        self._table_height = self._table_height_for(embed)
        self._table_fit = bool((embed.options or {}).get("fit"))
        self._table_ratio = bool(
            str((embed.options or {}).get("ratio", "")).strip())
        before = len(self.images)
        try:
            return self.render_value(value, embed.ref)
        finally:
            if (embed.options or {}).get("fit"):
                self._mark_fit(embed, before)
            (self._image_width, self._aspect, self._scale_mult,
             self._max_rows, self._table_scale, self._table_height,
             self._table_fit, self._table_ratio) = was

    def _mark_fit(self, embed, before: int) -> None:
        """Record the images this embed added as candidates for the
        end-of-layout shrink. `fit` needs a page to fit *within*, so on a
        report card — which has none — it says so rather than doing nothing
        silently."""
        added = range(before, len(self.images))
        if self._page_height is None:
            if added:
                self.problems.append(
                    f"“{embed.ref}”: “fit” only works on a report page")
            return
        self.fit_marks.extend(added)

    def _width_for(self, embed) -> int:
        """`width=50%` of the page's text column, or `width=280` in points.

        The percentage is of the *available* width rather than of the
        image's natural size: "half the page" is what someone means by 50%
        when they are trying to fit a chart beside a heading, and it is the
        only reading that gives the same result for two different charts.
        """
        raw = (embed.options or {}).get("width", "").strip()
        if not raw:
            return self._image_width
        try:
            if raw.endswith("%"):
                fraction = float(raw[:-1]) / 100.0
                return max(40, int(self._image_width * fraction))
            return max(40, int(float(raw.removesuffix("pt").strip())))
        except ValueError:
            self.problems.append(
                f"“{embed.ref}”: “{raw}” is not a width — try 50% or 280")
            return self._image_width

    def _aspect_for(self, embed) -> "float | None":
        """The width/height the chart should be drawn at.

        `ratio=16:9` says it directly; `height=180` says it as points, and
        is turned into a ratio against the width now in force so the two
        options can share one code path downstream. `ratio` wins if both
        are given.
        """
        options = embed.options or {}
        raw = str(options.get("ratio", "")).strip()
        if raw:
            aspect = parse_aspect(raw)
            if aspect is None:
                self.problems.append(
                    f"“{embed.ref}”: “{raw}” is not a ratio — try 16:9 or 1.5")
            return aspect
        raw = str(options.get("height", "")).strip()
        if raw:
            try:
                points = float(raw.removesuffix("pt").strip())
                if points > 0:
                    return self._image_width / points
            except ValueError:
                pass
            self.problems.append(
                f"“{embed.ref}”: “{raw}” is not a height — try 180 or 180pt")
        return None

    def _scale_for(self, embed) -> float:
        """`scale=2` renders the chart at twice the density the placement
        asked for — for a chart with small text or dense lines. Capped, and
        never below 1: this knob makes things sharper, not softer."""
        raw = str((embed.options or {}).get("scale", "")).strip()
        if not raw:
            return 1.0
        try:
            value = float(raw.rstrip("x"))
        except ValueError:
            self.problems.append(
                f"“{embed.ref}”: “{raw}” is not a scale — try 2")
            return 1.0
        return max(1.0, min(MAX_SCALE_MULTIPLIER, value))

    def _rows_for(self, embed) -> int:
        """`rows=50` shows fifty rows of a table before the "showing N of
        M" note. The default is deliberately short — a report is a summary,
        and a table that runs for nine pages is nearly always an accident —
        but "nearly always" is why it can be asked for."""
        raw = str((embed.options or {}).get("rows", "")).strip()
        if not raw:
            return TABLE_ROWS
        try:
            value = int(float(raw))
        except ValueError:
            self.problems.append(
                f"“{embed.ref}”: “{raw}” is not a row count — try 50")
            return TABLE_ROWS
        return max(1, min(MAX_TABLE_ROWS, value))

    def _table_scale_for(self, embed) -> float:
        """`scale=` read the way a *table* means it: text size.

        The same word does two jobs because each is the obvious reading of
        its own medium. A chart is a picture, so scaling it is about
        density and never goes below 1 — asking for a softer picture is
        asking for a worse one. A table is text, and the reason anyone
        scales text on a page is to get more of it into the space, so here
        it goes both ways.
        """
        raw = str((embed.options or {}).get("scale", "")).strip()
        if not raw:
            return 1.0
        try:
            value = float(raw.rstrip("x"))
        except ValueError:
            return 1.0          # `_scale_for` has already said so
        return max(MIN_TABLE_SCALE, min(MAX_TABLE_SCALE, value))

    def _table_height_for(self, embed) -> "float | None":
        """`height=200` read the way a *table* means it: a budget of page,
        in points, that it shows as many rows as will fit inside.

        A chart turns the same number into a shape to be redrawn at. A
        table has no shape — it is as tall as its rows — so the honest
        reading is how much room it may take, and the "showing N of M rows"
        note it already carries says what that cost.
        """
        raw = str((embed.options or {}).get("height", "")).strip()
        if not raw:
            return None
        try:
            points = float(raw.removesuffix("pt").strip())
        except ValueError:
            return None         # `_aspect_for` has already said so
        return points if points > 0 else None

    #: How many report cards deep an embed may go. Wires are acyclic, so
    #: this can't actually run away — it is a guard against a graph state
    #: nobody has thought of, and a bound on how much a single `![[...]]`
    #: can pull into a page.
    MAX_DEPTH = 5

    def _render_nested(self, ref: str, body: str, lookup, source) -> str:
        """Render a report card's body in place, on *this* resolver.

        Reusing self rather than building a second one is the whole trick:
        images are collected in one list and spliced into one document, so a
        chart inside an embedded card arrives on the page like any other.
        Only the lookup and the source finder are swapped, and put back
        afterwards — the nested embeds must resolve against the card's
        inputs, and everything after it in the body against the page again.
        """
        if self._depth >= self.MAX_DEPTH:
            self.problems.append(f"“{ref}” nests reports more than "
                                 f"{self.MAX_DEPTH} deep")
            return (f"> **⚠ “{ref}” nests reports too deeply** — a report "
                    "card embedding another, more than "
                    f"{self.MAX_DEPTH} levels down.")
        was = (self._lookup, self._source, self._depth)
        self._lookup, self._source = lookup, source
        self._depth += 1
        try:
            return replace_embeds(body, self.render)
        finally:
            self._lookup, self._source, self._depth = was

    def _grid_for(self, embed) -> tuple:
        from flograph.core.chart_grid import grid_settings
        node = self._node_for(embed.ref)
        return grid_settings(node.params if node is not None else None)

    def _node_for(self, ref: str):
        """The node that produced this embed's value, if it can be found."""
        if self._source is None:
            return None
        try:
            return self._source(ref)
        except Exception:
            return None

    def render_list(self, values, ref: str) -> str:
        """A list laid out on the node's grid.

        Markdown has no grid, so a multi-column stack becomes a small HTML
        table — which Qt's rich text does understand, and which survives
        into the PDF. One column stays plain markdown blocks, so the
        ordinary case produces no table markup at all.
        """
        from flograph.core.chart_grid import cells, grid_shape
        columns, rows, direction = self._grid
        n_columns, n_rows = grid_shape(len(values), columns, rows,
                                       direction)
        if n_columns <= 1:
            return "\n\n".join(self.render_value(v, ref) for v in values)

        # Each cell is narrower, so the images inside must be too — and
        # the arithmetic has to match the cell chrome exactly or the last
        # column runs off the page. The <td>s below carry an inline style
        # zeroing the report stylesheet's table border and padding, leaving
        # only GRID_GAP between them.
        was, self._image_width = self._image_width, max(
            80, (self._image_width - GRID_GAP * (n_columns - 1)) // n_columns)
        try:
            rendered = [self.render_value(v, ref) for v in values]
        finally:
            self._image_width = was

        grid: dict = {}
        for content, (row, column) in zip(
                rendered, cells(len(values), columns, rows, direction)):
            grid[(row, column)] = content

        out = ['<table style="border:none;border-collapse:collapse"'
               ' class="flograph-chart-grid"><tbody>']
        for row in range(n_rows):
            out.append("<tr>")
            for column in range(n_columns):
                cell = grid.get((row, column), "")
                pad = 0 if column == n_columns - 1 else GRID_GAP
                out.append(
                    f'<td style="border:none;padding:0 {pad}px '
                    f'{GRID_GAP}px 0;vertical-align:top">'
                    f"{self._as_html(cell)}</td>")
            out.append("</tr>")
        out.append("</tbody></table>")
        return "".join(out)

    def render_columns(self, columns: list, weights: list) -> str:
        """A columns block as a one-row table.

        The same device as a chart grid, and for the same reason: Qt's rich
        text has no columns of its own, but it does understand a table, and
        a table survives into the PDF and the exported HTML unchanged.

        Each column's embeds are resolved *while its own width is in force*,
        so a chart in a third of the page is drawn a third of the page wide
        rather than drawn full width and then squeezed.
        """
        total = sum(weights) or 1.0
        gap = GRID_GAP * (len(columns) - 1)
        room = max(80, self._image_width - gap)
        widths = [max(40, int(room * weight / total)) for weight in weights]

        cells = []
        for text, width in zip(columns, widths):
            was, self._image_width = self._image_width, width
            try:
                cells.append(self._as_html(
                    mark_page_breaks(replace_embeds(text, self.render))))
            finally:
                self._image_width = was

        out = ['<table style="border:none;border-collapse:collapse"'
               ' class="flograph-columns"><tbody><tr>']
        for index, (cell, width) in enumerate(zip(cells, widths)):
            pad = 0 if index == len(cells) - 1 else GRID_GAP
            # Top and bottom padding, not just the gutter: a table has no
            # margin of its own in Qt's rich text, so without it the
            # paragraph above and the first line of a cell sit flush
            # together and read as one block.
            out.append(
                f'<td width="{width}" style="border:none;'
                f'padding:{GRID_GAP}px {pad}px {GRID_GAP}px 0;'
                f'vertical-align:top">{cell}</td>')
        out.append("</tr></tbody></table>")
        return "".join(out)

    @staticmethod
    def _as_html(markdown: str) -> str:
        """A cell's content as HTML. Image tokens pass through untouched —
        they are swapped for <img> after the markdown pass either way."""
        if not markdown.strip():
            return ""
        if markdown.strip().startswith("@@flograph-embed-"):
            return markdown.strip()
        staged = _document()
        staged.setMarkdown(markdown)
        body = staged.toHtml()
        start, end = body.find("<body"), body.rfind("</body>")
        if start == -1 or end == -1:
            return markdown
        return body[body.find(">", start) + 1:end]

    def _matplotlib_image(self, value):
        """A matplotlib Figure as a QImage with this embed's shape and
        density applied, or None for anything that isn't a Figure.

        `ratio=` / `height=` change the figure's size in inches for the
        draw, so the axes and labels lay out for the new shape rather than
        being stretched into it afterwards — the size is borrowed and put
        back, the same way `_as_image` borrows the dpi.
        """
        if not hasattr(value, "canvas") or not hasattr(value, "savefig"):
            return None
        original = None
        if self._aspect:
            width_in = float(value.get_size_inches()[0])
            original = tuple(value.get_size_inches())
            value.set_size_inches(width_in, width_in / self._aspect,
                                  forward=False)
        try:
            density = self._scale_mult
            if self._for_print:
                density *= print_scale(value, self._image_width)
            density = max(1.0, min(MAX_IMAGE_SCALE, density))
            return _as_image(value, density)
        finally:
            if original is not None:
                value.set_size_inches(original, forward=False)

    def _webview_image(self, value, ref: str) -> "str | None":
        """This embed as a picture of its webview card, or None if it isn't
        one — in which case the ordinary branches below have it.

        A card that *is* a webview and cannot be photographed says so
        rather than falling back to inlining its HTML: the fallback is the
        wrecked-layout wall of text this branch exists to replace, and a
        report is better off naming the missing piece.
        """
        node = self._node_for(ref)
        if node is None:
            return None
        from ..canvas.node_item import card_kind
        if card_kind(node) != "webview":
            return None
        picture = html_image(value, node.params, self._image_width,
                             self._for_print, self._aspect, self._scale_mult,
                             self._grid)
        if picture:
            image = QImage()
            if image.loadFromData(picture, "PNG") and not image.isNull():
                return self._token(image)
        self.problems.append(f"“{ref}” could not be drawn")
        return ("> **⚠ This web view could not be drawn** — Qt WebEngine "
                "is not available to take a picture of it. Install the full "
                "PySide6 package from Manage Packages…, then run again.")

    def render_value(self, value, ref: str) -> str:
        if value is None:
            self.problems.append(f"“{ref}” produced nothing")
            return unrun_embed(ref)

        # A list is how a node says "one of these per value of a column".
        # Rendering it as a run of blocks means a loop in a node's own code
        # is all a faceted report section takes.
        if isinstance(value, (list, tuple)):
            if not value:
                self.problems.append(f"“{ref}” produced an empty list")
                return f"> *(“{ref}” produced nothing to show)*"
            return self.render_list(value, ref)

        image = self._matplotlib_image(value)
        if image is not None:
            return self._token(image)

        plotly = plotly_image(value, self._image_width, self._for_print,
                              self._aspect, self._scale_mult)
        if isinstance(plotly, bytes):
            image = QImage()
            image.loadFromData(plotly, "PNG")
            return self._token(image)
        if plotly is not None:
            self.problems.append(f"“{ref}” could not be drawn")
            return plotly

        # A webview card's own HTML, photographed at the card's size. This
        # sits above the string branch below on purpose: a Web View node's
        # output *is* a string, and inlining it as markdown was what threw
        # the layout away — the page kept the words and lost the design.
        web = self._webview_image(value, ref)
        if web is not None:
            return web

        # Before the string branch below: an Image node's `data_uri` is a
        # string, and inlining that as markdown would print the base64.
        picture = _as_payload_image(value)
        if picture is not None:
            # A chart is redrawn at whatever shape and density is asked for;
            # a picture is a fixed grid of pixels, so `ratio`, `height` and
            # `scale` have nothing to act on. `fit` still does — a tall
            # photo can overflow a page just as a chart can.
            if self._aspect is not None or self._scale_mult != 1.0:
                self.problems.append(
                    f"“{ref}”: ratio, height and scale only apply to charts")
            # A chart is drawn to fill the column, but a picture has a real
            # size of its own: a 120px logo stretched across the page would
            # just be a blurry logo. Fill only if it has the pixels for it.
            width = min(self._image_width, max(1, picture.width()))
            token = self._token(picture, width)
            # On screen an animation can actually move; on paper it can't, so
            # print gets the poster frame that is already in `picture`.
            if not self._for_print:
                moving = _animation_bytes(value)
                if moving is not None:
                    self.animations[len(self.images) - 1] = moving
            return token

        # A plain string is inlined *as markdown*, which is what makes a
        # report writable by the flow: a node that returns prose, headings
        # and tables drops straight in. Dedented on the way — the string was
        # built inside run(), so Python's indentation is on every line, and
        # four spaces in markdown is a code block (see inline_markdown).
        if isinstance(value, str):
            return inline_markdown(value)

        pd = sys.modules.get("pandas")
        if pd is not None and isinstance(value, (pd.DataFrame, pd.Series)):
            return self._table(value, ref)
        if hasattr(value, "itertuples") and hasattr(value, "columns"):
            return self._table(value, ref)    # duck-typed frame

        return format_scalar(value)

    def _table(self, value, ref: str) -> str:
        """A frame as a table, carrying whatever formatting its card shows.

        HTML rather than markdown, and not because of the colours: a
        markdown table has no width either, so `![[Sales|width=50%]]` did
        nothing on the one kind of embed most likely to need it. Written as
        HTML the table takes the placement width like a chart, keeps the
        conditional formatting its Show Table card is displaying, and is
        still *text* — selectable in the PDF, and free to break across a
        page where a picture of a table could not.

        Falls back to the markdown table if anything about the styling
        cannot be worked out: a report showing an unstyled table is a small
        loss, and a report that fails to render is a large one.
        """
        from flograph.core.table_html import frame_to_html
        if self._table_ratio:
            # The one option a table genuinely cannot take: it has no shape
            # to be redrawn at, being exactly as tall as its own rows.
            # Said rather than ignored, the way a picture says it.
            self.problems.append(
                f"“{ref}”: ratio only applies to a chart — a table takes "
                "width, height, rows, scale and fit")
        rules, hidden = self._table_style(ref)
        measured = self._table_height is not None or self._table_fit
        marker = table_marker(len(self.tables)) if measured else ""
        font_pt = (REPORT_FONT_PT * self._table_scale
                   if self._table_scale != 1.0 else None)

        def build(rows: int, size: "float | None") -> str:
            return frame_to_html(value, rules, hidden, max_rows=rows,
                                 width=self._image_width, font_pt=size,
                                 marker=marker)

        try:
            html = build(self._max_rows, font_pt)
        except Exception:
            return frame_to_markdown(value, self._max_rows)
        if measured:
            self.tables.append(_TablePlacement(
                ref=ref, marker=marker, build=build,
                rows=self._max_rows, font_pt=font_pt,
                height=self._table_height, fit=self._table_fit))
        return html

    def _table_style(self, ref: str) -> tuple:
        """(rules, hidden columns) for this embed's table.

        Read off the producing node's own `style` output — the port a Show
        Table already publishes so one table's formatting can be wired into
        another. Taking it from there rather than from the node's params is
        what makes an *incoming* style (from a Table Style node, or another
        table) show up on the page too: the port carries the merged result,
        which is exactly what the card is drawing.
        """
        node = self._node_for(ref)
        if node is None or self._cache is None:
            return (), ()
        if not any(port.name == "style" for port in node.spec.outputs):
            return (), ()
        try:
            style = self._cache.outputs_for(node.id).get("style")
            from flograph.core.table_format import (hidden_columns,
                                                    rules_from_style)
            return rules_from_style(style), hidden_columns(style)
        except Exception:
            return (), ()


def source_by_label(graph):
    """The node an embed names, for reading how its card is set up — the
    grid a list is laid out on, and (for a webview card) the pixel size the
    HTML was designed at."""
    def lookup(ref: str):
        wanted = ref.strip().casefold()
        return next((n for n in graph.nodes.values()
                     if n.label.casefold() == wanted), None)
    return lookup


def source_by_wired_input(graph, node_id: str):
    """Whatever an embed on this card names — the node feeding the input, or
    the node of that label. Same order as by_wired_input, so a chart grid is
    laid out from its own node's settings either way."""
    def lookup(ref: str):
        name = ref.strip()
        node = graph.nodes.get(node_id)
        if node is not None and name in {p.name for p in node.spec.inputs}:
            conn = graph.input_connection(node_id, name)
            return graph.nodes.get(conn.src_node) if conn else None
        matches = _labelled(graph, ref)
        return matches[0] if len(matches) == 1 else None
    return lookup


def render_report(body: str, graph, cache, image_scale: float = 1.0,
                  setup=None, page_break_rule: bool = False) -> RenderedReport:
    """A report *page*: embeds name nodes by label.

    Naming a report *card* renders that card's contents onto the page —
    charts, tables and all — rather than reproducing its source markdown.

    `setup` is the page's PageSetup. Two things are taken from it here: the
    body width, because charts are raster by the time they reach the
    document and the width they are drawn at has to be decided now; and the
    body height, so an `![[chart|fit]]` can be shrunk to the room left on
    its page. None keeps the A4 default.
    """
    width = setup.body_width_points() if setup is not None else FIGURE_WIDTH
    page_height = None
    if setup is not None:
        from .export import body_rect, printable_points
        page_height = body_rect(printable_points(setup), setup).height()
    return render_body(body, by_label(graph, cache), image_width=width,
                       image_scale=image_scale,
                       source=source_by_label(graph),
                       nested=nested_by_label(graph, cache),
                       page_break_rule=page_break_rule,
                       page_height=page_height, cache=cache)


def render_card(body: str, graph, cache, node_id: str,
                width: "int | None" = None,
                image_scale: float = 1.0,
                page_break_rule: bool = False) -> RenderedReport:
    """A report *card*: embeds name the node's own wired inputs.

    `width` is the card's usable width — charts are raster by the time they
    get here and Qt's rich text has no percentage sizing, so a figure drawn
    at the page width would simply hang off the edge of a narrow card.

    `image_scale` is for the card's own Export PDF: on the canvas a card is
    drawn at screen resolution, and printing that would put a visibly soft
    chart on paper.
    """
    return render_body(body, by_wired_input(graph, cache, node_id),
                       image_width=width or FIGURE_WIDTH,
                       image_scale=image_scale,
                       source=source_by_wired_input(graph, node_id),
                       nested=nested_by_wired_input(graph, cache, node_id),
                       page_break_rule=page_break_rule, cache=cache)


def render_body(body: str, lookup, image_width: int = FIGURE_WIDTH,
                image_scale: float = 1.0, source=None,
                nested=None, page_break_rule: bool = False,
                page_height: "float | None" = None,
                cache=None) -> RenderedReport:
    """Lay a report body out as a document ready to show or print.

    `page_break_rule` is for the on-screen preview, which is one
    continuous scroll and so has no page boundary for a forced break to
    land on. It draws the break as a visible rule instead, which is the
    only way the writer can see that the marker took effect at all; the
    printed document gets a real break and no rule.

    `page_height` is the body height of one page in points, and only a
    report *page* has one. It is what an `![[chart|fit]]` is measured
    against; without it `fit` is a no-op that says so.
    """
    resolver = _Resolver(lookup, image_scale, image_width, source, nested,
                         page_height, cache)
    # Columns first, and they resolve their own embeds as they go: an embed
    # inside a column has to be rendered knowing how wide that column is.
    staged_body = replace_columns(body, resolver.render_columns)
    # After the embeds, not before: a node that returns markdown can then
    # force a break of its own, which is how a per-region section built in
    # a Python Script node gets to start each region on a fresh page.
    resolved = mark_page_breaks(replace_embeds(staged_body, resolver.render))

    staged = _document()
    staged.setMarkdown(resolved)
    html = staged.toHtml()
    for index, width in enumerate(resolver.widths):
        html = html.replace(IMAGE_TOKEN.format(index), _img_tag(index, width))
    if page_break_rule:
        html = _PAGEBREAK_P_RE.sub("<hr />", html)

    document = _document()
    # Qt insets rich text by 4px a side by default. An image sized to the
    # caller's available width would then be exactly that much too wide, so
    # every embedded chart would hang off the edge; the inset belongs to the
    # widget's padding (and the PDF's margins) instead.
    document.setDocumentMargin(0)
    document.setDefaultStyleSheet(REPORT_CSS)
    for index, image in enumerate(resolver.images):
        document.addResource(QTextDocument.ImageResource,
                             QUrl(IMAGE_TOKEN_URL.format(index)), image)
    document.setHtml(html)
    apply_page_breaks(document)
    if resolver.tables:
        # before the images: a table that loses rows moves everything under
        # it, and an image measured against the old layout would be fitted
        # to a page it is no longer on
        html = fit_tables(document, html, resolver, page_height, image_width)
    if resolver.fit_marks and page_height:
        _fit_to_page(document, html, resolver, page_height, image_width)
    return RenderedReport(
        document=document, problems=resolver.problems,
        animations=resolver.animations,
        image_widths={i: w for i, w in enumerate(resolver.widths)},
        images=list(resolver.images))


#: How far `fit` will shrink a chart before it gives up and lets it start
#: its own page — a fraction of the width the embed was going to be.
_FIT_FLOOR = 0.45


def _img_tag(index: int, width: int) -> str:
    """The `<img>` an embed token becomes. One place, so the initial pass
    and the `fit` rewrite cannot spell it differently."""
    return f'<img src="embed:{index}" width="{max(80, int(width))}" />'


_TABLE_TAG_RE = re.compile(r"<\s*(/?)\s*table\b", re.IGNORECASE)


def _table_span(html: str, marker: str) -> "tuple | None":
    """`(start, end)` of the whole `<table>…</table>` the marker sits in.

    Found rather than remembered: by the time this runs the table has been
    through Qt's markdown reader and back out of `toHtml`, which rewrites
    the markup — so the string this module wrote is no longer in the page,
    but the marker it put in the header cell still is. A data bar is itself
    a little table inside a cell, so the scan counts depth and takes the
    outermost one.
    """
    at = html.find(marker)
    if at == -1:
        return None
    depth, start = 0, None
    for match in _TABLE_TAG_RE.finditer(html):
        closing = match.group(1) == "/"
        if not closing:
            if depth == 0:
                start = match.start()
            depth += 1
            continue
        depth -= 1
        if depth <= 0:
            depth = 0
            end = html.find(">", match.end())
            if start is not None and end != -1 and start < at < end:
                return start, _with_note(html, end + 1, marker)
            start = None
    return None


def _with_note(html: str, end: int, marker: str) -> int:
    """Extend a table's span over the "showing N of M rows" note under it.

    The note is a paragraph of its own, so replacing only the table would
    leave the old count sitting under the new table. It carries the same
    marker, which is what identifies it as this table's own.
    """
    opening = html.find("<p", end)
    if opening == -1:
        return end
    closing = html.find("</p>", opening)
    if closing == -1 or marker not in html[opening:closing]:
        return end
    return closing + len("</p>")


def _measure(document, placement: "_TablePlacement") -> "tuple | None":
    """`(top, height, rows drawn)` for a placed table, or None if it cannot
    be found — a table that fell inside a nested card, say."""
    from PySide6.QtGui import QTextTable

    cursor = document.find(placement.marker)
    if cursor.isNull():
        return None
    table = document.frameAt(cursor.position())
    if not isinstance(table, QTextTable):
        return None
    rect = document.documentLayout().frameBoundingRect(table)
    if rect.height() <= 0 or table.rows() < 2:
        return None
    return rect.top(), rect.height(), table.rows() - 1      # minus the header


def fit_tables(document, html: str, resolver, page_height: "float | None",
               page_width: int) -> str:
    """Give each measured table the size it asked for, now that there is a
    page to measure against.

    Two questions the HTML could not answer on its own:

    * `height=200` — how many rows *is* 200 points? The row height depends
      on the font, the padding and whatever the cells hold, so the table is
      drawn once and then trimmed to the rows that fit.
    * `fit` — how much room is left on the page this table landed on? The
      table's own top answers it, and unlike an image a table does not
      float to the next page first: Qt breaks it across the boundary, so
      where it starts is where it was written.

    One measure-and-rebuild pass, like the image fit. Returns the HTML as
    it now stands, so the image pass that follows works from the same text.
    """
    from PySide6.QtCore import QSizeF
    from PySide6.QtGui import QGuiApplication

    # Measuring means laying the document out, and laying it out means font
    # metrics, which Qt will not produce without a GUI application — it
    # aborts the process rather than returning something wrong. Nothing is
    # being shown in that case anyway, so the tables keep the size they
    # were written at.
    if QGuiApplication.instance() is None:
        return html
    # Nothing can be measured until the document has been laid out at a
    # known width — asking a frame for its rectangle before that aborts Qt
    # outright, not politely. A card has no page height, and still has a
    # width, which is all `height=` needs.
    if page_height:
        document.setPageSize(QSizeF(page_width, page_height))
    else:
        document.setTextWidth(page_width)
    for placement in resolver.tables:
        if placement.fit and not page_height:
            # the same thing an `![[chart|fit]]` on a card is told
            resolver.problems.append(
                f"“{placement.ref}”: “fit” only works on a report page")
        measured = _measure(document, placement)
        if measured is None:
            continue
        top, height, drawn = measured
        per_row = height / max(1, drawn + 1)     # the header is a row too
        rows, font_pt = placement.rows, placement.font_pt

        if placement.height and height > placement.height:
            # one row of the budget belongs to the header
            fits = int(placement.height / per_row) - 1
            if fits < 1:
                resolver.problems.append(
                    f"“{placement.ref}”: height={placement.height:g} is not "
                    f"room for even one row — showing one")
            rows = max(1, min(rows, fits))

        if placement.fit and page_height:
            room = page_height - (top % page_height)
            if height > room:
                # Rows, not text size: a table's height *is* its rows, and
                # a table shrunk to fit an arbitrary gap is a table nobody
                # can read. What it drops, its own "showing N of M" says.
                fits = int(room / per_row) - 1
                if fits >= FIT_MIN_ROWS:
                    rows = min(rows, fits)
                else:
                    # Less than a glance-worth would fit. A whole table
                    # broken over two pages beats a two-row tease on this
                    # one, so it is left alone — as an over-tall chart is.
                    resolver.problems.append(
                        f"“{placement.ref}”: not enough room left on the "
                        f"page for “fit” — showing the table in full")

        if rows == placement.rows and font_pt == placement.font_pt:
            continue
        span = _table_span(html, placement.marker)
        if span is None:
            continue
        try:
            rebuilt = placement.build(rows, font_pt)
        except Exception:
            continue
        html = html[:span[0]] + rebuilt + html[span[1]:]
        placement.rows, placement.font_pt = rows, font_pt
        # Relaid out now, not at the end: a table that just lost eight rows
        # has pulled everything under it up the page, and the next table's
        # "room left on its page" is a different number because of it.
        _relayout(document, html, page_height, page_width)

    return html


def _relayout(document, html: str, page_height: "float | None",
              page_width: int) -> None:
    document.setHtml(html)
    apply_page_breaks(document)
    from PySide6.QtCore import QSizeF
    if page_height:
        document.setPageSize(QSizeF(page_width, page_height))
    else:
        document.setTextWidth(page_width)


def _fit_to_page(document, html: str, resolver, page_height: float,
                 page_width: int) -> None:
    """Shrink each `![[...|fit]]` image that would overflow the room left
    on its page, so it stays on the page it was written on instead of
    starting a new one and leaving a gap.

    One measure-and-relayout pass. The case it is for — a chart under a
    heading and a paragraph — is caught by it; a chart still too tall after
    one shrink is left to start its own page, which is where it was headed
    anyway. Opt-in per embed, because it makes a chart a different size
    depending on where on the page it falls.

    The room left is measured from the *bottom of the paragraph before* the
    chart, not the chart's own top: Qt has already floated an oversized
    image onto the next page by the time this runs, so its own position
    reads as a fresh page and says nothing about where it was written.

    A floor of `_FIT_FLOOR` of the intended width: past that a chart is too
    small to read, and the reader is better served by it whole on the next
    page than shrunk to a stamp on this one.
    """
    from PySide6.QtCore import QSizeF

    from .animate import image_positions

    document.setPageSize(QSizeF(page_width, page_height))
    layout = document.documentLayout()
    positions = image_positions(document)
    changes: dict[int, int] = {}
    for index in resolver.fit_marks:
        image = resolver.images[index]
        if image is None or image.width() <= 0 or image.height() <= 0:
            continue
        position = positions.get(IMAGE_TOKEN_URL.format(index))
        if position is None:
            continue
        block = document.findBlock(position)
        if not block.isValid():
            continue
        # walk back past blank blocks to the last one with real content
        before = block.previous()
        while before.isValid() and not before.text().strip():
            before = before.previous()
        if not before.isValid():
            continue          # nothing above it — it is already page-top
        anchor = layout.blockBoundingRect(before).bottom()
        remaining = page_height - (anchor % page_height)
        width = resolver.widths[index]
        drawn_height = width * image.height() / image.width()
        # Act only when it overflows this page but would fit on a fresh
        # one: a chart taller than a whole page has to break regardless.
        if drawn_height <= remaining + 1 or drawn_height >= page_height:
            continue
        scaled = int(width * (remaining - 6) / drawn_height)
        new_width = min(width, scaled)
        if _FIT_FLOOR * width <= new_width < width:
            changes[index] = new_width
    if not changes:
        return
    for index, new_width in changes.items():
        resolver.widths[index] = new_width
        html = re.sub(rf'<img src="embed:{index}" width="\d+" />',
                      lambda _m, w=new_width, i=index: _img_tag(i, w), html)
    document.setHtml(html)
    apply_page_breaks(document)


#: The whole paragraph Qt wraps a lone page-break token in. Matched as a
#: unit because what replaces it is a different *block*, not different text
#: inside one — an empty <p> left behind would print as a blank line.
_PAGEBREAK_P_RE = re.compile(
    r"<p[^>]*>\s*" + re.escape(PAGEBREAK_TOKEN) + r"\s*</p>",
    re.IGNORECASE)


def apply_page_breaks(document: QTextDocument) -> int:
    """Turn every page-break token in `document` into a real break.

    Done on the finished document rather than in the HTML because a page
    break is a property of a *block* (QTextBlockFormat.PageBreak_AlwaysBefore),
    and the property has to end up on the block that starts the new page —
    not on the marker, which is then deleted so it costs no blank line.

    Returns how many breaks were applied, which is what makes it testable
    without printing anything.
    """
    from PySide6.QtGui import QTextBlockFormat, QTextCursor

    positions = []
    block = document.begin()
    while block.isValid():
        if block.text().strip() == PAGEBREAK_TOKEN:
            positions.append(block.position())
        block = block.next()

    # Back to front: every deletion shifts the positions after it, and none
    # of the positions before it.
    #
    # Delete first, format second, and in that order for a reason. Removing
    # a block's paragraph separator *merges* it with the block below, and
    # the merged block keeps the upper block's format — so a policy set on
    # the following block before the marker was deleted would be thrown
    # away by the deletion that was meant to tidy up after it.
    applied = 0
    for position in reversed(positions):
        cursor = QTextCursor(document)
        cursor.setPosition(position)
        cursor.movePosition(QTextCursor.NextBlock, QTextCursor.KeepAnchor)
        if cursor.hasSelection():
            cursor.removeSelectedText()
            block = document.findBlock(position)
            # A break *before the first block* asks for a page break before
            # page one, which is a blank sheet and nothing else. The marker
            # is still consumed — it just has nothing to do.
            if block.isValid() and block.position() > 0:
                fmt = QTextBlockFormat(block.blockFormat())
                fmt.setPageBreakPolicy(
                    QTextBlockFormat.PageBreak_AlwaysBefore)
                QTextCursor(block).setBlockFormat(fmt)
                applied += 1
        else:
            # Nothing follows: a break here would only produce a blank
            # page. The marker still goes, taking the separator above it so
            # it leaves no empty paragraph behind.
            cursor.movePosition(QTextCursor.EndOfBlock,
                                QTextCursor.KeepAnchor)
            cursor.removeSelectedText()
            if position > 0:
                cursor.deletePreviousChar()
    return applied
