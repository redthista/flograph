"""The arithmetic behind the drawn-in-Python visuals.

`core.svgplot` and `core.tilegrid` hold the parts of a waffle, a slope, a
bump chart and a tile map that are worth testing without a picture in the
way: how a hundred squares are shared out, which ink reads on which fill,
where a label goes when two want the same place, and which square a place
name lands on.
"""
from __future__ import annotations

import pytest

from flograph.core import svgplot, tilegrid


class TestAllocate:
    """A waffle's squares. The invariant is that they can be counted."""

    def test_the_squares_always_come_to_the_number_asked_for(self):
        for values in ([50, 30, 20], [1, 1, 1], [7, 3], [1000, 1, 1],
                       [0.1, 0.2, 0.7], [5]):
            assert sum(svgplot.allocate(values, 100)) == 100

    def test_an_even_split_is_exact(self):
        assert svgplot.allocate([50, 30, 20], 100) == [50, 30, 20]

    def test_a_third_each_still_adds_up(self):
        """Three thirds of a hundred is the case naive rounding gets wrong."""
        assert svgplot.allocate([1, 1, 1], 100) == [34, 33, 33]

    def test_a_category_too_small_to_round_to_one_still_gets_a_square(self):
        """"Too small to see" and "not there" have to look different."""
        counts = svgplot.allocate([1000, 1, 1], 100)
        assert counts == [98, 1, 1]

    def test_the_square_is_taken_from_the_biggest_holding(self):
        counts = svgplot.allocate([1000, 500, 1], 100)
        assert counts[2] == 1
        assert sum(counts) == 100
        assert counts[0] > counts[1] > counts[2]

    def test_a_category_with_nothing_gets_nothing(self):
        assert svgplot.allocate([0, 5], 10) == [0, 10]

    def test_more_categories_than_squares_does_not_loop_for_ever(self):
        counts = svgplot.allocate([1] * 20, 10)
        assert sum(counts) == 10

    def test_no_values_at_all_is_no_squares(self):
        assert svgplot.allocate([], 100) == []
        assert svgplot.allocate([0, 0], 100) == [0, 0]


class TestColour:

    def test_three_digit_hex_is_the_same_as_six(self):
        assert svgplot.rgb("#fff") == svgplot.rgb("#ffffff") == (255, 255, 255)

    def test_a_colour_that_is_not_one_says_so(self):
        with pytest.raises(ValueError, match="not a hex colour"):
            svgplot.rgb("nearly-blue")

    def test_halfway_between_black_and_white_is_grey(self):
        assert svgplot.mix("#000000", "#ffffff", 0.5) == "#808080"

    def test_a_ramp_lands_on_its_own_stops(self):
        stops = ["#000000", "#ff0000", "#ffffff"]
        assert svgplot.ramp(stops, 0.0) == "#000000"
        assert svgplot.ramp(stops, 0.5) == "#ff0000"
        assert svgplot.ramp(stops, 1.0) == "#ffffff"

    def test_a_one_colour_ramp_is_that_colour(self):
        assert svgplot.ramp(["#123456"], 0.7) == "#123456"

    def test_dark_ink_goes_on_a_light_fill_and_light_on_a_dark_one(self):
        assert svgplot.readable_on("#fde047") == "#0b1220"
        assert svgplot.readable_on("#1e3a8a") == "#ffffff"

    def test_a_mid_tone_takes_dark_ink(self):
        """A label merely legible is not good enough on top of its number."""
        assert svgplot.readable_on("#94a3b8") == "#0b1220"

    def test_a_series_keeps_its_colour_when_another_disappears(self):
        palette = ["#111111", "#222222", "#333333"]
        both = svgplot.series_colours(["a", "b", "c"], palette)
        without_b = svgplot.series_colours(["a", "c"], palette)
        assert both["a"] == without_b["a"]
        assert both["c"] != without_b["c"]      # first-seen, so c moves up

    def test_the_nth_colour_wraps_round(self):
        """`cycle` is the plain one, for a node that just wants the next
        colour and does not care about collisions."""
        palette = ["#111111", "#222222"]
        assert svgplot.cycle(palette, 0) == "#111111"
        assert svgplot.cycle(palette, 3) == "#222222"
        with pytest.raises(ValueError, match="empty palette"):
            svgplot.cycle([], 0)

    def test_past_the_palette_the_colours_are_shaded_not_repeated(self):
        """Twelve regions against eight colours would give two of them the
        same indigo, and then the legend cannot tell you which is which."""
        names = [str(i) for i in range(20)]
        colours = svgplot.series_colours(names, ["#2563eb", "#10b981",
                                                 "#f59e0b", "#ef4444"])
        assert len(set(colours.values())) == 20

    def test_the_first_lap_is_the_palette_exactly(self):
        palette = ["#111111", "#222222"]
        colours = svgplot.series_colours(list("ab"), palette)
        assert list(colours.values()) == palette

    def test_an_empty_palette_is_an_error_not_a_blank_chart(self):
        with pytest.raises(ValueError, match="empty palette"):
            svgplot.series_colours(["a"], [])


