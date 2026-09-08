"""Auto-colour a column by category (T4).

Point at a column, say "auto colour", and every distinct value takes its
own colour from a palette. The whole point is that **nothing is named in
advance**, which is exactly what a `colormap` cannot do — a map has to be
written out, and a column of statuses nobody has seen yet cannot be.

Two decisions are load-bearing and are what most of this file tests:

* **Sorted, not first-appearance.** Ordering the categories by the order
  they turn up would repaint the whole column the moment a row arrived at
  the top, and a colour you cannot learn is worse than one nobody picked.
* **A pill by default.** T1 shipped the lozenge, and that is the shape a
  category wants: eight saturated chart colours flooding a column is not
  the same request. `fill` and `text` ask for the other two.

The third is smaller but real: a chart palette's colours are built to be
**grounds**, so half of them are darker than the grid they would have to
be read against as ink — `#1e293b` on `#2a2c33` is 1.05:1, which is not
dim, it is invisible. `on_dark` is what stops `text` mode shipping that.
"""
import pytest

pd = pytest.importorskip("pandas")

from flograph.core.table_format import (  # noqa: E402
    CARD_GROUND, DEFAULT_PALETTE, INK_CONTRAST, PALETTES, auto_colors,
    column_stats, contrast_ratio, evaluate_column, for_paper, on_dark,
    parse_rules, parse_rules_lenient, rule_summary,
)
from flograph.core.table_html import frame_to_html  # noqa: E402

FRAME = pd.DataFrame({
    "job": ["Weld line A", "Paint bay", "Assembly 3", "Packing"],
    "status": ["breach", "watch", "ok", "breach"],
    "site": ["Leeds", "Hull", "Leeds", "York"],
})


def styles_for(frame, column, text):
    rules = parse_rules(text)
    return evaluate_column(frame[column], rules,
                           column_stats(frame[column]), frame)


class TestNothingIsNamedInAdvance:
    def test_every_distinct_value_gets_a_colour(self):
        wheel = auto_colors(["breach", "watch", "ok"])
        assert set(wheel) == {"breach", "watch", "ok"}
        assert len(set(wheel.values())) == 3

    def test_the_same_value_always_gets_the_same_colour(self):
        styles = styles_for(FRAME, "status", "status autocolour")
        # rows 0 and 3 are both "breach"
        assert styles[0].pill == styles[3].pill
        assert styles[0].pill != styles[1].pill

    def test_a_column_of_one_value_spends_one_colour(self):
        wheel = auto_colors(["same"] * 20)
        assert len(wheel) == 1


class TestTheOrderIsSortedNotFirstSeen:
    """The decision that makes an automatic colour learnable."""

    def test_the_row_order_does_not_change_the_colours(self):
        first = auto_colors(["watch", "breach", "ok"])
        later = auto_colors(["ok", "breach", "watch", "breach"])
        assert first == later

    def test_a_new_row_at_the_top_repaints_nothing(self):
        before = auto_colors(["breach", "ok"])
        after = auto_colors(["ok", "breach"])       # the new row arrived first
        assert before == after

    def test_numbers_sort_as_numbers(self):
        assert list(auto_colors([10, 2, 33])) == ["2", "10", "33"]

    def test_a_column_of_mixed_types_falls_back_to_text(self):
        # sorted() would raise on this; a table is not the place to be
        # strict about a column somebody typed by hand
        assert list(auto_colors([1, "a"])) == ["1", "a"]

    def test_a_new_category_only_shifts_the_ones_after_it(self):
        before = auto_colors(["b", "d"])
        after = auto_colors(["b", "c", "d"])
        assert after["b"] == before["b"]


class TestWhatIsNotACategory:
    def test_blanks_and_missing_values_get_no_colour(self):
        wheel = auto_colors([None, "", "   ", float("nan"), "real"])
        assert list(wheel) == ["real"]

    def test_an_empty_cell_is_left_alone(self):
        frame = pd.DataFrame({"status": ["ok", None, "breach"]})
        styles = styles_for(frame, "status", "status autocolour")
        assert styles[1] is None


