"""The Qt half of the web-view bridge — see flograph.core.bridge for the
contract and the JavaScript the page actually sees.

All this does is wire one QWebEngineView so that `flograph.set(name, value)`
inside its page arrives in Python as a signal. Three pieces have to line up:

* **qwebchannel.js**, read out of Qt's own resources rather than fetched
  from a CDN. It is the reason an interactive visual still works with no
  internet, which matters more here than anywhere else in the app: a page
  whose clicks stop working offline would be worse than one that never
  claimed to be interactive.
* **The injected scripts**, added to the page at *DocumentCreation* so the
  shim is installed before any chart's own script runs. A visual that binds
  a click handler in its first inline `<script>` cannot be asked to wait.
* **The channel**, whose receiver is registered under the same name the
  shim looks for (`core.bridge.GLOBAL`).

Kept out of PlotlyView so the widget stays about rendering, and so the
plumbing can be tested against a bare QWebEngineView.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QObject, Signal, Slot

from flograph.core import bridge as core_bridge

_channel_js: "str | None | bool" = False   # False = not looked for yet


def qwebchannel_js() -> Optional[str]:
    """Qt's qwebchannel.js, or None if this build doesn't carry it.

    Cached: it is ~16 KB of resource read that every interactive card would
    otherwise repeat.
    """
    global _channel_js
    if _channel_js is not False:
        return _channel_js            # type: ignore[return-value]
    _channel_js = None
    try:
        from PySide6.QtCore import QFile, QIODevice
        # Importing the module is what registers its Qt resources: without
        # this the :/qtwebchannel/ path simply does not exist yet and the
        # read comes back empty, with no error to say why.
        import PySide6.QtWebChannel  # noqa: F401
    except ImportError:
        return None
    source = QFile(":/qtwebchannel/qwebchannel.js")
    if source.open(QIODevice.ReadOnly):
        try:
            _channel_js = bytes(source.readAll().data()).decode("utf-8")
        finally:
            source.close()
    return _channel_js                # type: ignore[return-value]


class BridgeReceiver(QObject):
    """The object the page holds a reference to.

    Deliberately tiny and deliberately dumb: it does no validation, because
    what a node allows is a question about the *node*, and the widget that
    owns this receiver doesn't know which node it is showing. It emits, and
    the host (a canvas card, a dashboard tile) vets the write against the
    node's spec via core.bridge.accept.
    """

    #: (param name, JSON payload) exactly as the page sent them.
    param_written = Signal(str, str)

    @Slot(str, str)
    def set(self, name: str, payload: str) -> None:
        self.param_written.emit(str(name), str(payload))


def install(view, receiver: BridgeReceiver) -> bool:
    """Give `view`'s page a live channel and the injected scripts.

    Returns False when this build has no qwebchannel.js — the page still
    loads and still renders, it just reports `flograph.connected === false`,
    which is the same state a page has in a real browser.

    Safe to call more than once on one view: the scripts are named, and an
    existing one is replaced rather than stacked, so a re-install after the
    renderer is rebuilt doesn't leave two shims fighting.
    """
    from PySide6.QtWebEngineCore import QWebEngineScript
    from PySide6.QtWebChannel import QWebChannel

    channel_js = qwebchannel_js()
    sources = core_bridge.script_sources(channel_js)
    page = view.page()

    collection = page.scripts()
    for index, source in enumerate(sources):
        name = f"flograph-bridge-{index}"
        for existing in collection.find(name):
            collection.remove(existing)
        script = QWebEngineScript()
        script.setName(name)
        script.setSourceCode(source)
        # MainWorld: qt.webChannelTransport is only exposed there, and the
        # page's own scripts have to be able to see window.flograph.
        script.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
        script.setInjectionPoint(
            QWebEngineScript.InjectionPoint.DocumentCreation)
        script.setRunsOnSubFrames(False)
        collection.insert(script)

    channel = QWebChannel(page)
    channel.registerObject(core_bridge.GLOBAL, receiver)
    page.setWebChannel(channel)
    # Parented to the page so it dies with the renderer; kept on the view as
    # well because PlotlyView destroys and rebuilds the view to give back a
    # big chart's memory, and the receiver has to outlive that.
    view._flograph_channel = channel
    return channel_js is not None


def apply_write(scene, graph, node, name: str, payload: str) -> bool:
    """Vet one `flograph.set(...)` against `node` and commit it.

    The whole host-side contract, in one function because there are two
    hosts — a canvas card and a dashboard tile — and a click inside a chart
    must mean the same thing on a dashboard as it does on the canvas.
    Returns True if the graph changed.

    Errors go to `scene.view_error` rather than being swallowed: JavaScript
    inside a card has nowhere else to complain, and a write that silently
    does nothing is the worst thing to debug.
    """
    try:
        param, value = core_bridge.accept(node.spec, name, payload)
    except core_bridge.BridgeError as exc:
        scene.view_error.emit(node.id, str(exc))
        return False
    if value == node.params.get(param):
        # Nothing changed, so no command and — the part that matters — no
        # re-run. A visual that calls select() while restoring its own state
        # on load would otherwise re-run the flow forever.
        return False
    from flograph.ui.commands import SetParamCommand
    # merge=False: one Ctrl+Z undoes one click inside the chart, rather than
    # a session's worth of them collapsing into a single undo step.
    scene.undo_stack.push(
        SetParamCommand(graph, node.id, param, value, merge=False))
    if core_bridge.wants_rerun(node.spec, param):
        scene.view_changed.emit(node.id)
    return True
