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
                                  replace_embeds, unrun_embed)

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

# On screen there is no paper to match, so charts are drawn at twice the
# width they are placed at — enough to stay sharp on a HiDPI display
# without paying print resolution for a preview.
PREVIEW_OVERSAMPLE = 2


def plotly_geometry(value, image_width: int, for_print: bool) -> tuple:
    """(width, height, scale) to draw a Plotly figure at.

    The split matters. Plotly lays out in CSS pixels and sizes its fonts in
    them, so asking for a *wider* figure makes the text proportionally
    smaller rather than the picture sharper — a chart exported at 2000px
    comes out with unreadable labels. Resolution is the `scale` factor's
    job, which multiplies the pixel density and leaves the layout alone.
    Kaleido draws the same distinction; so does this.

    So the figure keeps the size it was designed at, and only the density
    follows the placement: on paper, enough to land at PRINT_DPI for the
    width the picture is actually placed at. Capped, because the cost is
    quadratic and a stack can hold forty charts.
    """
    layout = getattr(value, "layout", None)
    width = int(getattr(layout, "width", None) or PLOTLY_SIZE[0])
    height = int(getattr(layout, "height", None) or PLOTLY_SIZE[1])
    if for_print:
        wanted = image_width / 72.0 * PRINT_DPI
    else:
        wanted = image_width * PREVIEW_OVERSAMPLE
    scale = max(1.0, min(MAX_IMAGE_SCALE, wanted / width))
    return width, height, round(scale, 3)


def _plotly_image(value, image_width: int, for_print: bool):
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
    width, height, scale = plotly_geometry(value, image_width, for_print)
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
    return sorted((node for node in graph.nodes.values()
                   if cache.get(node.id) is not None
                   and cache.get(node.id).outputs),
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
                params_by_wired_input(graph, node_id))
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
                params_by_wired_input(graph, source.id))
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
        if entry is None or name not in entry.outputs:
            return None, unrun_embed(ref), f"“{ref}” hasn’t run"
        return entry.outputs[name], "", ""
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
        if entry is None or conn.src_port not in entry.outputs:
            return None, unrun_embed(name), f"“{name}” hasn’t run"
        return entry.outputs[conn.src_port], "", ""
    return lookup


class _Resolver:
    """Turns each embed into report markdown, collecting images to be
    spliced in afterwards. How an embed finds its value is the `lookup`
    passed in — see by_label and by_wired_input."""

    def __init__(self, lookup, image_scale: float = 1.0,
                 image_width: int = FIGURE_WIDTH, params=None,
                 nested=None) -> None:
        self._lookup = lookup
        # (ref, port) -> (body, lookup, params) when the embed names a report
        # card, so its contents are rendered here instead of its source text.
        self._nested = nested
        self._depth = 0
        # (ref) -> the producing node's params, so a list embed can be laid
        # out on the grid that node configured. None = no grid settings.
        self._params = params
        from flograph.core.chart_grid import DEFAULT_DIRECTION
        self._grid = (0, 0, DEFAULT_DIRECTION)
        # 1.0 = leave figures at their own resolution (the on-screen
        # preview); "print" = scale each so it lands at PRINT_DPI on paper
        self._for_print = image_scale != 1.0
        self._image_width = image_width
        self.images: list[QImage] = []
        # the width each image should be drawn at — per image, because a
        # multi-column grid renders its cells narrower than the page
        self.widths: list[int] = []
        self.problems: list[str] = []
        # image index -> encoded bytes, for the ones that move. Never
        # collected for print: a PDF gets the poster frame and nothing else.
        self.animations: dict[int, bytes] = {}

    def _token(self, image: QImage, width: Optional[int] = None) -> str:
        self.images.append(image)
        self.widths.append(self._image_width if width is None else width)
        return IMAGE_TOKEN.format(len(self.images) - 1)

    def render(self, embed) -> str:
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
        return self.render_value(value, embed.ref)

    #: How many report cards deep an embed may go. Wires are acyclic, so
    #: this can't actually run away — it is a guard against a graph state
    #: nobody has thought of, and a bound on how much a single `![[...]]`
    #: can pull into a page.
    MAX_DEPTH = 5

    def _render_nested(self, ref: str, body: str, lookup, params) -> str:
        """Render a report card's body in place, on *this* resolver.

        Reusing self rather than building a second one is the whole trick:
        images are collected in one list and spliced into one document, so a
        chart inside an embedded card arrives on the page like any other.
        Only the lookup and params are swapped, and put back afterwards —
        the nested embeds must resolve against the card's inputs, and
        everything after it in the body against the page again.
        """
        if self._depth >= self.MAX_DEPTH:
            self.problems.append(f"“{ref}” nests reports more than "
                                 f"{self.MAX_DEPTH} deep")
            return (f"> **⚠ “{ref}” nests reports too deeply** — a report "
                    "card embedding another, more than "
                    f"{self.MAX_DEPTH} levels down.")
        was = (self._lookup, self._params, self._depth)
        self._lookup, self._params = lookup, params
        self._depth += 1
        try:
            return replace_embeds(body, self.render)
        finally:
            self._lookup, self._params, self._depth = was

    def _grid_for(self, embed) -> tuple:
        from flograph.core.chart_grid import grid_settings
        params = self._params(embed.ref) if self._params else None
        return grid_settings(params)

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

    @staticmethod
    def _as_html(markdown: str) -> str:
        """A cell's content as HTML. Image tokens pass through untouched —
        they are swapped for <img> after the markdown pass either way."""
        if not markdown.strip():
            return ""
        if markdown.strip().startswith("@@flograph-embed-"):
            return markdown.strip()
        staged = QTextDocument()
        staged.setMarkdown(markdown)
        body = staged.toHtml()
        start, end = body.find("<body"), body.rfind("</body>")
        if start == -1 or end == -1:
            return markdown
        return body[body.find(">", start) + 1:end]

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

        image = _as_image(
            value, print_scale(value, self._image_width)
            if self._for_print and hasattr(value, "get_size_inches") else 1.0)
        if image is not None:
            return self._token(image)

        plotly = _plotly_image(value, self._image_width, self._for_print)
        if isinstance(plotly, bytes):
            image = QImage()
            image.loadFromData(plotly, "PNG")
            return self._token(image)
        if plotly is not None:
            self.problems.append(f"“{ref}” could not be drawn")
            return plotly

        # Before the string branch below: an Image node's `data_uri` is a
        # string, and inlining that as markdown would print the base64.
        picture = _as_payload_image(value)
        if picture is not None:
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
            return frame_to_markdown(value)
        if hasattr(value, "itertuples") and hasattr(value, "columns"):
            return frame_to_markdown(value)   # duck-typed frame

        return format_scalar(value)


