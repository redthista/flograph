"""The Show Plotly card: interactive plotly chart in an embedded webview."""
import json

import pandas as pd
import pytest
from PySide6.QtGui import QUndoStack

from flograph.core import Graph, NodeRegistry, PortType, compile_run
from flograph.ui.canvas import NodeGraphScene
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
    spec = registry.get("flograph.viz.show_plotly")
    defaults = spec.default_params()
    defaults.update(params or {})
    run = compile_run(spec.source, "test-plotly")
    return run(FakeContext(params=defaults), **inputs)


def test_registered_with_dataframe_in_object_out(registry):
    spec = registry.get("flograph.viz.show_plotly")
    assert spec.inputs[0].type == PortType.DATAFRAME
    assert spec.outputs[0].type == PortType.OBJECT
    for name in ("kind", "x", "y", "color", "title", "width", "height",
                 "scale"):
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
        node = graph.add_node(registry.instantiate("flograph.viz.show_plotly"))
        return scene.node_items[node.id]

    def test_is_a_resizable_card_with_placeholder(self, env, registry):
        item = self._item(env, registry)
        assert item.plotly_card and item.figure_card
        assert item._figure_placeholder.isVisible()
        assert item._plotly_widget.view is None  # webview only built on first figure
        # "figure" stays first: Open in Browser and the card both read the
        # first declared output. "selected"/"table" carry what a click
        # filtered — see the On click param.
        assert list(item.output_ports) == ["figure", "selected", "table"]
        graph = env[0]
        graph.set_param(item.node.id, "width", 700)
        assert item.width == 700.0
        from flograph.ui.canvas.node_item import PORT_EDGE_GAP, PortItem
        assert (item.output_ports["figure"].pos().x()
                == 700.0 + PortItem.RADIUS + PORT_EDGE_GAP)

    def test_figure_loads_into_webview(self, env, registry, monkeypatch):
        item = self._item(env, registry)
        graph = env[0]
        graph.set_param(item.node.id, "scale", 150)
        loaded, shown, zoomed = [], [], []

        class StubView:
            def load(self, url):
                loaded.append(url.toLocalFile())

            def show(self):
                shown.append(True)

            def hide(self):
                pass

            def setZoomFactor(self, factor):
                zoomed.append(factor)

        # a preassigned view short-circuits _ensure_view, no webengine needed
        monkeypatch.setattr(item._plotly_widget, "view", StubView())

        class StubFigure:
            def to_html(self, **kwargs):
                assert kwargs["full_html"] and kwargs["include_plotlyjs"]
                return "<html>chart</html>"

        item.set_plotly_figure(StubFigure())
        assert shown and loaded
        assert zoomed == [1.5]  # scale param drives the webview zoom factor
        assert item._figure_placeholder.isHidden()
        with open(loaded[0], encoding="utf-8") as fh:
            assert fh.read() == "<html>chart</html>"

    def test_placeholder_explains_missing_webengine(self, env, registry,
                                                    monkeypatch):
        item = self._item(env, registry)
        monkeypatch.setattr(item._plotly_widget, "_ensure_view", lambda: None)

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


@pytest.fixture
def sales():
    return pd.DataFrame({"region": ["n", "s", "n", "s", "e"],
                         "year": [2022, 2022, 2023, 2023, 2024],
                         "revenue": [100.0, 150.0, 300.0, 320.0, 90.0],
                         "units": [1, 2, 3, 4, 5]})


def _zoom(**axes):
    return json.dumps({axis: entry for axis, entry in axes.items()})