class TestNumbers:

    def test_a_whole_number_loses_its_decimal_point(self):
        assert svgplot.num(3.0) == "3"
        assert svgplot.num(3.14159) == "3.14"

    def test_text_and_blanks_are_not_numbers(self):
        for value in (None, "", "north", float("nan"), True):
            assert svgplot.to_number(value) is None

    def test_a_number_written_as_text_is_a_number(self):
        assert svgplot.to_number("12.5") == 12.5

    def test_an_empty_extent_is_not_an_error(self):
        assert svgplot.extent([]) == (0.0, 0.0)
        assert svgplot.extent(["a", None]) == (0.0, 0.0)

    def test_every_value_the_same_sits_in_the_middle(self):
        """Not at the empty end of the ramp: one flat value is one shade."""
        assert svgplot.position(5, 5, 5) == 0.5

    def test_a_value_outside_the_bounds_is_clamped(self):
        assert svgplot.position(20, 0, 10) == 1.0
        assert svgplot.position(-5, 0, 10) == 0.0


class TestRanking:

    def test_the_biggest_is_first(self):
        rows = [{"p": "Q1", "v": 3}, {"p": "Q1", "v": 9}, {"p": "Q1", "v": 5}]
        assert svgplot.rank_within(rows, group="p", value="v") == {1: 1, 2: 2,
                                                                  0: 3}

    def test_lowest_first_turns_it_round(self):
        rows = [{"p": "Q1", "v": 3}, {"p": "Q1", "v": 9}]
        ranks = svgplot.rank_within(rows, group="p", value="v",
                                    highest_first=False)
        assert ranks == {0: 1, 1: 2}

    def test_each_period_is_ranked_on_its_own(self):
        rows = [{"p": "Q1", "v": 1}, {"p": "Q2", "v": 100}]
        assert svgplot.rank_within(rows, group="p", value="v") == {0: 1, 1: 1}

    def test_a_tie_shares_a_place(self):
        rows = [{"p": "Q1", "v": 5}, {"p": "Q1", "v": 5}, {"p": "Q1", "v": 1}]
        ranks = svgplot.rank_within(rows, group="p", value="v")
        assert ranks[0] == ranks[1] == 1
        assert ranks[2] == 3          # the tie used up two places

    def test_a_row_with_no_number_has_no_place_at_all(self):
        """Not reporting is not the same as coming last."""
        rows = [{"p": "Q1", "v": 5}, {"p": "Q1", "v": None}]
        assert svgplot.rank_within(rows, group="p", value="v") == {0: 1}


class TestSpread:
    """Labels nudged apart — what stops a slope graph being a smear."""

    def test_labels_that_do_not_collide_are_left_alone(self):
        assert svgplot.spread([10, 60, 90], 14, 0, 100) == [10, 60, 90]

    def test_two_labels_wanting_one_place_are_separated(self):
        out = svgplot.spread([50, 50], 14, 0, 100)
        assert out[1] - out[0] == pytest.approx(14)

    def test_the_order_is_kept(self):
        out = svgplot.spread([11, 10, 10.5], 14, 0, 100)
        assert out[1] < out[2] < out[0]

    def test_a_run_at_the_bottom_is_pushed_back_inside(self):
        out = svgplot.spread([95, 96, 97, 98], 14, 0, 100)
        assert max(out) <= 100
        assert min(out) >= 0
        assert all(b - a >= 14 - 1e-9 for a, b in zip(sorted(out),
                                                      sorted(out)[1:]))

    def test_more_labels_than_room_shares_the_space_out(self):
        out = svgplot.spread([50] * 6, 40, 0, 100)
        assert min(out) >= 0 and max(out) <= 100 + 1e-6
        assert out == sorted(out)

    def test_nothing_to_place_is_not_an_error(self):
        assert svgplot.spread([], 14, 0, 100) == []