def params_by_label(graph):
    """The params of the node an embed names, for reading its grid layout."""
    def lookup(ref: str):
        wanted = ref.strip().casefold()
        node = next((n for n in graph.nodes.values()
                     if n.label.casefold() == wanted), None)
        return node.params if node is not None else None
    return lookup


def params_by_wired_input(graph, node_id: str):
    """The params of whatever an embed on this card names — the node feeding
    the input, or the node of that label. Same order as by_wired_input, so a
    chart grid is laid out from its own node's settings either way."""
    def lookup(ref: str):
        name = ref.strip()
        node = graph.nodes.get(node_id)
        if node is not None and name in {p.name for p in node.spec.inputs}:
            conn = graph.input_connection(node_id, name)
            source = graph.nodes.get(conn.src_node) if conn else None
            return source.params if source is not None else None
        matches = _labelled(graph, ref)
        return matches[0].params if len(matches) == 1 else None
    return lookup


def render_report(body: str, graph, cache, image_scale: float = 1.0,
                  setup=None, page_break_rule: bool = False) -> RenderedReport:
    """A report *page*: embeds name nodes by label.

    Naming a report *card* renders that card's contents onto the page —
    charts, tables and all — rather than reproducing its source markdown.

    `setup` is the page's PageSetup, and the only thing taken from it here
    is the body width: charts are raster by the time they reach the
    document, so the width they are drawn at has to be decided now, from
    the paper they are going onto. None keeps the A4 default.
    """
    width = setup.body_width_points() if setup is not None else FIGURE_WIDTH
    return render_body(body, by_label(graph, cache), image_width=width,
                       image_scale=image_scale,
                       params=params_by_label(graph),
                       nested=nested_by_label(graph, cache),
                       page_break_rule=page_break_rule)


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
                       params=params_by_wired_input(graph, node_id),
                       nested=nested_by_wired_input(graph, cache, node_id),
                       page_break_rule=page_break_rule)


def render_body(body: str, lookup, image_width: int = FIGURE_WIDTH,
                image_scale: float = 1.0, params=None,
                nested=None, page_break_rule: bool = False) -> RenderedReport:
    """Lay a report body out as a document ready to show or print.

    `page_break_rule` is for the on-screen preview, which is one
    continuous scroll and so has no page boundary for a forced break to
    land on. It draws the break as a visible rule instead, which is the
    only way the writer can see that the marker took effect at all; the
    printed document gets a real break and no rule.
    """
    resolver = _Resolver(lookup, image_scale, image_width, params, nested)
    # After the embeds, not before: a node that returns markdown can then
    # force a break of its own, which is how a per-region section built in
    # a Python Script node gets to start each region on a fresh page.
    resolved = mark_page_breaks(replace_embeds(body, resolver.render))

    staged = QTextDocument()
    staged.setMarkdown(resolved)
    html = staged.toHtml()
    for index, width in enumerate(resolver.widths):
        html = html.replace(
            IMAGE_TOKEN.format(index),
            f'<img src="embed:{index}" width="{max(80, width)}" />')
    if page_break_rule:
        html = _PAGEBREAK_P_RE.sub("<hr />", html)

    document = QTextDocument()
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
    return RenderedReport(
        document=document, problems=resolver.problems,
        animations=resolver.animations,
        image_widths={i: w for i, w in enumerate(resolver.widths)},
        images=list(resolver.images))


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
