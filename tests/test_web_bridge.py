"""The web-view bridge: a page writing its own node's params from JavaScript.

Three layers, tested where each one actually decides something:

* `flograph.core.bridge` — what a page is allowed to write, and what the
  value becomes. Qt-free, so it is tested directly.
* `NODE["interactive"]` — the declaration that turns the channel on.
* The host (canvas card / dashboard tile) — vetting, the undo command, and
  the re-run, driven by emitting the receiver's signal.

Deliberately no QWebEngineView here. The JavaScript half was verified live
(a page calling `flograph.select([...])` before the channel handshake
completes arrives in Python, in order, once the queue flushes), but a real
Chromium in this suite is the one thing known to leave zombie renderers and
hang an xdist worker — see the teardown history in the project notes. The
seam that belongs to Python is `BridgeReceiver.param_written`, and that is
the gesture these tests send.
"""
from __future__ import annotations

import pytest

from flograph.core import NodeInstance, NodeRegistry
from flograph.core import bridge
from flograph.core.params import ParamSpec
from flograph.core.script import NodeScriptError, parse_spec


@pytest.fixture(scope="module")
def registry():
    reg = NodeRegistry()
    reg.load_builtins()
    return reg


@pytest.fixture
def scene(qtbot, registry):
    from PySide6.QtGui import QUndoStack
    from flograph.core import Graph
    from flograph.ui.canvas import NodeGraphScene
    graph = Graph()
    return graph, NodeGraphScene(graph, QUndoStack(), registry=registry)


SOURCE = '''NODE = {{
    "label": "Clicky",
    "category": "Viz",
    "card": "{card}",
    {interactive}
    "inputs": [],
    "outputs": [("view", "object")],
}}
PARAMS = [
    {{"name": "selected", "type": "string", "default": ""}},
    {{"name": "depth", "type": "int", "default": 1, "min": 0, "max": 10}},
    {{"name": "ratio", "type": "float", "default": 0.5}},
    {{"name": "shown", "type": "bool", "default": False}},
    {{"name": "mode", "type": "choice", "options": ["a", "b"], "default": "a"}},
    {{"name": "width", "type": "int", "default": 400, "cosmetic": True}},
]


def run(ctx):
    return "<p>hi</p>"
'''


def spec_for(card="webview", interactive=True, type_id="test.clicky"):
    return parse_spec(
        SOURCE.format(
            card=card,
            interactive='"interactive": True,' if interactive else ""),
        type_id)


@pytest.fixture(scope="module")
def spec():
    return spec_for()


# ------------------------------------------------------ NODE["interactive"]

class TestDeclaration:
    def test_declared_interactive_is_parsed(self, spec):
        assert spec.interactive is True

    def test_absent_defaults_to_false(self):
        assert spec_for(interactive=False).interactive is False

    def test_non_bool_is_rejected(self):
        source = SOURCE.format(card="webview",
                               interactive='"interactive": "yes",')
        with pytest.raises(NodeScriptError, match="must be True or False"):
            parse_spec(source, "test.bad")

    def test_only_a_webview_may_be_interactive(self):
        """There is no page to put a channel in on any other card kind, so
        this is caught at parse time rather than silently doing nothing."""
        with pytest.raises(NodeScriptError, match="'webview'"):
            spec_for(card="kpi")

    def test_is_interactive_needs_both(self, spec):
        assert bridge.is_interactive(spec)
        assert not bridge.is_interactive(spec_for(interactive=False))

    def test_show_web_declares_it(self, registry):
        """The template node people fork to build their own visual is the
        one that has to arrive interactive."""
        built_in = registry.get("flograph.viz.show_web")
        assert bridge.is_interactive(built_in)
        assert built_in.param("selected") is not None


# ------------------------------------------------------------ what's allowed

class TestAccept:
    def test_writes_a_declared_param(self, spec):
        assert bridge.accept(spec, "selected", '"north"') == ("selected",
                                                              "north")

    def test_select_lands_as_the_slicer_format(self, spec):
        """flograph.select(["a","b"]) has to arrive in exactly the form
        core.controls.selected_values reads, so a chart that filters and a
        Slicer that filters look identical from inside run()."""
        from flograph.core.controls import selected_values
        _, value = bridge.accept(spec, "selected", '["north", "south"]')
        assert selected_values(value) == ["north", "south"]

    def test_undeclared_param_is_refused(self, spec):
        with pytest.raises(bridge.BridgeError, match="no parameter 'nope'"):
            bridge.accept(spec, "nope", '"x"')

    def test_refusal_names_what_is_declared(self, spec):
        """The message is the only debugging aid JavaScript in a card gets."""
        with pytest.raises(bridge.BridgeError, match="depth"):
            bridge.accept(spec, "nope", '"x"')

    def test_a_non_interactive_node_refuses_everything(self):
        quiet = spec_for(interactive=False)
        with pytest.raises(bridge.BridgeError, match="interactive"):
            bridge.accept(quiet, "selected", '"north"')

    def test_malformed_json_is_refused(self, spec):
        with pytest.raises(bridge.BridgeError, match="isn't JSON"):
            bridge.accept(spec, "selected", "{not json")


