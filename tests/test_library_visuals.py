"""The visuals built on installed web libraries: Network Graph, Calendar
Heatmap, Sankey Flow and Circle Pack.

Each one is the two new features together — it draws with a library from the
local store (never a CDN) and it writes its own `selected` param when you
click, so the `table` output is the input filtered to what you clicked.

These are headless: the libraries are planted, not downloaded. That the JS
they emit actually *runs* was verified separately in a real QWebEngineView
against the real libraries (D3 drew its circles, ECharts and Cytoscape their
canvases, no console errors); a browser in this suite is what leaves zombie
renderers behind, so it stays out of it. What is tested here is everything
Python decides: the shape of the data handed to the page, the filtering, and
the errors.
"""
from __future__ import annotations

import json

import pandas as pd
import pytest

from flograph.core import NodeRegistry, compile_run
from flograph.weblibs import MissingLibrary
from tests.conftest import FakeContext, install_fake_weblib


@pytest.fixture(scope="module")
def registry():
    reg = NodeRegistry()
    reg.load_builtins()
    return reg


@pytest.fixture
def libraries(monkeypatch, tmp_path):
    """Every library these nodes draw with, present but not downloaded."""
    for name in ("d3", "echarts", "cytoscape"):
        install_fake_weblib(monkeypatch, tmp_path, name)


def run_node(registry, type_id, params=None, **inputs):
    spec = registry.get(type_id)
    defaults = spec.default_params()
    defaults.update(params or {})
    context = FakeContext(params=defaults)
    out = compile_run(spec.source, f"test-{type_id}")(context, **inputs)
    return context, out


def embedded(html: str, name: str):
    """One `NAME = <json>` value out of a rendered page.

    Not anchored on `var`: several of these pages declare two or three
    values on one line (`var NODES = …, LINKS = …`).
    """
    marker = f"{name} = "
    assert marker in html, f"no {name} in the page"
    body = html.split(marker, 1)[1]
    return json.JSONDecoder().raw_decode(body)[0]


NODES = ["flograph.viz.network_graph", "flograph.viz.calendar_heatmap",
         "flograph.viz.sankey_flow", "flograph.viz.circle_pack"]


@pytest.fixture
def edges():
    return pd.DataFrame({"mgr": ["CEO", "CEO", "CTO", "CTO"],
                         "rep": ["CTO", "CFO", "Eng", "Ops"],
                         "n": [5, 2, 9, 1]})


@pytest.fixture
def funnel():
    return pd.DataFrame({
        "stage": ["applied", "applied", "screened", "screened"],
        "next": ["screened", "rejected", "onsite", "rejected"],
        "n": [100, 40, 30, 20]})


@pytest.fixture
def sales():
    return pd.DataFrame({
        "region": ["north", "north", "south", "south", "south"],
        "city": ["leeds", "york", "bath", "bath", "exeter"],
        "amount": [10, 5, 20, 3, 7]})


@pytest.fixture
def diary():
    return pd.DataFrame({"when": pd.date_range("2026-01-01", periods=40),
                         "amount": range(40)})


