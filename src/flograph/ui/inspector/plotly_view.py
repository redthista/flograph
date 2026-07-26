"""HtmlView (aka PlotlyView): renders any HTML in an embedded QWebEngineView,
shared by the webview canvas card and dashboard tiles. It accepts whatever a
node's run() returns — a raw HTML string, or any object with `to_html()`
(Plotly) or `_repr_html_()` (folium, Altair, pandas Styler, …) — so a visual
node can be built from *any* Python library. The webview is created lazily on
first content — Chromium is heavy and the import can be missing on trimmed
PySide6 installs — and the page loads from a temp file, not setHtml: a
self-contained Plotly page embeds all of plotly.js (~3 MB) and setHtml caps
content at 2 MB."""
from __future__ import annotations

import uuid

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from flograph.core.chart_grid import DEFAULT_DIRECTION

RUN_PROMPT = "Run the graph to see the view here."
NO_WEBENGINE = ("Qt WebEngine is not available — install the full PySide6 "
                "package (Tools > Manage Packages) to display web views.")

_plotly_tmp = None  # TemporaryDirectory for the HTML, cleaned at exit


def _plotly_html_path(token: str):
    import tempfile
    from pathlib import Path
    global _plotly_tmp
    if _plotly_tmp is None:
        _plotly_tmp = tempfile.TemporaryDirectory(prefix="flograph-plotly-")
    return Path(_plotly_tmp.name) / f"{token}.html"


def to_html(obj, columns: int = 0, rows: int = 0,
            direction: str = DEFAULT_DIRECTION) -> str | None:
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
        return _wrap(obj)
    render = getattr(obj, "to_html", None)
    if callable(render):
        try:
            return render(full_html=True, include_plotlyjs=True,
                          default_width="100%", default_height="100%",
                          config={"responsive": True})
        except TypeError:
            return _wrap(render())
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
            return _wrap(page())
    render = getattr(obj, "_repr_html_", None)
    if callable(render):
        return _wrap(render())
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


def _wrap(html: str) -> str:
    """Ensure an HTML fragment is a full, full-bleed document."""
    if "<html" in html.lower():
        return html
    return ("<!doctype html><html><head><meta charset='utf-8'>"
            "<style>html,body{margin:0;padding:0;height:100%;width:100%}"
            "body>*{max-width:100%}</style></head>"
            f"<body>{html}</body></html>")


class PlotlyView(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        # per-instance file token: a canvas card and a dashboard tile showing
        # the same node must not race on one HTML file
        self._token = uuid.uuid4().hex
        self.view = None  # the QWebEngineView, once built
        # (columns, rows, direction) for a stacked list — see
        # core.chart_grid. The host sets it from the node's own params.
        self._grid = (0, 0, DEFAULT_DIRECTION)
        self._content = None   # last content, so set_grid can re-render

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self._layout = layout

        placeholder = QLabel(RUN_PROMPT)
        placeholder.setAlignment(Qt.AlignCenter)
        placeholder.setWordWrap(True)
        placeholder.setStyleSheet("color: #6b7280;")
        layout.addWidget(placeholder, 1)
        self.placeholder = placeholder

    def _ensure_view(self):
        if self.view is not None:
            return self.view
        try:
            from PySide6.QtWebEngineWidgets import QWebEngineView
            from PySide6.QtWebEngineCore import QWebEngineSettings
        except ImportError:
            return None
        view = QWebEngineView()
        # content is loaded from a local temp file (see set_content), and Qt
        # WebEngine's default local-content sandbox blocks that file from
        # fetching remote subresources — so a folium/Leaflet map or any
        # library relying on a CDN script tag would load the page but never
        # run the script it points to.
        view.settings().setAttribute(
            QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls,
            True)
        view.hide()
        self._layout.addWidget(view, 1)
        self.view = view
        return view

    def set_grid(self, columns: int = 0, rows: int = 0,
                 direction: str = DEFAULT_DIRECTION) -> None:
        """How a *list* of figures should be arranged: 0 means work it out.

        Re-renders immediately from the content already on show — a param
        change evicts the node's cache, so waiting for a run would leave
        the old arrangement up (see FigureView.set_grid).
        """
        grid = (columns, rows, direction)
        if grid == self._grid:
            return
        self._grid = grid
        if isinstance(self._content, (list, tuple)) and self._content:
            self.set_content(self._content)

    def set_content(self, content) -> None:
        """Render freshly computed content (or None) into the embedded webview
        — a raw HTML string, or any object with to_html()/_repr_html_(). Call
        from the GUI thread only."""
        self._content = content
        html = to_html(content, *self._grid)
        if html is None:
            if self.view is not None:
                self.view.hide()
            self.placeholder.setText(RUN_PROMPT)
            self.placeholder.show()
            return
        view = self._ensure_view()
        if view is None:
            self.placeholder.setText(NO_WEBENGINE)
            self.placeholder.show()
            return
        from PySide6.QtCore import QUrl
        path = _plotly_html_path(self._token)
        path.write_text(html, encoding="utf-8")
        view.load(QUrl.fromLocalFile(str(path)))
        self.placeholder.hide()
        view.show()

    # historical name — callers still push output via set_figure()
    set_figure = set_content

    def set_zoom(self, factor: float) -> None:
        """Chromium zooms natively (and stays crisp) — callers drive this
        instead of scaling the widget through a graphics transform."""
        if self.view is not None:
            self.view.setZoomFactor(factor)


# neutral name for the generalized any-HTML view; PlotlyView stays as the
# historical alias used across the canvas and dashboard imports
HtmlView = PlotlyView
