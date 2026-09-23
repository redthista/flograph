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
from collections import deque
from contextlib import contextmanager

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
# Keys whose draw failed or timed out. Not queued again, so a figure the page
# cannot draw falls back the way it always has instead of looping forever
# between a placeholder and another attempt.
_FAILED: "set[tuple]" = set()

# What `snapshot` answers, inside `deferred()`, for a picture that is being
# drawn in the background: the caller puts a placeholder where it goes.
PENDING = object()

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
        # Background drawing (see `deferred`): one figure at a time, queued.
        self._queue: deque = deque()     # (key, spec json, w, h, scale)
        self._waiting: dict = {}         # key -> [callback(key)]
        self._job = None                 # key being drawn in the background
        self._loading = False            # page being loaded without blocking
        self._deadline = None

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
            from ..webprofile import new_view

            view = new_view()
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
        self._release_on_quit(view)
        return view

    # ------------------------------------------------ background drawing

    def request(self, key, spec: str, width: int, height: int,
                scale: float, done) -> None:
        """Draw this figure without blocking; `done(key)` when it has been
        (or could not be). A key already queued just gains a listener."""
        if key in self._waiting:
            self._waiting[key].append(done)
            return
        self._waiting[key] = [done]
        self._queue.append((key, spec, width, height, scale))
        self._pump()

    def _pump(self) -> None:
        if self._job is not None or self._busy or not self._queue:
            return
        if self._broken:
            while self._queue:
                self._finish(self._queue.popleft()[0], None)
            return
        if self._view is None:
            self._load_async()
            return
        key, spec, width, height, scale = self._queue.popleft()
        self._job = key
        payload = json.dumps(spec)
        self._view.page().runJavaScript(
            f"window.__snapStart(JSON.parse({payload}),"
            f" {int(width)}, {int(height)}, {float(scale)})")
        self._arm_deadline(DRAW_TIMEOUT_MS, lambda: self._job_done(None))
        QTimer.singleShot(POLL_MS, self._poll_job)

    def _arm_deadline(self, ms: int, expire) -> None:
        timer = QTimer()
        timer.setSingleShot(True)
        timer.timeout.connect(expire)
        timer.start(ms)
        self._deadline = timer

    def _poll_job(self) -> None:
        if self._job is None or self._view is None:
            return
        self._view.page().runJavaScript("window.__snap", self._job_answer)

    def _job_answer(self, value) -> None:
        if self._job is None:
            return
        if not value:
            QTimer.singleShot(POLL_MS, self._poll_job)
            return
        self._job_done(value)

    def _job_done(self, url) -> None:
        key, self._job = self._job, None
        if self._deadline is not None:
            self._deadline.stop()
            self._deadline = None
        if key is None:
            return
        data = None
        if isinstance(url, str) and url.startswith(_DATA_URL):
            try:
                data = base64.b64decode(url[len(_DATA_URL):])
            except Exception:
                data = None
        self._finish(key, data)
        self._pump()

    def _finish(self, key, data) -> None:
        if data:
            _remember(key, data)
        else:
            _FAILED.add(key)
        for done in self._waiting.pop(key, []):
            try:
                done(key)
            except Exception:
                pass

    def _release_on_quit(self, view) -> None:
        """Delete the hidden page before the web profile goes at quit —
        a page outliving its profile is Qt WebEngine's "Release of profile
        requested but WebEnginePage still not deleted", and can take the
        process down on the way out."""
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance()
        if app is None:
            return

        def release():
            self._loading = False
            self._job = None
            self._queue.clear()
            self._view = None
            self._pending_view = None
            try:
                view.setPage(None)
            except Exception:
                pass
            view.deleteLater()

        app.aboutToQuit.connect(release)

    def _load_async(self) -> None:
        """Build the hidden page the way `_ready_view` does, but by timers:
        parsing plotly.js takes seconds the first time, and nobody should
        wait for it with their input shut off."""
        if self._loading:
            return
        try:
            from PySide6.QtWidgets import QApplication
            if QApplication.instance() is None:
                return
            from ..webprofile import new_view
            view = new_view()
            view.resize(1200, 800)
            view.load(self._shell_url())
        except Exception:
            self._broken = True
            self._pump()
            return
        self._loading = True

        def ready_answer(value):
            if not self._loading:
                return
            if value:
                self._loading = False
                self._deadline.stop()
                self._view = view
                self._pump()
            else:
                QTimer.singleShot(POLL_MS, poll)

        def poll():
            if self._loading:
                view.page().runJavaScript("window.__snapReady === true",
                                          ready_answer)

        def give_up():
            if self._loading:
                self._loading = False
                self._broken = True
                self._pump()

        self._pending_view = view      # kept alive while it loads
        self._release_on_quit(view)
        self._arm_deadline(LOAD_TIMEOUT_MS, give_up)
        QTimer.singleShot(POLL_MS, poll)

    def png(self, figure, width: int, height: int,
            scale: float = 1.0) -> "bytes | None":
        if self._busy:
            return None          # already inside a snapshot; do not nest
        if self._job is not None or self._loading:
            # A background draw owns the page. An export asking now waits
            # for it — bounded, like every other wait here — rather than
            # being told there is no picture.
            loop = QEventLoop()
            waited = QTimer()
            waited.timeout.connect(
                lambda: (self._job is None and not self._loading)
                and loop.quit())
            waited.start(POLL_MS)
            QTimer.singleShot(DRAW_TIMEOUT_MS + LOAD_TIMEOUT_MS, loop.quit)
            loop.exec(QEventLoop.ExcludeUserInputEvents)
            waited.stop()
            if self._job is not None or self._loading:
                return None
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
    if _batch is not None:
        if key in _FAILED:
            return None          # the caller's fallback, as before
        _batch.add(key)
        _SNAPSHOTTER.request(key, spec, width, height, scale, _batch.done)
        return PENDING
    data = _SNAPSHOTTER.png(figure, width, height, scale)
    if data:
        _remember(key, data)
    return data


