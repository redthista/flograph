"""A table can say what order it opens in — on the card and on paper.

Clicking a header sorted the card and forgot. That is no use to a
dashboard tile nobody clicks, and no use at all to a printed report, which
has no header to click. `sort` is a rule like `wrap`: table-wide, read
once, and applied by both renderers from the same key function so the page
and the card cannot disagree.
"""
import pytest
from PySide6.QtCore import Qt

pd = pytest.importorskip("pandas")

from flograph.core import Graph, NodeRegistry              # noqa: E402
from flograph.core.table_format import (Rule, parse_rules,  # noqa: E402
                                        rules_from_style, sort_order,
                                        style_payload)
from flograph.core.table_html import frame_to_html          # noqa: E402
from flograph.core.table_sort import sorted_frame           # noqa: E402
from flograph.engine.cache import OutputCache               # noqa: E402
from flograph.ui.inspector.pandas_model import PandasModel  # noqa: E402
from flograph.ui.report.render import render_report         # noqa: E402

FRAME = pd.DataFrame({
    "region": ["South", "North", "East", "West"],
    "revenue": [30, 10, 40, 20],
})


def rows_of(html: str, column: int = 0) -> list:
    """The text of one column of a rendered table, top to bottom."""
    import re
    body = re.search(r"<tbody>(.*)</tbody>", html, re.S)
    if not body:
        return []
    out = []
    for row in re.findall(r"<tr>(.*?)</tr>", body.group(1), re.S):
        cells = re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)
        if len(cells) > column:
            out.append(re.sub(r"<[^>]+>", "", cells[column]).strip())
    return out


class TestTheRule:
    def test_a_direction_survives_the_style_port(self):
        """`to_dict` drops False as absence, so an `ascending` bool would
        have come back the other way round. Hence a string."""
        rule = parse_rules("revenue sort desc")[0]
        assert sort_order([Rule.from_dict(rule.to_dict())]) == ("revenue",
                                                                False)

    def test_the_last_sort_line_wins(self):
        """A table has one row order — a second line replaces, it does not
        tie-break."""
        rules = parse_rules("region sort asc\nrevenue sort desc")
        assert sort_order(rules) == ("revenue", False)

    def test_no_sort_rule_means_no_opinion(self):
        assert sort_order(parse_rules("revenue scale green")) is None

    def test_two_columns_is_refused_rather_than_half_obeyed(self):
        with pytest.raises(ValueError, match="one row order"):
            parse_rules("region, revenue sort asc")

    def test_a_direction_it_cannot_read_is_refused(self):
        with pytest.raises(ValueError, match="don't understand sort"):
            parse_rules("revenue sort sideways")

    def test_the_dropdown_beats_a_typed_line(self):
        """The box is the advanced way in; the control is the obvious one,
        and the obvious one should not lose."""
        payload = style_payload({"format_rules": "region sort asc",
                                 "sort": "revenue", "sort_dir": "descending"})
        assert sort_order(rules_from_style(payload)) == ("revenue", False)


class TestOnPaper:
    def test_a_report_table_prints_in_the_order_asked_for(self):
        html = frame_to_html(FRAME, parse_rules("revenue sort desc"))
        assert rows_of(html) == ["East", "South", "West", "North"]

    def test_ascending_is_the_default_direction(self):
        html = frame_to_html(FRAME, parse_rules("revenue sort"))
        assert rows_of(html) == ["North", "West", "South", "East"]

    def test_the_sort_happens_before_the_rows_are_cut(self):
        """`rows=` and `fit` keep the *top* of the table. Sorting after the
        cut would print an arbitrary handful, neatly ordered among
        themselves — which looks right and is wrong."""
        html = frame_to_html(FRAME, parse_rules("revenue sort desc"),
                             max_rows=2)
        assert rows_of(html) == ["East", "South"]

    def test_a_sort_on_a_column_that_is_not_there_prints_anyway(self):
        """A render path must not raise: the honest failure is the table
        in the order it arrived, not a blank card."""
        html = frame_to_html(FRAME, parse_rules("nope sort desc"))
        assert rows_of(html) == ["South", "North", "East", "West"]

    def test_numbers_stored_as_text_still_sort_as_numbers(self):
        """The whole reason the key function is shared with the card."""
        frame = pd.DataFrame({"n": ["10", "9", "100", "2"]})
        html = frame_to_html(frame, parse_rules("n sort asc"))
        assert rows_of(html) == ["2", "9", "10", "100"]