class TestMoreValuesThanColours:
    def test_the_palette_wraps_rather_than_running_out(self):
        wheel = auto_colors([f"v{i:02d}" for i in range(20)], "cool")
        assert len(wheel) == 20
        assert len(set(wheel.values())) == len(PALETTES["cool"])

    def test_no_value_is_left_uncoloured(self):
        wheel = auto_colors([f"v{i:02d}" for i in range(20)], "cool")
        assert all(wheel.values())


class TestTheThreeShapes:
    def test_a_pill_is_the_default(self):
        rule = parse_rules("status autocolour")[0]
        assert rule.as_pill is True
        assert rule.ink_only is False
        style = styles_for(FRAME, "status", "status autocolour")[0]
        assert style.pill and style.pill_fg
        assert style.bg is None

    def test_fill_floods_the_cell_and_picks_a_readable_ink(self):
        style = styles_for(FRAME, "status", "status autocolour fill")[0]
        assert style.bg and style.fg
        assert style.pill is None

    def test_text_colours_the_value_and_nothing_else(self):
        style = styles_for(FRAME, "status", "status autocolour text")[0]
        assert style.fg
        assert style.bg is None and style.pill is None

    def test_the_word_pill_is_allowed_even_though_it_is_the_default(self):
        assert parse_rules("status autocolour pill")[0].as_pill is True


class TestChoosingThePalette:
    def test_it_defaults_to_the_apps_own(self):
        assert parse_rules("status autocolour")[0].palette is None
        assert auto_colors(["a"]) == auto_colors(["a"], DEFAULT_PALETTE)

    @pytest.mark.parametrize("name", sorted(PALETTES))
    def test_every_chart_palette_can_be_asked_for(self, name):
        rule = parse_rules(f"status autocolour {name}")[0]
        assert rule.palette == name
        assert set(auto_colors(["a", "b"], name)) == {"a", "b"}

    def test_a_palette_nobody_has_says_so_and_lists_the_ones_there_are(self):
        _, errors = parse_rules_lenient("status autocolour neon")
        assert errors and "neon" in errors[0]
        assert "vivid" in errors[0]

    def test_an_unknown_palette_at_evaluation_falls_back_rather_than_raising(self):
        # the parser is the gate; the evaluator is reached by a style that
        # crossed a port and must not take the table down
        assert auto_colors(["a"], "neon") == auto_colors(["a"])


class TestReadingAnotherColumn:
    def test_by_clause_takes_the_categories_from_the_other_column(self):
        styles = styles_for(FRAME, "job", "job autocolour by site")
        # rows 0 and 2 are different jobs on the same site
        assert styles[0].pill == styles[2].pill

    def test_without_it_the_column_decides_its_own(self):
        styles = styles_for(FRAME, "job", "job autocolour")
        assert styles[0].pill != styles[2].pill

    def test_a_source_the_table_does_not_have_paints_nothing(self):
        styles = styles_for(FRAME, "job", "job autocolour by nosuchcolumn")
        assert styles == [None] * len(FRAME)


class TestInkHasToClearTheGrid:
    """A palette colour is built to be a ground. As ink it has to be lifted
    off the grid first, or `text` mode ships something invisible."""

    @pytest.mark.parametrize("name", sorted(PALETTES))
    def test_every_colour_is_legible_as_ink(self, name):
        for colour in PALETTES[name]:
            assert (contrast_ratio(on_dark(colour), CARD_GROUND)
                    >= INK_CONTRAST - 0.01), colour

    def test_the_worst_case_really_was_invisible_before(self):
        # #1e293b against #2a2c33 — this is the case that justifies on_dark
        assert contrast_ratio("#1e293b", CARD_GROUND) < 1.1
        assert contrast_ratio(on_dark("#1e293b"), CARD_GROUND) >= INK_CONTRAST

    def test_a_colour_that_already_reads_is_left_exactly_as_it_is(self):
        assert on_dark("#ffffff") == "#ffffff"

    def test_it_lifts_no_further_than_it_has_to(self):
        lifted = on_dark("#1e293b")
        assert lifted != "#e5e7eb"          # not just given up on and whited

    def test_only_the_text_shape_is_lifted(self):
        # a fill keeps its palette colour outright — it is a ground, which
        # is what the colour was built to be
        fill = styles_for(FRAME, "status", "status autocolour fill")[0]
        assert fill.bg in PALETTES[DEFAULT_PALETTE]


