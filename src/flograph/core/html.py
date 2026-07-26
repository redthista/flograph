"""Turning a node's output into an HTML page.

A "webview" node returns whatever its library produces — a raw HTML string,
a Plotly figure, a folium map, an Altair chart, a pandas Styler — and this
module is the single place that decides what HTML that becomes. It lives in
core, with no Qt, because two very different things now need the *same*
answer: the embedded web view on a card, and the page handed to a real
browser. Sharing the function is what makes "Open in Browser" show what the
card shows rather than something that merely resembles it.

The rules, in order: a raw HTML string is used verbatim; then `to_html()`
(Plotly and friends); then `_repr_html_()`, the protocol every
notebook-friendly library implements. A list is laid out on a CSS grid from
core.chart_grid, so a stack is arranged the same way here, in matplotlib and
in the PDF.
"""
from __future__ import annotations

from flograph.core.chart_grid import DEFAULT_DIRECTION


def to_html(obj, columns: int = 0, rows: int = 0,
            direction: str = DEFAULT_DIRECTION) -> "str | None":
    """Coerce a node output to a full HTML page, or None if it can't render.

    Order: a raw HTML string is used verbatim; then `to_html()` (Plotly and
    friends — the rich signature first, plain call as fallback); then the
    universal `_repr_html_()` protocol. Fragments are wrapped into a minimal
    full-bleed document so they fill the card."""
    if obj is None:
        return None
    if isinstance(obj, (list, tuple)):
        return _stack(obj, columns, rows, direction)
    if isinstance(obj, str):
        return wrap(obj)
    render = getattr(obj, "to_html", None)
    if callable(render):
        try:
            return render(full_html=True, include_plotlyjs=True,
                          default_width="100%", default_height="100%",
                          config={"responsive": True})
        except TypeError:
            return wrap(render())
    # folium / branca objects: _repr_html_() wraps the map in an <iframe
    # srcdoc=...> whose "Make this Notebook Trusted to load map" placeholder
    # QtWebEngine leaves visible. Render the full standalone document instead.
    root = getattr(obj, "get_root", None)
    if callable(root):
        try:
            rendered = root()
        except Exception:
            rendered = None
        page = getattr(rendered, "render", None)
        if callable(page):
            return wrap(page())
    render = getattr(obj, "_repr_html_", None)
    if callable(render):
        return wrap(render())
    return None


STACK_ITEM_HEIGHT = "68vh"


def _fragment(obj, first: bool) -> "str | None":
    """One chart of a stack as an HTML fragment.

    Only the first carries plotly.js. It is ~3 MB, they all share one
    document, and repeating it per chart is the difference between a page
    that opens and one that doesn't.
    """
    if obj is None:
        return None
    if isinstance(obj, str):
        return obj
    render = getattr(obj, "to_html", None)
    if callable(render):
        try:
            return render(full_html=False, include_plotlyjs=bool(first),
                          default_width="100%", default_height="100%",
                          config={"responsive": True})
        except TypeError:
            return render()
    render = getattr(obj, "_repr_html_", None)
    return render() if callable(render) else None


