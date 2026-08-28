"""Plotly Style: restyles a figure without touching what it plots."""
import pandas as pd
import pytest

from flograph.core import NodeRegistry, PortType, compile_run
from tests.conftest import FakeContext

pytest.importorskip("plotly")


@pytest.fixture(scope="module")
def registry():
    reg = NodeRegistry()
    reg.load_builtins()
    return reg


@pytest.fixture
def figure():
    import plotly.express as px
    return px.bar(pd.DataFrame({"region": ["n", "s"], "units": [10, 20]}),
                  x="region", y="units")


def style(registry, params=None, **inputs):
    spec = registry.get("flograph.viz.plotly_style")
    values = spec.default_params()
    values.update(params or {})
    run = compile_run(spec.source, "test-style")
    return run(FakeContext(params=values), **inputs)["figure"]


def test_registered_figure_in_figure_out(registry):
    spec = registry.get("flograph.viz.plotly_style")
    assert spec.label == "Plotly Style"
    assert spec.inputs[0].type == PortType.ANY
    assert spec.outputs[0].type == PortType.ANY
    assert spec.card == "webview"


class TestLeavesThingsAlone:
    def test_defaults_change_nothing(self, registry, figure):
        """Every setting has a "keep" position, so a Style node dropped in
        front of a figure somebody else built is inert until asked."""
        before = figure.to_dict()["layout"]
        after = style(registry, {}, figure=figure).to_dict()["layout"]
        assert after == before

    def test_the_input_figure_is_not_modified(self, registry, figure):
        """Outputs are cached and shared — styling in place would restyle
        every other node wired to the same chart."""
        style(registry, {"title": "Changed", "template": "plotly_dark"},
              figure=figure)
        assert figure.layout.title.text is None

    def test_the_data_is_untouched(self, registry, figure):
        out = style(registry, {"title": "T"}, figure=figure)
        assert list(out.data[0].y) == list(figure.data[0].y)


class TestSettings:
    def test_title_and_axis_titles(self, registry, figure):
        out = style(registry, {"title": "Sales", "x_title": "Region",
                               "y_title": "Units"}, figure=figure)
        assert out.layout.title.text == "Sales"
        assert out.layout.xaxis.title.text == "Region"
        assert out.layout.yaxis.title.text == "Units"

    def test_theme_and_palette(self, registry, figure):
        import plotly.express as px
        out = style(registry, {"template": "plotly_dark",
                               "colorway": "Bold"}, figure=figure)
        assert out.layout.colorway == tuple(px.colors.qualitative.Bold)

    def test_legend_hidden_and_repositioned(self, registry, figure):
        out = style(registry, {"legend": "hide", "legend_pos": "bottom"},
                    figure=figure)
        assert out.layout.showlegend is False
        assert out.layout.legend.orientation == "h"

    def test_hover_off_is_false_not_the_word(self, registry, figure):
        out = style(registry, {"hovermode": "off"}, figure=figure)
        assert out.layout.hovermode is False

    def test_unified_hover(self, registry, figure):
        out = style(registry, {"hovermode": "x unified"}, figure=figure)
        assert out.layout.hovermode == "x unified"

    def test_gridlines_and_tick_format(self, registry, figure):
        out = style(registry, {"grid_y": "off", "y_format": ",.0f",
                               "tick_angle": "-45"}, figure=figure)
        assert out.layout.yaxis.showgrid is False
        assert out.layout.yaxis.tickformat == ",.0f"
        assert out.layout.xaxis.tickangle == -45

    def test_sort_categories(self, registry, figure):
        out = style(registry, {"category_order": "total descending"},
                    figure=figure)
        assert out.layout.xaxis.categoryorder == "total descending"

    def test_log_axis_and_range(self, registry, figure):
        out = style(registry, {"log_y": "on", "min_y": "10",
                               "max_y": "1000"}, figure=figure)
        assert out.layout.yaxis.type == "log"
        assert out.layout.yaxis.range == (1.0, 3.0)

    def test_a_plain_range_is_not_converted(self, registry, figure):
        out = style(registry, {"min_y": "0", "max_y": "50"}, figure=figure)
        assert out.layout.yaxis.range == (0.0, 50.0)

    def test_half_a_range_is_no_range(self, registry, figure):
        out = style(registry, {"min_y": "0"}, figure=figure)
        assert out.layout.yaxis.range is None

    def test_reference_line(self, registry, figure):
        out = style(registry, {"line_at": "15", "line_label": "Target"},
                    figure=figure)
        line = out.layout.shapes[0]
        assert (line.y0, line.y1) == (15, 15)
        assert out.layout.annotations[0].text == "Target"

    def test_a_vertical_reference_line(self, registry, figure):
        out = style(registry, {"line_at": "1", "line_axis": "x"},
                    figure=figure)
        assert out.layout.shapes[0].x0 == 1

    def test_note_in_a_corner(self, registry, figure):
        out = style(registry, {"note": "two\nlines",
                               "note_pos": "bottom right"}, figure=figure)
        note = out.layout.annotations[0]
        assert note.text == "two<br>lines"
        assert (note.x, note.y) == (0.99, 0.01)

    def test_fonts_backgrounds_and_margins(self, registry, figure):
        out = style(registry, {"font_family": "Georgia", "font_size": 14,
                               "paper_color": "#fff", "plot_color": "#eee",
                               "margin": "10,20,30,40"}, figure=figure)
        assert out.layout.font.family == "Georgia"
        assert out.layout.font.size == 14
        assert out.layout.paper_bgcolor == "#fff"
        assert (out.layout.margin.l, out.layout.margin.b) == (10, 40)

    def test_a_half_written_margin_is_ignored(self, registry, figure):
        out = style(registry, {"margin": "10,20"}, figure=figure)
        assert out.layout.margin.l is None


