"""The two Plotly nodes offer every chart kind, from one shared set.

`test_plotly_spec.py` covers the parameter set itself. This is about the
nodes that use it: that both really do offer all of it, that they behave
the same way where they should, and that Chart per Value's shared Y scale
still means what it meant when it was the only thing those boxes did.
"""
import pandas as pd
import pytest

from flograph.core import NodeRegistry, compile_run, plotly_spec
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
        "revenue": [100.0, 150.0, 300.0, 320.0, 90.0, 210.0],
    })


def run_node(registry, type_id, params=None, **inputs):
    spec = registry.get(type_id)
    values = spec.default_params()
    values.update(params or {})
    ctx = FakeContext(params=values)
    out = compile_run(spec.source, "test")(ctx, **inputs)
    return out, ctx


class TestBothNodesShareTheSameSettings:
    @pytest.mark.parametrize("type_id", [SHOW, PER_VALUE])
    def test_every_chart_kind_is_offered(self, registry, type_id):
        kinds = registry.get(type_id).param("kind").options
        assert kinds == list(plotly_spec.KINDS)
        assert len(kinds) == 28

    @pytest.mark.parametrize("type_id", [SHOW, PER_VALUE])
    def test_the_shared_settings_are_all_there(self, registry, type_id):
        spec = registry.get(type_id)
        for name in ("size", "symbol", "facet_col", "trendline", "marginal",
                     "hover_data", "labels", "template", "color_sequence",
                     "log_y", "opacity", "animation_frame", "more"):
            assert spec.param(name) is not None, name

    @pytest.mark.parametrize("type_id", [SHOW, PER_VALUE])
    def test_no_setting_is_declared_twice(self, registry, type_id):
        names = [p.name for p in registry.get(type_id).params]
        assert len(names) == len(set(names))

    @pytest.mark.parametrize("type_id", [SHOW, PER_VALUE])
    def test_more_options_is_cosmetic(self, registry, type_id):
        """Revealing the rest of the panel must not re-run the chart."""
        assert registry.get(type_id).param("more").cosmetic


class TestShowPlotly:
    def test_the_old_settings_still_mean_what_they_did(self, registry,
                                                       table):
        """Graphs saved before this node grew: same names, same defaults."""
        spec = registry.get(SHOW)
        assert spec.param("kind").default == "line"
        assert spec.param("barmode").default == "group"
        assert spec.param("width").default == 420
        assert not spec.param("x").multi and spec.param("y").multi

    @pytest.mark.parametrize("kind,params", [
        ("pie", {"names": "region", "values": "units"}),
        ("treemap", {"path": "region,city", "values": "units"}),
        ("scatter_matrix", {}),
        ("scatter_3d", {"x": "units", "y": "revenue", "z": "units"}),
        ("bar_polar", {"r": "units", "theta": "region"}),
        ("ecdf", {"x": "revenue"}),
        ("funnel", {"x": "units", "y": "region"}),
    ])
    def test_a_new_kind_draws(self, registry, table, kind, params):
        out, _ = run_node(registry, SHOW, {"kind": kind, **params},
                          table=table)
        assert out["figure"].data

    def test_facets_and_encodings_reach_the_figure(self, registry, table):
        out, _ = run_node(registry, SHOW,
                          {"kind": "scatter", "x": "units", "y": "revenue",
                           "facet_col": "region", "size": "units"},
                          table=table)
        figure = out["figure"]
        assert figure.layout.xaxis3 is not None  # three facet panels
        assert figure.data[0].marker.size is not None

    def test_a_theme_reaches_the_figure(self, registry, table):
        out, _ = run_node(registry, SHOW,
                          {"y": "units", "template": "plotly_dark"},
                          table=table)
        assert out["figure"].layout.template.layout.paper_bgcolor

    def test_settings_the_kind_cannot_use_are_logged(self, registry, table):
        out, ctx = run_node(registry, SHOW,
                            {"kind": "line", "y": "units", "hole": 0.4},
                            table=table)
        assert out["figure"].data
        assert any("has no use for: Hole" in line for line in ctx.logs)

    def test_a_missing_role_column_names_the_box_to_fill(self, registry,
                                                         table):
        with pytest.raises(ValueError, match="needs names — set Labels"):
            run_node(registry, SHOW, {"kind": "pie"}, table=table)

    def test_bar_barnorm_goes_through_the_layout(self, registry, table):
        """px.bar has no barnorm argument; the layout attribute does."""
        out, _ = run_node(registry, SHOW,
                          {"kind": "bar", "x": "region", "y": "units",
                           "barnorm": "percent"}, table=table)
        assert out["figure"].layout.barnorm == "percent"


