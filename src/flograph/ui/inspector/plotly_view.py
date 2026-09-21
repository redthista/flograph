"""HtmlView (aka PlotlyView): renders any HTML in an embedded QWebEngineView,
shared by the webview canvas card and dashboard tiles. It accepts whatever a
node's run() returns — a raw HTML string, or any object with `to_html()`
(Plotly) or `_repr_html_()` (folium, Altair, pandas Styler, …) — so a visual
node can be built from *any* Python library. The webview is created lazily on
first content — Chromium is heavy and the import can be missing on trimmed
PySide6 installs — and the page loads from a temp file, not setHtml: a
self-contained Plotly page embeds all of plotly.js (~3 MB) and setHtml caps
content at 2 MB.

When Chromium fails, it fails *silently*: a page that will not load, and a
page whose renderer process is killed, both leave a blank white rectangle
that is indistinguishable from a node returning an empty chart. So the view
watches for both and says which happened — and a dead renderer is reloaded
once first, because one lost to a momentary squeeze comes back."""
from __future__ import annotations

import uuid

from PySide6.QtCore import QUrl, Qt, Signal
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from flograph.core import html as core_html
from flograph.core.chart_grid import DEFAULT_DIRECTION

RUN_PROMPT = "Run the graph to see the view here."
NO_WEBENGINE = ("Qt WebEngine is not available — install the full PySide6 "
                "package (Tools > Manage Packages) to display web views.")
LOAD_FAILED = ("This view's page did not load. The HTML is written to a temp "
               "file and handed to Qt WebEngine, so a failure here is "
               "Chromium's rather than the node's — re-run the node to try "
               "again.")
RENDERER_GONE = ("Qt WebEngine gave up on this view: {why}. It was reloaded "
                 "once and went again. A very large chart or a machine short "
                 "of memory are the usual causes.")

#: Chromium's word for why a page's process went away, keyed by
#: QWebEnginePage.RenderProcessTerminationStatus. Plain ints, so the message
#: can be built and tested without importing WebEngine.
TERMINATION = {
    0: "the renderer exited normally",
    1: "the renderer exited abnormally",
    2: "the renderer crashed",
    3: "the renderer was killed",
}


def termination_reason(status, code) -> str:
    """Why a page's renderer stopped, in words, for the card to show.

    A webview whose renderer dies goes *blank* and says nothing — the widget
    is still there, the page behind it is not. That is indistinguishable
    from "the node produced an empty chart" unless the view says so, which
    is the whole reason this text exists.
    """
    return (f"{TERMINATION.get(int(status), 'the renderer stopped')} "
            f"(exit code {int(code)})")

_plotly_tmp = None  # TemporaryDirectory for the HTML, cleaned at exit


def _plotly_html_path(token: str):
    import tempfile
    from pathlib import Path
    global _plotly_tmp
    if _plotly_tmp is None:
        _plotly_tmp = tempfile.TemporaryDirectory(prefix="flograph-plotly-")
    return Path(_plotly_tmp.name) / f"{token}.html"


# The coercion itself lives in flograph.core.html: the same function has to
# answer for the embedded view and for "Open in Browser", or the two would
# drift into showing different pages. Re-exported here because the canvas,
# the dashboard and the report all import it from this module.
to_html = core_html.to_html
STACK_ITEM_HEIGHT = core_html.STACK_ITEM_HEIGHT


