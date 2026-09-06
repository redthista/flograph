"""The Story node and the model under it.

A story is the one visual whose *fallback* is as important as the thing it
does: the document it writes is an illustrated article, and the scrolling is
an upgrade applied on top when there is a viewport to scroll in. So there
are two shapes to check and they are checked separately — the markup that
lands on paper, and the script that turns it into a story on a screen.

What the page looks like was verified by rendering it through the real
report snapshot path and looking at the pictures; a browser in this suite is
what leaves zombie renderers behind, so it stays out of it.
"""
from __future__ import annotations

import html as htmllib
import re

import pandas as pd
import pytest

from flograph.core import NodeRegistry, compile_run, story
from tests.conftest import FakeContext

STORY = "flograph.viz.story"


@pytest.fixture(scope="module")
def registry():
    reg = NodeRegistry()
    reg.load_builtins()
    return reg


def run_node(registry, params=None, **inputs):
    spec = registry.get(STORY)
    settings = spec.default_params()
    settings.update(params or {})
    context = FakeContext(params=settings)
    out = compile_run(spec.source, "test-story")(context, **inputs)
    return context, out


def scene_page(name="one", colour="#123456"):
    """A stand-in for another visual's output: a whole document."""
    return (f"<!doctype html><html><head><style>"
            f"body{{background:{colour}}}</style></head>"
            f"<body><h1>{name} & \"friends\"</h1></body></html>")


_SCENE = re.compile(r"<div class='scene' data-scene='(\d+)'>"
                    r"<iframe [^>]*?srcdoc=\"([^\"]*)\"")


def srcdocs(html):
    """Every scene page, decoded back out of its iframe attribute.

    In document order, which is the order the *story* uses them in — not
    scene order. A scene nobody pointed at goes last.
    """
    return [htmllib.unescape(page) for _, page in _SCENE.findall(html)]


def scenes_in(html):
    """Scene number to the page sealed inside it."""
    return {int(number): htmllib.unescape(page)
            for number, page in _SCENE.findall(html)}


class TestSplitting:
    def test_a_line_of_dashes_ends_a_step(self):
        assert story.split_steps("one\n---\ntwo") == ["one", "two"]

    def test_more_than_three_dashes_still_counts(self):
        assert story.split_steps("one\n-----\ntwo") == ["one", "two"]

    def test_a_trailing_separator_is_not_an_empty_step(self):
        assert story.split_steps("one\n---\n") == ["one"]

    def test_a_doubled_separator_is_not_an_empty_step(self):
        assert story.split_steps("one\n---\n---\ntwo") == ["one", "two"]

    def test_text_with_no_separator_is_one_step(self):
        assert story.split_steps("just this") == ["just this"]

    def test_nothing_is_no_steps(self):
        assert story.split_steps("") == []
        assert story.split_steps("   \n  ") == []

    def test_a_dash_inside_a_line_is_not_a_separator(self):
        assert story.split_steps("a --- b") == ["a --- b"]


class TestSceneMarker:
    def test_it_is_found_and_removed(self):
        assert story.scene_marker("@scene 3\nwords") == ("words", 3)

    def test_no_marker_reads_as_no_opinion(self):
        assert story.scene_marker("words") == ("words", None)

    def test_the_last_one_wins(self):
        assert story.scene_marker("@scene 1\na\n@scene 4\nb")[1] == 4

    def test_it_does_not_split_the_paragraph_it_sat_in(self):
        """The newline goes with the mark, or one paragraph becomes two."""
        text, _ = story.scene_marker("first line\n@scene 2\nsecond line")
        assert story.prose(text).count("<p>") == 1

    def test_it_must_be_alone_on_its_line(self):
        assert story.scene_marker("see @scene 2 there")[1] is None


