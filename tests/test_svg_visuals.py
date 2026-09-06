"""The four visuals drawn in Python: Waffle, Slope Chart, Bump Chart, Tile Map.

None of them loads a library, and none of them runs a script to lay itself
out — Python works out every coordinate and writes finished SVG. That is
what these check: the shape of the drawing, the numbers behind it, the
filtering a click does, and the messages you get when the table is not what
the chart needs.

The rendering itself was verified separately by printing each page through
the real report snapshot path and looking at the pictures; a browser in this
suite is what leaves zombie renderers behind, so it stays out of it.
"""
from __future__ import annotations

import json
import re

import pandas as pd
import pytest

from flograph.core import NodeRegistry, compile_run
from tests.conftest import FakeContext

NODES = ["flograph.viz.waffle", "flograph.viz.slope_chart",
         "flograph.viz.bump_chart", "flograph.viz.tile_map"]


@pytest.fixture(scope="module")
def registry():
    reg = NodeRegistry()
    reg.load_builtins()
    return reg


def run_node(registry, type_id, params=None, **inputs):
    spec = registry.get(type_id)
    settings = spec.default_params()
    settings.update(params or {})
    context = FakeContext(params=settings)
    out = compile_run(spec.source, f"test-{type_id}")(context, **inputs)
    return context, out


@pytest.fixture
def regions():
    return pd.DataFrame({
        "region": ["London", "South East", "North West", "Scotland", "Wales"],
        "revenue": [704.0, 502.0, 388.0, 196.0, 96.0],
    })


@pytest.fixture
def seasons():
    """Long: a contender, a period and a number."""
    rows = []
    for month_index, month in enumerate(["Jan", "Feb", "Mar"]):
        for place, brand in enumerate(["Alpha", "Beta", "Gamma"]):
            rows.append({"brand": brand, "month": month,
                         "share": 30 - place * 5 + month_index * place})
    return pd.DataFrame(rows)


def defaults_for(kind, extra=None):
    """The column settings each node needs, since auto-detection is only a
    convenience and these tests are not testing it."""
    base = {
        "flograph.viz.waffle": {"label_column": "region",
                                "value_column": "revenue"},
        "flograph.viz.slope_chart": {"label_column": "region",
                                     "start_column": "revenue",
                                     "end_column": "revenue"},
        "flograph.viz.bump_chart": {"label_column": "region",
                                    "period_column": "region",
                                    "value_column": "revenue"},
        "flograph.viz.tile_map": {"region_column": "region",
                                  "value_column": "revenue"},
    }[kind]
    return {**base, **(extra or {})}


