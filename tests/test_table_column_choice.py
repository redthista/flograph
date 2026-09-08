"""Choose the columns to show, in the order you chose them (V1).

`hide` was the only way to say which columns a table has, and it is
subtractive: you name what to lose. Naming what to *keep* is the other
half — and because a keep-list is written in an order, it is also the only
way to reorder a table's columns without a Select Columns node in front of
it.

Two decisions carry most of this file:

* **It is a view, not a transform.** The frame leaving the card's `table`
  port is the one that arrived, every column of it, in its original order.
  Select Columns is the node that reshapes data; a card is a way of looking
  at it.
* **One projection, used by both surfaces.** The card and the printed page
  ask the same function which columns exist and where they sit, because two
  implementations of one projection is exactly how a report starts quietly
  differing from the dashboard it came off.
"""
import pytest
from PySide6.QtCore import Qt

pd = pytest.importorskip("pandas")

from flograph.core.table_format import (  # noqa: E402
    merge_styles, parse_rules, parse_rules_lenient, quote_column,
    rule_summary, rules_from_style, shown_columns, split_rules, style_payload,
    style_report, visible_columns,
)
from flograph.core.table_html import frame_to_html            # noqa: E402
from flograph.ui.inspector.pandas_model import PandasModel    # noqa: E402

FRAME = pd.DataFrame({
    "region": ["South", "North"],
    "revenue": [30, 10],
    "product": ["Bolt", "Nut"],
    "_tmp_rank": [2, 1],
})

NAMES = list(FRAME.columns)


def headers(model) -> list:
    return [model.headerData(i, Qt.Horizontal, Qt.DisplayRole)
            for i in range(model.columnCount())]


def printed_headers(html: str) -> list:
    import re
    head = re.search(r"<thead>(.*?)</thead>", html, re.S)
    body = head.group(1) if head else html[:html.index("<tbody>")]
    return [re.sub(r"<[^>]+>", "", c).strip()
            for c in re.findall(r"<th[^>]*>(.*?)</th>", body, re.S)]


class TestTheRule:
    def test_show_names_the_columns_to_keep(self):
        rule = parse_rules("show region, product")[0]
        assert rule.mode == "show"
        assert rule.columns == ["region", "product"]

    def test_it_needs_a_column_like_hide_does(self):
        _, errors = parse_rules_lenient("show")
        assert errors and "needs a column name" in errors[0]

    def test_the_manager_can_describe_it(self):
        assert "region" in rule_summary(parse_rules("show region")[0])

    def test_it_shapes_the_table_rather_than_painting_a_cell(self):
        """`show` must not reach the per-cell evaluator: it decides which
        columns exist, which is answered once, before any cell is drawn."""
        col, row = split_rules(parse_rules("show region\nregion scale green"))
        assert [r.mode for r in col] == ["color_scale"]
        assert row == []

    def test_a_column_actually_called_show_has_to_be_quoted(self):
        assert quote_column("show") == '"show"'
        rule = parse_rules('"show" scale green')[0]
        assert rule.mode == "color_scale" and rule.columns == ["show"]

    def test_hide_still_leads_its_line_the_way_it_always_did(self):
        assert parse_rules("hide _tmp_rank")[0].mode == "hide"


class TestTheOrderIsTheOrderYouNamed:
    def test_the_columns_come_out_in_the_order_they_were_named(self):
        assert visible_columns(NAMES, ["product", "region"]) == ["product",
                                                                 "region"]

    def test_naming_none_of_them_means_all_of_them(self):
        """Empty is the usual case and it is not the same as "none" — a
        table with no columns is a bug, not a request."""
        assert visible_columns(NAMES, []) == NAMES

    def test_a_pattern_contributes_its_matches_in_the_tables_own_order(self):
        assert visible_columns(["b", "a", "x1"], ["x*", "b", "a"]) == ["x1",
                                                                      "b", "a"]

    def test_a_column_the_table_does_not_have_is_dropped_not_left_as_a_hole(self):
        assert visible_columns(NAMES, ["nope", "region"]) == ["region"]

    def test_naming_one_twice_does_not_print_it_twice(self):
        assert visible_columns(NAMES, ["region", "region"]) == ["region"]


class TestNamingBoth:
    def test_the_keep_list_is_applied_first_and_hide_takes_from_what_is_left(self):
        assert visible_columns(NAMES, ["region", "revenue"],
                               ["revenue"]) == ["region"]

    def test_a_column_in_neither_list_is_gone_either_way(self):
        assert "product" not in visible_columns(NAMES, ["region"], [])
        assert "product" not in visible_columns(NAMES, [], ["product"])


