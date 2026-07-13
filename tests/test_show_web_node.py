"""The Show Web View template node, the NODE['card'] marker, and the
library-agnostic HTML coercion behind the webview card.

The regression at the centre of this file: a rich node saved as a user node
(fresh `user.<slug>` type_id) must keep its card, because the card is now
declared in the node source rather than inferred from the type_id."""
from __future__ import annotations

import pytest

from flograph.core import NodeInstance, NodeRegistry, PortType, compile_run
from flograph.core import user_nodes
from flograph.core.node import NodeSpec
from flograph.core.script import NodeScriptError, parse_spec
from tests.conftest import FakeContext


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


# --------------------------------------------------------------- NODE["card"]

MINIMAL = '''NODE = {{
    "label": "X",
    "category": "Viz",
    {card}
    "inputs": [],
    "outputs": [("view", "object")],
}}


def run(ctx):
    return "<p>hi</p>"
'''


class TestCardMarker:
    def test_valid_card_is_parsed(self):
        spec = parse_spec(MINIMAL.format(card='"card": "webview",'), "t.a")
        assert spec.card == "webview"

    def test_absent_card_is_none(self):
        spec = parse_spec(MINIMAL.format(card=""), "t.b")
        assert spec.card is None

    def test_unknown_card_rejected(self):
        with pytest.raises(NodeScriptError):
            parse_spec(MINIMAL.format(card='"card": "bogus",'), "t.c")


# ------------------------------------------------------------- HTML coercion

class TestToHtml:
    def test_raw_string_wrapped_into_document(self):
        from flograph.ui.inspector.plotly_view import to_html
        out = to_html("<p>hello</p>")
        assert "<html" in out.lower() and "<p>hello</p>" in out

    def test_full_document_passed_through(self):
        from flograph.ui.inspector.plotly_view import to_html
        page = "<!doctype html><html><body>x</body></html>"
        assert to_html(page) == page

    def test_to_html_object(self):
        from flograph.ui.inspector.plotly_view import to_html

        class Fig:
            def to_html(self, **kwargs):
                return "<html><body>fig</body></html>"

        assert "fig" in to_html(Fig())

    def test_plain_to_html_without_kwargs(self):
        from flograph.ui.inspector.plotly_view import to_html

        class Legacy:
            def to_html(self):  # rejects plotly's kwargs
                return "<div>legacy</div>"

        out = to_html(Legacy())
        assert "legacy" in out and "<html" in out.lower()

    def test_repr_html_protocol(self):
        from flograph.ui.inspector.plotly_view import to_html

        class Map:
            def _repr_html_(self):
                return "<iframe>map</iframe>"

        out = to_html(Map())
        assert "map" in out and "<html" in out.lower()

    def test_unsupported_returns_none(self):
        from flograph.ui.inspector.plotly_view import to_html
        assert to_html(object()) is None
        assert to_html(None) is None


# ----------------------------------------------------------- Show Web node

class TestShowWebNode:
    def test_registered_as_webview_card(self, registry):
        spec = registry.get("flograph.viz.show_web")
        assert spec.card == "webview"
        assert spec.inputs[0].optional
        assert spec.outputs[0].type == PortType.OBJECT
        assert spec.outputs[0].name == "view"

    def test_run_returns_html_with_title(self, registry):
        spec = registry.get("flograph.viz.show_web")
        params = spec.default_params()
        params["title"] = "My View"
        run = compile_run(spec.source, "test-web")
        html = run(FakeContext(params=params))
        assert isinstance(html, str) and "My View" in html

    def test_run_reports_input_type(self, registry):
        spec = registry.get("flograph.viz.show_web")
        run = compile_run(spec.source, "test-web")
        html = run(FakeContext(params=spec.default_params()), data=[1, 2, 3])
        assert "list" in html


# -------------------------------------------------- regression: saved cards

class TestSavedUserNodeKeepsCard:
    """Saving a rich node as a user node changes its type_id to user.*, but
    the card marker travels in the source, so card_kind still resolves it."""

    @pytest.mark.parametrize("type_id,kind", [
        ("flograph.viz.show_web", "webview"),
        ("flograph.viz.show_plotly", "webview"),
        ("flograph.viz.show_plot", "figure"),
        ("flograph.viz.show_table", "table_viewer"),
        ("flograph.viz.card", "kpi"),
    ])
    def test_card_survives_save_as_user_node(self, registry, tmp_path,
                                             type_id, kind):
        from flograph.ui.canvas.node_item import card_kind
        source = registry.get(type_id).source
        user_type_id = user_nodes.write_user_node(
            tmp_path, group=None, name="My Saved", source=source)
        assert user_type_id.startswith("user.")

        written = next(tmp_path.glob("*.py"))
        saved = parse_spec(written.read_text(), user_type_id)
        assert saved.card == kind
        # card_kind resolves off the marker even though the type_id changed
        node = NodeInstance.create(saved)
        assert node.type_id == user_type_id
        assert card_kind(node) == kind

    def test_show_web_builds_webview_card_on_canvas(self, scene, registry):
        graph, sc = scene
        node = graph.add_node(registry.instantiate("flograph.viz.show_web"))
        item = sc.node_items[node.id]
        assert item.plotly_card and item.figure_card
        assert item._plotly_widget is not None

    def test_saved_user_node_builds_webview_card_on_canvas(self, scene,
                                                           registry):
        """The bug fix, end to end: a webview node with a fresh user.* type_id
        still builds the embedded webview card on the canvas."""
        graph, sc = scene
        source = registry.get("flograph.viz.show_web").source
        spec = parse_spec(source, "user.my_saved")
        node = graph.add_node(NodeInstance.create(spec))
        item = sc.node_items[node.id]
        assert item.plotly_card
        assert item._plotly_widget is not None

    def test_legacy_fallback_without_marker(self):
        """Old forks/projects: a built-in type_id but no card field still
        resolves via the legacy map."""
        from flograph.ui.canvas.node_item import card_kind
        spec = NodeSpec(
            type_id="flograph.viz.show_plotly", label="L", category="Viz",
            inputs=[], outputs=[], params=[], source="", card=None)
        node = NodeInstance.create(spec)
        assert card_kind(node) == "webview"