class TestProse:
    def test_a_heading_is_a_line_not_a_block(self):
        """Nobody leaves a blank line under a heading before writing."""
        out = story.prose("# Title\nThe sentence under it.")
        assert "<h2 class='step-title'>Title</h2>" in out
        assert "<p>The sentence under it.</p>" in out

    def test_two_hashes_and_three_are_smaller(self):
        assert "<h3>Sub</h3>" in story.prose("## Sub")
        assert "<h4>Smaller</h4>" in story.prose("### Smaller")

    def test_a_single_newline_is_a_space(self):
        """Everyone hard-wraps in a small box; honouring it looks ragged."""
        out = story.prose("one line\nand its continuation")
        assert out == "<p>one line and its continuation</p>"

    def test_a_blank_line_starts_a_paragraph(self):
        assert story.prose("one\n\ntwo").count("<p>") == 2

    def test_two_trailing_spaces_force_a_break(self):
        assert "<br>" in story.prose("first  \nsecond")

    def test_a_trailing_backslash_forces_a_break(self):
        assert "<br>" in story.prose("first\\\nsecond")

    def test_emphasis(self):
        out = story.prose("**bold** and *slanted* and `code`")
        assert "<strong>bold</strong>" in out
        assert "<em>slanted</em>" in out
        assert "<code>code</code>" in out

    def test_a_link(self):
        assert '<a href="/x">go</a>' in story.prose("[go](/x)")

    def test_markup_is_left_alone(self):
        """The Steps box is markup, exactly as HTML Template's box is."""
        out = story.prose('<div class="card">mine</div>')
        assert out == '<div class="card">mine</div>'

    def test_nothing_makes_nothing(self):
        assert story.prose("") == ""
        assert story.prose(None) == ""

    def test_an_asterisk_in_the_middle_of_a_word_is_not_emphasis(self):
        assert "<em>" not in story.prose("2*3 and 4*5")


class TestAssigningScenes:
    def test_a_step_that_says_nothing_stays_where_the_story_was(self):
        """Three paragraphs about one chart is the commonest thing a story
        does, and it should need no marks after the first."""
        assert story.assign_scenes([None, None, None], 3) == [1, 1, 1]

    def test_a_step_that_names_one_moves_there(self):
        assert story.assign_scenes([None, 2, None], 3) == [1, 2, 2]

    def test_it_stays_moved(self):
        assert story.assign_scenes([3, None, None], 3) == [3, 3, 3]

    def test_out_of_range_is_clamped_not_raised(self):
        assert story.assign_scenes([9, 0, -4], 3) == [3, 1, 1]

    def test_no_scenes_at_all_is_no_scene(self):
        assert story.assign_scenes([None, 2], 0) == [0, 0]

    def test_no_steps(self):
        assert story.assign_scenes([], 3) == []


class TestStepsFromRows:
    def test_one_step_per_row(self):
        rows = [{"words": "a"}, {"words": "b"}]
        assert story.steps_from_rows(rows, "words") == [("a", None),
                                                        ("b", None)]

    def test_a_blank_cell_is_not_the_word_nan(self):
        """pandas hands a missing text cell over as a float NaN, and str()
        of that is 'nan' — which would read as a step someone wrote."""
        rows = [{"words": float("nan")}]
        assert story.steps_from_rows(rows, "words") == [("", None)]

    def test_the_scene_column_is_read(self):
        rows = [{"words": "a", "scene": 2}]
        assert story.steps_from_rows(rows, "words", "scene")[0][1] == 2

    def test_a_marker_in_the_text_works_too(self):
        rows = [{"words": "@scene 3\na"}]
        assert story.steps_from_rows(rows, "words")[0] == ("a", 3)

    def test_the_column_beats_the_marker(self):
        rows = [{"words": "@scene 3\na", "scene": 1}]
        assert story.steps_from_rows(rows, "words", "scene")[0][1] == 1

    def test_a_blank_scene_cell_leaves_the_marker_alone(self):
        rows = [{"words": "@scene 3\na", "scene": None}]
        assert story.steps_from_rows(rows, "words", "scene")[0][1] == 3

    def test_a_missing_column_is_a_blank_step_not_a_crash(self):
        assert story.steps_from_rows([{"other": 1}], "words") == [("", None)]


class TestAttributeEscaping:
    def test_a_whole_page_survives_the_round_trip(self):
        page = scene_page()
        assert htmllib.unescape(story.attribute(page)) == page

    def test_the_ampersand_goes_first(self):
        """Escaped last, it eats the escapes before it — and the page still
        loads, with &amp;quot; where the quotes were."""
        assert story.attribute('&"') == "&amp;&quot;"

    def test_quotes_cannot_close_the_attribute(self):
        assert '"' not in story.attribute('<a href="x">')


