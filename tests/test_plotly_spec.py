"""Each Plotly node's own copy of the chart-kind table.

Show Plotly and Chart per Value (Plotly) each carry an identical, private
copy of "every chart kind, and the code that turns one into a `px.<kind>()`
call" directly in the node script — see the note above `_figure_lock` in
either file, and in `core/plotly_spec.py`, for why they no longer share it
from a `core` module. `_KIND_ARGS` is a copy of plotly's own signatures,
and everything else — which settings a chart kind shows, which it silently
drops — is derived from it. If plotly renames or removes an argument, the
copy goes stale and the panel starts offering settings that no longer
exist. These tests run against *both* nodes' own copies (the `ps` fixture
below), so a stale table is caught wherever it happens to be, and a copy
that has drifted from the other fails here too.
"""
import inspect
import types

import pandas as pd
import pytest

from flograph.core import NodeRegistry
from flograph.core.params import ParamSpec

px = pytest.importorskip("plotly.express")

SHOW = "flograph.viz.show_plotly"
PER_VALUE = "flograph.viz.chart_per_value_plotly"

#: The private names each node script defines for what used to be
#: `core.plotly_spec`'s public API — see the module docstring above.
_ATTRS = ("_KINDS", "_KIND_ARGS", "_UNIVERSAL_ARGS", "_ARG_OF",
         "_kinds_taking", "_params", "_build", "_layout_updates")


@pytest.fixture(scope="module")
def registry():
    reg = NodeRegistry()
    reg.load_builtins()
    return reg


@pytest.fixture(params=[SHOW, PER_VALUE],
                ids=["show_plotly", "chart_per_value_plotly"])
def ps(request, registry):
    """One node's own module namespace, standing in for the old shared
    `core.plotly_spec` module — same shape, minus the leading underscores,
    so the rest of this file reads exactly as it did when there was one
    module both nodes imported."""
    namespace = {}
    exec(compile(registry.get(request.param).source, request.param, "exec"),
         namespace)
    return types.SimpleNamespace(
        KINDS=namespace["_KINDS"], KIND_ARGS=namespace["_KIND_ARGS"],
        UNIVERSAL_ARGS=namespace["_UNIVERSAL_ARGS"],
        _ARG_OF=namespace["_ARG_OF"],
        kinds_taking=namespace["_kinds_taking"],
        params=namespace["_params"], build=namespace["_build"],
        layout_updates=namespace["_layout_updates"])


@pytest.fixture
def table():
    return pd.DataFrame({
        "region": ["n", "s", "n", "s", "e", "w"],
        "city": list("abcdef"),
        "year": [2022, 2022, 2023, 2023, 2024, 2024],
        "units": [10, 20, 30, 40, 15, 25],
        "revenue": [100.0, 150.0, 300.0, 320.0, 90.0, 210.0],
        "start": pd.to_datetime(["2024-01-01"] * 6),
        "finish": pd.to_datetime(["2024-02-01"] * 6),
    })


#: What each kind needs before it can be drawn at all, for the sweeps below.
ROLES = {
    "timeline": {"x_start": "start", "x_end": "finish", "y": "city"},
    "pie": {"names": "region", "values": "units"},
    "funnel_area": {"names": "region", "values": "units"},
    "sunburst": {"path": "region,city", "values": "units"},
    "treemap": {"path": "region,city", "values": "units"},
    "icicle": {"path": "region,city", "values": "units"},
    "scatter_polar": {"r": "units", "theta": "region"},
    "line_polar": {"r": "units", "theta": "region"},
    "bar_polar": {"r": "units", "theta": "region"},
    "scatter_ternary": {"a": "units", "b": "revenue", "c": "year"},
    "line_ternary": {"a": "units", "b": "revenue", "c": "year"},
    "scatter_3d": {"x": "units", "y": "revenue", "z": "year"},
    "line_3d": {"x": "units", "y": "revenue", "z": "year"},
}


def defaults(ps, **overrides):
    values = {spec.name: spec.default
              for spec in (ParamSpec.from_dict(row) for row in ps.params())}
    values.update(overrides)
    return values


class TestTheKindTable:
    def test_every_kind_is_a_plotly_express_function(self, ps):
        for kind in ps.KINDS:
            assert callable(getattr(px, kind, None)), kind

    def test_kind_args_match_the_installed_plotly(self, ps):
        """The generated copy of plotly's signatures is still accurate."""
        for kind in ps.KINDS:
            live = set(inspect.signature(getattr(px, kind)).parameters)
            assert ps.KIND_ARGS[kind] == live - ps.UNIVERSAL_ARGS - {
                "data_frame"}, kind

    def test_universal_args_really_are_universal(self, ps):
        for kind in ps.KINDS:
            live = set(inspect.signature(getattr(px, kind)).parameters)
            assert ps.UNIVERSAL_ARGS <= live, kind

    def test_maps_and_imshow_are_left_out(self, ps):
        for absent in ("scatter_map", "choropleth", "density_mapbox",
                       "scatter_geo", "imshow"):
            assert absent not in ps.KINDS

    def test_every_param_feeds_an_argument_some_kind_has(self, ps):
        """A typo in an "arg" would hide its row from every chart kind."""
        for name, arg in ps._ARG_OF.items():
            assert ps.kinds_taking(arg), f"{name} -> {arg}"