class TestTheyAllShareTheContract:
    """Four nodes, one shape — worth asserting together so a fifth can't
    quietly arrive with different manners."""

    @pytest.mark.parametrize("type_id", NODES)
    def test_declared_interactive_with_the_three_outputs(self, registry,
                                                         type_id):
        spec = registry.get(type_id)
        assert spec.card == "webview" and spec.interactive
        assert [o.name for o in spec.outputs] == ["html", "selected", "table"]
        assert spec.param("selected") is not None
        assert spec.param("on_click") is not None

    @pytest.mark.parametrize("type_id", NODES)
    def test_it_says_what_to_install_when_the_library_is_missing(
            self, registry, monkeypatch, tmp_path, type_id, edges, funnel,
            sales, diary):
        monkeypatch.setenv("FLOGRAPH_USER_DIR", str(tmp_path / "empty"))
        params, inputs = {
            "flograph.viz.network_graph": (
                {"source": "mgr", "target": "rep"}, {"edges": edges}),
            "flograph.viz.calendar_heatmap": (
                {"date": "when", "value": "amount"}, {"table": diary}),
            "flograph.viz.sankey_flow": (
                {"source": "stage", "target": "next", "value": "n"},
                {"table": funnel}),
            "flograph.viz.circle_pack": (
                {"group_by": "region", "size_by": "amount"}, {"table": sales}),
        }[type_id]
        with pytest.raises(MissingLibrary, match="Web Libraries"):
            run_node(registry, type_id, params, **inputs)

    @pytest.mark.parametrize("type_id", NODES)
    def test_the_page_carries_no_remote_reference(
            self, registry, libraries, type_id, edges, funnel, sales, diary):
        """The rule the whole store exists for, asserted at the one place a
        user would actually notice it: the finished page."""
        params, inputs = {
            "flograph.viz.network_graph": (
                {"source": "mgr", "target": "rep"}, {"edges": edges}),
            "flograph.viz.calendar_heatmap": (
                {"date": "when", "value": "amount"}, {"table": diary}),
            "flograph.viz.sankey_flow": (
                {"source": "stage", "target": "next", "value": "n"},
                {"table": funnel}),
            "flograph.viz.circle_pack": (
                {"group_by": "region", "size_by": "amount"}, {"table": sales}),
        }[type_id]
        _, out = run_node(registry, type_id, params, **inputs)
        assert "https://" not in out["html"]
        assert "http://" not in out["html"]
        assert "file://" in out["html"]

    @pytest.mark.parametrize("type_id", NODES)
    def test_nothing_clicked_passes_the_table_through(
            self, registry, libraries, type_id, edges, funnel, sales, diary):
        params, inputs, table = {
            "flograph.viz.network_graph": (
                {"source": "mgr", "target": "rep"}, {"edges": edges}, edges),
            "flograph.viz.calendar_heatmap": (
                {"date": "when", "value": "amount"}, {"table": diary}, diary),
            "flograph.viz.sankey_flow": (
                {"source": "stage", "target": "next", "value": "n"},
                {"table": funnel}, funnel),
            "flograph.viz.circle_pack": (
                {"group_by": "region", "size_by": "amount"},
                {"table": sales}, sales),
        }[type_id]
        _, out = run_node(registry, type_id, params, **inputs)
        assert len(out["table"]) == len(table)
        assert out["selected"] == []