class TestChartPerValuePlotly:
    def _run(self, registry, table, params=None):
        values = {"split_by": "region", "x": "city", "y": "units"}
        values.update(params or {})
        return run_node(registry, PER_VALUE, values, table=table)

    def test_one_chart_per_value(self, registry, table):
        out, _ = self._run(registry, table)
        assert len(out["figures"]) == 3

    def test_each_chart_is_titled_by_its_group(self, registry, table):
        out, _ = self._run(registry, table)
        assert [f.layout.title.text for f in out["figures"]] == [
            "region: e", "region: n", "region: s"]

    def test_a_title_is_kept_in_front_of_the_group(self, registry, table):
        out, _ = self._run(registry, table, {"title": "Sales"})
        assert out["figures"][0].layout.title.text == "Sales — region: e"

    def test_the_split_column_is_not_charted_by_accident(self, registry):
        """"Every numeric column" must not include the numeric column the
        node is splitting on."""
        table = pd.DataFrame({"year": [1, 1, 2, 2], "units": [1, 2, 3, 4]})
        out, _ = run_node(registry, PER_VALUE, {"split_by": "year"},
                          table=table)
        figure = out["figures"][0]
        assert len(figure.data) == 1          # units, and not year as well
        assert list(figure.data[0].y) == [1, 2]

    def test_the_shared_scale_still_bounds_every_panel(self, registry,
                                                       table):
        out, _ = self._run(registry, table, {"shared_scale": True})
        ranges = {tuple(f.layout.yaxis.range) for f in out["figures"]}
        assert len(ranges) == 1

    def test_min_y_still_pins_without_a_max(self, registry, table):
        """On this node the two boxes cooperate with the shared scale, so
        one end alone is a real thing to ask for — unlike Show Plotly,
        where a range needs both."""
        out, _ = self._run(registry, table, {"min_y": "0"})
        assert out["figures"][0].layout.yaxis.range[0] == 0

    def test_a_distribution_kind_keeps_its_own_scale(self, registry, table):
        out, _ = self._run(registry, table,
                           {"kind": "histogram", "x": "units", "y": ""})
        assert out["figures"][0].layout.yaxis.range is None

    def test_a_kind_with_no_y_axis_is_not_bounded(self, registry, table):
        out, _ = self._run(registry, table,
                           {"kind": "pie", "names": "city",
                            "values": "units", "x": "", "y": ""})
        assert len(out["figures"]) == 3

    def test_a_categorical_y_is_not_measured_for_a_shared_scale(self,
                                                                registry,
                                                                table):
        """A funnel's Y is stage names, a timeline's is task names. The
        shared scale used to assume every Y column was a number, which is
        a crash inside pandas rather than a chart."""
        out, _ = self._run(registry, table,
                           {"kind": "funnel", "x": "units", "y": "city"})
        assert len(out["figures"]) == 3
        assert out["figures"][0].layout.yaxis.range is None

    def test_a_timeline_splits_without_measuring_its_task_names(self,
                                                                registry):
        frame = pd.DataFrame({
            "team": ["a", "a", "b"],
            "task": ["one", "two", "three"],
            "start": pd.to_datetime(["2024-01-01"] * 3),
            "finish": pd.to_datetime(["2024-02-01"] * 3),
        })
        out, _ = run_node(registry, PER_VALUE,
                          {"split_by": "team", "kind": "timeline",
                           "x_start": "start", "x_end": "finish",
                           "y": "task"}, table=frame)
        assert len(out["figures"]) == 2

    def test_max_charts_still_guards(self, registry, table):
        out, ctx = self._run(registry, table, {"max_charts": 2})
        assert len(out["figures"]) == 2
        assert any("Max charts" in line for line in ctx.logs)

    def test_the_stack_layout_params_survived(self, registry):
        spec = registry.get(PER_VALUE)
        for name in ("columns", "rows", "direction", "shared_scale",
                     "max_charts"):
            assert spec.param(name) is not None
        assert spec.param("direction").options == ["down", "across"]


