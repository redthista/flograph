"""Plotly Table: a table drawn as a Plotly figure.

Its own node rather than a chart kind, because Plotly Express has no table
function — `go.Table` is a graph_objects trace with headers and columns
where every px chart has x and y.
"""
import pandas as pd
import pytest

from flograph.core import NodeRegistry, PortType, compile_run
from tests.conftest import FakeContext

pytest.importorskip("plotly")

TABLE = "flograph.viz.plotly_table"


@pytest.fixture(scope="module")
def registry():
    reg = NodeRegistry()
    reg.load_builtins()
    return reg


@pytest.fixture
def table():
    return pd.DataFrame({
        "region": ["north", "south", "east"],
        "units": [10, 20, 30],
        "revenue": [100.5, 200.25, 300.0],
    })


def run_node(registry, params=None, **inputs):
    spec = registry.get(TABLE)
    values = spec.default_params()
    values.update(params or {})
    ctx = FakeContext(params=values)
    return compile_run(spec.source, "test")(ctx, **inputs), ctx


def test_registered_as_a_webview_card(registry):
    spec = registry.get(TABLE)
    assert spec.label == "Plotly Table"
    assert spec.inputs[0].type == PortType.DATAFRAME
    assert spec.outputs[0].type == PortType.OBJECT
    assert spec.card == "webview"


def test_px_has_no_table_which_is_why_this_node_exists():
    import plotly.express as px
    assert not hasattr(px, "table")


class TestRun:
    def test_every_column_by_default(self, registry, table):
        out, _ = run_node(registry, {}, table=table)
        cells = out["figure"].data[0].cells
        assert len(cells.values) == 3
        assert list(cells.values[0]) == ["north", "south", "east"]

    def test_headers_are_the_column_names(self, registry, table):
        out, _ = run_node(registry, {}, table=table)
        assert list(out["figure"].data[0].header.values) == [
            "<b>region</b>", "<b>units</b>", "<b>revenue</b>"]

    def test_columns_pick_and_reorder(self, registry, table):
        out, _ = run_node(registry, {"columns": "revenue,region"},
                          table=table)
        assert list(out["figure"].data[0].header.values) == [
            "<b>revenue</b>", "<b>region</b>"]

    def test_a_column_that_is_not_there(self, registry, table):
        with pytest.raises(ValueError, match="columns not in table"):
            run_node(registry, {"columns": "nope"}, table=table)

    def test_max_rows_trims_and_says_so(self, registry):
        frame = pd.DataFrame({"n": range(50)})
        out, ctx = run_node(registry, {"max_rows": 10}, table=frame)
        assert len(out["figure"].data[0].cells.values[0]) == 10
        assert any("showing the first 10" in line for line in ctx.logs)

    def test_a_number_format_skips_the_text_columns(self, registry, table):
        """A d3 format is per column and means nothing to words."""
        out, _ = run_node(registry, {"number_format": ",.2f"}, table=table)
        assert list(out["figure"].data[0].cells.format) == ["", ",.2f",
                                                            ",.2f"]

    def test_no_format_by_default(self, registry, table):
        out, _ = run_node(registry, {}, table=table)
        assert out["figure"].data[0].cells.format is None

    def test_striped_rows_alternate(self, registry, table):
        """Written in as `fill_color`, read back as `cells.fill.color` —
        plotly accepts the flat alias on input only."""
        out, _ = run_node(registry, {"striped": True}, table=table)
        column = out["figure"].data[0].cells.fill.color[0]
        assert column[0] == column[2] and column[0] != column[1]

    def test_unstriped_leaves_the_theme_alone(self, registry, table):
        out, _ = run_node(registry, {"striped": False}, table=table)
        assert out["figure"].data[0].cells.fill.color is None

    def test_theme_title_and_fonts(self, registry, table):
        out, _ = run_node(registry, {"template": "plotly_dark",
                                     "title": "Sales", "font_size": 14},
                          table=table)
        layout = out["figure"].layout
        assert layout.title.text == "Sales"
        assert layout.font.size == 14
        assert layout.template.layout.paper_bgcolor

    def test_an_empty_table_says_so(self, registry):
        with pytest.raises(ValueError, match="no columns"):
            run_node(registry, {}, table=pd.DataFrame())

    def test_it_wires_into_plotly_style(self, registry):
        from flograph.core import Graph

        graph = Graph()
        source = graph.add_node(registry.instantiate(TABLE))
        style = graph.add_node(
            registry.instantiate("flograph.viz.plotly_style"))
        graph.connect(source.id, "figure", style.id, "figure")
        assert len(graph.connections) == 1