class TestOtherShapes:
    def test_a_list_of_figures_is_styled_one_by_one(self, registry, figure):
        import plotly.graph_objects as go
        figures = [figure, go.Figure(figure)]
        out = style(registry, {"title": "T"}, figure=figures)
        assert [f.layout.title.text for f in out] == ["T", "T"]

    def test_an_empty_list_stays_a_list(self, registry):
        assert style(registry, {}, figure=[]) == []

    def test_a_chart_with_no_axes_is_styled_anyway(self, registry):
        """update_xaxes walks the axes a figure has, which for a pie is
        none — the theme still applies and nothing raises."""
        import plotly.express as px
        pie = px.pie(pd.DataFrame({"r": ["n", "s"], "v": [1, 2]}),
                     names="r", values="v")
        out = style(registry, {"template": "plotly_dark", "y_title": "Ignored",
                               "grid_y": "off"}, figure=pie)
        assert out.layout.template is not None

    def test_nothing_wired_in_says_so(self, registry):
        with pytest.raises(ValueError, match="nothing on the figure input"):
            style(registry, {}, figure=None)

    def test_something_that_is_not_a_figure_says_so(self, registry):
        with pytest.raises(TypeError, match="not a\n?\\s*Plotly figure"):
            style(registry, {}, figure=pd.DataFrame({"a": [1]}))


class TestWiring:
    """The point of a separate styling node is that it takes a figure from
    anywhere, so the ports have to accept every node that makes one."""

    @pytest.mark.parametrize("source,port", [
        ("flograph.viz.show_plotly", "figure"),
        ("flograph.viz.chart_per_value_plotly", "figures"),
        ("flograph.viz.gantt", "figure"),
        ("flograph.viz.plotly_style", "figure"),
    ])
    def test_a_figure_producer_wires_in(self, registry, source, port):
        from flograph.core import Graph

        graph = Graph()
        producer = graph.add_node(registry.instantiate(source))
        style = graph.add_node(
            registry.instantiate("flograph.viz.plotly_style"))
        graph.connect(producer.id, port, style.id, "figure")
        assert len(graph.connections) == 1