class TestTheTwoLayouts:
    """The article is the document; the story is an upgrade on top of it."""

    def test_the_article_is_the_base_state(self):
        assert ".story{display:block}" in story.CSS
        assert ".stage{display:none}" in story.CSS

    def test_the_scrolling_layout_is_reached_only_through_a_class(self):
        """Every rule that arranges the story is behind `.live`, which only
        the script adds — so a page whose script never ran cannot get a
        half-applied layout."""
        plain = re.sub(r"/\*.*?\*/", "", story.CSS, flags=re.S)
        for rule in plain[:plain.index("@media print{")].split("}"):
            if "position:sticky" not in rule and "display:flex" not in rule:
                continue
            assert ".live" in rule.split("{")[0], rule

    def test_a_missing_viewport_leaves_the_article_alone(self):
        """The report snapshot lays out in a view that was never shown,
        where innerHeight is 0. That is the switch."""
        assert "if (!window.innerHeight) { return; }" in story.SCRIPT

    def test_printing_a_live_page_undoes_the_stage(self):
        printing = story.CSS[story.CSS.index("@media print{"):]
        assert ".story.live{display:block}" in printing
        assert ".story.live .stage{display:none}" in printing

    def test_a_scene_is_loaded_eagerly(self):
        """A scene in the stage never scrolls anywhere — lazily loaded, it
        would fade in blank."""
        assert "loading='eager'" in story.scene_markup("<p>x</p>", 1)


class TestTheNode:
    def test_it_draws_from_the_steps_box(self, registry):
        _, out = run_node(registry, {"steps": "# One\nWords.\n---\n# Two"},
                          scene1=scene_page())
        assert "<h2 class='step-title'>One</h2>" in out["html"]
        assert out["html"].count("class='step'") == 2

    def test_each_scene_becomes_its_own_sealed_frame(self, registry):
        """Six complete pages cannot share one document, so each gets an
        iframe — which also gives it a real viewport of its own."""
        _, out = run_node(registry, {"steps": "a\n---\n@scene 2\nb"},
                          scene1=scene_page("one"), scene2=scene_page("two"))
        pages = srcdocs(out["html"])
        assert len(pages) == 2
        assert pages[0] == scene_page("one")
        assert pages[1] == scene_page("two")

    def test_a_scene_used_twice_is_written_once(self, registry):
        _, out = run_node(registry, {"steps": "a\n---\nb\n---\nc"},
                          scene1=scene_page())
        assert len(srcdocs(out["html"])) == 1

    def test_a_scene_nobody_pointed_at_is_still_in_the_page(self, registry):
        """It was wired on purpose; dropping it looks like a broken port."""
        _, out = run_node(registry, {"steps": "only one step"},
                          scene1=scene_page("a"), scene2=scene_page("b"))
        assert len(srcdocs(out["html"])) == 2

    def test_ports_are_numbered_by_what_is_wired(self, registry):
        """A hole in the middle is far likelier to be an unplugged wire than
        a scene somebody meant to leave blank."""
        context, out = run_node(registry, {"steps": "@scene 2\nb"},
                                scene1=scene_page("a"), scene4=scene_page("d"))
        assert scenes_in(out["html"])[2] == scene_page("d")
        assert any("scene4 is scene 2" in line for line in context.logs)

    def test_the_scenes_run_in_the_order_the_story_uses_them(self, registry):
        """Which is what makes the article read as one: the picture, then
        the words about it. A scene nobody pointed at goes last."""
        _, out = run_node(registry, {"steps": "@scene 2\nb"},
                          scene1=scene_page("a"), scene2=scene_page("b"))
        assert srcdocs(out["html"]) == [scene_page("b"), scene_page("a")]

    def test_a_scene_that_is_not_a_page_is_ignored(self, registry):
        context, out = run_node(registry, {"steps": "a"}, scene1=42)
        assert srcdocs(out["html"]) == []
        assert any("not a page" in line for line in context.logs)

    def test_asking_for_a_scene_that_is_not_wired_is_reported(self, registry):
        context, _ = run_node(registry, {"steps": "@scene 5\na"},
                              scene1=scene_page())
        assert any("not wired" in line for line in context.logs)

    def test_nothing_at_all_says_what_to_do(self, registry):
        _, out = run_node(registry)
        assert "Steps" in out["html"] and "scene 1" in out["html"]

    def test_the_page_is_a_whole_document(self, registry):
        _, out = run_node(registry, {"steps": "a"})
        html = out["html"]
        assert html.startswith("<!doctype html>") and html.endswith("</html>")

    def test_nothing_is_fetched(self, registry):
        """No font link, no script src, no stylesheet — so the card, a
        dashboard tile, a report and somebody else's browser agree."""
        _, out = run_node(registry, {"steps": "a"}, scene1=scene_page())
        html = out["html"]
        assert "<link" not in html
        assert "@import" not in html
        assert not re.search(r'src\s*=\s*"https?:', html)
        assert "cdn" not in html.lower()