def _stack(items, columns: int = 0, rows: int = 0,
           direction: str = DEFAULT_DIRECTION) -> "str | None":
    """A list of figures as one scrolling document.

    A list is how a node says "the same chart, once per value of a column" —
    a loop in the node's own code, no faceting UI to learn. Stacking them
    into a single page rather than a widget each keeps it to one webview,
    gives native scrolling for free, and carries plotly.js once.

    Laid out on a CSS grid from the same rules the matplotlib stack and the
    PDF use (core.chart_grid), so one node's charts are arranged the same
    way wherever they are shown. Explicit row/column placement rather than
    letting the grid flow, because "down" fills columns first and auto-flow
    only does rows.
    """
    from flograph.core.chart_grid import cells, grid_shape

    usable = [item for item in items if item is not None]
    n_columns, n_rows = grid_shape(len(usable), columns, rows, direction)
    placement = cells(len(usable), columns, rows, direction)

    fragments = []
    for item, (row, column) in zip(usable, placement):
        fragment = _fragment(item, first=not fragments)
        if fragment is None:
            continue
        fragments.append(
            f'<div class="flograph-stack-item" style="grid-row:{row + 1};'
            f'grid-column:{column + 1}">{fragment}</div>')
    if not fragments:
        return None

    # Side by side means less width each, so the tall single-column height
    # would leave a wide grid absurdly long. minmax(min, 1fr) is what makes
    # a short stack grow into the spare height rather than leaving the card
    # half empty, while a long one keeps its minimum and scrolls.
    minimum = STACK_ITEM_HEIGHT if n_columns == 1 else f"{70 // n_columns + 8}vh"
    body = "\n".join(fragments)
    return ("<!doctype html><html><head><meta charset='utf-8'><style>"
            "html,body{margin:0;padding:0;height:100%;background:#fff}"
            ".flograph-stack{display:grid;gap:6px;box-sizing:border-box;"
            "min-height:100%;"
            f"grid-template-columns:repeat({n_columns},minmax(0,1fr));"
            # template-rows, not auto-rows: an implicit row only exists if
            # something is placed in it, so a 2x3 grid holding 3 charts
            # would silently collapse to the rows actually used. Asking for
            # a shape should get you that shape, empty cells and all.
            f"grid-template-rows:repeat({n_rows},minmax("
            + str(minimum) + ",1fr))}"
            # overflow:hidden is not tidiness — plotly sizes its plot in
            # pixels at init, and if the grid hasn't settled by then it
            # picks its own default and spills out of the cell, painting
            # over the chart next door. Clipping keeps every chart in its
            # own box whatever plotly decides.
            ".flograph-stack-item{position:relative;overflow:hidden;"
            "min-height:0;height:100%;padding:4px 0;box-sizing:border-box}"
            ".flograph-stack-item>*{max-width:100%;height:100%}"
            "</style></head><body>"
            f'<div class="flograph-stack">{body}</div>'
            # ...and once the grid *has* settled, tell plotly to re-measure,
            # so the clip above never actually has anything to clip.
            "<script>window.addEventListener('load',function(){"
            "requestAnimationFrame(function(){"
            "if(!window.Plotly)return;"
            "document.querySelectorAll('.plotly-graph-div')"
            ".forEach(function(d){try{Plotly.Plots.resize(d)}catch(e){}});"
            "});});</script>"
            "</body></html>")


def wrap(html: str) -> str:
    """Ensure an HTML fragment is a full, full-bleed document."""
    if "<html" in html.lower():
        return html
    return ("<!doctype html><html><head><meta charset='utf-8'>"
            "<style>html,body{margin:0;padding:0;height:100%;width:100%}"
            "body>*{max-width:100%}</style></head>"
            f"<body>{html}</body></html>")


def titled(html: str, title: str) -> str:
    """Give a page a <title>, so a browser tab says which node it came from.

    Only ever *adds* one: a library that already titled its own document
    knows better than we do, and a page with no <head> at all is left alone
    rather than being restructured on a guess.

    "Already titled" means a <title> *in the head*, not anywhere in the
    document — Plotly's modebar carries an inline SVG <title> reading
    "plotly-logomark", which a whole-document search mistakes for the page
    title. It isn't one: browsers only read the head, so believing it left
    every Plotly page named after its temp file instead of its node.
    """
    title = (title or "").strip()
    if not title:
        return html
    lowered = html.lower()
    open_head = lowered.find("<head")
    if open_head == -1:
        return html
    cut = lowered.find(">", open_head)
    if cut == -1:
        return html
    cut += 1
    close_head = lowered.find("</head", cut)
    head = lowered[cut:close_head if close_head != -1 else len(lowered)]
    if "<title" in head:
        return html
    escaped = (title.replace("&", "&amp;").replace("<", "&lt;")
               .replace(">", "&gt;"))
    return f"{html[:cut]}<title>{escaped}</title>{html[cut:]}"
