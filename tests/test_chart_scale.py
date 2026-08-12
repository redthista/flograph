"""Explicit Y bounds on the Chart per Value nodes (idea E1).

The arithmetic lives in core.chart_scale so both nodes share one answer and
so it can be checked without matplotlib or plotly installed — which is the
case on a bare test box, where the node runs below skip themselves.
"""
import pandas as pd
import pytest

from flograph.core import compile_run
from flograph.core.chart_scale import as_bound, data_extent, y_limits
from tests.conftest import FakeContext

NODES = ("flograph.viz.chart_per_value", "flograph.viz.chart_per_value_plotly")


@pytest.fixture
def table():
    return pd.DataFrame({
        "region": ["north", "north", "south", "south"],
        "month": [1, 2, 1, 2],
        "units": [10.0, 30.0, 5.0, 7.0],
        "returns": [1.0, 2.0, 1.0, 3.0],
    })


def run_node(registry, type_id, params=None, **inputs):
    spec = registry.get(type_id)
    defaults = spec.default_params()
    defaults.update(params or {})
    run = compile_run(spec.source, f"test-{type_id}")
    return run(FakeContext(params=defaults), **inputs)


class TestAsBound:
    def test_a_number_reads_as_one(self):
        assert as_bound("12.5") == 12.5
        assert as_bound(0) == 0.0
        assert as_bound(-4) == -4.0

    def test_blank_is_not_pinned(self):
        for value in ("", "   ", None):
            assert as_bound(value) is None

    def test_nonsense_is_not_pinned_either(self):
        # half-typed text in an axis box must leave the chart alone rather
        # than fail the run
        assert as_bound("1.2.3") is None
        assert as_bound("up a bit") is None

    def test_a_bool_is_not_a_bound(self):
        # True would otherwise silently pin the axis to 1
        assert as_bound(True) is None


class TestDataExtent:
    def test_it_covers_every_column_with_headroom(self, table):
        low, high = data_extent(table, ["units", "returns"])
        assert low < 1.0 and high > 30.0
        assert (high - low) == pytest.approx((30.0 - 1.0) * 1.1)

    def test_stacked_bounds_the_row_totals(self, table):
        # 30 + 2 in one row: bounding by the tallest column would crop it
        _low, high = data_extent(table, ["units", "returns"], stacked=True)
        assert high > 32.0

    def test_negatives_pile_separately(self):
        frame = pd.DataFrame({"a": [5.0], "b": [-4.0]})
        low, high = data_extent(frame, ["a", "b"], stacked=True)
        assert low < -4.0 and high > 5.0

    def test_nothing_numeric_has_no_extent(self):
        frame = pd.DataFrame({"a": [float("nan"), float("nan")]})
        assert data_extent(frame, ["a"]) is None
        assert data_extent(frame, []) is None


class TestYLimits:
    def test_no_bounds_leaves_the_extent_alone(self):
        assert y_limits((0.0, 10.0)) == (0.0, 10.0)

    def test_a_bound_replaces_that_end_exactly(self):
        # unpadded: someone who types 0 means 0
        assert y_limits((-0.5, 10.5), min_y=0.0) == (0.0, 10.5)
        assert y_limits((-0.5, 10.5), max_y=100.0) == (-0.5, 100.0)

    def test_both_bounds_need_no_extent_at_all(self):
        assert y_limits(None, 0.0, 100.0) == (0.0, 100.0)

    def test_a_half_known_range_is_no_range(self):
        # nothing to hand a plotting library, so it keeps its own autoscale
        assert y_limits(None, min_y=0.0) is None
        assert y_limits(None) is None

    def test_the_wrong_way_round_is_passed_through(self):
        # both libraries read that as a flipped axis, which is occasionally
        # the point — not something to silently correct
        assert y_limits(None, 10.0, 0.0) == (10.0, 0.0)


class TestParams:
    @pytest.mark.parametrize("type_id", NODES)
    def test_both_nodes_declare_the_bounds(self, registry, type_id):
        spec = registry.get(type_id)
        for name in ("min_y", "max_y"):
            param = spec.param(name)
            assert param is not None, name
            # a string, so blank can mean "not pinned" — a spin box cannot
            assert param.type == "string"
            assert spec.default_params()[name] == ""

    @pytest.mark.parametrize("type_id", NODES)
    def test_the_bounds_are_not_cosmetic(self, registry, type_id):
        # changing the axis changes the figures, so the node must re-run
        assert not registry.get(type_id).param("min_y").cosmetic


class TestMatplotlibNode:
    def limits(self, figures):
        return [figure.axes[0].get_ylim() for figure in figures]

    def test_bounds_pin_every_chart(self, registry, table):
        pytest.importorskip("matplotlib")
        out = run_node(registry, NODES[0],
                       {"split_by": "region", "x": "month", "y": "units",
                        "min_y": "0", "max_y": "50"}, table=table)
        assert self.limits(out["figures"]) == [(0.0, 50.0), (0.0, 50.0)]

    def test_one_end_pinned_leaves_the_other_derived(self, registry, table):
        pytest.importorskip("matplotlib")
        out = run_node(registry, NODES[0],
                       {"split_by": "region", "x": "month", "y": "units",
                        "min_y": "0"}, table=table)
        for low, high in self.limits(out["figures"]):
            assert low == 0.0
            assert high > 30.0          # the shared extent, kept

    def test_pinning_survives_same_scale_being_off(self, registry, table):
        pytest.importorskip("matplotlib")
        out = run_node(registry, NODES[0],
                       {"split_by": "region", "x": "month", "y": "units",
                        "shared_scale": False, "max_y": "50"}, table=table)
        limits = self.limits(out["figures"])
        assert [high for _low, high in limits] == [50.0, 50.0]
        # ...and the free end is still per-chart: south tops out at 7
        assert limits[0][0] != limits[1][0]

    def test_blank_bounds_change_nothing(self, registry, table):
        pytest.importorskip("matplotlib")
        params = {"split_by": "region", "x": "month", "y": "units"}
        before = run_node(registry, NODES[0], params, table=table)
        after = run_node(registry, NODES[0],
                         {**params, "min_y": "", "max_y": "  "}, table=table)
        assert self.limits(before["figures"]) == self.limits(after["figures"])


class TestPlotlyNode:
    def ranges(self, figures):
        return [tuple(figure.layout.yaxis.range or ()) for figure in figures]

    def test_bounds_pin_every_chart(self, registry, table):
        pytest.importorskip("plotly")
        out = run_node(registry, NODES[1],
                       {"split_by": "region", "x": "month", "y": "units",
                        "min_y": "0", "max_y": "50"}, table=table)
        assert self.ranges(out["figures"]) == [(0.0, 50.0), (0.0, 50.0)]

    def test_a_box_plot_takes_a_pair_or_nothing(self, registry, table):
        pytest.importorskip("plotly")
        # box derives its own value axis, so there is no extent to take a
        # free end from — one bound alone can do nothing
        both = run_node(registry, NODES[1],
                        {"split_by": "region", "y": "units", "kind": "box",
                         "min_y": "0", "max_y": "50"}, table=table)
        assert self.ranges(both["figures"]) == [(0.0, 50.0), (0.0, 50.0)]
        one = run_node(registry, NODES[1],
                       {"split_by": "region", "y": "units", "kind": "box",
                        "min_y": "0"}, table=table)
        assert self.ranges(one["figures"]) == [(), ()]