def _remember(key, data: bytes) -> None:
    if len(_CACHE) >= CACHE_LIMIT and key not in _CACHE:
        # plain FIFO: a report renders its charts in a stable order, so
        # the oldest entry is the one least likely to be wanted again
        del _CACHE[next(iter(_CACHE))]
    _CACHE[key] = data
    _FAILED.discard(key)


class _Batch:
    """The pictures one render asked for in the background, and what to
    call once the last of them is in."""

    def __init__(self, on_ready) -> None:
        self.on_ready = on_ready
        self.keys: set = set()
        self.closed = False
        # a placeholder went out: the render must be redone even if every
        # draw has already finished (or failed) by the time it ends
        self.asked = False

    def add(self, key) -> None:
        self.keys.add(key)
        self.asked = True

    def done(self, key) -> None:
        self.keys.discard(key)
        self._maybe_ready()

    def close(self) -> None:
        self.closed = True
        self._maybe_ready()

    def _maybe_ready(self) -> None:
        if self.closed and not self.keys and self.on_ready is not None:
            ready, self.on_ready = self.on_ready, None
            # never from inside the render that asked: the caller is still
            # building its document when a cached-by-now picture reports in
            QTimer.singleShot(0, ready)


_batch: "_Batch | None" = None


@contextmanager
def deferred(on_ready):
    """Renders inside this don't wait for Chromium.

    A picture already taken is returned as always; one that isn't comes
    back as `PENDING` and is drawn in the background, and `on_ready()` is
    called — once, after the render — when the last of them is in (or has
    failed), so the caller can render again and find them all cached, or
    fall back. A render that needed nothing new never calls it.

    For what is on screen (a report card, the preview). An export wants
    every picture before it writes the file and stays synchronous.
    """
    global _batch
    previous, _batch = _batch, _Batch(on_ready)
    batch = _batch
    try:
        yield
    finally:
        _batch = previous
        if batch.asked:
            batch.close()
        else:
            batch.on_ready = None      # nothing to wait for


def clear_cache() -> None:
    _CACHE.clear()
    _FAILED.clear()