class TestGroupAndTotal:
    """Testing W2: a chart that summarises big raw data the way a Power BI
    visual does, while what flows on stays the raw rows."""

    def test_one_bar_per_x_with_y_summed(self, registry, sales):
        pytest.importorskip("plotly")
        out = run_node(registry, {"kind": "bar", "x": "region",
                                  "y": "revenue", "summarise": "sum"},
                       table=sales)
        bar = out["figure"].data[0]
        assert list(bar.x) == ["n", "s", "e"]
        assert list(bar.y) == [400.0, 470.0, 90.0]
        assert len(out["table"]) == len(sales)      # the raw rows flow on

    @pytest.mark.parametrize("how, expected", [
        ("average", [200.0, 235.0, 90.0]), ("count", [2, 2, 1]),
        ("min", [100.0, 150.0, 90.0]), ("max", [300.0, 320.0, 90.0])])
    def test_the_other_ways_to_total(self, registry, sales, how, expected):
        pytest.importorskip("plotly")
        fig = run_node(registry, {"kind": "bar", "x": "region",
                                  "y": "revenue", "summarise": how},
                       table=sales)["figure"]
        assert list(fig.data[0].y) == expected

    def test_colour_keeps_its_split(self, registry, sales):
        pytest.importorskip("plotly")
        fig = run_node(registry, {"kind": "bar", "x": "year", "y": "revenue",
                                  "color": "region", "summarise": "sum"},
                       table=sales)["figure"]
        assert {trace.name for trace in fig.data} == {"n", "s", "e"}

    def test_the_axis_says_what_it_shows(self, registry, sales):
        pytest.importorskip("plotly")
        fig = run_node(registry, {"kind": "bar", "x": "region",
                                  "y": "revenue", "summarise": "sum"},
                       table=sales)["figure"]
        assert fig.layout.yaxis.title.text == "Sum of revenue"

    def test_horizontal_bars_group_by_y(self, registry, sales):
        pytest.importorskip("plotly")
        fig = run_node(registry, {"kind": "bar", "x": "revenue",
                                  "y": "region", "orientation": "horizontal",
                                  "summarise": "sum"},
                       table=sales)["figure"]
        assert list(fig.data[0].y) == ["n", "s", "e"]
        assert list(fig.data[0].x) == [400.0, 470.0, 90.0]

    def test_a_column_with_no_value_per_group_is_left_out(self, registry,
                                                          sales):
        pytest.importorskip("plotly")
        fig = run_node(registry, {"kind": "bar", "x": "region",
                                  "y": "revenue", "hover_data": "units",
                                  "summarise": "sum"},
                       table=sales)["figure"]
        assert len(fig.data[0].x) == 3

    def test_without_an_x_it_draws_every_row(self, registry, sales):
        pytest.importorskip("plotly")
        fig = run_node(registry, {"kind": "bar", "y": "revenue",
                                  "summarise": "sum"}, table=sales)["figure"]
        assert len(fig.data[0].y) == len(sales)

    def test_it_is_offered_only_where_it_means_something(self, registry):
        when = registry.get("flograph.viz.show_plotly").param(
            "summarise").visible_when
        assert "bar" in when["kind"] and "pie" not in when["kind"]


