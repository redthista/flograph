"""Idea A4: per-embed sizing — `![[chart|width=50%]]`.

The question that produced it: a title, a paragraph and a chart, where the
chart doesn't fit in what's left of the page and so starts a new one,
leaving half a page empty. Sizing the chart is the answer Qt can actually
give; making it *shrink itself* into the space left needs CSS, and is
shelved with the HTML export (ideas_archived.md item 8).

The syntax had room because embeds already split on "|" for the port. A
segment with an "=" in it is an option and a bare one is the port, which is
what lets `![[c|width=50%]]` skip the port without a placeholder.
"""
import re

import pytest

from flograph.core.report import (EMBED_FLAGS, EMBED_OPTIONS, find_embeds,
                                  parse_options)
from flograph.ui.report.render import FIGURE_WIDTH, parse_aspect, render_body


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
        assert EMBED_OPTIONS == ("width", "ratio", "height", "scale",
                                 "rows")
        assert EMBED_FLAGS == ("fit",)

    def test_a_bare_flag_is_recognised_not_taken_as_the_port(self):
        assert parse_options("|fit") == ("", {"fit": True}, [])

    def test_a_flag_sits_alongside_the_port(self):
        assert parse_options("|scores|fit") == ("scores", {"fit": True}, [])

    def test_a_flag_is_case_insensitive(self):
        assert parse_options("|FIT") == ("", {"fit": True}, [])

    def test_ratio_and_scale_parse_as_options(self):
        assert parse_options("|ratio=16:9|scale=2") \
            == ("", {"ratio": "16:9", "scale": "2"}, [])


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


# --------------------------------------------------------------- tables

PAGE_HEIGHT = 700
#: Enough prose to push what follows to the bottom of the first page.
FILLER = "\n\n".join(
    f"Paragraph {i}. " + "Words to push the table down the page. " * 6
    for i in range(6))


@pytest.fixture
def frame():
    pd = pytest.importorskip("pandas")
    return pd.DataFrame({"region": [f"row {i}" for i in range(14)],
                         "revenue": [100000 + i * 7919 for i in range(14)]})


def table_render(body, frame, page_height=None):
    return render_body(body, lambda ref, port: (frame, "", ""),
                       image_width=510, page_height=page_height)


def table_shape(rendered, page_height=PAGE_HEIGHT):
    """`(rows drawn, height, room left on its page)` for the first table."""
    from PySide6.QtCore import QSizeF
    from PySide6.QtGui import QTextTable

    document = rendered.document
    document.setPageSize(QSizeF(510, page_height))
    layout = document.documentLayout()
    for child in document.rootFrame().childFrames():
        if isinstance(child, QTextTable):
            rect = layout.frameBoundingRect(child)
            return (child.rows() - 1, rect.height(),
                    page_height - (rect.top() % page_height))
    raise AssertionError("no table in the rendered document")


