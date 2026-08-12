"""Idea A11: columns — text on the left, chart on the right.

Markdown has no columns, but Qt's rich text understands a table, and the
renderer was already emitting one to lay a *list* of charts out on a grid.
So a columns block becomes a one-row table, which survives into the PDF and
the exported HTML unchanged.

The syntax is a fenced block for three reasons: a column holds blocks
(headings, paragraphs, an embed) so it needs somewhere multi-line to live;
the info string is somewhere to put the widths; and any other markdown
renderer shows it as a code block rather than as mangled prose, which is
the polite way to not be understood.
"""
import re

import pytest

from flograph.core.report import (parse_weights, replace_columns,
                                  split_columns)
from flograph.ui.report.render import FIGURE_WIDTH, render_body


@pytest.fixture(autouse=True)
def _app(qapp):
    return qapp


@pytest.fixture
def figure():
    matplotlib = pytest.importorskip("matplotlib")
    matplotlib.use("Agg")
    from matplotlib.figure import Figure
    fig = Figure(figsize=(5, 3))
    fig.add_subplot(111).plot([1, 2, 3])
    return fig


def block(spec, *columns):
    return "```columns" + (f" {spec}" if spec else "") + "\n" \
        + "\n---\n".join(columns) + "\n```\n"


def rendered(body, value=None):
    return render_body(body, lambda ref, port: (value, "", ""))


def widths_of(result):
    return [int(w) for w in re.findall(r'<img[^>]*width="(\d+)"',
                                       result.document.toHtml())]


class TestTheSyntax:

    def test_a_block_splits_on_the_rule(self):
        seen = []
        replace_columns(block("", "Left", "Right"),
                        lambda columns, weights: seen.append(columns) or "x")
        assert seen == [["Left", "Right"]]

    def test_three_columns(self):
        assert split_columns("a\n---\nb\n---\nc") == ["a", "b", "c"]

    def test_a_column_keeps_its_own_blocks(self):
        seen = []
        replace_columns("```columns\n# Head\n\nText\n---\nOther\n```\n",
                        lambda columns, weights: seen.append(columns) or "x")
        assert seen[0][0] == "# Head\n\nText"

    def test_text_outside_the_block_is_untouched(self):
        out = replace_columns("Before\n\n" + block("", "a", "b") + "\nAfter\n",
                              lambda columns, weights: "TABLE")
        assert "Before" in out and "After" in out and "TABLE" in out

    def test_two_blocks_are_both_found(self):
        seen = []
        replace_columns(block("", "a", "b") + "\n" + block("", "c", "d"),
                        lambda columns, weights: seen.append(columns) or "x")
        assert seen == [["a", "b"], ["c", "d"]]

    def test_one_column_is_not_a_layout(self):
        """Returned unwrapped rather than as a table of one cell, which
        would look like nothing happened while quietly changing the width
        everything inside was drawn at."""
        out = replace_columns("```columns\nJust me\n```\n",
                              lambda columns, weights: "TABLE")
        assert out.strip() == "Just me"

    def test_an_ordinary_code_block_is_left_alone(self):
        source = "```python\nx = 1\n---\ny = 2\n```\n"
        assert replace_columns(source, lambda c, w: "TABLE") == source

    def test_a_rule_outside_a_block_is_still_a_rule(self):
        assert replace_columns("a\n\n---\n\nb\n", lambda c, w: "TABLE") \
            == "a\n\n---\n\nb\n"


class TestTheWidths:

    def test_no_spec_is_equal_columns(self):
        assert parse_weights("", 2) == [1.0, 1.0]

    def test_ratios(self):
        assert parse_weights("2 1", 2) == [2.0, 1.0]

    def test_percentages_are_the_same_idea(self):
        assert parse_weights("60% 40%", 2) == [60.0, 40.0]

    def test_commas_are_allowed(self):
        assert parse_weights("2,1", 2) == [2.0, 1.0]

    def test_the_wrong_number_falls_back_to_equal(self):
        assert parse_weights("2 1 1", 2) == [1.0, 1.0]

    def test_nonsense_falls_back_to_equal(self):
        """A typo in a width should still show the content."""
        assert parse_weights("wide narrow", 2) == [1.0, 1.0]

    def test_zero_does_not_vanish_a_column(self):
        assert parse_weights("0 1", 2)[0] > 0


class TestRendering:

    def test_it_becomes_a_table(self):
        html = rendered(block("", "Left", "Right")).document.toHtml()
        assert "<table" in html

    def test_both_columns_are_there(self):
        text = rendered(block("", "Left side", "Right side")
                        ).document.toPlainText()
        assert "Left side" in text and "Right side" in text

    def test_a_chart_is_drawn_at_its_column_width(self, figure):
        """The reason columns resolve their own embeds: a chart drawn full
        width and then squeezed into a third of the page is unreadable."""
        result = rendered(block("", "Words", "![[Chart]]"), figure)
        assert widths_of(result) == [(FIGURE_WIDTH - 8) // 2]

    def test_an_uneven_split_sizes_the_chart_to_match(self, figure):
        result = rendered(block("2 1", "Words", "![[Chart]]"), figure)
        room = FIGURE_WIDTH - 8
        assert widths_of(result) == [int(room * 1 / 3)]

    def test_a_per_embed_width_still_applies_inside_a_column(self, figure):
        result = rendered(block("", "Words", "![[Chart|width=50%]]"), figure)
        assert widths_of(result) == [((FIGURE_WIDTH - 8) // 2) // 2]

    def test_a_chart_after_the_block_is_full_width_again(self, figure):
        result = rendered(block("", "Words", "![[Chart]]") + "\n![[Chart]]\n",
                          figure)
        assert widths_of(result) == [(FIGURE_WIDTH - 8) // 2, FIGURE_WIDTH]

    def test_markdown_inside_a_column_is_rendered(self):
        html = rendered(block("", "# Heading", "**bold**")).document.toHtml()
        assert "font-weight" in html.lower() or "<b" in html.lower()

    def test_a_page_break_inside_a_column_does_not_explode(self):
        result = rendered(block("", "One\n\n\\pagebreak\n\nTwo", "Right"))
        assert "One" in result.document.toPlainText()

    def test_an_unresolved_embed_inside_a_column_is_reported(self):
        result = rendered(block("", "Words", "![[Nothing]]"), None)
        assert result.problems

    def test_it_survives_being_printed(self, figure, tmp_path):
        from flograph.ui.report.export import export_pdf
        result = rendered(block("2 1", "Words and words", "![[Chart]]"),
                          figure)
        target = tmp_path / "columns.pdf"
        export_pdf(result.document, str(target))
        assert target.read_bytes()[:5] == b"%PDF-"

    def test_it_survives_being_saved_as_html(self, figure):
        from flograph.ui.report.html import report_html
        result = rendered(block("", "Words", "![[Chart]]"), figure)
        html = report_html(result, "R")
        assert "<table" in html and "data:image/png;base64," in html