class TestEveryOne:
    """What all four owe, whatever they draw."""

    @pytest.mark.parametrize("type_id", NODES)
    def test_it_draws_an_svg(self, registry, regions, type_id):
        _, out = run_node(registry, type_id, defaults_for(type_id),
                          table=regions)
        assert "<svg" in out["html"]
        assert "</svg>" in out["html"]

    @pytest.mark.parametrize("type_id", NODES)
    def test_nothing_is_fetched(self, registry, regions, type_id):
        """A CDN is where a library is installed from, never where a page
        renders from — and these have no library at all."""
        _, out = run_node(registry, type_id, defaults_for(type_id),
                          table=regions)
        page = out["html"]
        assert "<script src" not in page
        assert "http://" not in page.replace("http://www.w3.org", "")
        assert "https://" not in page.replace("https://www.w3.org", "")

    @pytest.mark.parametrize("type_id", NODES)
    def test_the_drawing_scales_rather_than_fixing_its_size(
            self, registry, regions, type_id):
        _, out = run_node(registry, type_id, defaults_for(type_id),
                          table=regions)
        tag = re.search(r"<svg[^>]*>", out["html"]).group(0)
        assert "viewBox=" in tag

    @pytest.mark.parametrize("type_id", NODES)
    def test_it_passes_the_style_on(self, registry, regions, type_id):
        """So a chain of visuals can share one Visual Style node."""
        style = {"tokens": {"theme": "light", "accent": "#ff0000"}}
        _, out = run_node(registry, type_id, defaults_for(type_id),
                          table=regions, style=style)
        assert out["style"]["tokens"]["accent"] == "#ff0000"
        assert "#ff0000" in out["html"] or "light" in out["html"]

    @pytest.mark.parametrize("type_id", NODES)
    def test_the_theme_reaches_the_page(self, registry, regions, type_id):
        _, out = run_node(registry, type_id,
                          defaults_for(type_id), table=regions,
                          style={"tokens": {"theme": "light"}})
        assert "#f1f5f9" in out["html"]        # the light background

    @pytest.mark.parametrize("type_id", NODES)
    def test_an_empty_table_says_something_useful(self, registry, type_id):
        empty = pd.DataFrame({"region": [], "revenue": []})
        with pytest.raises(ValueError) as caught:
            run_node(registry, type_id, defaults_for(type_id), table=empty)
        assert str(caught.value)

    @pytest.mark.parametrize("type_id", NODES)
    def test_a_column_that_is_not_there_names_the_ones_that_are(
            self, registry, regions, type_id):
        settings = defaults_for(type_id)
        first = next(iter(settings))
        settings[first] = "nope"
        with pytest.raises(ValueError, match="nope"):
            run_node(registry, type_id, settings, table=regions)

    @pytest.mark.parametrize("type_id", NODES)
    def test_a_blank_label_never_becomes_a_category_called_nan(
            self, registry, type_id):
        """pandas hands a blank text cell over as a float NaN, and `str()`
        of that is "nan" — which draws as a real place, sitting on the
        chart looking like data."""
        table = pd.DataFrame({"region": ["London", None, ""],
                              "revenue": [10.0, 20.0, 30.0]})
        try:
            _, out = run_node(registry, type_id, defaults_for(type_id),
                              table=table)
        except ValueError:
            return                      # refusing to draw it is fine too
        # Only as a *label*: "dominant-baseline" has an innocent "nan" in it.
        drawn = re.findall(r">([^<>]+)<", out["html"])
        assert not [word for word in drawn if word.strip().lower() == "nan"]

    @pytest.mark.parametrize("type_id", NODES)
    def test_clicking_is_off_until_it_is_on(self, registry, regions, type_id):
        _, out = run_node(registry, type_id,
                          defaults_for(type_id, {"on_click": "nothing",
                                                 "selected": '["London"]'}),
                          table=regions)
        assert out["selected"] == []
        assert len(out["table"]) == len(regions)
        assert "flograph.select" not in out["html"]

    @pytest.mark.parametrize("type_id", NODES)
    def test_a_click_filters_the_table(self, registry, regions, type_id):
        _, out = run_node(registry, type_id,
                          defaults_for(type_id, {"on_click": "select one",
                                                 "selected": '["London"]'}),
                          table=regions)
        assert out["selected"] == ["London"]
        assert list(out["table"]["region"]) == ["London"]

    @pytest.mark.parametrize("type_id", NODES)
    def test_a_selection_of_something_not_on_the_chart_is_ignored(
            self, registry, regions, type_id):
        """Otherwise every shape dims at once and it reads as a broken
        render rather than as a stale click."""
        _, out = run_node(registry, type_id,
                          defaults_for(type_id, {"on_click": "select one",
                                                 "selected": '["Atlantis"]'}),
                          table=regions)
        assert out["selected"] == []
        assert len(out["table"]) == len(regions)


class TestWaffle:

    def test_a_hundred_squares_by_default(self, registry, regions):
        _, out = run_node(registry, "flograph.viz.waffle",
                          defaults_for("flograph.viz.waffle"), table=regions)
        assert out["html"].count("<rect") == 100

    def test_the_number_of_squares_is_yours_to_choose(self, registry,
                                                      regions):
        _, out = run_node(registry, "flograph.viz.waffle",
                          defaults_for("flograph.viz.waffle", {"cells": 50}),
                          table=regions)
        assert out["html"].count("<rect") == 50

    def test_an_icon_waffle_draws_glyphs_not_boxes(self, registry, regions):
        _, out = run_node(registry, "flograph.viz.waffle",
                          defaults_for("flograph.viz.waffle",
                                       {"shape": "icon", "icon": "★"}),
                          table=regions)
        assert out["html"].count("★") == 100
        assert "<rect" not in out["html"]

    def test_with_no_value_column_it_counts_the_rows(self, registry):
        table = pd.DataFrame({"kind": ["a", "a", "a", "b"]})
        ctx, out = run_node(registry, "flograph.viz.waffle",
                            {"label_column": "kind", "value_column": "",
                             "cells": 100}, table=table)
        assert "counting rows" in " ".join(ctx.logs)
        # 3:1 — and the squares still come to a hundred
        assert out["html"].count("<rect") == 100

    def test_the_legend_can_show_the_share_or_the_value(self, registry,
                                                        regions):
        _, share = run_node(registry, "flograph.viz.waffle",
                            defaults_for("flograph.viz.waffle",
                                         {"legend_shows": "share"}),
                            table=regions)
        assert "37%" in share["html"]
        _, value = run_node(registry, "flograph.viz.waffle",
                            defaults_for("flograph.viz.waffle",
                                         {"legend_shows": "value"}),
                            table=regions)
        assert "704" in value["html"]

    def test_a_table_with_no_usable_row_says_so(self, registry):
        table = pd.DataFrame({"region": ["", None], "revenue": [1, 2]})
        with pytest.raises(ValueError, match="nothing to draw"):
            run_node(registry, "flograph.viz.waffle",
                     defaults_for("flograph.viz.waffle"), table=table)


