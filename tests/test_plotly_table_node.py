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


class TestClickToFilter:
    """W2: the table filters what is downstream of it when a row is clicked,
    on the same terms as Show Plotly."""

    def test_it_is_interactive_with_the_click_outputs(self, registry):
        spec = registry.get(TABLE)
        assert spec.interactive
        assert [o.name for o in spec.outputs] == ["figure", "selected",
                                                  "table"]
        for name in ("on_click", "click_column", "selected"):
            assert spec.param(name) is not None

    def test_clicking_is_off_until_it_is_on(self, registry, table):
        out, _ = run_node(registry, {"selected": '["south"]'}, table=table)
        assert getattr(out["figure"], "_flograph_post_script", None) is None
        assert out["selected"] == [] and len(out["table"]) == 3

    def test_a_click_filters_on_the_first_column_by_default(self, registry,
                                                             table):
        out, _ = run_node(registry, {"on_click": "select one",
                                     "selected": '["south"]'}, table=table)
        assert out["selected"] == ["south"]
        assert list(out["table"]["region"]) == ["south"]

    def test_the_click_column_is_what_it_filters_on(self, registry, table):
        out, _ = run_node(registry, {"on_click": "select many",
                                     "click_column": "units",
                                     "selected": '["10", "30"]'}, table=table)
        assert list(out["table"]["region"]) == ["north", "east"]

    def test_it_filters_the_whole_input_not_just_the_rows_drawn(
            self, registry):
        big = pd.DataFrame({"k": ["a", "b"] * 10})
        out, _ = run_node(registry, {"on_click": "select one", "max_rows": 2,
                                     "selected": '["b"]'}, table=big)
        assert len(out["table"]) == 10

    def test_the_page_knows_the_value_of_every_row_drawn(self, registry,
                                                          table):
        out, _ = run_node(registry, {"on_click": "select many"}, table=table)
        script = out["figure"]._flograph_post_script
        assert '["north", "south", "east"]' in script
        assert "multi = true" in script
        assert ".column-cell" in script and '"header"' in script

    def test_a_value_cannot_close_the_script_it_rides_in(self, registry):
        odd = pd.DataFrame({"k": ["</script><b>"]})
        out, _ = run_node(registry, {"on_click": "select one"}, table=odd)
        assert "</script>" not in out["figure"]._flograph_post_script

    def test_the_clicked_rows_are_shaded(self, registry, table):
        out, _ = run_node(registry, {"on_click": "select one",
                                     "striped": False,
                                     "selected": '["east"]'}, table=table)
        fill = out["figure"].data[0].cells.fill.color
        assert fill[0][2] != fill[0][0] and fill[0][0] == fill[0][1]

    def test_a_click_column_that_is_not_there(self, registry, table):
        with pytest.raises(ValueError, match="Click column"):
            run_node(registry, {"on_click": "select one",
                                "click_column": "nope"}, table=table)
