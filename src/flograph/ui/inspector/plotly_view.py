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


def to_html(obj) -> str | None:
    """Coerce a node output to a full HTML page, or None if it can't render.

    Order: a raw HTML string is used verbatim; then `to_html()` (Plotly and
    friends — the rich signature first, plain call as fallback); then the
    universal `_repr_html_()` protocol. Fragments are wrapped into a minimal
    full-bleed document so they fill the card."""
    if obj is None:
        return None
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

    def set_content(self, content) -> None:
        """Render freshly computed content (or None) into the embedded webview
        — a raw HTML string, or any object with to_html()/_repr_html_(). Call
        from the GUI thread only."""
        html = to_html(content)
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