class PlotlyView(QWidget):
    #: (param name, JSON payload) written by the page itself via
    #: `flograph.set(...)` — only ever emitted once set_interactive(True) has
    #: been called. Raw and unvetted: the host owns the node, so the host
    #: decides what the node allows (flograph.core.bridge.accept).
    param_written = Signal(str, str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        # The page-writes-back channel, off until a host turns it on: a
        # channel per web view is not free and an ordinary chart has nothing
        # to say. The receiver outlives the QWebEngineView, which set_content
        # destroys and rebuilds to give back a big chart's memory.
        self._interactive = False
        self._receiver = None
        # per-instance file token: a canvas card and a dashboard tile showing
        # the same node must not race on one HTML file
        self._token = uuid.uuid4().hex
        self.view = None  # the QWebEngineView, once built
        # the file currently in front of the view, so a page whose renderer
        # died can be reloaded without waiting for the next run
        self._path = None
        self._retried = False
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
        placeholder.setStyleSheet("color: palette(mid);")
        layout.addWidget(placeholder, 1)
        self.placeholder = placeholder

    def _ensure_view(self):
        if self.view is not None:
            return self.view
        try:
            from PySide6.QtWebEngineCore import QWebEngineSettings

            from ..webprofile import new_view
            view = new_view()
        except ImportError:
            return None
        # content is loaded from a local temp file (see set_content), and Qt
        # WebEngine's default local-content sandbox blocks that file from
        # fetching remote subresources — so a folium/Leaflet map or any
        # library relying on a CDN script tag would load the page but never
        # run the script it points to.
        view.settings().setAttribute(
            QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls,
            True)
        view.hide()
        # A page that fails to load, or whose renderer Chromium kills, leaves
        # a blank white rectangle and no clue whose fault it was. Both are
        # said out loud instead.
        view.loadFinished.connect(self._on_load_finished)
        view.page().renderProcessTerminated.connect(self._on_renderer_gone)
        self._layout.addWidget(view, 1)
        self.view = view
        if self._interactive:
            self._install_bridge(view)
        return view

    def set_interactive(self, interactive: bool) -> None:
        """Let this view's page write back (see flograph.core.bridge).

        Called by the host from the node's spec. Applied to a view that
        already exists as well as to the next one built, so toggling it —
        editing a node's code to add NODE['interactive'] — takes effect
        without rebuilding the card.
        """
        interactive = bool(interactive)
        if interactive == self._interactive:
            return
        self._interactive = interactive
        if interactive and self.view is not None:
            self._install_bridge(self.view)

    def _install_bridge(self, view) -> None:
        from flograph.ui.web_bridge import BridgeReceiver, install
        if self._receiver is None:
            self._receiver = BridgeReceiver(self)
            self._receiver.param_written.connect(self.param_written)
        install(view, self._receiver)

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
                # Drop the renderer, not just the page. A renderer's heap
                # stays at its peak even after navigating it away, so the
                # only way to give back the memory a big chart took is to
                # destroy the view; _ensure_view rebuilds it lazily when the
                # next content arrives.
                self._drop_view()
            self._path = None
            self.placeholder.setText(RUN_PROMPT)
            self.placeholder.show()
            return
        view = self._ensure_view()
        if view is None:
            self.placeholder.setText(NO_WEBENGINE)
            self.placeholder.show()
            return
        path = _plotly_html_path(self._token)
        path.write_text(html, encoding="utf-8")
        self._path = path
        # new content gets its own retry: one bad chart having killed the
        # renderer must not spend the next one's second chance
        self._retried = False
        view.load(QUrl.fromLocalFile(str(path)))
        self.placeholder.hide()
        view.show()

    def _drop_view(self) -> None:
        """Take the webview out and let it go."""
        view = self.view
        self.view = None
        if view is None:
            return
        self._layout.removeWidget(view)
        view.hide()
        view.deleteLater()

    def _fail(self, message: str) -> None:
        """Put a reason where the page should have been."""
        if self.view is not None:
            self.view.hide()
        self.placeholder.setText(message)
        self.placeholder.show()

    def _on_load_finished(self, ok: bool) -> None:
        if not ok:
            self._fail(LOAD_FAILED)
            return
        self.placeholder.hide()
        if self.view is not None:
            self.view.show()

    def _reload(self) -> None:
        """Build a fresh view and put the same file back in front of it."""
        self._drop_view()
        view = self._ensure_view()
        if view is None:
            return
        view.load(QUrl.fromLocalFile(str(self._path)))
        self.placeholder.hide()
        view.show()

    def _on_renderer_gone(self, status, code) -> None:
        """Chromium killed the page's process.

        The widget survives it; the page does not, so what is left is a
        blank rectangle that will never paint again. Rebuild it and reload
        the same file **once** — a renderer lost to a momentary squeeze
        comes back, and that is the common case. A second death on the same
        content is reported rather than retried, or a page that kills the
        renderer every time would loop forever.
        """
        why = termination_reason(status, code)
        if self._retried or self._path is None:
            self._fail(RENDERER_GONE.format(why=why))
            return
        self._retried = True
        self._reload()

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