class TestOnTheCard:
    def test_the_card_opens_in_the_order_asked_for(self, qapp):
        model = PandasModel(FRAME, rules=parse_rules("revenue sort desc"))
        assert [model.index(r, 0).data() for r in range(4)] == [
            "East", "South", "West", "North"]

    def test_the_card_and_the_page_agree(self, qapp):
        """The point of sharing the key function."""
        rules = parse_rules("revenue sort desc")
        model = PandasModel(FRAME, rules=rules)
        assert ([model.index(r, 0).data() for r in range(4)]
                == rows_of(frame_to_html(FRAME, rules)))

    def test_clicking_a_header_still_wins(self, qapp):
        model = PandasModel(FRAME, rules=parse_rules("revenue sort desc"))
        model.sort(0, Qt.AscendingOrder)
        assert [model.index(r, 0).data() for r in range(4)] == [
            "East", "North", "South", "West"]

    def test_clearing_returns_to_the_frames_own_order(self, qapp):
        """Not to the default. "Clear" means no sort; the default comes
        back with the next run."""
        model = PandasModel(FRAME, rules=parse_rules("revenue sort desc"))
        model.sort(0, None)
        assert [model.index(r, 0).data() for r in range(4)] == [
            "South", "North", "East", "West"]

    def test_changing_the_colours_does_not_reorder_the_rows(self, qapp):
        """set_rules runs while someone is reading. Re-applying the default
        there would yank the table out from under a header click."""
        model = PandasModel(FRAME, rules=parse_rules("revenue sort desc"))
        model.sort(0, Qt.AscendingOrder)                  # reader clicks
        model.set_rules(parse_rules("revenue sort desc\nrevenue scale green"))
        assert [model.index(r, 0).data() for r in range(4)] == [
            "East", "North", "South", "West"]

    def test_a_missing_column_leaves_the_card_alone(self, qapp):
        model = PandasModel(FRAME, rules=parse_rules("nope sort desc"))
        assert [model.index(r, 0).data() for r in range(4)] == [
            "South", "North", "East", "West"]


class TestThroughTheNode:
    def table_node(self, params):
        registry = NodeRegistry()
        registry.load_builtins()
        graph, cache = Graph(), OutputCache()
        node = graph.add_node(registry.instantiate("flograph.viz.show_table"))
        graph.set_label(node.id, "Sales")
        cache.set(node.id, {"table": FRAME,
                            "style": style_payload(params)}, 0.0)
        return graph, cache

    def test_the_sort_by_param_reaches_a_report(self):
        graph, cache = self.table_node(
            {"sort": "revenue", "sort_dir": "descending"})
        html = render_report("![[Sales]]", graph, cache).document.toHtml()
        assert html.index("East") < html.index("North")

    def test_the_node_passes_its_table_through_unsorted(self):
        """Sorting is presentation. The `table` output is what it was —
        Sort is the node that reorders data."""
        from flograph.core import compile_run
        from tests.conftest import FakeContext

        registry = NodeRegistry()
        registry.load_builtins()
        spec = registry.get("flograph.viz.show_table")
        params = spec.default_params()
        params.update({"sort": "revenue", "sort_dir": "descending"})
        run = compile_run(spec.source, "test-show-table")
        out = run(FakeContext(params=params), table=FRAME)
        assert list(out["table"]["region"]) == ["South", "North",
                                                "East", "West"]


class TestSortedFrame:
    def test_no_column_named_is_no_change(self):
        assert sorted_frame(FRAME, None) is FRAME
        assert sorted_frame(FRAME, "") is FRAME

    def test_an_unknown_column_is_no_change(self):
        assert sorted_frame(FRAME, "nope") is FRAME

    def test_it_does_not_touch_the_frame_it_was_given(self):
        before = list(FRAME["region"])
        sorted_frame(FRAME, "revenue", False)
        assert list(FRAME["region"]) == before
