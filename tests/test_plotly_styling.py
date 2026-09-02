"""The styling pass folded into both Plotly nodes.

Show Plotly and Chart per Value (Plotly) each carry an identical copy of
the Plotly Style capability — `_STYLE_ROWS` and `_apply_styling` — so the
one node masters what plotly offers. These tests run against both copies
(the `node` fixture) and check they stay in step.

`test_plotly_style_node.py` still covers the standalone Plotly Style node,
which does the same job on a figure these nodes did not draw.
"""
import pandas as pd
import pytest

from flograph.core import NodeRegistry, compile_run
from tests.conftest import FakeContext

pytest.importorskip("plotly")

SHOW = "flograph.viz.show_plotly"
PER_VALUE = "flograph.viz.chart_per_value_plotly"


@pytest.fixture(scope="module")
def registry():
    reg = NodeRegistry()
    reg.load_builtins()
    return reg


@pytest.fixture
def table():
    return pd.DataFrame({
        "region": ["n", "n", "s", "s", "e", "e"],
        "city": list("abcdef"),
        "units": [10, 20, 30, 40, 15, 25],
    })


def _fig(registry, type_id, params, table):
    """Build one figure from either node — the single figure, or the first
    of Chart per Value's stack."""
    spec = registry.get(type_id)
    values = spec.default_params()
    if type_id == PER_VALUE:
        values.update(split_by="region", x="city", y="units")
    else:
        values.update(kind="bar", x="region", y="units")
    values.update(params)
    out = compile_run(spec.source, "t")(FakeContext(params=values), table=table)
    figure = out["figure"] if type_id == SHOW else out["figures"][0]
    return figure


both = pytest.mark.parametrize("type_id", [SHOW, PER_VALUE],
                               ids=["show_plotly", "chart_per_value_plotly"])


class TestTheTwoCopiesAgree:
    def test_style_rows_are_identical(self, registry):
        show, per_value = {}, {}
        exec(compile(registry.get(SHOW).source, SHOW, "exec"), show)
        exec(compile(registry.get(PER_VALUE).source, PER_VALUE, "exec"),
             per_value)
        assert show["_STYLE_ROWS"] == per_value["_STYLE_ROWS"]
        assert show["_LEGEND_POS"] == per_value["_LEGEND_POS"]
        assert show["_LEGEND_CLICK"] == per_value["_LEGEND_CLICK"]

    @both
    def test_the_styling_params_are_all_there(self, registry, type_id):
        spec = registry.get(type_id)
        for name in ("styling", "legend", "legend_pos", "legend_orientation",
                     "legend_click", "legend_x", "legend_y", "legend_order",
                     "legend_font_size", "legend_bg", "x_title", "y_title",
                     "grid_x", "grid_y", "x_format", "tick_angle",
                     "category_order", "range_slider", "line_at", "ref_dash",
                     "note", "note_pos", "font_family", "paper_color",
                     "margin", "hovermode", "colorbar_title",
                     "layout_json", "traces_json", "config_json"):
            assert spec.param(name) is not None, name

    @both
    def test_no_param_is_declared_twice(self, registry, type_id):
        names = [p.name for p in registry.get(type_id).params]
        assert len(names) == len(set(names))

    @both
    def test_styling_is_cosmetic(self, registry, type_id):
        """Opening the drawer must not re-run the chart."""
        assert registry.get(type_id).param("styling").cosmetic


class TestInertUntilAsked:
    @both
    def test_defaults_touch_nothing(self, registry, type_id, table):
        figure = _fig(registry, type_id, {}, table)
        assert figure.layout.showlegend is None
        assert figure.layout.shapes == ()
        assert figure.layout.legend.orientation is None

    @both
    def test_a_styling_value_with_the_drawer_shut_still_applies(
            self, registry, type_id, table):
        """The tick only hides the rows in the panel; a value that is set
        is a value that is set."""
        figure = _fig(registry, type_id, {"legend": "hide"}, table)
        assert figure.layout.showlegend is False