class TestDragToFilter:
    """Testing W2: dragging a box or lasso picks, and a zoom filters to what
    is still in view — and survives the chart being redrawn."""

    def test_the_page_listens_for_drags_and_zooms(self, registry, sales):
        pytest.importorskip("plotly")
        fig = run_node(registry, {"kind": "scatter", "x": "year",
                                  "y": "revenue", "on_click": "select many"},
                       table=sales)["figure"]
        script = fig._flograph_post_script
        for event in ("plotly_click", "plotly_selected", "plotly_deselect",
                      "plotly_relayout"):
            assert event in script
        assert 'flograph.set("view_range"' in script

    def test_a_double_click_lets_a_saved_selection_go(self, registry, sales):
        """A selection that came back with a reopened flow is not one plotly
        drew, so it never sends plotly_deselect for it: the double-click that
        zooms back out has to clear the picked values itself."""
        pytest.importorskip("plotly")
        fig = run_node(registry, {"kind": "scatter", "x": "year",
                                  "y": "revenue", "on_click": "select many",
                                  "selected": '["2022"]'},
                       table=sales)["figure"]
        script = fig._flograph_post_script
        assert 'var picked = ["2022"]' in script
        handler = script.split('gd.on("plotly_doubleclick"', 1)[1]
        handler = handler.split("});", 1)[0]
        assert "picked = []" in handler and "flograph.select(picked)" in handler

    def test_a_zoom_keeps_the_rows_in_view_and_stays_zoomed(self, registry,
                                                            sales):
        pytest.importorskip("plotly")
        out = run_node(registry, {
            "kind": "scatter", "x": "year", "y": "revenue",
            "on_click": "select many",
            "view_range": _zoom(x={"range": [2022.5, 2024.5]})}, table=sales)
        assert list(out["table"]["year"]) == [2023, 2023, 2024]
        assert list(out["figure"].layout.xaxis.range) == [2022.5, 2024.5]

    def test_a_zoom_on_both_axes_narrows_both(self, registry, sales):
        pytest.importorskip("plotly")
        out = run_node(registry, {
            "kind": "scatter", "x": "year", "y": "revenue",
            "on_click": "select many",
            "view_range": _zoom(x={"range": [2022.5, 2024.5]},
                                y={"range": [0, 310]})}, table=sales)
        assert list(out["table"]["revenue"]) == [300.0, 90.0]

    def test_a_category_zoom_keeps_the_categories_in_view(self, registry,
                                                          sales):
        pytest.importorskip("plotly")
        out = run_node(registry, {
            "kind": "bar", "x": "region", "y": "revenue",
            "on_click": "select many", "summarise": "sum",
            "view_range": _zoom(x={"range": [-0.5, 1.5],
                                   "values": ["n", "s"]})}, table=sales)
        assert sorted(set(out["table"]["region"])) == ["n", "s"]
        assert len(out["table"]) == 4

    def test_a_date_zoom(self, registry):
        pytest.importorskip("plotly")
        days = pd.DataFrame({"when": pd.date_range("2026-03-01", periods=5),
                             "amount": [1, 2, 3, 4, 5]})
        out = run_node(registry, {
            "kind": "line", "x": "when", "y": "amount",
            "on_click": "select many",
            "view_range": _zoom(x={"range": ["2026-03-01 12:00",
                                             "2026-03-03 12:00"]})},
                       table=days)
        assert list(out["table"]["amount"]) == [2, 3]

    def test_zooming_the_totals_narrows_the_view_not_the_rows(self, registry,
                                                              sales):
        pytest.importorskip("plotly")
        out = run_node(registry, {
            "kind": "bar", "x": "region", "y": "revenue",
            "on_click": "select many", "summarise": "sum",
            "view_range": _zoom(y={"range": [0, 200]})}, table=sales)
        assert len(out["table"]) == len(sales)
        assert list(out["figure"].layout.yaxis.range) == [0, 200]

    def test_a_drag_and_a_zoom_filter_together(self, registry, sales):
        pytest.importorskip("plotly")
        out = run_node(registry, {
            "kind": "scatter", "x": "year", "y": "revenue",
            "color": "region", "on_click": "select many",
            "selected": '["2023", "2024"]',
            "view_range": _zoom(y={"range": [0, 310]})}, table=sales)
        assert list(out["table"]["revenue"]) == [300.0, 90.0]

    def test_nothing_is_filtered_while_clicking_is_off(self, registry, sales):
        pytest.importorskip("plotly")
        out = run_node(registry, {
            "kind": "scatter", "x": "year", "y": "revenue",
            "view_range": _zoom(x={"range": [2022.5, 2024.5]})}, table=sales)
        assert len(out["table"]) == len(sales)

    def test_a_zoom_that_cannot_be_read_keeps_every_row(self, registry,
                                                        sales):
        pytest.importorskip("plotly")
        out = run_node(registry, {
            "kind": "scatter", "x": "year", "y": "revenue",
            "on_click": "select many", "view_range": "not json"}, table=sales)
        assert len(out["table"]) == len(sales)


class TestATextAxisKeepsItsOrder:
    """Reported testing W2: a Year Month axis split by Color put a month only
    the second series had after the first series' last month, so the lines
    zigzagged — plotly orders a text axis trace by trace."""

    @pytest.fixture
    def readings(self):
        # "2019 01" is only in B, and B comes second
        return pd.DataFrame({
            "month": ["2018 03", "2018 04", "2019 01", "2024 06", "2018 03",
                      "2024 06", "2018 04"],
            "test": ["A", "A", "B", "A", "B", "B", "A"],
            "value": [1.0, 2.0, 9.0, 3.0, 5.0, 6.0, 4.0]})

    def test_a_sorted_table_draws_a_sorted_axis(self, registry, readings):
        pytest.importorskip("plotly")
        rows = readings.sort_values(["month", "test"])
        fig = run_node(registry, {"kind": "line", "x": "month",
                                  "y": "value", "color": "test"},
                       table=rows)["figure"]
        assert list(fig.layout.xaxis.categoryarray) == [
            "2018 03", "2018 04", "2019 01", "2024 06"]

    def test_group_and_total_draws_a_sorted_axis(self, registry, readings):
        pytest.importorskip("plotly")
        fig = run_node(registry, {"kind": "line", "x": "month", "y": "value",
                                  "color": "test", "summarise": "average"},
                       table=readings)["figure"]
        assert list(fig.layout.xaxis.categoryarray) == [
            "2018 03", "2018 04", "2019 01", "2024 06"]
        for trace in fig.data:
            assert list(trace.x) == sorted(trace.x)

    def test_a_number_axis_is_left_to_order_itself(self, registry):
        pytest.importorskip("plotly")
        rows = pd.DataFrame({"year": [2024, 2022, 2023],
                             "value": [1.0, 2.0, 3.0]})
        fig = run_node(registry, {"kind": "line", "x": "year", "y": "value"},
                       table=rows)["figure"]
        assert fig.layout.xaxis.categoryarray is None