class TestSlopeChart:

    def test_two_columns_is_a_slope(self, registry):
        table = pd.DataFrame({"region": ["North", "South"],
                              "before": [10, 20], "after": [15, 12]})
        ctx, out = run_node(registry, "flograph.viz.slope_chart",
                            {"label_column": "region",
                             "start_column": "before", "end_column": "after"},
                            table=table)
        assert "1 up, 1 down" in " ".join(ctx.logs)
        assert out["html"].count("<circle") == 4      # two ends, two series

    def test_a_long_table_uses_the_first_and_last_period(self, registry,
                                                         seasons):
        ctx, out = run_node(registry, "flograph.viz.slope_chart",
                            {"label_column": "brand",
                             "period_column": "month",
                             "value_column": "share"}, table=seasons)
        assert "Jan -> Mar" in " ".join(ctx.logs)
        assert "3 periods in the data" in out["html"]

    def test_up_is_green_and_down_is_red_whatever_the_palette(self, registry):
        """"Worse than last year" is not a palette decision."""
        table = pd.DataFrame({"region": ["North", "South"],
                              "before": [10, 20], "after": [15, 12]})
        _, out = run_node(registry, "flograph.viz.slope_chart",
                          {"label_column": "region", "start_column": "before",
                           "end_column": "after", "colour_by": "direction"},
                          table=table, style={"tokens": {"palette":
                                                         ["#000000"]}})
        assert "#10b981" in out["html"]
        assert "#ef4444" in out["html"]

    def test_a_series_missing_one_end_is_left_out_and_counted(self, registry):
        table = pd.DataFrame({"region": ["North", "South"],
                              "before": [10, None], "after": [15, 12]})
        ctx, out = run_node(registry, "flograph.viz.slope_chart",
                            {"label_column": "region",
                             "start_column": "before", "end_column": "after"},
                            table=table)
        assert "1 incomplete" in " ".join(ctx.logs)
        assert "1 series left out" in out["html"]

    def test_one_period_is_not_a_slope(self, registry):
        table = pd.DataFrame({"brand": ["a", "b"], "month": ["Jan", "Jan"],
                              "share": [1, 2]})
        with pytest.raises(ValueError, match="two moments"):
            run_node(registry, "flograph.viz.slope_chart",
                     {"label_column": "brand", "period_column": "month",
                      "value_column": "share"}, table=table)

    def test_nothing_joinable_says_why(self, registry):
        table = pd.DataFrame({"region": ["North"], "before": [None],
                              "after": [3]})
        with pytest.raises(ValueError, match="joins two values"):
            run_node(registry, "flograph.viz.slope_chart",
                     {"label_column": "region", "start_column": "before",
                      "end_column": "after"}, table=table)

    def test_showing_only_the_biggest_movers(self, registry):
        table = pd.DataFrame({"region": ["Big", "Small", "Tiny"],
                              "before": [10, 10, 10],
                              "after": [90, 12, 11]})
        _, out = run_node(registry, "flograph.viz.slope_chart",
                          {"label_column": "region", "start_column": "before",
                           "end_column": "after", "rows": 1}, table=table)
        assert "Big" in out["html"]
        assert "Tiny" not in out["html"]