class TestOnTheCard:
    def test_the_card_shows_what_was_asked_for_in_that_order(self):
        model = PandasModel(FRAME, shown=["product", "region"])
        assert headers(model) == ["product", "region"]

    def test_the_values_follow_their_header(self):
        """A projection that moved the headers and not the cells would look
        right and be wrong, which is the worst kind."""
        model = PandasModel(FRAME, shown=["product", "region"])
        assert [model.data(model.index(0, i), Qt.DisplayRole)
                for i in range(2)] == ["Bolt", "South"]

    def test_hiding_still_works_on_its_own(self):
        model = PandasModel(FRAME, hidden=["_tmp*"])
        assert headers(model) == ["region", "revenue", "product"]

    def test_sorting_a_projected_table_sorts_the_right_column(self):
        """The view's column 0 is not the frame's column 0 any more, and a
        sort that forgot that would order the table by something the reader
        cannot see."""
        model = PandasModel(FRAME, shown=["revenue", "region"])
        model.sort(0, Qt.AscendingOrder)
        assert [model.data(model.index(r, 0), Qt.DisplayRole)
                for r in range(2)] == ["10", "30"]

    def test_a_frame_with_two_columns_of_one_name_keeps_both(self):
        frame = pd.DataFrame([[1, 2, 3]], columns=["x", "x", "y"])
        assert headers(PandasModel(frame, hidden=["y"])) == ["x", "x"]

    def test_nothing_asked_for_leaves_the_model_on_its_fast_path(self):
        assert PandasModel(FRAME)._visible is None


class TestOnPaper:
    def test_the_page_prints_the_same_columns_in_the_same_order(self):
        html = frame_to_html(FRAME, (), (), ["product", "region"])
        assert printed_headers(html) == ["product", "region"]

    def test_the_page_and_the_card_agree(self):
        """The one thing this whole area exists to protect."""
        shown, hidden = ["product", "region", "revenue"], ["revenue"]
        assert (printed_headers(frame_to_html(FRAME, (), hidden, shown))
                == headers(PandasModel(FRAME, shown=shown, hidden=hidden)))

    def test_hiding_on_paper_is_unchanged(self):
        html = frame_to_html(FRAME, (), ["_tmp*"])
        assert printed_headers(html) == ["region", "revenue", "product"]

    def test_a_keep_list_that_keeps_nothing_says_so_rather_than_raising(self):
        assert "no columns" in frame_to_html(FRAME, (), (), ["nope"])


class TestItSurvivesTheStylePort:
    def test_the_picker_and_the_rule_line_end_up_in_one_list(self):
        payload = style_payload({"format_rules": "show region",
                                 "show": "product"})
        assert shown_columns(payload) == ["region", "product"]

    def test_the_keep_list_does_not_travel_as_a_cell_rule(self):
        payload = style_payload({"format_rules": "show region"})
        assert rules_from_style(payload) == []

    def test_a_style_wired_in_brings_its_keep_list_with_it(self):
        wired = style_payload({"show": "region, revenue"})
        own = style_payload({"show": "product"})
        assert shown_columns(merge_styles(wired, own)) == ["region", "revenue",
                                                           "product"]

    def test_a_card_adds_to_an_incoming_keep_list_rather_than_arguing(self):
        """The same bargain `hide` has always struck. Replacing would let a
        card silently drop a column the style it was handed was built
        around, and nothing here can tell which was meant."""
        wired = style_payload({"show": "region"})
        assert shown_columns(merge_styles(wired, style_payload({}))) == ["region"]

    def test_naming_a_column_the_table_lacks_is_reported(self):
        messages = style_report(style_payload({"show": "nosuchcolumn"}), FRAME)
        assert any("nosuchcolumn" in m for m in messages)


class TestTheDataIsUntouched:
    """A card is a way of looking at a table, not a way of changing one."""

    def test_every_column_still_leaves_the_table_port_in_its_own_order(self,
                                                                       fake_ctx):
        from flograph.nodes.viz.show_table import run
        out = run(fake_ctx({"show": "product", "hide": "region",
                            "format_rules": ""}), FRAME)
        assert list(out["table"].columns) == NAMES

    def test_but_the_style_it_publishes_carries_the_choice(self, fake_ctx):
        from flograph.nodes.viz.show_table import run
        out = run(fake_ctx({"show": "product, region", "format_rules": ""}),
                  FRAME)
        assert shown_columns(out["style"]) == ["product", "region"]