class TestPaths:

    def test_a_curve_starts_and_ends_where_it_should(self):
        path = svgplot.smooth_path([(0, 0), (10, 10), (20, 0)])
        assert path.startswith("M 0 0")
        assert path.endswith("20 0")
        assert "C" in path

    def test_no_tension_gives_straight_lines(self):
        assert svgplot.smooth_path([(0, 0), (10, 10)], 0) == "M 0 0 L 10 10"

    def test_one_point_is_just_a_move(self):
        assert svgplot.smooth_path([(4, 5)]) == "M 4 5"

    def test_no_points_is_an_empty_path(self):
        assert svgplot.smooth_path([]) == ""


class TestMarkup:

    def test_a_label_too_long_is_cut_and_says_so(self):
        assert svgplot.shorten("Yorkshire and The Humber", 10) == "Yorkshire…"
        assert svgplot.shorten("short", 10) == "short"

    def test_the_svg_scales_rather_than_fixing_its_size(self):
        """A viewBox and no width/height is what lets one drawing suit a
        card, a tile and a printed page."""
        tag = svgplot.svg_open(100, 50)
        assert "viewBox='0 0 100 50'" in tag
        assert "width=" not in tag and "height=" not in tag

    def test_a_click_handler_only_appears_when_a_click_does_something(self):
        assert svgplot.click_attr("North", "nothing") == ""
        assert "pick(" in svgplot.click_attr("North", "select one")

    def test_the_class_is_not_in_the_click_attribute(self):
        """Two `class` attributes on one tag and the browser drops one."""
        assert "class" not in svgplot.click_attr("North", "select one")
        assert svgplot.hit_class("select one") == " hit"
        assert svgplot.hit_class("nothing") == ""

    def test_a_name_with_a_quote_in_it_cannot_break_out(self):
        attr = svgplot.click_attr('North "one"', "select one")
        assert '"North "one""' not in attr
        assert "&quot;" in attr

    def test_a_legend_key_carries_its_colour_and_note(self):
        html = svgplot.legend([("North", "#2563eb", "40%")])
        assert "background:#2563eb" in html
        assert "North" in html and "40%" in html

    def test_the_keys_not_picked_are_dimmed(self):
        html = svgplot.legend([("North", "#111111", ""),
                               ("South", "#222222", "")],
                              "select one", ["North"])
        assert html.count("key off") == 1

    def test_no_entries_is_no_legend(self):
        assert svgplot.legend([]) == ""

    def test_a_ramp_legend_is_built_from_the_same_stops(self):
        html = svgplot.ramp_legend(["#000000", "#ffffff"], "0", "100")
        assert "#000000, #ffffff" in html
        assert ">0<" in html and ">100<" in html


class TestChartPage:

    @pytest.fixture
    def tokens(self):
        from flograph.core import visual_style

        return visual_style.tokens(None)

    def test_the_page_carries_everything_it_needs(self, tokens):
        """No script src, no stylesheet href, no font link: it has to draw
        the same from a file:// URL with the app closed."""
        page = svgplot.chart_page("<svg></svg>", tokens, title="T")
        assert "<script src" not in page
        assert "href=" not in page
        assert "cdn" not in page.lower()

    def test_the_height_chain_starts_at_a_viewport_unit(self, tokens):
        """A percentage resolves to zero inside a report's print-to-PDF, and
        the drawing collapses or is pushed to a page of its own."""
        page = svgplot.chart_page("<svg></svg>", tokens)
        assert "100vh" in page

    def test_the_svg_is_a_block(self, tokens):
        """Inline, its descender space overflows the card and leaves a
        scrollbar that steals width for ever."""
        assert "svg{display:block" in svgplot.chart_page("", tokens).replace(
            " > svg{display:block", "svg{display:block")

    def test_a_title_is_escaped(self, tokens):
        page = svgplot.chart_page("", tokens, title="Sales <b>Q3</b>")
        assert "<b>Q3</b>" not in page
        assert "&lt;b&gt;" in page

    def test_no_click_handler_when_nothing_is_clickable(self, tokens):
        assert "flograph.select" not in svgplot.chart_page("", tokens)
        assert "flograph.select" in svgplot.chart_page(
            "", tokens, mode="select one")

    def test_the_click_handler_survives_having_no_flograph(self, tokens):
        """The page is meant to be saved out and opened anywhere."""
        page = svgplot.chart_page("", tokens, mode="select one")
        assert "window.flograph && flograph.select" in page