class TestCoercion:
    def test_int(self, spec):
        assert bridge.accept(spec, "depth", "3") == ("depth", 3)

    def test_int_from_a_string(self, spec):
        """JSON from a page is whatever the page felt like sending."""
        assert bridge.accept(spec, "depth", '"3"') == ("depth", 3)

    def test_int_rounds_rather_than_truncates(self, spec):
        assert bridge.accept(spec, "depth", "2.6") == ("depth", 3)

    def test_int_is_clamped_to_declared_bounds(self, spec):
        assert bridge.accept(spec, "depth", "99") == ("depth", 10)
        assert bridge.accept(spec, "depth", "-99") == ("depth", 0)

    def test_float_keeps_precision(self, spec):
        assert bridge.accept(spec, "ratio", "0.25") == ("ratio", 0.25)

    def test_bool(self, spec):
        assert bridge.accept(spec, "shown", "true") == ("shown", True)

    def test_choice_must_be_an_offered_option(self, spec):
        assert bridge.accept(spec, "mode", '"b"') == ("mode", "b")
        with pytest.raises(bridge.BridgeError, match="no option"):
            bridge.accept(spec, "mode", '"z"')

    def test_a_number_param_refuses_a_list(self, spec):
        with pytest.raises(bridge.BridgeError, match="is a number"):
            bridge.accept(spec, "depth", "[1, 2]")

    def test_a_number_param_refuses_nan(self, spec):
        with pytest.raises(bridge.BridgeError):
            bridge.accept(spec, "ratio", '"nan"')

    def test_a_structure_becomes_json_not_a_python_repr(self, spec):
        """`str(["a"])` would give "['a']" — single quotes, unreadable by
        json.loads, and not what a hand-edited param looks like."""
        _, value = bridge.accept(spec, "selected", '["a"]')
        assert value == '["a"]'

    def test_selection_json_matches_what_select_sends(self):
        assert bridge.selection_json(["a", "b"]) == '["a", "b"]'
        assert bridge.selection_json([]) == ""


class TestRerun:
    def test_a_real_param_re_runs(self, spec):
        assert bridge.wants_rerun(spec, "selected")

    def test_a_cosmetic_param_does_not(self, spec):
        """Committing a card's width must not cost a run of the flow."""
        assert not bridge.wants_rerun(spec, "width")


class TestShim:
    def test_installs_the_documented_global(self):
        assert f"window.{bridge.GLOBAL} = api" in bridge.SHIM_JS

    def test_offers_the_documented_api(self):
        for member in ("set:", "select:", "ready:", "connected:"):
            assert member in bridge.SHIM_JS

    def test_select_writes_the_slicer_param_name(self):
        assert f'api.set("{bridge.SELECT_PARAM}"' in bridge.SHIM_JS

    def test_goes_quiet_with_no_host(self):
        """A page in a real browser or an exported file has no transport;
        it must stop queueing writes it can never deliver."""
        assert "api.__closed = true" in bridge.SHIM_JS

    def test_shim_tag_wraps_the_source(self):
        assert bridge.shim_tag().startswith("<script>")
        assert bridge.SHIM_JS in bridge.shim_tag()

    def test_qwebchannel_js_runs_before_the_shim(self):
        """Order matters: the shim looks for the QWebChannel that Qt's own
        script defines."""
        assert bridge.script_sources("QT") == ["QT", bridge.SHIM_JS]

    def test_a_build_without_qwebchannel_still_gets_the_shim(self):
        assert bridge.script_sources(None) == [bridge.SHIM_JS]


# --------------------------------------------------------- the Qt half

class TestQtPlumbing:
    def test_qwebchannel_js_is_found_in_qt_itself(self):
        """The reason an interactive visual works offline: the transport
        script comes out of Qt's resources, not a CDN."""
        from flograph.ui import web_bridge
        source = web_bridge.qwebchannel_js()
        assert source and "QWebChannel" in source

    def test_receiver_forwards_verbatim(self, qtbot):
        """The receiver vets nothing — the host owns the node, so the host
        decides. This just has to arrive unchanged."""
        from flograph.ui.web_bridge import BridgeReceiver
        receiver = BridgeReceiver()
        seen = []
        receiver.param_written.connect(lambda n, p: seen.append((n, p)))
        receiver.set("selected", '["a"]')
        assert seen == [("selected", '["a"]')]


