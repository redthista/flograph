"""An icon chosen by a condition, and a colour chosen by a value.

Two gaps that together were reported as "the 20* rule doesn't work". The
glob was never the problem — `20* = 1 => bg green` and `20* icons check`
both parse and both match every year column. What could not be said was
the thing actually wanted, *a green tick where the cell is 1*:

* a `=>` highlight painted bg / fg / bold and nothing else, so there was
  no way to place an icon by a test; and
* `iconmap` demanded a *named* source column, so under a pattern it read
  one column and painted its answer into all of them.

`colormap` is the third piece, and the one that makes a rule map a table
rather than a stack of near-identical condition lines.
"""
import re

import pytest

pd = pytest.importorskip("pandas")

from flograph.core.table_format import (Rule, column_stats,  # noqa: E402
                                        evaluate_column, parse_rules,
                                        rule_summary)
from flograph.core.table_html import frame_to_html          # noqa: E402

YEARS = pd.DataFrame({
    "name": ["a", "b", "c"],
    "2023": [1, 0, 1],
    "2024": [0, 1, 1],
})
STATUS = pd.DataFrame({"status": ["ok", "fail", "unknown"]})


def styles_for(frame, column, text):
    rules = parse_rules(text)
    return evaluate_column(frame[column], rules,
                           column_stats(frame[column]), frame)


def cells(html):
    return re.findall(r"<td[^>]*>(.*?)</td>", html, re.S)


class TestAnIconFromACondition:
    def test_a_tick_where_the_cell_is_one(self):
        """Dan's line, verbatim."""
        got = styles_for(YEARS, "2023", "20* = 1 => icon ✓ green")
        assert [s.icon if s else None for s in got] == ["✓", None, "✓"]

    def test_the_same_rule_reads_each_matching_column(self):
        got = styles_for(YEARS, "2024", "20* = 1 => icon ✓ green")
        assert [s.icon if s else None for s in got] == [None, "✓", "✓"]

    def test_a_column_the_pattern_misses_is_untouched(self):
        html = frame_to_html(YEARS, parse_rules("20* = 1 => icon ✓ green"))
        # the name column's cells carry no icon
        assert cells(html)[0].strip() == "a"

    def test_a_colour_can_be_given_or_left_out(self):
        with_colour = styles_for(YEARS, "2023", "20* = 1 => icon ✓ green")[0]
        without = styles_for(YEARS, "2023", "20* = 1 => icon ✓")[0]
        assert with_colour.icon_color and not without.icon_color

    def test_an_icon_combines_with_a_fill(self):
        style = styles_for(YEARS, "2023",
                           "20* = 1 => icon ✓ green, bg blue, bold")[0]
        assert style.icon == "✓" and style.bg and style.bold

    def test_an_icon_on_a_whole_row_is_refused(self):
        """A row highlight paints every cell; an icon in each of them is
        not what anyone means, so say so rather than doing it."""
        with pytest.raises(ValueError, match="cannot be combined with 'row'"):
            parse_rules("2023 = 1 => row green, icon ✓")

    def test_a_style_that_is_only_an_icon_is_still_a_style(self):
        """The empty-style guard must not reject it."""
        assert parse_rules("2023 = 1 => icon ✓")[0].glyph == "✓"

    def test_it_survives_the_style_port(self):
        rule = parse_rules("2023 = 1 => icon ✓ green")[0]
        back = Rule.from_dict(rule.to_dict())
        assert (back.glyph, back.glyph_color) == (rule.glyph,
                                                  rule.glyph_color)

    def test_it_reaches_a_printed_table(self):
        html = frame_to_html(YEARS, parse_rules("20* = 1 => icon ✓ green"))
        assert html.count("✓") == 4        # 1,1 in 2023 and 1,1 in 2024


class TestAMapThatReadsItsOwnColumn:
    def test_iconmap_with_no_source_reads_the_drawn_column(self):
        got = styles_for(YEARS, "2023", "20* iconmap: 1=✓ green, 0=✗ red")
        assert [s.icon for s in got] == ["✓", "✗", "✓"]

    def test_and_it_really_is_per_column(self):
        got = styles_for(YEARS, "2024", "20* iconmap: 1=✓ green, 0=✗ red")
        assert [s.icon for s in got] == ["✗", "✓", "✓"]

    def test_a_named_source_still_works(self):
        """The spelling that already existed must not have moved."""
        frame = pd.DataFrame({"sla": ["breach", "ok"], "note": ["x", "y"]})
        got = styles_for(frame, "note", "note iconmap sla: breach=✗, ok=✓")
        assert [s.icon for s in got] == ["✗", "✓"]

    def test_a_map_with_no_colon_says_what_is_missing(self):
        with pytest.raises(ValueError, match="to read the column it draws"):
            parse_rules("sla iconmap 1=x")

    def test_only_can_be_written_against_the_colon(self):
        rule = parse_rules("2023 iconmap only: 1=✓")[0]
        assert rule.hide_value and rule.source == ""

    def test_the_summary_says_where_the_icon_came_from(self):
        assert "its own value" in rule_summary(
            parse_rules("2023 iconmap: 1=✓")[0])


class TestAColourFromAValue:
    def test_each_value_takes_its_own_fill(self):
        got = styles_for(STATUS, "status",
                         "status colormap: fail=red, ok=green")
        assert got[0].bg and got[1].bg and got[0].bg != got[1].bg

    def test_a_value_that_is_not_mapped_gets_nothing(self):
        got = styles_for(STATUS, "status",
                         "status colormap: fail=red, ok=green")
        assert got[2] is None

    def test_the_ink_is_computed_from_the_fill(self):
        """A dark preset must not get dark text — the same readable_fg
        every other colour rule uses."""
        got = styles_for(STATUS, "status", "status colormap: ok=red")
        assert got[0].fg and got[0].fg != got[0].bg

    def test_an_ink_can_be_stated(self):
        """And it resolves against the *vivid* presets, not the dark fill
        ones — an ink is text on a block, so `blue` has to be a blue you
        can read rather than a blue background."""
        got = styles_for(STATUS, "status", "status colormap: ok=red blue")
        auto = styles_for(STATUS, "status", "status colormap: ok=red")
        assert got[0].fg == "#4a90d9" != auto[0].fg

    def test_the_british_spelling_works_too(self):
        assert parse_rules("status colourmap: ok=green")[0].mode == "color_map"

    def test_it_can_read_another_column(self):
        frame = pd.DataFrame({"product": ["x", "y"],
                              "severity": ["high", "low"]})
        got = styles_for(frame, "product",
                         "product colourmap severity: high=red, low=green")
        assert got[0].bg != got[1].bg

    def test_only_hides_the_value_and_keeps_the_block(self):
        got = styles_for(STATUS, "status", "status colormap only: ok=green")
        assert got[0].hide_value and got[0].bg

    def test_it_survives_the_style_port(self):
        rule = parse_rules("status colormap: fail=red, ok=green")[0]
        back = Rule.from_dict(rule.to_dict())
        assert back.mode == "color_map" and back.mapping == rule.mapping

    def test_it_reaches_a_printed_table_and_is_tinted_for_paper(self):
        html = frame_to_html(STATUS,
                             parse_rules("status colormap: fail=red"))
        assert "background-color:" in html
        # for_paper lightens the dark card fill rather than printing it raw
        assert "#5c2b2b" not in html

    def test_a_map_with_no_pairs_is_refused(self):
        with pytest.raises(ValueError, match="has no value=colour pairs"):
            parse_rules("status colormap: ")