class TestTileGrid:

    def test_every_built_in_grid_parses(self):
        assert set(tilegrid.GRIDS) == {"UK regions", "UK nations",
                                       "US states"}
        for cells in tilegrid.GRIDS.values():
            assert cells
            assert all(isinstance(v, tuple) and len(v) == 2
                       for v in cells.values())

    def test_no_two_places_share_a_square(self):
        for name, cells in tilegrid.GRIDS.items():
            assert len(set(cells.values())) == len(cells), name

    def test_every_state_and_dc_is_on_the_us_grid(self):
        states = ("AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME "
                  "MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND OH OK OR PA "
                  "RI SC SD TN TX UT VT VA WA WV WI WY DC").split()
        assert set(tilegrid.GRIDS["US states"]) == set(states)
        assert len(states) == 51

    def test_every_uk_region_is_on_the_uk_grid(self):
        assert len(tilegrid.GRIDS["UK regions"]) == 12

    def test_the_grid_is_the_shape_of_the_country(self):
        """Scotland above England, Cornwall below it — if this ever fails
        the picture has stopped being a map."""
        cells = tilegrid.GRIDS["UK regions"]
        assert cells["SCO"][0] < cells["NW"][0] < cells["WM"][0]
        assert cells["WM"][0] < cells["SW"][0]
        assert cells["WAL"][1] < cells["EE"][1]        # Wales west of East

    def test_a_place_is_found_by_its_code_or_its_name(self):
        cells = tilegrid.GRIDS["UK regions"]
        for spelling in ("YH", "yh", "Yorkshire and The Humber",
                         "yorkshire & the humber", "Yorks and Humber"):
            assert tilegrid.lookup(spelling, cells, "UK regions") == "YH"

    def test_a_place_that_is_not_there_is_none_not_a_guess(self):
        cells = tilegrid.GRIDS["UK regions"]
        assert tilegrid.lookup("Atlantis", cells, "UK regions") is None
        assert tilegrid.lookup("", cells, "UK regions") is None

    def test_washington_the_state_is_not_washington_dc(self):
        cells = tilegrid.GRIDS["US states"]
        assert tilegrid.lookup("Washington", cells, "US states") == "WA"
        assert tilegrid.lookup("Washington DC", cells, "US states") == "DC"
        assert tilegrid.lookup("District of Columbia", cells,
                               "US states") == "DC"

    def test_a_custom_grid_is_three_columns_of_text(self):
        cells = tilegrid.parse_custom("North, 0, 1\nWest,1,0\n# a note\n")
        assert cells == {"North": (0, 1), "West": (1, 0)}

    def test_a_custom_grid_may_use_tabs_or_wide_spaces(self):
        assert tilegrid.parse_custom("North\t0\t1") == {"North": (0, 1)}
        assert tilegrid.parse_custom("New York   0   1") == {
            "New York": (0, 1)}

    def test_a_broken_custom_line_says_which_line(self):
        with pytest.raises(tilegrid.GridError, match="line 2"):
            tilegrid.parse_custom("North, 0, 0\nSouth, over there")

    def test_a_custom_row_must_be_a_number(self):
        with pytest.raises(tilegrid.GridError, match="whole numbers"):
            tilegrid.parse_custom("North, first, 0")

    def test_an_empty_custom_grid_says_so(self):
        with pytest.raises(tilegrid.GridError, match="empty"):
            tilegrid.parse_custom("   \n# nothing here\n")

    def test_an_unknown_grid_lists_the_ones_there_are(self):
        with pytest.raises(tilegrid.GridError, match="UK regions"):
            tilegrid.grid("Narnia")

    def test_the_bounds_cover_every_tile(self):
        down, across = tilegrid.bounds(tilegrid.GRIDS["US states"].values())
        assert (down, across) == (8, 12)
        assert tilegrid.bounds([]) == (0, 0)