class TestBothNodesAgree:
    """The one invariant duplication puts at risk: the two copies must
    still describe exactly the same chart set."""

    def test_the_kind_tables_are_identical(self, registry):
        show = {}
        exec(compile(registry.get(SHOW).source, SHOW, "exec"), show)
        per_value = {}
        exec(compile(registry.get(PER_VALUE).source, PER_VALUE, "exec"),
            per_value)
        assert show["_KINDS"] == per_value["_KINDS"]
        assert show["_KIND_ARGS"] == per_value["_KIND_ARGS"]


class TestParams:
    def test_every_row_is_a_valid_param(self, ps):
        specs = [ParamSpec.from_dict(row) for row in ps.params()]
        assert len(specs) == len({s.name for s in specs})

    def test_a_row_is_gated_to_the_kinds_that_take_it(self, ps):
        rows = {row["name"]: row for row in ps.params()}
        assert rows["hole"]["visible_when"]["kind"] == ["pie"]
        assert "scatter" in rows["trendline"]["visible_when"]["kind"]
        assert "bar" not in rows["trendline"]["visible_when"]["kind"]

    def test_universal_rows_carry_no_kind_gate(self, ps):
        rows = {row["name"]: row for row in ps.params()}
        for name in ("kind", "title", "template", "labels"):
            assert "kind" not in rows[name].get("visible_when", {})

    def test_advanced_rows_hide_behind_more_options(self, ps):
        rows = {row["name"]: row for row in ps.params()}
        assert rows["symbol"]["visible_when"]["more"] == ["True"]
        assert "more" not in rows["color"].get("visible_when", {})

    def test_more_is_cosmetic_so_opening_it_never_re_runs(self, ps):
        rows = {row["name"]: row for row in ps.params()}
        assert rows["more"]["cosmetic"] is True


class TestBuildDrawsEveryKind:
    def test_kind_draws_from_its_defaults(self, ps, table):
        for kind in ps.KINDS:
            values = defaults(ps, kind=kind, **ROLES.get(kind, {}))
            kwargs, ignored = ps.build(values, table, px)
            figure = getattr(px, kind)(table, **kwargs)
            assert figure.data, kind
            assert ignored == [], kind

    def test_blank_columns_plot_every_number_on_y(self, ps, table):
        kwargs, _ = ps.build(defaults(ps, kind="line"), table, px)
        assert kwargs["y"] == ["year", "units", "revenue"]

    def test_a_distribution_fills_x_instead(self, ps, table):
        """A histogram of a column is what "histogram" means; filling y
        would quietly make a two-dimensional one."""
        kwargs, _ = ps.build(defaults(ps, kind="histogram"), table, px)
        assert kwargs["x"] == ["year", "units", "revenue"]
        assert "y" not in kwargs

    def test_a_named_x_is_not_also_plotted_on_y(self, ps, table):
        kwargs, _ = ps.build(defaults(ps, kind="line", x="year"), table, px)
        assert kwargs["y"] == ["units", "revenue"]

    def test_a_single_y_is_a_name_not_a_one_item_list(self, ps, table):
        """A one-item list puts plotly into wide mode, which fights the
        other role columns — px.scatter_3d rejects it outright."""
        kwargs, _ = ps.build(
            defaults(ps, kind="scatter_3d", x="units", y="revenue", z="year"),
            table, px)
        assert kwargs["y"] == "revenue"

    def test_extra_columns_the_node_owns_are_left_out(self, ps, table):
        kwargs, _ = ps.build(defaults(ps, kind="line"), table, px,
                             exclude=["year"])
        assert kwargs["y"] == ["units", "revenue"]