class TestATableTakesThePipeOptions:
    """`width` and `rows` always worked. `scale`, `height` and `fit` used to
    be refused as chart-only — a table reads each of them its own way."""

    def test_scale_sets_the_text_size(self, frame):
        html = table_render("![[t|scale=0.7]]", frame).document.toHtml()
        assert "font-size:7.7pt" in html.replace(" ", "")

    def test_scale_is_not_refused_as_chart_only(self, frame):
        assert table_render("![[t|scale=0.7]]", frame).problems == []

    def test_a_bigger_scale_works_too(self, frame):
        """A chart's `scale` only ever sharpens; a table's goes both ways,
        because the reason to scale text is to change how much fits."""
        html = table_render("![[t|scale=1.5]]", frame).document.toHtml()
        assert "font-size:16.5pt" in html.replace(" ", "")

    def test_height_becomes_a_budget_of_rows(self, frame):
        tall = table_shape(table_render("![[t]]", frame))
        short = table_shape(table_render("![[t|height=120]]", frame))
        assert short[0] < tall[0]
        assert short[1] <= 120

    def test_the_height_budget_covers_the_note_as_well(self, frame):
        """The "showing N of M rows" line sits outside the table and so
        outside what was measured, but it is still part of what the embed
        takes off the page — a budget that ignored it would overrun."""
        budget = 120
        _rows, height, _room = table_shape(
            table_render(f"![[t|height={budget}]]", frame))
        plain = table_shape(table_render("![[t|rows=1]]", frame))
        one_row = plain[1] / 2          # header + one row, so half each
        assert height + one_row <= budget

    def test_a_height_a_table_already_fits_changes_nothing(self, frame):
        plain = table_shape(table_render("![[t|rows=3]]", frame))
        budgeted = table_shape(table_render("![[t|rows=3|height=600]]", frame))
        assert plain[0] == budgeted[0]

    def test_a_trimmed_table_says_how_many_rows_it_shows(self, frame):
        rendered = table_render("![[t|height=120]]", frame)
        rows, _height, _room = table_shape(rendered)
        assert f"Showing {rows} of 14 rows" in rendered.document.toPlainText()

    def test_the_old_row_count_does_not_survive_the_trim(self, frame):
        """The note lives in a paragraph of its own, so a rebuilt table has
        to take it with it or the page carries both counts."""
        text = table_render("![[t|height=120]]", frame).document.toPlainText()
        assert text.count("Showing") == 1

    def test_fit_trims_the_table_into_the_room_left(self, frame):
        body = FILLER + "\n\n![[t|fit]]\n"
        rows, height, room = table_shape(
            table_render(body, frame, PAGE_HEIGHT))
        assert height <= room
        assert rows < 14

    def test_a_fitted_table_keeps_its_note_on_the_same_page(self, frame):
        """The trim is only honest because of the "showing N of M" line, so
        it has to land with the table rather than alone at the top of the
        next page looking like a mistake."""
        from PySide6.QtCore import QSizeF

        body = FILLER + "\n\n![[t|fit]]\n"
        rendered = table_render(body, frame, PAGE_HEIGHT)
        document = rendered.document
        document.setPageSize(QSizeF(510, PAGE_HEIGHT))
        _rows, height, room = table_shape(rendered)
        # room for the note under it, not just for the table itself
        assert height < room

    def test_without_fit_it_runs_over_the_page_as_before(self, frame):
        body = FILLER + "\n\n![[t]]\n"
        _rows, height, room = table_shape(
            table_render(body, frame, PAGE_HEIGHT))
        assert height > room

    def test_fit_leaves_a_table_that_already_fits_alone(self, frame):
        plain = table_shape(table_render("![[t]]", frame, PAGE_HEIGHT))
        fitted = table_shape(table_render("![[t|fit]]", frame, PAGE_HEIGHT))
        assert plain == fitted

    def test_fit_with_almost_no_room_says_so_and_keeps_the_table_whole(
            self, frame):
        """Two rows and a promise is worse than a table that breaks. A
        short page with prose most of the way down it leaves under three
        rows' worth, which is where `fit` gives up and says so."""
        tight = "\n\n".join(f"P{i}. " + "Words to push it down. " * 8
                            for i in range(3))
        rendered = table_render(tight + "\n\n![[t|fit]]\n", frame, 300)
        rows, _height, _room = table_shape(rendered, 300)
        assert rows == 14
        assert any("not enough room" in p for p in rendered.problems)

    def test_fit_on_a_card_says_it_needs_a_page(self, frame):
        rendered = table_render("![[t|fit]]", frame, page_height=None)
        assert any("only works on a report page" in p
                   for p in rendered.problems)

    def test_a_second_table_is_measured_after_the_first_one_moved(self, frame):
        """Trimming the first table pulls everything under it up the page,
        so the second one's "room left" is a different number by then. Both
        have to end up fitting, not just the one that was measured first."""
        from PySide6.QtCore import QSizeF
        from PySide6.QtGui import QTextTable

        page = 500
        filler = "\n\n".join(f"P{i}. " + "Words to push it down. " * 8
                             for i in range(4))
        rendered = table_render(
            filler + "\n\n![[t|fit]]\n\nBetween the two.\n\n![[t|fit]]\n",
            frame, page)
        document = rendered.document
        document.setPageSize(QSizeF(510, page))
        layout = document.documentLayout()
        seen = 0
        for child in document.rootFrame().childFrames():
            if isinstance(child, QTextTable):
                rect = layout.frameBoundingRect(child)
                assert rect.height() <= page - (rect.top() % page)
                seen += 1
        assert seen == 2