class TestNetworkGraph:
    TYPE = "flograph.viz.network_graph"

    def test_it_builds_nodes_from_both_ends_of_the_links(self, registry,
                                                         libraries, edges):
        _, out = run_node(registry, self.TYPE,
                          {"source": "mgr", "target": "rep"}, edges=edges)
        elements = embedded(out["html"], "ELEMENTS")
        assert {n["data"]["id"] for n in elements["nodes"]} == {
            "CEO", "CTO", "CFO", "Eng", "Ops"}
        assert len(elements["edges"]) == 4

    def test_clicking_a_node_keeps_the_links_touching_it(self, registry,
                                                         libraries, edges):
        _, out = run_node(registry, self.TYPE,
                          {"source": "mgr", "target": "rep",
                           "selected": '["CTO"]'}, edges=edges)
        assert len(out["table"]) == 3        # CEO→CTO, CTO→Eng, CTO→Ops
        assert out["selected"] == ["CTO"]

    def test_weights_become_widths_relative_to_the_busiest(self, registry,
                                                          libraries, edges):
        """A linear map of raw values lets one outlier hide everything, so
        the widths are scaled to the largest."""
        _, out = run_node(registry, self.TYPE,
                          {"source": "mgr", "target": "rep", "weight": "n"},
                          edges=edges)
        widths = [e["data"]["weight"]
                  for e in embedded(out["html"], "ELEMENTS")["edges"]]
        assert max(widths) == 6.0 and min(widths) >= 1.0

    def test_every_edge_carries_a_label_field(self, registry, libraries,
                                              edges):
        """The stylesheet maps data(label) for all edges, and Cytoscape
        warns once per element when the field is absent."""
        _, out = run_node(registry, self.TYPE,
                          {"source": "mgr", "target": "rep"}, edges=edges)
        assert all("label" in e["data"]
                   for e in embedded(out["html"], "ELEMENTS")["edges"])

    def test_a_second_table_sizes_and_colours_the_circles(self, registry,
                                                          libraries, edges):
        people = pd.DataFrame({"who": ["CEO", "CTO", "CFO", "Eng", "Ops"],
                               "reports": [2, 2, 0, 0, 0],
                               "dept": ["exec", "exec", "fin", "eng", "eng"]})
        _, out = run_node(registry, self.TYPE,
                          {"source": "mgr", "target": "rep",
                           "node_key": "who", "size_by": "reports",
                           "colour_by": "dept"},
                          edges=edges, nodes=people)
        by_id = {n["data"]["id"]: n["data"]
                 for n in embedded(out["html"], "ELEMENTS")["nodes"]}
        assert by_id["CEO"]["size"] > by_id["CFO"]["size"]
        assert by_id["CEO"]["colour"] == by_id["CTO"]["colour"]
        assert by_id["CEO"]["colour"] != by_id["CFO"]["colour"]

    def test_links_with_a_blank_end_are_dropped(self, registry, libraries):
        ragged = pd.DataFrame({"a": ["x", ""], "b": ["y", "z"]})
        _, out = run_node(registry, self.TYPE,
                          {"source": "a", "target": "b"}, edges=ragged)
        assert len(embedded(out["html"], "ELEMENTS")["edges"]) == 1

    def test_no_usable_links_is_an_error(self, registry, libraries):
        empty = pd.DataFrame({"a": [""], "b": [""]})
        with pytest.raises(ValueError, match="no links"):
            run_node(registry, self.TYPE, {"source": "a", "target": "b"},
                     edges=empty)

    def test_missing_columns_are_named(self, registry, libraries, edges):
        with pytest.raises(ValueError, match="From' and 'To"):
            run_node(registry, self.TYPE, {}, edges=edges)
        with pytest.raises(ValueError, match="'nope' is not in the table"):
            run_node(registry, self.TYPE,
                     {"source": "mgr", "target": "nope"}, edges=edges)


