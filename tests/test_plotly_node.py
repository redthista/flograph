"""The Show Plotly card: interactive plotly chart in an embedded webview."""
import pandas as pd
import pytest
from PySide6.QtGui import QUndoStack

from flopy.core import Graph, NodeRegistry, PortType, compile_run
from flopy.ui.canvas import NodeGraphScene
from tests.conftest import FakeContext


@pytest.fixture(scope="module")
def registry():
    reg = NodeRegistry()
    reg.load_builtins()
    return reg


@pytest.fixture
def env(qtbot, registry):
    graph = Graph()
    stack = QUndoStack()
    scene = NodeGraphScene(graph, stack, registry=registry)
    return graph, stack, scene


@pytest.fixture
def table():
    return pd.DataFrame({"region": ["n", "s", "n", "s"],
                         "units": [10, 20, 30, 40],
                         "revenue": [100.0, 150.0, 300.0, 320.0]})


def run_node(registry, params=None, **inputs):
    spec = registry.get("flopy.viz.show_plotly")
    defaults = spec.default_params()
    defaults.update(params or {})
    run = compile_run(spec.source, "test-plotly")
    return run(FakeContext(params=defaults), **inputs)


def test_registered_with_dataframe_in_object_out(registry):
    spec = registry.get("flopy.viz.show_plotly")
    assert spec.inputs[0].type == PortType.DATAFRAME
    assert spec.outputs[0].type == PortType.OBJECT
    for name in ("kind", "x", "y", "color", "title", "width", "height"):
        assert spec.param(name) is not None
    assert not spec.param("x").multi and spec.param("y").multi


class TestRun:
    def test_line_defaults_plot_all_numeric(self, registry, table):
        pytest.importorskip("plotly")
        fig = run_node(registry, {}, table=table)["figure"]
        assert len(fig.data) == 2  # units + revenue

    def test_explicit_columns_and_kind(self, registry, table):
        pytest.importorskip("plotly")
        fig = run_node(registry, {"kind": "scatter", "x": "units",
                                  "y": "revenue", "title": "T"},
                       table=table)["figure"]
        assert fig.layout.title.text == "T"
        assert len(fig.data) == 1

    def test_color_grouping(self, registry, table):
        pytest.importorskip("plotly")
        fig = run_node(registry, {"y": "revenue", "color": "region"},
                       table=table)["figure"]
        assert len(fig.data) == 2  # one trace per region

    def test_missing_column(self, registry, table):
        pytest.importorskip("plotly")
        with pytest.raises(ValueError, match="not in table"):
            run_node(registry, {"y": "nope"}, table=table)

    def test_no_numeric(self, registry):
        pytest.importorskip("plotly")
        with pytest.raises(ValueError, match="no numeric"):
            run_node(registry, {}, table=pd.DataFrame({"s": ["a"]}))


class TestCard:
    def _item(self, env, registry):
        graph, stack, scene = env
        node = graph.add_node(registry.instantiate("flopy.viz.show_plotly"))
        return scene.node_items[node.id]

    def test_is_a_resizable_card_with_placeholder(self, env, registry):
        item = self._item(env, registry)
        assert item.plotly_card and item.figure_card
        assert item._figure_placeholder.isVisible()
        assert item._plotly_view is None  # webview only built on first figure
        assert list(item.output_ports) == ["figure"]
        graph = env[0]
        graph.set_param(item.node.id, "width", 700)
        assert item.width == 700.0
        assert item.output_ports["figure"].pos().x() == 700.0

    def test_figure_loads_into_webview(self, env, registry, monkeypatch):
        item = self._item(env, registry)
        loaded, shown = [], []

        class StubView:
            def load(self, url):
                loaded.append(url.toLocalFile())

            def show(self):
                shown.append(True)

            def hide(self):
                pass

        monkeypatch.setattr(item, "_ensure_plotly_view", lambda: StubView())

        class StubFigure:
            def to_html(self, **kwargs):
                assert kwargs["full_html"] and kwargs["include_plotlyjs"]
                return "<html>chart</html>"

        item.set_plotly_figure(StubFigure())
        assert shown and loaded
        assert item._figure_placeholder.isHidden()
        with open(loaded[0], encoding="utf-8") as fh:
            assert fh.read() == "<html>chart</html>"

    def test_placeholder_explains_missing_webengine(self, env, registry,
                                                    monkeypatch):
        item = self._item(env, registry)
        monkeypatch.setattr(item, "_ensure_plotly_view", lambda: None)

        class StubFigure:
            def to_html(self, **kwargs):
                return "x"

        item.set_plotly_figure(StubFigure())
        assert item._figure_placeholder.isVisible()
        assert "WebEngine" in item._figure_placeholder.text()

    def test_none_resets_to_run_prompt(self, env, registry):
        item = self._item(env, registry)
        item.set_plotly_figure(None)
        assert item._figure_placeholder.isVisible()
        assert "Run the graph" in item._figure_placeholder.text()