class TestTheStylingPass:
    @both
    def test_legend_placement_and_clicks(self, registry, type_id, table):
        figure = _fig(registry, type_id,
                      {"legend_pos": "bottom", "legend_x": "0.1",
                       "legend_click": "off"}, table)
        assert figure.layout.legend.orientation == "h"   # from the preset
        assert figure.layout.legend.x == 0.1             # merged override
        assert figure.layout.legend.itemclick is False

    @both
    def test_axis_titles_gridlines_and_formats(self, registry, type_id,
                                               table):
        figure = _fig(registry, type_id,
                      {"x_title": "Region", "y_title": "Units",
                       "grid_y": "off", "y_format": ",.0f",
                       "tick_angle": "-45"}, table)
        assert figure.layout.xaxis.title.text == "Region"
        assert figure.layout.yaxis.title.text == "Units"
        assert figure.layout.yaxis.showgrid is False
        assert figure.layout.yaxis.tickformat == ",.0f"
        assert figure.layout.xaxis.tickangle == -45

    @both
    def test_reference_line_and_note(self, registry, type_id, table):
        figure = _fig(registry, type_id,
                      {"line_at": "25", "line_label": "Target",
                       "line_axis": "y", "ref_dash": "dot",
                       "note": "two\nlines", "note_pos": "bottom right"},
                      table)
        assert (figure.layout.shapes[0].y0, figure.layout.shapes[0].y1) == (25, 25)
        texts = {a.text for a in figure.layout.annotations}
        assert {"Target", "two<br>lines"} <= texts

    @both
    def test_hover_note_fonts_and_backgrounds(self, registry, type_id, table):
        figure = _fig(registry, type_id,
                      {"hovermode": "x unified", "font_family": "Georgia",
                       "font_size": 13, "paper_color": "#fff",
                       "plot_color": "#eee", "margin": "10,20,30,40"}, table)
        assert figure.layout.hovermode == "x unified"
        assert figure.layout.font.family == "Georgia"
        assert figure.layout.font.size == 13
        assert figure.layout.paper_bgcolor == "#fff"
        assert (figure.layout.margin.l, figure.layout.margin.b) == (10, 40)

    @both
    def test_hover_off_is_false_not_the_word(self, registry, type_id, table):
        figure = _fig(registry, type_id, {"hovermode": "off"}, table)
        assert figure.layout.hovermode is False

    def test_a_half_written_margin_is_left_alone(self, registry, table):
        figure = _fig(registry, SHOW, {"margin": "10,20"}, table)
        assert figure.layout.margin.l is None

    def test_a_reference_line_on_a_pie_is_skipped_not_a_crash(self, registry,
                                                              table):
        """A pie has no cartesian axis; add_hline raises on it. The line
        just doesn't apply, like a gridline doesn't."""
        spec = registry.get(SHOW)
        values = spec.default_params()
        values.update(kind="pie", names="region", values="units",
                      styling=True, line_at="20", grid_y="off",
                      note="still fine")
        figure = compile_run(spec.source, "t")(
            FakeContext(params=values), table=table)["figure"]
        assert figure.data
        assert figure.layout.shapes == ()
        assert figure.layout.annotations[0].text == "still fine"

    def test_the_px_title_still_wins_over_a_style_align(self, registry, table):
        """title is a px argument; title_align only nudges it."""
        figure = _fig(registry, SHOW,
                      {"title": "Sales", "title_align": "right"}, table)
        assert figure.layout.title.text == "Sales"
        assert figure.layout.title.xanchor == "right"


class TestTheEscapeHatch:
    """The three JSON boxes reach everything the toggles don't."""

    @both
    def test_layout_json_reaches_the_whole_layout_schema(self, registry,
                                                         type_id, table):
        figure = _fig(registry, type_id,
                      {"layout_json": '{"bargap": 0.4, "barmode": "overlay"}'},
                      table)
        assert figure.layout.bargap == 0.4
        assert figure.layout.barmode == "overlay"

    @both
    def test_traces_json_is_applied_to_every_trace(self, registry, type_id,
                                                   table):
        figure = _fig(registry, type_id,
                      {"traces_json": '{"marker_line_width": 3}'}, table)
        assert all(t.marker.line.width == 3 for t in figure.data)

    @both
    def test_config_json_rides_along_on_the_figure(self, registry, type_id,
                                                   table):
        figure = _fig(registry, type_id,
                      {"config_json": '{"scrollZoom": true}'}, table)
        assert figure._flograph_config == {"scrollZoom": True}

    @both
    def test_a_raw_override_wins_over_a_toggle(self, registry, type_id, table):
        """grid_y off, then layout_json turns the same gridline back on —
        the JSON runs last."""
        figure = _fig(registry, type_id,
                      {"grid_y": "off",
                       "layout_json": '{"yaxis": {"showgrid": true}}'}, table)
        assert figure.layout.yaxis.showgrid is True

    def test_bad_json_names_the_box_and_does_not_draw(self, registry, table):
        with pytest.raises(ValueError, match="Layout \\(JSON\\): not valid"):
            _fig(registry, SHOW, {"layout_json": "{nope}"}, table)

    def test_a_json_list_is_rejected_it_has_to_be_an_object(self, registry,
                                                            table):
        with pytest.raises(ValueError, match="expected a JSON object"):
            _fig(registry, SHOW, {"traces_json": "[1, 2, 3]"}, table)

    def test_the_card_hands_the_config_to_plotly_js(self, registry, table):
        from flograph.core.html import to_html

        figure = _fig(registry, SHOW,
                      {"config_json": '{"scrollZoom": true}'}, table)
        page = to_html(figure)
        assert '"scrollZoom": true' in page

    def test_a_plain_figure_still_renders_with_no_config(self, registry,
                                                         table):
        from flograph.core.html import to_html

        assert to_html(_fig(registry, SHOW, {}, table))


class TestThePanelStillGates:
    def _rows(self, qtbot, registry, more, styling):
        from PySide6.QtGui import QUndoStack

        from flograph.core import Graph
        from flograph.ui.properties.params_panel import ParamsPanel

        graph = Graph()
        node = graph.add_node(registry.instantiate(SHOW))
        graph.set_param(node.id, "kind", "bar")
        graph.set_param(node.id, "more", more)
        graph.set_param(node.id, "styling", styling)
        panel = ParamsPanel(graph, QUndoStack())
        qtbot.addWidget(panel)
        panel.set_node(node.id)
        tree = panel.tree
        return {tree.topLevelItem(i).text(0)
                for i in range(tree.topLevelItemCount())}

    def test_styling_rows_are_hidden_until_the_tick(self, qtbot, registry):
        shut = self._rows(qtbot, registry, more=False, styling=False)
        open_ = self._rows(qtbot, registry, more=False, styling=True)
        assert "Legend position" not in shut
        assert "Legend position" in open_
        assert "Reference line" in open_

    def test_both_drawers_open_is_still_under_a_hundred_rows(self, qtbot,
                                                            registry):
        rows = self._rows(qtbot, registry, more=True, styling=True)
        assert len(rows) < 100
