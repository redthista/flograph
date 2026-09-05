"""Letting a web view talk back.

Every visual on the canvas has been a one-way street: the graph computes
HTML, the card shows it, and whatever the user does inside that page —
clicking a bar, brushing a range, dragging a handle — dies in Chromium. The
only interactive cards (Slicer, the input controls) are bespoke *Qt*
widgets, so "interactive" has meant "someone wrote a widget for it".

This module is the other direction: a page can write one of its own node's
declared params, which dirties the node and re-runs everything downstream —
exactly what a Slicer tick already does. Click a bar, the board filters.

The rules, and why each one is a rule:

* **Opt in.** A node says `NODE["interactive"] = True`. A channel per web
  view is not free, and a plain chart has nothing to say.
* **Declared params only.** A page can write `selected` if the node declares
  `selected`, and nothing else. HTML arrives from libraries, templates and
  the user's own `run()`; the node's PARAMS list is the whole of what it is
  allowed to touch, which keeps a visual from reaching sideways into the
  graph.
* **Typed.** The value is coerced to the param's declared type, so an `int`
  param cannot end up holding the string `"7"` and a `choice` cannot end up
  holding an option that isn't in its list.
* **Undoable.** The host turns an accepted write into a SetParamCommand, so
  a click inside a chart is one Ctrl+Z like every other edit — commands stay
  the sole writers to the graph.

The shim degrades instead of breaking. The same HTML is shown on the card,
handed to a real browser by Open in Browser, and written to a file by an
export; only the first has a channel behind it. Everywhere else
`flograph.set()` is a no-op that reports `connected === false`, so one page
works in all three places rather than throwing a ReferenceError in two.
"""
from __future__ import annotations

import json
from typing import Any, Optional

#: Name the shim registers on `window`, and the name the channel registers
#: its receiver under. One constant because the two must agree.
GLOBAL = "flograph"

#: The param a `flograph.select(...)` shorthand writes. Named for the Slicer
#: param it deliberately mirrors: a chart that filters and a slicer that
#: filters should look the same from inside run().
SELECT_PARAM = "selected"


class BridgeError(ValueError):
    """A page asked for something the node does not allow."""


# --------------------------------------------------------------- the shim

# Injected into every interactive page at document creation, *before* the
# page's own scripts, so a chart's click handler can call it immediately
# without racing the channel's asynchronous handshake — calls made before
# the transport is up are queued and flushed on connect.
SHIM_JS = """
(function () {
  if (window.%(global)s && window.%(global)s.__flograph) { return; }
  var receiver = null, queued = [], waiting = [];

  function deliver(name, value) {
    receiver.set(String(name), JSON.stringify(value === undefined ? null : value));
  }

  var api = {
    __flograph: true,

    // False in a plain browser and in an exported file: the page still
    // renders, it just has nothing to write back to.
    connected: false,

    // Write one of this node's declared params. Anything JSON can carry.
    set: function (name, value) {
      if (receiver) { deliver(name, value); return true; }
      if (api.__closed) { return false; }
      queued.push([name, value]);
      return false;
    },

    // The common case, and the one that matches a Slicer: hand back the
    // values the user picked. A single value is wrapped, so both
    // select("north") and select(["north"]) mean the same thing.
    select: function (values) {
      if (values === null || values === undefined) { values = []; }
      if (!Array.isArray(values)) { values = [values]; }
      return api.set("%(select)s", values);
    },

    // Run fn once there is a live channel — never, in a plain browser.
    ready: function (fn) {
      if (receiver) { fn(api); } else { waiting.push(fn); }
    }
  };
  window.%(global)s = api;

  function connect(channel) {
    receiver = channel.objects.%(global)s;
    if (!receiver) { return; }
    api.connected = true;
    for (var i = 0; i < queued.length; i++) { deliver(queued[i][0], queued[i][1]); }
    queued = [];
    for (var j = 0; j < waiting.length; j++) { waiting[j](api); }
    waiting = [];
  }

  if (typeof qt !== "undefined" && qt.webChannelTransport
      && typeof QWebChannel !== "undefined") {
    new QWebChannel(qt.webChannelTransport, connect);
  } else {
    // No host: stop queueing writes that can never be delivered, so a page
    // left open in a browser doesn't grow a list of them forever.
    api.__closed = true;
  }
})();
""" % {"global": GLOBAL, "select": SELECT_PARAM}