class TestBumpChart:

    def test_it_plots_places_not_values(self, registry, seasons):
        _, out = run_node(registry, "flograph.viz.bump_chart",
                          {"label_column": "brand", "period_column": "month",
                           "value_column": "share", "dots": "the place"},
                          table=seasons)
        # three contenders, three periods: nine dots, each labelled 1-3
        assert out["html"].count("<circle") == 9
        assert ">1<" in out["html"] and ">3<" in out["html"]

    def test_the_lowest_can_be_first_instead(self, registry):
        table = pd.DataFrame({"runner": ["a", "b"], "race": ["one", "one"],
                              "time": [9.9, 12.0]})
        _, out = run_node(registry, "flograph.viz.bump_chart",
                          {"label_column": "runner", "period_column": "race",
                           "value_column": "time", "best": "the lowest",
                           "labels": "left"}, table=table)
        # `a` was quicker, so `a` is above `b`
        ys = [float(m) for m in re.findall(r"<circle cx='[\d.]+' cy='([\d.]+)'",
                                           out["html"])]
        assert ys[0] < ys[1]

    def test_a_missing_period_breaks_the_line_rather_than_dropping_it(
            self, registry, seasons):
        """Not reporting in March is not the same as coming last in March."""
        gappy = seasons[~((seasons.brand == "Beta")
                          & (seasons.month == "Feb"))]
        _, out = run_node(registry, "flograph.viz.bump_chart",
                          {"label_column": "brand", "period_column": "month",
                           "value_column": "share"}, table=gappy)
        # Beta keeps both its ends, so it is still drawn — as two runs
        assert out["html"].count("<circle") == 8

    def test_only_the_top_places_when_asked(self, registry, seasons):
        _, out = run_node(registry, "flograph.viz.bump_chart",
                          {"label_column": "brand", "period_column": "month",
                           "value_column": "share", "top": 2}, table=seasons)
        assert out["html"].count("<circle") == 6

    def test_the_caption_names_the_biggest_mover_either_way(self, registry):
        rows = [{"b": "Faller", "m": "Jan", "v": 100},
                {"b": "Riser", "m": "Jan", "v": 10},
                {"b": "Steady", "m": "Jan", "v": 50},
                {"b": "Faller", "m": "Feb", "v": 1},
                {"b": "Riser", "m": "Feb", "v": 90},
                {"b": "Steady", "m": "Feb", "v": 50}]
        _, out = run_node(registry, "flograph.viz.bump_chart",
                          {"label_column": "b", "period_column": "m",
                           "value_column": "v"}, table=pd.DataFrame(rows))
        assert "fell 2 places" in out["html"] or "climbed 2 places" in out[
            "html"]

    def test_periods_keep_the_order_the_table_had(self, registry):
        """Dates, quarters and made-up names all sort differently; only the
        flow knows what "left to right" means."""
        rows = [{"b": "a", "m": m, "v": 1} for m in ("Dec", "Jan", "Feb")]
        _, out = run_node(registry, "flograph.viz.bump_chart",
                          {"label_column": "b", "period_column": "m",
                           "value_column": "v"}, table=pd.DataFrame(rows))
        assert out["html"].index(">Dec<") < out["html"].index(">Jan<")


