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


def outputs(registry, params=None, **inputs):
    spec = registry.get("flograph.viz.plotly_style")
    values = spec.default_params()
    values.update(params or {})
    run = compile_run(spec.source, "test-style")
    return run(FakeContext(params=values), **inputs)


def style(registry, params=None, **inputs):
    return outputs(registry, params, **inputs)["figure"]


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
    def test_hide_titles_ticks_axes_and_color_bar(self, registry, figure):
        out = style(registry, {"axis_titles": "hide X", "tick_labels":
                               "hide Y", "hide_axis": "hide both",
                               "hide_legend_title": True,
                               "hide_colorbar": True}, figure=figure)
        assert out.layout.xaxis.title.text == ""
        assert out.layout.yaxis.showticklabels is False
        assert out.layout.xaxis.visible is False
        assert out.layout.yaxis.visible is False
        assert out.layout.legend.title.text == ""
        assert out.layout.coloraxis.showscale is False

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

    def test_legend_orientation_is_independent_of_position(self, registry,
                                                           figure):
        out = style(registry, {"legend_orientation": "horizontal"},
                    figure=figure)
        assert out.layout.legend.orientation == "h"

    def test_legend_fine_placement(self, registry, figure):
        out = style(registry, {"legend_x": "1.02", "legend_y": "0.5"},
                    figure=figure)
        assert (out.layout.legend.x, out.layout.legend.y) == (1.02, 0.5)

    def test_a_tweak_merges_onto_a_position_preset(self, registry, figure):
        out = style(registry, {"legend_pos": "bottom",
                               "legend_x": "0.1"}, figure=figure)
        assert out.layout.legend.orientation == "h"   # from the preset
        assert out.layout.legend.x == 0.1             # the override

    def test_legend_clicks_can_be_frozen(self, registry, figure):
        out = style(registry, {"legend_click": "off"}, figure=figure)
        assert out.layout.legend.itemclick is False
        assert out.layout.legend.itemdoubleclick is False

    def test_legend_isolate_swaps_click_and_double_click(self, registry,
                                                         figure):
        out = style(registry, {"legend_click": "isolate one"}, figure=figure)
        assert out.layout.legend.itemclick == "toggleothers"
        assert out.layout.legend.itemdoubleclick == "toggle"

    def test_legend_order_and_marker_and_text(self, registry, figure):
        out = style(registry, {"legend_order": "reversed grouped",
                               "legend_item_size": "uniform",
                               "legend_font_size": 11}, figure=figure)
        assert out.layout.legend.traceorder == "reversed+grouped"
        assert out.layout.legend.itemsizing == "constant"
        assert out.layout.legend.font.size == 11

    def test_legend_background_and_border(self, registry, figure):
        out = style(registry, {"legend_bg": "#fff", "legend_border": "#333",
                               "legend_border_width": 1}, figure=figure)
        assert out.layout.legend.bgcolor == "#fff"
        assert out.layout.legend.bordercolor == "#333"
        assert out.layout.legend.borderwidth == 1

    def test_legend_title_still_works_alongside_a_legend_tweak(self, registry,
                                                              figure):
        out = style(registry, {"legend_title": "Region",
                               "legend_orientation": "horizontal"},
                    figure=figure)
        assert out.layout.legend.title.text == "Region"
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

    def test_the_json_escape_hatch(self, registry, figure):
        out = style(registry, {"layout_json": '{"bargap": 0.5}',
                               "traces_json": '{"marker_line_width": 2}',
                               "config_json": '{"scrollZoom": true}'},
                    figure=figure)
        assert out.layout.bargap == 0.5
        assert out.data[0].marker.line.width == 2
        assert out._flograph_config == {"scrollZoom": True}

    def test_a_json_override_runs_after_a_setting_above_it(self, registry,
                                                          figure):
        out = style(registry, {"grid_y": "off",
                               "layout_json": '{"yaxis": {"showgrid": true}}'},
                    figure=figure)
        assert out.layout.yaxis.showgrid is True

    def test_bad_json_says_which_box(self, registry, figure):
        with pytest.raises(ValueError, match="Traces \\(JSON\\): not valid"):
            style(registry, {"traces_json": "{oops}"}, figure=figure)


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

    def test_a_reference_line_on_a_pie_is_skipped_not_a_crash(self, registry):
        import plotly.express as px
        pie = px.pie(pd.DataFrame({"r": ["n", "s"], "v": [1, 2]}),
                     names="r", values="v")
        out = style(registry, {"line_at": "1", "note": "ok"}, figure=pie)
        assert out.layout.shapes == ()
        assert out.layout.annotations[0].text == "ok"

    def test_no_figure_passes_the_style_on(self, registry):
        """The head of a chain is a style and nothing else — it has no
        chart of its own to style."""
        out = outputs(registry, {"title": "House"})
        assert out["figure"] is None
        assert out["style"]["layers"] == [{"title": "House"}]

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


