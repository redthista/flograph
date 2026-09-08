"""More than one decoration in a cell, and somewhere to put it (T1).

Asked for as four things that turned out to be one thing: an icon on the
**right** as well as the left, **two icons at once** (an "OT" mark and then
a green tick), **above / below** as positions, and **pill** styles — a
coloured lozenge around an icon, some text, or the column's own value.

None of it was a drawing problem. `CellStyle` held exactly one
`icon` / `icon_color` pair and `over()` merged two rules with
``icon=self.icon or base.icon``, so a second icon rule could not *add* one
— it could only fail to replace what was there. Every test here is really
one test of that: a cell holds a *list*, each entry knows its own place,
and rules accumulate into it.

The two shapes that were decisions rather than deductions, both taken by
Dan with a real table in front of him:

* **above / below is per-cell**, not table-wide like `wrap`. A rule fires
  on the rows that match it, so only those rows grow.
* **a pill is both**, and which one is decided by whether anything is
  written in it: ``pill green`` wraps the cell's own value, ``pill green
  "OT"`` is a mark of its own standing beside it.
"""
import pytest

pd = pytest.importorskip("pandas")

from flograph.core.table_format import (  # noqa: E402
    DECOR_PLACES, CellStyle, Decoration, Rule, column_stats, evaluate_column,
    for_paper, parse_rules,
)
from flograph.core.table_html import frame_to_html  # noqa: E402

FRAME = pd.DataFrame({
    "name": ["a", "b", "c"],
    "score": [10, 50, 90],
    "status": ["breach", "watch", "ok"],
})


def styles_for(frame, column, text):
    rules = parse_rules(text)
    return evaluate_column(frame[column], rules,
                           column_stats(frame[column]), frame)


def texts(style):
    return [d.text for d in style.decorations]


def places(style):
    return [d.where for d in style.decorations]


class TestTwoRulesBothLandInTheCell:
    """The whole point. Before this, the second rule silently lost."""

    def test_a_second_icon_adds_rather_than_replacing(self):
        got = styles_for(FRAME, "name",
                         'name = a => icon ✱ amber\n'
                         'name = a => icon ✓ green')
        assert texts(got[0]) == ["✱", "✓"]

    def test_the_earlier_rule_keeps_the_earlier_place(self):
        """Reading order, not rule order reversed: the first rule read is
        the leftmost mark, and a later one arrives beside it."""
        got = styles_for(FRAME, "name",
                         'name = a => icon 1 green\n'
                         'name = a => icon 2 green\n'
                         'name = a => icon 3 green')
        assert texts(got[0]) == ["1", "2", "3"]

    def test_rules_that_miss_contribute_nothing(self):
        got = styles_for(FRAME, "name",
                         'name = a => icon ✱ amber\n'
                         'name = b => icon ✓ green')
        assert texts(got[0]) == ["✱"]
        assert texts(got[1]) == ["✓"]

    def test_over_concatenates_and_does_not_lose_either_side(self):
        base = CellStyle(decorations=[Decoration(text="A")])
        top = CellStyle(decorations=[Decoration(text="B")])
        assert [d.text for d in top.over(base).decorations] == ["A", "B"]


