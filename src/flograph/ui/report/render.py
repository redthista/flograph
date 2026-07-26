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

import sys
from dataclasses import dataclass, field

from PySide6.QtCore import QUrl
from PySide6.QtGui import QImage, QTextDocument

from flograph.core.report import (IMAGE_TOKEN, format_scalar,
                                  frame_to_markdown, missing_embed,
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


def _plotly_note(value) -> "str | None":
    """Plotly figures are interactive HTML, not pictures. Static export
    needs kaleido, which flograph doesn't require — so say so plainly
    rather than leaving a blank space in a printed report."""
    module = type(value).__module__ or ""
    if not module.startswith("plotly"):
        return None
    try:
        image = value.to_image(format="png", width=1100, height=650)
    except Exception:
        return ("> **⚠ Plotly charts need the `kaleido` package to appear in "
                "a report** — install it from Manage Packages…, then run "
                "again.")
    return image   # bytes; the caller turns it into a QImage


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
        wanted = ref.strip().casefold()
        matches = [n for n in graph.nodes.values()
                   if n.label.casefold() == wanted]
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
    """Lookup for a report *card*: embeds name one of the node's own inputs.

    A card lives inside the flow, so it must not reach across the graph the
    way a page does — a dependency the scheduler can't see wouldn't re-run
    when its source changed, and wouldn't be ordered after it. Naming your
    own wired inputs keeps the dependency real, visible on the canvas, and
    correct on every run.
    """
    def lookup(ref: str, port: str):
        name = (port or ref).strip()
        node = graph.nodes.get(node_id)
        if node is None:
            return None, missing_embed(ref), f"no node for “{ref}”"
        if name not in {p.name for p in node.spec.inputs}:
            return None, (f"> **⚠ No input called “{name}”** — wire it up, or "
                          "edit the node's code to add the port."), \
                f"no input called “{name}”"
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
                 image_width: int = FIGURE_WIDTH, params=None) -> None:
        self._lookup = lookup
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

    def _token(self, image: QImage) -> str:
        self.images.append(image)
        self.widths.append(self._image_width)
        return IMAGE_TOKEN.format(len(self.images) - 1)

    def render(self, embed) -> str:
        value, failure, problem = self._lookup(embed.ref, embed.port)
        if failure:
            self.problems.append(problem)
            return failure
        # the grid settings belong to the node that produced the list, so
        # its charts are arranged the same on paper as on its own card
        self._grid = self._grid_for(embed)
        return self.render_value(value, embed.ref)

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

        plotly = _plotly_note(value)
        if isinstance(plotly, bytes):
            image = QImage()
            image.loadFromData(plotly, "PNG")
            return self._token(image)
        if plotly is not None:
            self.problems.append(f"“{ref}” needs kaleido to render")
            return plotly

        # A plain string is inlined *as markdown*, which is what makes a
        # report writable by the flow: a node that returns prose, headings
        # and tables drops straight in.
        if isinstance(value, str):
            return value

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
    """The params of whatever feeds this card's named input."""
    def lookup(ref: str):
        conn = graph.input_connection(node_id, ref.strip())
        source = graph.nodes.get(conn.src_node) if conn else None
        return source.params if source is not None else None
    return lookup


def render_report(body: str, graph, cache,
                  image_scale: float = 1.0) -> RenderedReport:
    """A report *page*: embeds name nodes by label."""
    return render_body(body, by_label(graph, cache), image_scale=image_scale,
                       params=params_by_label(graph))


def render_card(body: str, graph, cache, node_id: str,
                width: "int | None" = None) -> RenderedReport:
    """A report *card*: embeds name the node's own wired inputs.

    `width` is the card's usable width — charts are raster by the time they
    get here and Qt's rich text has no percentage sizing, so a figure drawn
    at the page width would simply hang off the edge of a narrow card.
    """
    return render_body(body, by_wired_input(graph, cache, node_id),
                       image_width=width or FIGURE_WIDTH,
                       params=params_by_wired_input(graph, node_id))


def render_body(body: str, lookup, image_width: int = FIGURE_WIDTH,
                image_scale: float = 1.0, params=None) -> RenderedReport:
    """Lay a report body out as a document ready to show or print."""
    resolver = _Resolver(lookup, image_scale, image_width, params)
    resolved = replace_embeds(body, resolver.render)

    staged = QTextDocument()
    staged.setMarkdown(resolved)
    html = staged.toHtml()
    for index, width in enumerate(resolver.widths):
        html = html.replace(
            IMAGE_TOKEN.format(index),
            f'<img src="embed:{index}" width="{max(80, width)}" />')

    document = QTextDocument()
    # Qt insets rich text by 4px a side by default. An image sized to the
    # caller's available width would then be exactly that much too wide, so
    # every embedded chart would hang off the edge; the inset belongs to the
    # widget's padding (and the PDF's margins) instead.
    document.setDocumentMargin(0)
    document.setDefaultStyleSheet(REPORT_CSS)
    for index, image in enumerate(resolver.images):
        document.addResource(QTextDocument.ImageResource,
                             QUrl(f"embed:{index}"), image)
    document.setHtml(html)
    return RenderedReport(document=document, problems=resolver.problems)