class TestItSurvivesTheStylePort:
    @pytest.mark.parametrize("line", [
        "status autocolour",
        "status autocolour vivid",
        "status autocolour earth fill",
        "status autocolour cool text",
        "status autocolour by site",
        "status autocolour vivid fill by site only",
    ])
    def test_a_rule_round_trips_through_a_dict(self, line):
        from flograph.core.table_format import Rule
        rule = parse_rules(line)[0]
        assert Rule.from_dict(rule.to_dict()) == rule

    def test_the_manager_can_describe_it(self):
        text = rule_summary(parse_rules("status autocolour vivid fill")[0])
        assert "auto colour" in text and "vivid" in text

    @pytest.mark.parametrize("spelling", [
        "autocolour", "autocolor", "auto-colour", "auto-color"])
    def test_all_four_spellings_mean_the_same_rule(self, spelling):
        assert parse_rules(f"status {spelling}")[0].mode == "auto_color"

    def test_a_bare_auto_is_not_a_keyword(self):
        # `region width auto` must stay a width rule — the keyword scan
        # runs right-to-left, so a bare `auto` would swallow it
        assert parse_rules("region width auto")[0].mode == "column_width"


class TestOnPaper:
    def test_a_pill_prints_with_its_colour_tinted_for_white(self):
        html = frame_to_html(FRAME, rules=parse_rules("status autocolour"),
                             paper=True)
        body = html[html.index("<tbody>"):]
        assert "background-color" in body
        assert "breach" in body

    def test_a_fill_prints_as_a_cell_background(self):
        html = frame_to_html(FRAME,
                             rules=parse_rules("status autocolour fill"),
                             paper=True)
        body = html[html.index("<tbody>"):]
        assert "<td style=\"background-color" in body

    def test_ink_lifted_for_the_card_is_darkened_again_for_the_page(self):
        style = styles_for(FRAME, "status", "status autocolour cool text")[0]
        printed = for_paper(style)
        assert printed.fg != style.fg


class TestNothingElseMoved:
    """The keyword table grew, and the keyword scan runs right-to-left over
    every token on the line. That is the sort of change that breaks a rule
    it has nothing to do with."""

    @pytest.mark.parametrize("line,mode", [
        ("status colormap: breach=red, ok=green", "color_map"),
        ("status iconmap: breach=x, ok=y", "icon_map"),
        ("score bar blue", "data_bar"),
        ("score scale green", "color_scale"),
        ("score icons traffic", "icons"),
        ("job width 150", "column_width"),
        ("job align centre", "align"),
        ("job label \"Job name\"", "header_label"),
        ("score format ,.0f", "number_format"),
        ("wrap", "wrap"),
        ("score sort desc", "sort"),
    ])
    def test_the_rules_that_were_there_still_mean_what_they_did(self, line, mode):
        assert parse_rules(line)[0].mode == mode

    def test_a_colormap_still_needs_its_values_named(self):
        _, errors = parse_rules_lenient("status colormap:")
        assert errors

    def test_a_column_actually_called_autocolour_still_works(self):
        # the keyword search runs on tokens, and a column name sits to the
        # left of the keyword — so this is a width rule on an oddly-named
        # column, not two keywords fighting
        assert parse_rules("autocolour width 90")[0].columns == ["autocolour"]