class TestThePropertiesPanel:
    """The gating has to hold in the panel, not only in the spec: a
    hundred rows is unusable if they all show at once."""

    def _panel(self, qtbot, registry, kind, more=False):
        from PySide6.QtGui import QUndoStack

        from flograph.core import Graph
        from flograph.ui.properties.params_panel import ParamsPanel

        graph = Graph()
        node = graph.add_node(registry.instantiate(SHOW))
        graph.set_param(node.id, "kind", kind)
        graph.set_param(node.id, "more", more)
        panel = ParamsPanel(graph, QUndoStack())
        qtbot.addWidget(panel)
        panel.set_node(node.id)
        return panel

    def _rows(self, panel):
        tree = panel.tree
        return {tree.topLevelItem(i).text(0)
                for i in range(tree.topLevelItemCount())}

    def test_a_line_chart_shows_a_readable_handful(self, qtbot, registry):
        rows = self._rows(self._panel(qtbot, registry, "line"))
        assert 10 <= len(rows) <= 20
        assert {"Kind", "X column", "Y columns", "Color by"} <= rows

    def test_a_pie_chart_shows_pie_things_not_axis_things(self, qtbot,
                                                          registry):
        rows = self._rows(self._panel(qtbot, registry, "pie"))
        assert {"Labels column", "Values column", "Hole"} <= rows
        assert not rows & {"X column", "Y columns", "Log Y", "Bins"}

    def test_more_options_reveals_the_rest(self, qtbot, registry):
        few = self._rows(self._panel(qtbot, registry, "scatter"))
        many = self._rows(self._panel(qtbot, registry, "scatter", more=True))
        assert few < many
        assert "Symbol by" in many and "Symbol by" not in few

    def test_no_kind_shows_everything_at_once(self, qtbot, registry):
        for kind in plotly_spec.KINDS:
            rows = self._rows(self._panel(qtbot, registry, kind, more=True))
            assert len(rows) < 50, kind


class TestGraphsSavedBeforeThis:
    """A .flograph written when these nodes had eight settings.

    Loading merges the spec's defaults under the file's own params
    (`serialization`), so the node arrives complete — but `build()` must
    also stand on its own with keys simply absent, which is what a direct
    run and a headless call look like.
    """

    OLD_SHOW = {"kind": "bar", "barmode": "stack", "x": "region",
                "y": "units,revenue", "color": "", "title": "Old",
                "width": 420, "height": 320, "scale": 100}

    def test_show_plotly_draws_from_the_old_params_alone(self, registry,
                                                         table):
        spec = registry.get(SHOW)
        run = compile_run(spec.source, "test")
        figure = run(FakeContext(params=dict(self.OLD_SHOW)),
                     table=table)["figure"]
        assert len(figure.data) == 2
        assert figure.layout.barmode == "stack"
        assert figure.layout.title.text == "Old"

    def test_chart_per_value_draws_from_the_old_params_alone(self, registry,
                                                             table):
        spec = registry.get(PER_VALUE)
        run = compile_run(spec.source, "test")
        old = {"split_by": "region", "kind": "line", "barmode": "group",
               "x": "city", "y": "units", "color": "", "shared_scale": True,
               "min_y": "", "max_y": "", "max_charts": 20, "columns": 0,
               "rows": 0, "direction": "down", "width": 460, "height": 380,
               "scale": 100}
        figures = run(FakeContext(params=old), table=table)["figures"]
        assert len(figures) == 3

    def test_loading_fills_the_new_settings_with_their_defaults(self,
                                                               registry):
        """What `serialization` does to an old file's node."""
        spec = registry.get(SHOW)
        loaded = {**spec.default_params(), **self.OLD_SHOW}
        assert loaded["kind"] == "bar"          # the file's own value
        assert loaded["trendline"] == "none"    # a setting it never had
        assert loaded["more"] is False
