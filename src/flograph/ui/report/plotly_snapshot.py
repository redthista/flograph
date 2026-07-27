"""Static pictures of Plotly figures, without kaleido.

Kaleido's whole job is to drive a headless Chromium that runs plotly.js and
asks it for a PNG. flograph already embeds that Chromium — it is what a
webview card draws in — so the dependency buys nothing the app cannot do
itself. This module asks plotly.js for the picture directly.

One hidden page is kept alive with plotly.js already parsed, and every
figure is drawn into that page and exported by `Plotly.toImage`. Parsing
the library is far and away the slowest part of the job — it is roughly
5 MB of JavaScript — so holding the page open is what makes a report of
forty charts practical instead of a minute of waiting.

The report renderer is an ordinary function called from a slot, so this has
to look synchronous, while the browser is anything but. A bounded nested
event loop bridges the two, and excludes user input so typing in the editor
cannot re-enter the renderer half way through a snapshot. Everything here
fails soft: no Qt WebEngine, no plotly, a page that will not load, a figure
that will not draw — all return None, and the caller falls back to kaleido
if it happens to be installed, or says so on the page. A report never
disappears because a picture could not be taken.
"""
from __future__ import annotations

import base64
import hashlib
import json

from PySide6.QtCore import QEventLoop, QTimer, QUrl

# Long enough for a slow first paint on a loaded machine, short enough that
# a wedged page cannot hang the app.
LOAD_TIMEOUT_MS = 20000
DRAW_TIMEOUT_MS = 20000
POLL_MS = 25

# Finished PNGs, keyed by figure content and size. The preview re-renders on
# a debounce whenever the body is edited, and pushing unchanged charts back
# through Chromium on every keystroke would make typing unusable.
CACHE_LIMIT = 48
_CACHE: "dict[tuple, bytes]" = {}

_DATA_URL = "data:image/png;base64,"

_SHELL = """<!doctype html>
<html><head><meta charset="utf-8">
<style>html,body{margin:0;padding:0;background:#fff}</style>
<script src="plotly.js"></script></head>
<body><div id="gd"></div><script>
// undefined = idle, null = drawing, string = a data URL or an "ERR:" note.
// The Python side polls this global because runJavaScript cannot wait on a
// promise — it serialises a pending one as an empty string.
window.__snap = undefined;
window.__snapStart = function (spec, w, h, s) {
  window.__snap = null;
  var gd = document.getElementById('gd');
  Plotly.newPlot(gd, spec.data || [], spec.layout || {},
                 {staticPlot: true, responsive: false})
    .then(function () {
      // width/height are the layout; scale is the density. Inflating the
      // width instead would shrink every label relative to the chart.
      return Plotly.toImage(gd, {format: 'png', width: w, height: h,
                                 scale: s});
    })
    .then(function (url) { window.__snap = url; },
          function (err) { window.__snap = 'ERR:' + err; });
};
window.__snapReady = true;
</script></body></html>
"""


def _await_js(view, expression: str, timeout_ms: int):
    """Poll `expression` until it answers with something truthy.

    Returns the value, or None on timeout. The page parks its result in a
    global and this watches for it, because a promise handed back through
    runJavaScript arrives as an empty string rather than its eventual value.
    """
    loop = QEventLoop()
    answer: dict = {}

    def got(value):
        if value:
            answer["value"] = value
            loop.quit()
        else:
            QTimer.singleShot(POLL_MS, poll)

    def poll():
        view.page().runJavaScript(expression, got)

    deadline = QTimer()
    deadline.setSingleShot(True)
    deadline.timeout.connect(loop.quit)
    deadline.start(timeout_ms)
    QTimer.singleShot(0, poll)
    # Excluding user input keeps a keystroke in the report editor from
    # kicking off a second render inside this one.
    loop.exec(QEventLoop.ExcludeUserInputEvents)
    deadline.stop()
    return answer.get("value")


class _Snapshotter:
    """The hidden page: built on first use, kept for the session."""

    def __init__(self) -> None:
        self._view = None
        self._tmp = None
        self._broken = False    # a structural failure — stop retrying
        self._busy = False      # re-entrancy guard for the nested loop

    def _shell_url(self):
        import tempfile
        from pathlib import Path
        from plotly.offline import get_plotlyjs

        if self._tmp is None:
            self._tmp = tempfile.TemporaryDirectory(
                prefix="flograph-snapshot-")
            root = Path(self._tmp.name)
            # plotly.js lives in its own file rather than inline: a <script>
            # body cannot safely carry arbitrary text, and a real file is
            # what lets Chromium parse the library once per page.
            (root / "plotly.js").write_text(get_plotlyjs(), encoding="utf-8")
            (root / "shell.html").write_text(_SHELL, encoding="utf-8")
        return QUrl.fromLocalFile(str(Path(self._tmp.name) / "shell.html"))

    def _ready_view(self):
        if self._broken:
            return None
        if self._view is not None:
            return self._view
        try:
            from PySide6.QtWidgets import QApplication
            if QApplication.instance() is None:
                return None      # no app yet; try again later, not broken
            from PySide6.QtWebEngineWidgets import QWebEngineView

            view = QWebEngineView()
            # A viewport big enough to lay out in; toImage takes its own
            # size, so this is not what decides the picture's dimensions.
            view.resize(1200, 800)
            view.load(self._shell_url())
            if not _await_js(view, "window.__snapReady === true",
                             LOAD_TIMEOUT_MS):
                raise RuntimeError("snapshot page never became ready")
        except Exception:
            self._broken = True
            return None
        self._view = view
        return view

    def png(self, figure, width: int, height: int,
            scale: float = 1.0) -> "bytes | None":
        if self._busy:
            return None          # already inside a snapshot; do not nest
        view = self._ready_view()
        if view is None:
            return None
        self._busy = True
        try:
            spec = figure.to_json()
            # Double-encoded on purpose: the JSON becomes a JavaScript
            # string literal that the page parses, so nothing in the figure
            # can be read as code on the way in.
            payload = json.dumps(spec)
            view.page().runJavaScript(
                f"window.__snapStart(JSON.parse({payload}),"
                f" {int(width)}, {int(height)}, {float(scale)})")
            url = _await_js(view, "window.__snap", DRAW_TIMEOUT_MS)
        except Exception:
            return None
        finally:
            self._busy = False
        if not isinstance(url, str) or not url.startswith(_DATA_URL):
            return None          # timed out, or the page reported "ERR:"
        try:
            return base64.b64decode(url[len(_DATA_URL):])
        except Exception:
            return None


_SNAPSHOTTER = _Snapshotter()


def snapshot(figure, width: int, height: int,
             scale: float = 1.0) -> "bytes | None":
    """PNG bytes for a Plotly figure, or None.

    `width`/`height` are the figure's own layout size and `scale` the
    pixel density, so the picture comes out width*scale across.

    None means "no picture available here" — no Qt WebEngine, no plotly, or
    a draw that failed — and is always the caller's cue to fall back, never
    an error to show.
    """
    try:
        spec = figure.to_json()
    except Exception:
        return None
    key = (hashlib.sha1(spec.encode("utf-8")).hexdigest(),
           int(width), int(height), float(scale))
    if key in _CACHE:
        return _CACHE[key]
    data = _SNAPSHOTTER.png(figure, width, height, scale)
    if data:
        if len(_CACHE) >= CACHE_LIMIT:
            # plain FIFO: a report renders its charts in a stable order, so
            # the oldest entry is the one least likely to be wanted again
            del _CACHE[next(iter(_CACHE))]
        _CACHE[key] = data
    return data


def clear_cache() -> None:
    _CACHE.clear()
