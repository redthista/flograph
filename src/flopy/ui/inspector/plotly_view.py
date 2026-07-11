"""PlotlyView: a plotly figure in an embedded QWebEngineView, shared by the
Show Plotly canvas card and dashboard tiles. The webview is created lazily on
the first figure — Chromium is heavy and the import can be missing on trimmed
PySide6 installs — and the page loads from a temp file, not setHtml: the
self-contained page embeds all of plotly.js (~3 MB) and setHtml caps content
at 2 MB."""
from __future__ import annotations

import uuid

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

RUN_PROMPT = "Run the graph to see an interactive chart here."
NO_WEBENGINE = ("Qt WebEngine is not available — install the full PySide6 "
                "package (Tools > Manage Packages) to display Plotly charts.")

_plotly_tmp = None  # TemporaryDirectory for the HTML, cleaned at exit


def _plotly_html_path(token: str):
    import tempfile
    from pathlib import Path
    global _plotly_tmp
    if _plotly_tmp is None:
        _plotly_tmp = tempfile.TemporaryDirectory(prefix="flopy-plotly-")
    return Path(_plotly_tmp.name) / f"{token}.html"


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
        except ImportError:
            return None
        view = QWebEngineView()
        view.hide()
        self._layout.addWidget(view, 1)
        self.view = view
        return view

    def set_figure(self, figure) -> None:
        """Render a freshly computed plotly figure (or None) into the
        embedded webview — call from the GUI thread only."""
        if figure is None or not hasattr(figure, "to_html"):
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
        path.write_text(figure.to_html(
            full_html=True, include_plotlyjs=True,
            default_width="100%", default_height="100%",
            config={"responsive": True}), encoding="utf-8")
        view.load(QUrl.fromLocalFile(str(path)))
        self.placeholder.hide()
        view.show()

    def set_zoom(self, factor: float) -> None:
        """Chromium zooms natively (and stays crisp) — callers drive this
        instead of scaling the widget through a graphics transform."""
        if self.view is not None:
            self.view.setZoomFactor(factor)
