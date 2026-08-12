"""Idea A4: per-embed sizing — `![[chart|width=50%]]`.

The question that produced it: a title, a paragraph and a chart, where the
chart doesn't fit in what's left of the page and so starts a new one,
leaving half a page empty. Sizing the chart is the answer Qt can actually
give; making it *shrink itself* into the space left is chunk B's, via CSS.

The syntax had room because embeds already split on "|" for the port. A
segment with an "=" in it is an option and a bare one is the port, which is
what lets `![[c|width=50%]]` skip the port without a placeholder.
"""
import re

import pytest

from flograph.core.report import EMBED_OPTIONS, find_embeds, parse_options
from flograph.ui.report.render import FIGURE_WIDTH, render_body


@pytest.fixture(autouse=True)
def _app(qapp):
    return qapp


@pytest.fixture
def figure():
    matplotlib = pytest.importorskip("matplotlib")
    matplotlib.use("Agg")
    from matplotlib.figure import Figure
    fig = Figure(figsize=(6, 3))
    fig.add_subplot(111).plot([1, 2, 3])
    return fig


def render(body, value):
    rendered = render_body(body, lambda ref, port: (value, "", ""))
    widths = [int(w) for w in
              re.findall(r'<img[^>]*width="(\d+)"',
                         rendered.document.toHtml())]
    return widths, rendered.problems


class TestTheSyntax:

    def test_a_bare_segment_is_the_port(self):
        assert parse_options("|scores") == ("scores", {}, [])

    def test_a_segment_with_an_equals_is_an_option(self):
        assert parse_options("|width=50%") == ("", {"width": "50%"}, [])

    def test_a_port_and_an_option_together(self):
        assert parse_options("|scores|width=50%") \
            == ("scores", {"width": "50%"}, [])

    def test_order_does_not_matter(self):
        assert parse_options("|width=50%|scores") \
            == ("scores", {"width": "50%"}, [])

    def test_whitespace_is_forgiven(self):
        assert parse_options("|  scores  |  width = 50%  ") \
            == ("scores", {"width": "50%"}, [])

    def test_an_unknown_option_is_kept_to_be_reported(self):
        assert parse_options("|widht=50%") == ("", {}, ["widht=50%"])

    def test_a_second_bare_segment_is_not_a_second_port(self):
        assert parse_options("|scores|extra") == ("scores", {}, ["extra"])

    def test_nothing_at_all(self):
        assert parse_options("") == ("", {}, [])

    def test_the_option_list_is_closed(self):
        """A closed set is what makes a typo reportable at all."""
        assert EMBED_OPTIONS == ("width",)


class TestParsingInPlace:

    def test_a_plain_embed_still_parses(self):
        found = find_embeds("![[Sales]]")
        assert (found[0].ref, found[0].port, found[0].options) \
            == ("Sales", "", {})

    def test_a_port_still_parses(self):
        assert find_embeds("![[Model|scores]]")[0].port == "scores"

    def test_a_width_parses(self):
        embed = find_embeds("![[Chart|width=50%]]")[0]
        assert embed.ref == "Chart" and embed.port == ""
        assert embed.options == {"width": "50%"}

    def test_a_label_with_spaces_and_a_width(self):
        embed = find_embeds("![[Sales by Region|width=60%]]")[0]
        assert embed.ref == "Sales by Region"
        assert embed.options == {"width": "60%"}

    def test_two_embeds_on_a_line_keep_their_own_options(self):
        first, second = find_embeds("![[a|width=30%]] and ![[b|width=70%]]")
        assert first.options == {"width": "30%"}
        assert second.options == {"width": "70%"}

    def test_it_is_still_not_a_markdown_image(self):
        assert find_embeds("![alt](path.png) and [[a wiki link]]") == []


class TestSizing:

    def test_no_width_is_the_page_width(self, figure):
        widths, problems = render("![[c]]", figure)
        assert widths == [FIGURE_WIDTH] and problems == []

    def test_a_percentage_is_of_the_text_column(self, figure):
        """Of the *available* width, not of the image's natural size: "half
        the page" is what someone fitting a chart under a heading means, and
        it is the only reading that gives two different charts the same
        answer."""
        widths, problems = render("![[c|width=50%]]", figure)
        assert widths == [FIGURE_WIDTH // 2] and problems == []

    def test_an_absolute_width_is_points(self, figure):
        widths, _ = render("![[c|width=280]]", figure)
        assert widths == [280]

    def test_pt_may_be_spelled_out(self, figure):
        widths, _ = render("![[c|width=280pt]]", figure)
        assert widths == [280]

    def test_a_width_applies_to_one_embed_only(self, figure):
        """The next chart must come back to the page width — a width that
        leaked would silently shrink the rest of the report."""
        widths, _ = render("![[c|width=40%]]\n\n![[c]]\n", figure)
        assert widths == [int(FIGURE_WIDTH * 0.4), FIGURE_WIDTH]

    def test_a_silly_width_is_floored(self, figure):
        widths, _ = render("![[c|width=1%]]", figure)
        assert widths[0] >= 40

    def test_a_nonsense_width_is_reported_not_ignored(self, figure):
        widths, problems = render("![[c|width=wide]]", figure)
        assert widths == [FIGURE_WIDTH]
        assert problems and "not a width" in problems[0]

    def test_a_typo_in_the_option_name_is_reported(self, figure):
        _widths, problems = render("![[c|widht=50%]]", figure)
        assert problems and "widht=50%" in problems[0]

    def test_a_width_on_a_list_sizes_every_chart(self, figure):
        widths, _ = render("![[c|width=50%]]", [figure, figure])
        assert widths == [FIGURE_WIDTH // 2] * 2