class TestChaining:
    """A Plotly Style's style output feeds the next one's style input, and
    the chain applies in order — the same chart as passing the figure
    through each node in turn."""

    def test_registered_with_optional_style_ports(self, registry):
        spec = registry.get("flograph.viz.plotly_style")
        assert [p.name for p in spec.inputs] == ["figure", "style"]
        assert all(p.optional for p in spec.inputs)
        assert [p.name for p in spec.outputs] == ["figure", "style"]

    def test_only_what_was_set_travels(self, registry, figure):
        out = outputs(registry, {"y_format": ",.0f", "width": 900,
                                 "more": True}, figure=figure)
        assert out["style"]["layers"] == [{"y_format": ",.0f"}]

    def test_an_untouched_node_adds_nothing_to_a_chain(self, registry):
        house = outputs(registry, {"template": "plotly_dark"})["style"]
        out = outputs(registry, {}, style=house)
        assert out["style"]["layers"] == house["layers"]

    def test_incoming_style_applies_then_this_nodes_own(
            self, registry, figure):
        house = outputs(registry, {"template": "simple_white",
                                   "title": "House title",
                                   "y_format": ",.0f"})["style"]
        out = style(registry, {"title": "Sales"}, figure=figure, style=house)
        assert out.layout.title.text == "Sales"          # later wins
        assert out.layout.yaxis.tickformat == ",.0f"     # earlier kept
        assert out.layout.template.layout.plot_bgcolor is not None

    def test_three_deep_matches_passing_the_figure_through_each(
            self, registry, figure):
        a = {"template": "plotly_dark", "line_at": "12", "note": "a"}
        b = {"legend": "hide", "line_at": "15", "line_label": "Target"}
        c = {"title": "Chained", "layout_json": '{"bargap": 0.4}'}
        chained = outputs(registry, b, style=outputs(registry, a)["style"])
        via_styles = style(registry, c, figure=figure,
                           style=chained["style"])
        via_figures = style(registry, c, figure=style(
            registry, b, figure=style(registry, a, figure=figure)))
        assert via_styles.to_dict()["layout"] == \
            via_figures.to_dict()["layout"]
        # both reference lines drawn, as two nodes in a row would
        assert len(via_styles.layout.shapes) == 2

    def test_the_chain_carries_on_down_the_style_output(
            self, registry, figure):
        first = outputs(registry, {"title": "A"})["style"]
        second = outputs(registry, {"x_title": "B"}, figure=figure,
                         style=first)["style"]
        assert second["layers"] == [{"title": "A"}, {"x_title": "B"}]

    def test_the_incoming_style_is_not_modified(self, registry, figure):
        house = outputs(registry, {"title": "A"})["style"]
        outputs(registry, {"title": "B"}, figure=figure, style=house)
        assert house["layers"] == [{"title": "A"}]

    def test_a_table_style_on_the_style_input_says_so(self, registry, figure):
        with pytest.raises(TypeError, match="not a Plotly Style"):
            style(registry, {}, figure=figure,
                  style={"rules": [], "errors": []})

    def test_bad_json_fails_the_style_only_node(self, registry):
        with pytest.raises(ValueError, match="Layout \\(JSON\\)"):
            outputs(registry, {"layout_json": "{nope"})

    def test_a_list_of_figures_takes_the_chain(self, registry, figure):
        import plotly.graph_objects as go
        house = outputs(registry, {"title": "T"})["style"]
        out = style(registry, {}, figure=[figure, go.Figure(figure)],
                    style=house)
        assert [f.layout.title.text for f in out] == ["T", "T"]

    def test_one_style_wires_into_another(self, registry):
        from flograph.core import Graph

        graph = Graph()
        house = graph.add_node(
            registry.instantiate("flograph.viz.plotly_style"))
        chart = graph.add_node(
            registry.instantiate("flograph.viz.plotly_style"))
        graph.connect(house.id, "style", chart.id, "style")
        assert len(graph.connections) == 1