class TestTileMap:

    def test_a_place_lands_on_its_square(self, registry, regions):
        ctx, out = run_node(registry, "flograph.viz.tile_map",
                            defaults_for("flograph.viz.tile_map"),
                            table=regions)
        assert "5 of 12 squares" in " ".join(ctx.logs)
        assert "Ldn" in out["html"]

    def test_a_square_with_no_data_is_drawn_empty_not_left_out(
            self, registry, regions):
        """A blank square is a fact worth seeing; a missing one is a map
        that looks complete and is not."""
        _, out = run_node(registry, "flograph.viz.tile_map",
                          defaults_for("flograph.viz.tile_map"),
                          table=regions)
        assert "stroke-dasharray" in out["html"]
        assert "7 square(s) with no data" in out["html"]

    def test_a_place_that_is_not_on_the_grid_is_reported(self, registry):
        table = pd.DataFrame({"region": ["London", "Atlantis"],
                              "revenue": [1.0, 2.0]})
        ctx, out = run_node(registry, "flograph.viz.tile_map",
                            defaults_for("flograph.viz.tile_map"),
                            table=table)
        assert "not on the grid: Atlantis" in " ".join(ctx.logs)
        assert "1 not on the map: Atlantis" in out["html"]

    def test_nothing_matching_at_all_is_an_error_not_a_blank_map(
            self, registry):
        table = pd.DataFrame({"region": ["Narnia", "Atlantis"],
                              "revenue": [1.0, 2.0]})
        with pytest.raises(ValueError, match="none of the places"):
            run_node(registry, "flograph.viz.tile_map",
                     defaults_for("flograph.viz.tile_map"), table=table)

    def test_the_us_grid_holds_every_state(self, registry):
        table = pd.DataFrame({"state": ["California", "Texas"],
                              "customers": [10.0, 5.0]})
        ctx, _ = run_node(registry, "flograph.viz.tile_map",
                          {"region_column": "state",
                           "value_column": "customers",
                           "grid": "US states"}, table=table)
        assert "2 of 51 squares" in " ".join(ctx.logs)

    def test_a_custom_grid_is_a_map_of_anything(self, registry):
        table = pd.DataFrame({"depot": ["Ayr", "Bury"], "vans": [4.0, 9.0]})
        _, out = run_node(registry, "flograph.viz.tile_map",
                          {"region_column": "depot", "value_column": "vans",
                           "grid": "Custom",
                           "custom_grid": "Ayr, 0, 0\nBury, 0, 1"},
                          table=table)
        assert "Ayr" in out["html"] and "Bury" in out["html"]

    def test_a_broken_custom_grid_says_which_line(self, registry):
        table = pd.DataFrame({"depot": ["Ayr"], "vans": [4.0]})
        with pytest.raises(ValueError, match="line 1"):
            run_node(registry, "flograph.viz.tile_map",
                     {"region_column": "depot", "value_column": "vans",
                      "grid": "Custom", "custom_grid": "Ayr somewhere"},
                     table=table)

    def test_the_ink_stays_readable_on_both_ends_of_the_ramp(self, registry):
        table = pd.DataFrame({"region": ["London", "Wales"],
                              "revenue": [1000.0, 1.0]})
        _, out = run_node(registry, "flograph.viz.tile_map",
                          defaults_for("flograph.viz.tile_map",
                                       {"ramp": "grey"}), table=table)
        assert "#0b1220" in out["html"]        # dark ink on the light end
        assert "#ffffff" in out["html"]        # light ink on the dark end

    def test_the_legend_is_built_from_the_scale_it_explains(self, registry,
                                                            regions):
        _, out = run_node(registry, "flograph.viz.tile_map",
                          defaults_for("flograph.viz.tile_map"),
                          table=regions)
        assert "linear-gradient" in out["html"]
        assert ">96<" in out["html"] and ">704<" in out["html"]

    def test_duplicate_rows_for_one_place_are_added_up(self, registry):
        table = pd.DataFrame({"region": ["London", "London", "Wales"],
                              "revenue": [10.0, 5.0, 1.0]})
        _, out = run_node(registry, "flograph.viz.tile_map",
                          defaults_for("flograph.viz.tile_map"), table=table)
        assert ">15<" in out["html"]


class TestClickPayload:
    """What the page sends back, and what it does with what it was given."""

    def test_the_selection_is_written_as_json_the_param_can_hold(
            self, registry, regions):
        _, out = run_node(registry, "flograph.viz.waffle",
                          defaults_for("flograph.viz.waffle",
                                       {"on_click": "select many",
                                        "selected": '["London", "Wales"]'}),
                          table=regions)
        assert out["selected"] == ["London", "Wales"]
        assert sorted(out["table"]["region"]) == ["London", "Wales"]

    def test_a_comma_separated_hand_edit_still_works(self, registry, regions):
        _, out = run_node(registry, "flograph.viz.waffle",
                          defaults_for("flograph.viz.waffle",
                                       {"on_click": "select one",
                                        "selected": "London"}),
                          table=regions)
        assert out["selected"] == ["London"]

    def test_the_mode_travels_with_the_page(self, registry, regions):
        _, out = run_node(registry, "flograph.viz.waffle",
                          defaults_for("flograph.viz.waffle",
                                       {"on_click": "select many"}),
                          table=regions)
        assert 'var MODE = "select many"' in out["html"]
        assert json.loads(re.search(r"var PICKED = (\[[^\]]*\]);",
                                    out["html"]).group(1)) == []