class TestFromATable:
    @pytest.fixture
    def table(self):
        return pd.DataFrame({
            "region": ["North", "London"],
            "change": [31.0, -12.0],
            "scene": [1, 2],
            "words": ["# {{region}} led\nUp {{change:+.1f}}%.",
                      "# {{region}} fell\nDown {{change:.1f}}%."],
        })

    def test_one_step_per_row(self, registry, table):
        _, out = run_node(registry, {"text_column": "words"}, steps=table)
        assert out["html"].count("class='step'") == 2

    def test_the_prose_is_a_template_over_its_own_row(self, registry, table):
        """This is what makes a story that rewrites itself when the numbers
        change, rather than one that has to be retyped."""
        _, out = run_node(registry, {"text_column": "words"}, steps=table)
        assert "North led" in out["html"]
        assert "Up +31.0%." in out["html"]
        assert "Down -12.0%." in out["html"]

    def test_the_scene_column_is_used(self, registry, table):
        _, out = run_node(registry,
                          {"text_column": "words", "scene_column": "scene"},
                          steps=table, scene1=scene_page("a"),
                          scene2=scene_page("b"))
        assert re.search(r"class='step' data-scene='2'", out["html"])

    def test_the_widest_text_column_is_the_prose(self, registry, table):
        """The prose is the longest thing in the row; the *first* text
        column would pick the label instead."""
        context, out = run_node(registry, steps=table)
        assert any("prose from words" in line for line in context.logs)

    def test_a_column_that_is_not_there_says_so(self, registry, table):
        with pytest.raises(ValueError, match="nope"):
            run_node(registry, {"text_column": "nope"}, steps=table)
        with pytest.raises(ValueError, match="nope"):
            run_node(registry, {"scene_column": "nope"}, steps=table)

    def test_an_empty_table_falls_back_to_the_steps_box(self, registry):
        _, out = run_node(registry, {"steps": "typed instead"},
                          steps=pd.DataFrame())
        assert "typed instead" in out["html"]

    def test_a_blank_cell_never_draws_the_word_nan(self, registry):
        frame = pd.DataFrame({"words": ["real text here", None]})
        _, out = run_node(registry, {"text_column": "words"}, steps=frame)
        text = " ".join(re.findall(r">([^<>]+)<", out["html"]))
        assert "nan" not in text.lower()


class TestStyle:
    def test_the_style_is_passed_on(self, registry):
        payload = {"tokens": {"theme": "light", "accent": "#ff0000"}}
        _, out = run_node(registry, {"steps": "a"}, style=payload)
        assert out["style"]["tokens"]["accent"] == "#ff0000"

    def test_the_theme_reaches_the_page(self, registry):
        light = {"tokens": {"theme": "light"}}
        _, dark_out = run_node(registry, {"steps": "a"})
        _, light_out = run_node(registry, {"steps": "a"}, style=light)
        assert dark_out["html"] != light_out["html"]

    def test_a_style_shaped_thing_that_is_not_one_is_ignored(self, registry):
        _, out = run_node(registry, {"steps": "a"}, style={"nope": 1})
        assert out["style"]["tokens"] == {}

    def test_the_settings_reach_the_page(self, registry):
        _, out = run_node(registry, {"steps": "a", "prose_width": 44,
                                     "ratio": "1:1", "prose_side": "right"})
        assert "--prose:44%" in out["html"]
        assert "--ratio:1/1" in out["html"]
        assert "class='story prose-left'" not in out["html"]

    def test_the_words_default_to_the_left(self, registry):
        _, out = run_node(registry, {"steps": "a"})
        assert "class='story prose-left'" in out["html"]

    def test_the_progress_bar_can_be_turned_off(self, registry):
        _, on = run_node(registry, {"steps": "a"})
        _, off = run_node(registry, {"steps": "a", "progress": False})
        assert "<div class='live-rail'>" in on["html"]
        assert "<div class='live-rail'>" not in off["html"]