class TestWhereItGoes:
    def test_every_place_parses(self):
        for word in ("left", "right", "above", "below", "in"):
            got = styles_for(FRAME, "name", f'name = a => icon ✓ {word}')
            assert places(got[0]) == [word], word

    def test_the_words_people_actually_reach_for(self):
        for word, means in (("over", "above"), ("top", "above"),
                            ("under", "below"), ("bottom", "below"),
                            ("instead", "in"), ("inplace", "in")):
            got = styles_for(FRAME, "name", f'name = a => icon ✓ {word}')
            assert places(got[0]) == [means], word

    def test_a_colour_and_a_place_together_in_either_order(self):
        for rest in ("green right", "right green"):
            got = styles_for(FRAME, "name", f'name = a => icon ✓ {rest}')
            assert places(got[0]) == ["right"]
            assert got[0].decorations[0].color == "#5cb85c"

    def test_absent_means_left_which_is_where_it_always_was(self):
        got = styles_for(FRAME, "name", 'name = a => icon ✓ green')
        assert places(got[0]) == ["left"]

    def test_a_graded_icon_set_can_be_placed_too(self):
        got = styles_for(FRAME, "score", "score icons traffic right")
        assert places(got[0]) == ["right"]

    def test_and_so_can_a_map(self):
        got = styles_for(FRAME, "status",
                         "status iconmap right: breach=✗, ok=✓")
        assert places(got[0]) == ["right"]

    def test_all_four_sides_at_once_on_one_cell(self):
        """Dan's ask in one line: something above, below, left and right of
        the content, all in the same cell."""
        got = styles_for(FRAME, "name",
                         'name = a => icon L left\n'
                         'name = a => icon R right\n'
                         'name = a => icon A above\n'
                         'name = a => icon B below')
        assert dict(zip(places(got[0]), texts(got[0]))) == {
            "left": "L", "right": "R", "above": "A", "below": "B"}

    def test_places_are_the_documented_set(self):
        assert set(DECOR_PLACES) == {"left", "right", "above", "below", "in"}


class TestInPlaceOfTheValue:
    def test_in_takes_the_value_away(self):
        got = styles_for(FRAME, "name", 'name = a => icon ✓ in')
        assert got[0].hide_value is True
        assert places(got[0]) == ["in"]

    def test_only_is_the_other_spelling_of_it(self):
        """`only` predates the places and has to keep working — and has to
        land in the same place, or paper and card would disagree."""
        got = styles_for(FRAME, "status",
                         "status iconmap only: breach=🔥, ok=✅")
        assert got[0].hide_value is True
        assert places(got[0]) == ["in"]

    def test_only_with_a_place_keeps_the_place(self):
        """The two overlap but are not the same thing. `only` takes the
        value away; `in` also says where the format goes instead. So a
        rule that named its place keeps it, and only a rule that named
        none falls back to the middle."""
        got = styles_for(FRAME, "status",
                         "status iconmap only right: breach=✗, ok=✓")
        assert got[0].hide_value is True
        assert places(got[0]) == ["right"]

    def test_a_bar_only_rule_still_hides_without_any_decoration(self):
        got = styles_for(FRAME, "score", "score bar blue only")
        assert got[0].hide_value is True
        assert got[0].decorations == []


class TestPills:
    def test_a_bare_pill_wraps_the_cells_own_value(self):
        got = styles_for(FRAME, "status", 'status = breach => pill red')
        assert got[0].pill == "#5c2b2b"
        assert got[0].decorations == []
        # and it is a lozenge, not a cell fill
        assert got[0].bg is None

    def test_a_pill_with_a_label_stands_beside_the_value(self):
        got = styles_for(FRAME, "status", 'status = breach => pill red "OT"')
        assert got[0].pill is None
        assert texts(got[0]) == ["OT"]
        assert got[0].decorations[0].pill == "#5c2b2b"

    def test_a_labelled_pill_can_be_placed_like_any_other_mark(self):
        got = styles_for(FRAME, "status",
                         'status = breach => pill red "OT" right')
        assert places(got[0]) == ["right"]

    def test_a_pill_and_an_icon_are_two_marks_not_one(self):
        got = styles_for(FRAME, "status",
                         'status = breach => pill amber "OT"\n'
                         'status = breach => icon ✓ green right')
        assert texts(got[0]) == ["OT", "✓"]
        assert places(got[0]) == ["left", "right"]

    def test_a_colormap_can_draw_lozenges_instead_of_flooding_the_cell(self):
        """The category-pill shape a status column wants, and what T4 will
        write into once it picks the colours itself."""
        got = styles_for(FRAME, "status",
                         "status colormap pill: breach=red, ok=green")
        assert got[0].pill == "#5c2b2b"
        assert got[0].bg is None
        assert got[2].pill == "#2e4d33"

    def test_without_pill_a_colormap_still_fills_the_cell(self):
        got = styles_for(FRAME, "status", "status colormap: breach=red")
        assert got[0].bg == "#5c2b2b"
        assert got[0].pill is None

    def test_an_iconmap_pill_makes_the_mapped_colour_the_ground(self):
        """There is no third colour in the map to be both ink and fill, so
        `pill` re-reads the one there is."""
        plain = styles_for(FRAME, "status", "status iconmap: breach=✗ red")
        potted = styles_for(FRAME, "status",
                            "status iconmap pill: breach=✗ red")
        assert plain[0].decorations[0].color == "#d9534f"
        assert plain[0].decorations[0].pill is None
        assert potted[0].decorations[0].pill == "#d9534f"

    def test_a_pill_cannot_be_asked_for_on_a_whole_row(self):
        with pytest.raises(ValueError, match="cannot be combined with 'row'"):
            parse_rules("status = breach => row grey, pill red")