def shim_tag() -> str:
    """The shim as a `<script>` tag, for HTML built outside the card.

    The card injects `SHIM_JS` through Qt instead (it has to run before the
    page's own scripts, which a tag in the body cannot promise).
    """
    return f"<script>{SHIM_JS}</script>"


# ----------------------------------------------------------- the contract

def is_interactive(spec) -> bool:
    """Whether this node's page is allowed to write back.

    A card kind that isn't a web view can declare `interactive` all it likes
    and still not get a channel: there is no page to put one in.
    """
    return bool(getattr(spec, "interactive", False)) and spec.card == "webview"


def coerce(param, value: Any) -> Any:
    """One JSON value from a page as a value of `param`'s declared type.

    Raises BridgeError rather than guessing when the value cannot be that
    type — a page writing nonsense should show up as a message, not as a
    param quietly holding something run() will trip over later.
    """
    kind = param.type
    if kind == "bool":
        return bool(value)

    if kind in ("int", "float"):
        if isinstance(value, bool) or not isinstance(value, (int, float, str)):
            raise BridgeError(
                f"{param.name!r} is a number, got {_describe(value)}")
        try:
            number = float(value)
        except ValueError:
            raise BridgeError(
                f"{param.name!r} is a number, got {value!r}") from None
        if number != number or number in (float("inf"), float("-inf")):
            raise BridgeError(f"{param.name!r} cannot be {number}")
        if param.minimum is not None:
            number = max(number, float(param.minimum))
        if param.maximum is not None:
            number = min(number, float(param.maximum))
        return int(round(number)) if kind == "int" else number

    if kind == "choice":
        text = _text(value)
        if param.options and text not in param.options:
            allowed = ", ".join(str(o) for o in param.options)
            raise BridgeError(
                f"{param.name!r} has no option {text!r} (has: {allowed})")
        return text

    # Everything else is stored as text. A list or dict is JSON-encoded
    # rather than str()-ed, so `select(["a", "b"])` lands in exactly the
    # form core.controls.selected_values already reads — the format a
    # hand-edited Slicer param uses too.
    return _text(value)


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value) if isinstance(value, float) else str(value)
    return json.dumps(value)


def _describe(value: Any) -> str:
    return "nothing" if value is None else f"{type(value).__name__} {value!r}"


def accept(spec, name: str, payload: str) -> tuple[str, Any]:
    """Vet one write from a page: `(param name, value to store)`.

    `payload` is the JSON text the shim sends. Raises BridgeError if the
    node is not interactive, if it declares no such param, if the param is
    one no page may write, or if the value isn't of the declared type.
    """
    if not is_interactive(spec):
        raise BridgeError("this node's view cannot write parameters "
                          "(it does not declare NODE['interactive'])")
    param = spec.param(name)
    if param is None:
        declared = ", ".join(p.name for p in spec.params) or "none"
        raise BridgeError(
            f"no parameter {name!r} on this node (declared: {declared})")
    try:
        value = json.loads(payload) if payload else None
    except ValueError:
        raise BridgeError(
            f"{name!r} was sent something that isn't JSON") from None
    return param.name, coerce(param, value)


def wants_rerun(spec, name: str) -> bool:
    """Whether a write to `name` should re-run the flow.

    A cosmetic param cannot change what run() produces, so committing one
    must not cost a run — the same bargain the properties panel strikes.
    """
    param = spec.param(name)
    return param is not None and not param.cosmetic


def selection_json(values) -> str:
    """The JSON a `selected` param holds, from a list of values.

    Here so the Python side of a test, a node, or a template writes the
    exact string the shim's `select()` would have sent.
    """
    return json.dumps([_text(v) for v in values]) if values else ""


def script_sources(qwebchannel_js: Optional[str]) -> list[str]:
    """The scripts an interactive page needs, in the order they must run.

    Qt's own qwebchannel.js first (it defines the QWebChannel the shim
    looks for), then the shim. Split out so the host only has to find the
    Qt resource, and so the order lives with the shim rather than in the
    widget that injects it.
    """
    return [js for js in (qwebchannel_js, SHIM_JS) if js]