class TestCalendarHeatmap:
    TYPE = "flograph.viz.calendar_heatmap"

    def test_days_are_combined_and_dated(self, registry, libraries):
        twice = pd.DataFrame({"when": ["2026-03-01", "2026-03-01"],
                              "amount": [2, 3]})
        _, out = run_node(registry, self.TYPE,
                          {"date": "when", "value": "amount"}, table=twice)
        assert embedded(out["html"], "DATA") == [["2026-03-01", 5.0]]

    def test_combine_can_average_instead(self, registry, libraries):
        twice = pd.DataFrame({"when": ["2026-03-01", "2026-03-01"],
                              "amount": [2, 4]})
        _, out = run_node(registry, self.TYPE,
                          {"date": "when", "value": "amount",
                           "combine": "mean"}, table=twice)
        assert embedded(out["html"], "DATA") == [["2026-03-01", 3.0]]

    def test_no_value_column_counts_rows(self, registry, libraries):
        twice = pd.DataFrame({"when": ["2026-03-01", "2026-03-01"]})
        _, out = run_node(registry, self.TYPE, {"date": "when"}, table=twice)
        assert embedded(out["html"], "DATA") == [["2026-03-01", 2.0]]

    def test_the_latest_year_is_drawn_by_default(self, registry, libraries):
        spread = pd.DataFrame({"when": ["2024-01-01", "2026-01-01"],
                               "amount": [1, 2]})
        _, out = run_node(registry, self.TYPE,
                          {"date": "when", "value": "amount"}, table=spread)
        assert embedded(out["html"], "YEAR") == "2026"

    def test_an_explicit_year_wins_and_says_what_it_left_out(
            self, registry, libraries):
        spread = pd.DataFrame({"when": ["2024-01-01", "2026-01-01"],
                               "amount": [1, 2]})
        context, out = run_node(registry, self.TYPE,
                                {"date": "when", "value": "amount",
                                 "year": "2024"}, table=spread)
        assert embedded(out["html"], "YEAR") == "2024"
        assert any("not shown" in line for line in context.logs)

    def test_a_year_with_no_rows_lists_the_ones_there_are(self, registry,
                                                          libraries, diary):
        with pytest.raises(ValueError, match="the data covers: 2026"):
            run_node(registry, self.TYPE,
                     {"date": "when", "value": "amount", "year": "1999"},
                     table=diary)

    def test_clicking_a_day_keeps_that_day(self, registry, libraries, diary):
        _, out = run_node(registry, self.TYPE,
                          {"date": "when", "value": "amount",
                           "selected": '["2026-01-05"]'}, table=diary)
        assert len(out["table"]) == 1

    def test_unparseable_dates_are_counted_not_fatal(self, registry,
                                                     libraries):
        messy = pd.DataFrame({"when": ["2026-01-01", "not a date"],
                              "amount": [1, 2]})
        context, out = run_node(registry, self.TYPE,
                                {"date": "when", "value": "amount"},
                                table=messy)
        assert any("no usable date" in line for line in context.logs)
        assert embedded(out["html"], "DATA") == [["2026-01-01", 1.0]]

    def test_a_column_of_no_dates_at_all_is_an_error(self, registry,
                                                     libraries, sales):
        with pytest.raises(ValueError, match="reads as a date"):
            run_node(registry, self.TYPE, {"date": "region"}, table=sales)

    def test_it_does_not_warn_about_date_formats(self, registry, libraries,
                                                 recwarn):
        """Coercing mixed input is the job here; pandas' inference warning
        would land in the user's log looking like a fault."""
        messy = pd.DataFrame({"when": ["2026-01-01", "01/02/2026"],
                              "amount": [1, 2]})
        run_node(registry, self.TYPE, {"date": "when", "value": "amount"},
                 table=messy)
        assert not [w for w in recwarn if "infer format" in str(w.message)]


class TestSankeyFlow:
    TYPE = "flograph.viz.sankey_flow"

    def test_flows_are_summed_per_pair(self, registry, libraries):
        repeated = pd.DataFrame({"a": ["x", "x"], "b": ["y", "y"],
                                 "n": [2, 3]})
        _, out = run_node(registry, self.TYPE,
                          {"source": "a", "target": "b", "value": "n"},
                          table=repeated)
        assert embedded(out["html"], "LINKS") == [
            {"source": "x", "target": "y", "value": 5.0}]

    def test_stages_chain_through_shared_names(self, registry, libraries,
                                               funnel):
        _, out = run_node(registry, self.TYPE,
                          {"source": "stage", "target": "next",
                           "value": "n"}, table=funnel)
        names = [n["name"] for n in embedded(out["html"], "NODES")]
        assert set(names) == {"applied", "screened", "rejected", "onsite"}

    def test_a_loop_is_dropped_because_it_has_no_width(self, registry,
                                                       libraries):
        looped = pd.DataFrame({"a": ["x", "y"], "b": ["x", "z"], "n": [1, 2]})
        context, out = run_node(registry, self.TYPE,
                                {"source": "a", "target": "b", "value": "n"},
                                table=looped)
        assert len(embedded(out["html"], "LINKS")) == 1
        assert any("skipped" in line for line in context.logs)

    def test_clicking_a_stage_keeps_rows_at_either_end(self, registry,
                                                       libraries, funnel):
        _, out = run_node(registry, self.TYPE,
                          {"source": "stage", "target": "next", "value": "n",
                           "selected": '["screened"]'}, table=funnel)
        assert len(out["table"]) == 3        # one in, two out

    def test_no_positive_flows_is_an_error(self, registry, libraries):
        nothing = pd.DataFrame({"a": ["x"], "b": ["x"], "n": [1]})
        with pytest.raises(ValueError, match="no flows"):
            run_node(registry, self.TYPE,
                     {"source": "a", "target": "b", "value": "n"},
                     table=nothing)

    def test_missing_columns_are_named(self, registry, libraries, funnel):
        with pytest.raises(ValueError, match="From' and 'To"):
            run_node(registry, self.TYPE, {}, table=funnel)