class TestItSurvivesTheStylePort:
    """Rules cross a wire as dicts. A position or a pill that did not
    round-trip would work on the node that declared it and nowhere else."""

    def test_a_place_and_a_pill_come_back(self):
        rule = parse_rules('name = a => pill red "OT" right')[0]
        back = Rule.from_dict(rule.to_dict())
        assert back.glyph_where == "right"
        assert back.as_pill is True
        assert back.glyph == "OT"

    def test_left_is_absence_and_stays_absent(self):
        rule = parse_rules('name = a => icon ✓ green')[0]
        assert "glyph_where" not in rule.to_dict()
        assert Rule.from_dict(rule.to_dict()).glyph_where is None

    def test_a_decoration_round_trips_on_its_own(self):
        d = Decoration(text="OT", color="#fff", pill="#f00", where="below")
        assert Decoration.from_dict(d.to_dict()) == d

    def test_the_old_glyph_colour_pair_still_reads(self):
        """A file written before this list existed stored a bare pair."""
        assert Decoration.from_dict(["✓", "#5cb85c"]) == Decoration(
            text="✓", color="#5cb85c")


class TestOnPaper:
    def test_the_arrangement_survives_to_html(self):
        frame = pd.DataFrame({"name": ["a"]})
        html = frame_to_html(frame, rules=parse_rules(
            'name = a => icon L left\n'
            'name = a => icon R right\n'
            'name = a => icon A above'))
        # look inside the cell: the table's own markup carries letters too
        cell = html[html.index("<tbody>"):]
        # above sits on its own line, and the sides bracket the value
        assert "<br>" in cell
        assert cell.index("A") < cell.index("L") < cell.index("> a <") \
            < cell.index("R")

    def test_a_pill_prints_as_a_coloured_ground(self):
        frame = pd.DataFrame({"status": ["breach"]})
        html = frame_to_html(frame, rules=parse_rules(
            "status colormap pill: breach=red"))
        assert "background-color" in html
        # square-cornered by necessity — Qt's rich text drops border-radius
        assert "border-radius" not in html

    def test_paper_tints_a_pill_and_re_picks_its_ink(self):
        """A solid card colour carrying white text goes pale on paper, and
        the white would go with it."""
        card = CellStyle(pill="#5c2b2b", pill_fg="#ffffff")
        paper = for_paper(card)
        assert paper.pill != card.pill
        assert paper.pill_fg != "#ffffff"

    def test_paper_keeps_an_ink_that_was_asked_for_by_name(self):
        card = CellStyle(decorations=[Decoration(text="✓", color="#5cb85c")])
        assert for_paper(card).decorations[0].color != "#ffffff"


class TestNothingElseMoved:
    def test_a_column_named_for_a_place_still_works(self):
        """The place words are looked for in the keyword's *argument*; the
        column names came off the line before that."""
        frame = pd.DataFrame({"right": [1, 2, 3]})
        got = evaluate_column(frame["right"], parse_rules("right bar blue"),
                              column_stats(frame["right"]), frame)
        assert got[2].bar == pytest.approx(1.0)

    def test_a_cell_with_nothing_on_it_is_still_empty(self):
        assert CellStyle().is_empty()

    def test_a_cell_with_only_a_pill_is_not(self):
        assert not CellStyle(pill="#5c2b2b").is_empty()

    def test_the_first_decoration_still_answers_to_icon(self):
        style = CellStyle(decorations=[Decoration(text="✓", color="#0f0"),
                                       Decoration(text="✗")])
        assert (style.icon, style.icon_color) == ("✓", "#0f0")