class TestBuildSettings:
    def test_a_choice_at_its_default_is_not_passed_on(self, ps, table):
        kwargs, _ = ps.build(defaults(ps, kind="histogram"), table, px)
        assert "histfunc" not in kwargs

    def test_a_changed_choice_is(self, ps, table):
        kwargs, _ = ps.build(defaults(ps, kind="histogram", histfunc="avg",
                                      y="units", x="region"), table, px)
        assert kwargs["histfunc"] == "avg"

    def test_orientation_is_translated_to_plotlys_letter(self, ps, table):
        kwargs, _ = ps.build(
            defaults(ps, kind="bar", x="units", y="region",
                     orientation="horizontal"), table, px)
        assert kwargs["orientation"] == "h"

    def test_a_palette_name_becomes_a_list_of_colours(self, ps, table):
        kwargs, _ = ps.build(
            defaults(ps, kind="bar", x="region", y="units",
                     color_sequence="Bold"), table, px)
        assert kwargs["color_discrete_sequence"] == px.colors.qualitative.Bold

    def test_rename_axes_lines_become_a_mapping(self, ps, table):
        kwargs, _ = ps.build(
            defaults(ps, kind="bar", x="region", y="units",
                     labels="units = Units sold\n# a comment\n\n"),
            table, px)
        assert kwargs["labels"] == {"units": "Units sold"}

    def test_a_trendline_window_becomes_trendline_options(self, ps, table):
        kwargs, _ = ps.build(
            defaults(ps, kind="scatter", x="units", y="revenue",
                     trendline="rolling", trendline_window=3), table, px)
        assert kwargs["trendline_options"] == {"window": 3}

    def test_both_ends_of_a_range_make_one(self, ps, table):
        kwargs, _ = ps.build(
            defaults(ps, kind="line", x="year", y="units", min_y="0",
                     max_y="50"), table, px)
        assert kwargs["range_y"] == [0.0, 50.0]

    def test_one_end_of_a_range_makes_none_and_says_so(self, ps, table):
        kwargs, ignored = ps.build(
            defaults(ps, kind="line", x="year", y="units", min_y="0"),
            table, px)
        assert "range_y" not in kwargs
        assert ignored == ["Min Y without Max Y"]

    def test_a_range_on_a_log_axis_is_converted_to_exponents(self, ps, table):
        """Plotly reads a log axis range as powers of ten. The boxes take
        the values you want to read off the axis, so they are converted."""
        kwargs, _ = ps.build(
            defaults(ps, kind="line", x="year", y="units", log_y=True,
                     min_y="10", max_y="1000"), table, px)
        assert kwargs["range_y"] == [1.0, 3.0]

    def test_a_log_axis_pinned_at_zero_is_refused_by_name(self, ps, table):
        with pytest.raises(ValueError, match="Min Y is 0"):
            ps.build(defaults(ps, kind="line", x="year", y="units",
                              log_y=True, min_y="0", max_y="1000"), table, px)

    def test_an_unreadable_number_falls_back_rather_than_failing(self, ps,
                                                                  table):
        kwargs, _ = ps.build(
            defaults(ps, kind="histogram", x="units", nbins="lots"),
            table, px)
        assert "nbins" not in kwargs


class TestBuildComplains:
    def test_a_column_that_is_not_there(self, ps, table):
        with pytest.raises(ValueError, match="columns not in table"):
            ps.build(defaults(ps, kind="line", x="nope"), table, px)

    def test_a_chart_missing_the_column_it_is_made_of(self, ps, table):
        with pytest.raises(ValueError, match="a pie chart needs names"):
            ps.build(defaults(ps, kind="pie"), table, px)

    def test_a_table_with_no_numbers_in_it(self, ps, table):
        with pytest.raises(ValueError, match="no numeric columns"):
            ps.build(defaults(ps, kind="line"), table[["region", "city"]], px)

    def test_an_unknown_kind(self, ps, table):
        with pytest.raises(ValueError, match="unknown chart kind"):
            ps.build(defaults(ps, kind="bubble"), table, px)


class TestSettingsTheChartCannotUse:
    def test_they_are_dropped_and_named(self, ps, table):
        """Switching kind leaves the old settings in place rather than
        wiping them, so the chart has to ignore what it can't use."""
        kwargs, ignored = ps.build(
            defaults(ps, kind="line", x="year", y="units", hole=0.4,
                     trendline="ols"), table, px)
        assert "hole" not in kwargs and "trendline" not in kwargs
        assert ignored == ["Hole", "Trendline"]

    def test_untouched_settings_are_not_named(self, ps, table):
        _, ignored = ps.build(defaults(ps, kind="pie", names="region",
                                       values="units"), table, px)
        assert ignored == []


class TestLayoutUpdates:
    def test_bar_gets_its_barnorm_through_the_layout(self, ps):
        """px.bar is the one bar chart with no barnorm argument."""
        assert "barnorm" not in ps.KIND_ARGS["bar"]
        assert ps.layout_updates({"barnorm": "percent"}, "bar") == {
            "barnorm": "percent"}

    def test_a_kind_that_takes_it_as_an_argument_does_not(self, ps):
        assert ps.layout_updates({"barnorm": "percent"}, "histogram") == {}

    def test_nothing_to_do_by_default(self, ps):
        assert ps.layout_updates({"barnorm": "none"}, "bar") == {}