class TestCirclePack:
    TYPE = "flograph.viz.circle_pack"

    def test_it_nests_outermost_first(self, registry, libraries, sales):
        _, out = run_node(registry, self.TYPE,
                          {"group_by": "region, city", "size_by": "amount"},
                          table=sales)
        tree = embedded(out["html"], "TREE")
        regions = {child["name"] for child in tree["children"]}
        assert regions == {"north", "south"}
        north = next(c for c in tree["children"] if c["name"] == "north")
        assert {c["name"] for c in north["children"]} == {"leeds", "york"}

    def test_only_leaves_carry_a_value(self, registry, libraries, sales):
        """d3's .sum() rolls branches up; a branch with its own value as
        well would be counted twice."""
        tree = embedded(run_node(
            registry, self.TYPE,
            {"group_by": "region, city", "size_by": "amount"},
            table=sales)[1]["html"], "TREE")
        for region in tree["children"]:
            assert "value" not in region
            assert all("value" in city for city in region["children"])

    def test_repeated_leaves_are_summed(self, registry, libraries, sales):
        tree = embedded(run_node(
            registry, self.TYPE,
            {"group_by": "region, city", "size_by": "amount"},
            table=sales)[1]["html"], "TREE")
        south = next(c for c in tree["children"] if c["name"] == "south")
        bath = next(c for c in south["children"] if c["name"] == "bath")
        assert bath["value"] == 23.0            # 20 + 3

    def test_no_size_column_counts_rows(self, registry, libraries, sales):
        tree = embedded(run_node(
            registry, self.TYPE, {"group_by": "region"},
            table=sales)[1]["html"], "TREE")
        south = next(c for c in tree["children"] if c["name"] == "south")
        assert south["value"] == 3.0

    def test_a_click_at_any_level_filters(self, registry, libraries, sales):
        _, out = run_node(registry, self.TYPE,
                          {"group_by": "region, city", "size_by": "amount",
                           "selected": '["south"]'}, table=sales)
        assert len(out["table"]) == 3
        _, out = run_node(registry, self.TYPE,
                          {"group_by": "region, city", "size_by": "amount",
                           "selected": '["bath"]'}, table=sales)
        assert len(out["table"]) == 2

    def test_rows_without_a_positive_size_are_dropped(self, registry,
                                                      libraries):
        mixed = pd.DataFrame({"g": ["a", "b"], "v": [5, 0]})
        tree = embedded(run_node(
            registry, self.TYPE, {"group_by": "g", "size_by": "v"},
            table=mixed)[1]["html"], "TREE")
        assert [c["name"] for c in tree["children"]] == ["a"]

    def test_nothing_positive_is_an_error(self, registry, libraries):
        mixed = pd.DataFrame({"g": ["a"], "v": [0]})
        with pytest.raises(ValueError, match="no row had a positive"):
            run_node(registry, self.TYPE, {"group_by": "g", "size_by": "v"},
                     table=mixed)

    def test_missing_columns_are_named(self, registry, libraries, sales):
        with pytest.raises(ValueError, match="Group by"):
            run_node(registry, self.TYPE, {}, table=sales)
        with pytest.raises(ValueError, match="'nope' is not in the table"):
            run_node(registry, self.TYPE, {"group_by": "nope"}, table=sales)

    def test_a_grouping_column_with_a_space_still_works(self, registry,
                                                        libraries):
        """itertuples renames those, which is why the tree is built from
        positions rather than attribute names."""
        spaced = pd.DataFrame({"cost centre": ["ops", "ops"], "v": [1, 2]})
        tree = embedded(run_node(
            registry, self.TYPE,
            {"group_by": "cost centre", "size_by": "v"},
            table=spaced)[1]["html"], "TREE")
        assert tree["children"] == [{"name": "ops", "value": 3.0}]