# ------------------------------------------------- host: commit and re-run

class TestApplyWrite:
    """The gesture: a page wrote a param. Sent at the seam the receiver
    emits from, so no browser is involved."""

    def _node(self, graph, interactive=True):
        return graph.add_node(NodeInstance.create(spec_for(
            interactive=interactive, type_id="test.clicky")))

    def _write(self, scene_pair, node, name, payload):
        from flograph.ui.web_bridge import apply_write
        graph, sc = scene_pair
        return apply_write(sc, graph, node, name, payload)

    def test_commits_the_param(self, scene):
        graph, sc = scene
        node = self._node(graph)
        assert self._write(scene, node, "selected", '["north"]')
        assert node.params["selected"] == '["north"]'

    def test_asks_for_a_re_run(self, scene, qtbot):
        graph, sc = scene
        node = self._node(graph)
        with qtbot.waitSignal(sc.view_changed, timeout=500) as caught:
            self._write(scene, node, "selected", '["north"]')
        assert caught.args == [node.id]

    def test_one_ctrl_z_undoes_one_click(self, scene):
        graph, sc = scene
        node = self._node(graph)
        self._write(scene, node, "selected", '["north"]')
        self._write(scene, node, "selected", '["south"]')
        sc.undo_stack.undo()
        assert node.params["selected"] == '["north"]'
        sc.undo_stack.undo()
        assert node.params["selected"] == ""
        sc.undo_stack.clear()

    def test_an_unchanged_value_does_not_re_run(self, scene):
        """The loop guard. A visual that calls select() while restoring its
        own state on load would otherwise re-run the flow forever."""
        graph, sc = scene
        node = self._node(graph)
        self._write(scene, node, "selected", '["north"]')
        runs = []
        sc.view_changed.connect(runs.append)
        assert not self._write(scene, node, "selected", '["north"]')
        assert runs == []
        sc.undo_stack.clear()

    def test_a_cosmetic_param_commits_without_a_re_run(self, scene):
        graph, sc = scene
        node = self._node(graph)
        runs = []
        sc.view_changed.connect(runs.append)
        assert self._write(scene, node, "width", "500")
        assert node.params["width"] == 500
        assert runs == []
        sc.undo_stack.clear()

    def test_a_refused_write_reports_and_changes_nothing(self, scene, qtbot):
        graph, sc = scene
        node = self._node(graph)
        before = dict(node.params)
        with qtbot.waitSignal(sc.view_error, timeout=500) as caught:
            assert not self._write(scene, node, "nope", '"x"')
        assert caught.args[0] == node.id
        assert "nope" in caught.args[1]
        assert node.params == before

    def test_a_non_interactive_node_is_refused(self, scene, qtbot):
        """Belt and braces: the view is never given a channel, but the host
        must refuse too — a saved project can pair old params with new code."""
        graph, sc = scene
        node = self._node(graph, interactive=False)
        with qtbot.waitSignal(sc.view_error, timeout=500):
            assert not self._write(scene, node, "selected", '["north"]')
        assert node.params["selected"] == ""


class TestCardWiring:
    def test_an_interactive_node_gets_a_live_view(self, scene, registry):
        graph, sc = scene
        node = graph.add_node(registry.instantiate("flograph.viz.show_web"))
        widget = sc.node_items[node.id]._plotly_widget
        assert widget is not None and widget._interactive

    def test_an_ordinary_webview_node_does_not(self, scene, registry):
        """A channel per web view is not free, and a plain chart has
        nothing to say."""
        graph, sc = scene
        node = graph.add_node(registry.instantiate("flograph.viz.mermaid"))
        widget = sc.node_items[node.id]._plotly_widget
        assert widget is not None and not widget._interactive

    def test_a_card_write_reaches_the_graph(self, scene, registry, qtbot):
        """End to end on the Python side: the view's signal is what the
        card listens to, so emitting it proves the card is wired, not just
        that apply_write works."""
        graph, sc = scene
        node = graph.add_node(registry.instantiate("flograph.viz.show_web"))
        widget = sc.node_items[node.id]._plotly_widget
        with qtbot.waitSignal(sc.view_changed, timeout=500):
            widget.param_written.emit("selected", '["north"]')
        assert node.params["selected"] == '["north"]'
        sc.undo_stack.clear()
