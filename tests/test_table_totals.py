"""Show Table total rows and grouped tables — core/table_totals.py, the rule
lines that ask for them, the card's model, the printed table, the node's
Totals in output, and the Rules dialog's Totals & groups page."""
import pandas as pd
import pytest
from PySide6.QtCore import Qt

from flograph.core import compile_run
from flograph.core import table_totals as tt
from flograph.core.table_format import (
    hidden_columns, parse_rules, rule_summary, rules_from_style,
    shown_columns, style_payload)
from tests.conftest import FakeContext


def sales():
    return pd.DataFrame({
        "region": ["north", "south", "north", "south", "east"],
        "product": ["a", "a", "b", "a", "c"],
        "price": [1.5, 2.0, 3.0, 4.0, 5.0],
        "profit": [5, -20, 3, 4, 1],
    })


def run_show_table(registry, table, **params):
    spec = registry.get("flograph.viz.show_table")
    values = spec.default_params()
    values.update(params)
    run = compile_run(spec.source, "test-show-table")
    return run(FakeContext(params=values), table)


# ------------------------------------------------------------- rule lines

class TestRuleLines:
    def test_a_blanket_total_line_takes_how_where_and_a_label(self):
        rule = parse_rules('total sum top "Grand total"')[0]
        assert (rule.mode, rule.columns, rule.total_agg, rule.total_place,
                rule.label) == ("total", [], "sum", "top", "Grand total")

    def test_a_column_total_line(self):
        rule = parse_rules("price total mean")[0]
        assert rule.columns == ["price"] and rule.total_agg == "average"
        rule = parse_rules('region total "All regions"')[0]
        assert rule.total_text == "All regions"
        assert parse_rules("id total none")[0].total_agg == "none"

    def test_group_and_subtotal_lines(self):
        group, sub = parse_rules('group region, product closed\n'
                                 'subtotal below "Subtotal"')
        assert group.mode == "group"
        assert group.columns == ["region", "product"]
        assert group.total_place == "closed"
        assert (sub.total_place, sub.label) == ("below", "Subtotal")

    def test_a_style_line_paints_a_kind_of_row(self):
        rule = parse_rules("subtotal => bg blue, bold")[0]
        assert rule.mode == "total_style"
        assert rule.rows_on == ["group", "subtotal"] and rule.bold

    def test_on_aims_a_highlight_at_total_rows(self):
        rule = parse_rules("profit < 0 => fg red, icon ▼ red, on totals")[0]
        assert rule.mode == "highlight"
        assert rule.rows_on == ["total", "group", "subtotal"]
        assert "on total and group and subtotal rows" in rule_summary(rule)

    def test_old_meanings_survive(self):
        """New lines only claim what the old parser refused: a column
        called "total" keeps its heatmap, a note column called "total"
        keeps its tooltip."""
        scale = parse_rules("total scale green")[0]
        assert scale.mode == "color_scale" and scale.columns == ["total"]
        tip = parse_rules("revenue tooltip total")[0]
        assert tip.mode == "tooltip" and tip.source == "total"
        cond = parse_rules("total > 5 => bg red")[0]
        assert cond.mode == "highlight" and cond.columns == ["total"]

    @pytest.mark.parametrize("line", ["total summ", "price total sideways",
                                      "subtotal sideways",
                                      "x > 1 => fg red, on nowhere",
                                      "total => icon ✓"])
    def test_a_wrong_total_line_says_what_was_meant(self, line):
        with pytest.raises(ValueError):
            parse_rules(line)

    def test_fg_names_the_vivid_ink_not_the_dark_fill(self):
        rule = parse_rules("profit < 0 => fg red")[0]
        assert rule.fg == "#d9534f"


# ----------------------------------------------------------- aggregations

class TestAggregate:
    @pytest.mark.parametrize("how,expected", [
        ("sum", 15.5), ("average", 3.1), ("median", 3.0), ("min", 1.5),
        ("max", 5.0), ("range", 3.5), ("count", 5), ("rows", 5),
        ("distinct", 5), ("first", 1.5), ("last", 5.0)])
    def test_numbers(self, how, expected):
        assert tt.aggregate(sales()["price"], how) == pytest.approx(expected)

    def test_std_variance_mode(self):
        s = pd.Series([1, 2, 2, 3])
        assert tt.aggregate(s, "mode") == 2
        assert tt.aggregate(s, "variance") == pytest.approx(s.var())
        assert tt.aggregate(s, "std") == pytest.approx(s.std())

    def test_text_is_counted_but_never_summed(self):
        s = sales()["region"]
        assert tt.aggregate(s, "sum") is None
        assert tt.aggregate(s, "distinct") == 3
        assert tt.aggregate(s, "mode") == "north"

    def test_blanks_are_skipped_except_by_rows(self):
        s = pd.Series([1.0, None, 3.0])
        assert tt.aggregate(s, "count") == 2
        assert tt.aggregate(s, "rows") == 3
        assert tt.aggregate(s, "average") == 2.0

    def test_every_aggregation_is_offered_by_show_table(self, registry):
        spec = registry.get("flograph.viz.show_table")
        assert spec.param("totals").options == ["off", *tt.AGGREGATIONS]


# ------------------------------------------------------------------ plan

class TestPlan:
    def test_a_later_line_wins_for_its_columns(self):
        plan = tt.plan_from_rules(parse_rules("total sum\nprice total average"),
                                  sales())
        assert plan.per_column == {"price": ("agg", "average"),
                                   "profit": ("agg", "sum")}
        plan = tt.plan_from_rules(parse_rules("price total average\ntotal sum"),
                                  sales())
        assert plan.per_column["price"] == ("agg", "sum")

    def test_none_and_text(self):
        plan = tt.plan_from_rules(parse_rules(
            'total sum\nprofit total none\nregion total "All"'), sales())
        assert plan.per_column == {"price": ("agg", "sum"),
                                   "region": ("text", "All")}

    def test_a_grouping_column_is_never_totalled(self):
        plan = tt.plan_from_rules(parse_rules(
            'group region\nregion total "x"\ntotal sum'), sales())
        assert "region" not in plan.per_column

    def test_the_dropdowns_come_first_so_the_box_refines_them(self):
        style = style_payload({"format_rules": "price total max",
                               "totals": "sum", "totals_at": "top",
                               "mode": "grouped", "group_by": "region",
                               "subtotals": "under the group",
                               "groups_start": "folded"})
        plan = tt.plan_from_rules(rules_from_style(style), sales())
        assert plan.per_column["price"] == ("agg", "max")
        assert plan.per_column["profit"] == ("agg", "sum")
        assert plan.place == "top" and plan.group_by == ["region"]
        assert plan.subtotal_place == "below" and plan.group_open == "closed"

    def test_group_by_is_ignored_unless_shown_grouped(self):
        style = style_payload({"totals": "sum", "mode": "table",
                               "group_by": "region"})
        assert not tt.plan_from_rules(rules_from_style(style),
                                      sales()).grouped


# ---------------------------------------------------------------- layout

def _kinds(layout):
    return [("data", pos) if special is None else (special.kind,
                                                   special.label)
            for pos, special in (layout.at(i) for i in range(len(layout)))]


class TestLayout:
    def test_total_rows_go_where_they_are_asked(self):
        for place, expect in (("bottom", [5]), ("top", [0]),
                              ("both", [0, 6])):
            plan = tt.plan_from_rules(parse_rules(f"total sum {place}"),
                                      sales())
            layout = tt.build_layout(sales(), plan)
            kinds = _kinds(layout)
            assert [i for i, k in enumerate(kinds) if k[0] == "total"] == \
                expect
        plan = tt.plan_from_rules(parse_rules("total sum none"), sales())
        assert not plan.active

    def test_groups_come_in_first_seen_order_and_keep_their_rows(self):
        plan = tt.plan_from_rules(parse_rules("total sum\ngroup region"),
                                  sales())
        kinds = _kinds(tt.build_layout(sales(), plan))
        assert kinds == [("group", "north"), ("data", 0), ("data", 2),
                         ("group", "south"), ("data", 1), ("data", 3),
                         ("group", "east"), ("data", 4),
                         ("total", "Total")]

    def test_subtotals_below_and_folding(self):
        plan = tt.plan_from_rules(parse_rules(
            "total sum\ngroup region\nsubtotal below"), sales())
        layout = tt.build_layout(sales(), plan, toggled={("south",)})
        kinds = _kinds(layout)
        assert ("group", "south") in kinds and ("data", 1) not in kinds
        assert ("subtotal", "north Total") in kinds
        assert ("subtotal", "south Total") not in kinds   # folded away
        north = next(layout.at(i)[1] for i in range(len(layout))
                     if kinds[i] == ("subtotal", "north Total"))
        assert north.values == {"price": 4.5, "profit": 8}
        # the header row carries nothing when subtotals go below
        header = layout.at(0)[1]
        assert header.kind == "group" and header.values == {}

    def test_groups_can_start_folded(self):
        plan = tt.plan_from_rules(parse_rules(
            "total sum\ngroup region, product first"), sales())
        kinds = _kinds(tt.build_layout(sales(), plan))
        # the outer level open, the inner folded: no data rows at all
        assert all(k[0] != "data" for k in kinds)
        assert ("group", "north") in kinds and ("group", "a") in kinds

    def test_a_blank_group_value_is_a_group_of_its_own(self):
        df = sales()
        df.loc[4, "region"] = None
        plan = tt.plan_from_rules(parse_rules("group region"), df)
        kinds = _kinds(tt.build_layout(df, plan))
        assert ("group", "(blank)") in kinds

    def test_written_out_and_taken_back(self):
        plan = tt.plan_from_rules(parse_rules(
            "total sum\ngroup region\nsubtotal below"), sales())
        out, added = tt.with_totals(sales(), plan)
        assert len(out) == len(sales()) + len(added)
        assert list(out.index[added]) == ["north Total", "south Total",
                                          "east Total", "Total"]
        assert out.loc["Total", "region"] == "Total"
        assert out.loc["Total", "profit"] == -7
        back = tt.strip_baked(out, added)
        assert sorted(back.index) == [0, 1, 2, 3, 4]


class TestStyles:
    def test_rules_reach_total_rows_only_when_aimed(self):
        rules = parse_rules("profit < 0 => fg red, icon ▼ red, on totals\n"
                            "profit < 0 => bg amber")
        plan = tt.plan_from_rules(parse_rules("total sum"), sales())
        layout = tt.build_layout(sales(), plan)
        total = layout.specials[0]
        [styles] = tt.special_styles([total], "total", rules,
                                     ["price", "profit"],
                                     lambda s: dict(s.values))
        assert styles["profit"].fg == "#d9534f"
        assert styles["profit"].decorations[0].text == "▼"
        # the plain rule is for data rows: no amber fill on the total
        assert styles["profit"].bg == tt.DEFAULT_LOOK["total"][0]

    def test_a_row_style_keeps_an_earlier_ink(self):
        rules = parse_rules("profit < 0 => fg red, on total\n"
                            "total => bg blue")
        plan = tt.plan_from_rules(parse_rules("total sum"), sales())
        total = tt.build_layout(sales(), plan).specials[0]
        [styles] = tt.special_styles([total], "total", rules,
                                     ["price", "profit"],
                                     lambda s: dict(s.values))
        assert styles["profit"].fg == "#d9534f"
        assert styles["profit"].bg == "#26415c"
        assert styles["price"].fg != "#d9534f"

    def test_a_total_takes_its_column_format_unless_it_is_a_count(self):
        rules = parse_rules("price format $,.2f")
        assert tt.cell_text(10.5, ("agg", "sum"), rules, "price") == "$10.50"
        assert tt.cell_text(5, ("agg", "count"), rules, "price") == "5"
        assert tt.plain_number(1234567.0) == "1234567"


# --------------------------------------------------------------- the card

@pytest.fixture
def model(qapp):
    from flograph.ui.inspector.pandas_model import styled_model

    def make(**params):
        style = style_payload(params)
        return styled_model(sales(), style)
    return make


def _texts(m, row):
    return [m.data(m.index(row, c)) for c in range(m.columnCount())]


class TestCardModel:
    def test_the_total_stays_put_through_a_sort(self, model):
        m = model(totals="sum", totals_at="both")
        assert m.rowCount() == 7
        assert _texts(m, 0)[0] == "Total"
        m.sort(2, Qt.DescendingOrder)            # price
        assert _texts(m, 0)[0] == "Total" and _texts(m, 6)[0] == "Total"
        assert _texts(m, 1)[2] == "5"            # the biggest price, first
        assert m.headerData(0, Qt.Vertical) == "Total"
        assert not m.is_data_row(0) and m.is_data_row(1)
        assert m.row_label(0) == ""

    def test_grouped_rows_fold_as_an_insert_and_a_removal(self, model,
                                                          qtbot):
        m = model(totals="sum", mode="grouped", group_by="region")
        assert m.headerData(0, Qt.Horizontal) == "region"
        assert "region" not in [m.headerData(c, Qt.Horizontal)
                                for c in range(1, m.columnCount())]
        assert _texts(m, 0)[0].startswith("▾ north")
        before = m.rowCount()
        with qtbot.waitSignal(m.rowsRemoved):
            assert m.toggle_group(0)
        assert m.rowCount() == before - 2
        assert _texts(m, 0)[0].startswith("▸ north")
        with qtbot.waitSignal(m.rowsInserted):
            m.toggle_group(0)
        assert m.rowCount() == before
        m.set_all_groups(True)
        assert m.rowCount() == 4                 # 3 groups and the total
        m.set_all_groups(False)
        assert m.rowCount() == before

    def test_folds_survive_a_rerun(self, model):
        m = model(totals="sum", mode="grouped", group_by="region")
        m.toggle_group(0)
        again = model(totals="sum", mode="grouped", group_by="region")
        again.carry_folds(m)
        assert again.rowCount() == m.rowCount()

    def test_a_picked_total_row_filters_nothing(self, model):
        m = model(totals="sum", totals_at="top")
        assert m.pick_texts(0, [0, 1]) == ["", "north"]
        assert m.rows_matching(0, ["north"]) == [1, 3]


# ----------------------------------------------------------- node + paper

class TestNode:
    def test_totals_stay_out_of_the_output_by_default(self, registry):
        out = run_show_table(registry, sales(), totals="sum")
        assert len(out["table"]) == 5
        assert "baked" not in out["style"]

    def test_totals_in_output(self, registry, qapp):
        out = run_show_table(registry, sales(), totals="sum",
                             totals_out=True)
        assert len(out["table"]) == 6
        assert out["table"].index[-1] == "Total"
        assert out["style"]["baked"] == [5]
        from flograph.ui.inspector.pandas_model import styled_model
        m = styled_model(out["table"], out["style"])
        # the card takes the written row back out and lays out its own
        assert m.rowCount() == 6

    def test_a_matrix_totals_the_rows_not_the_cells(self, registry):
        out = run_show_table(registry, sales(), mode="matrix",
                             matrix_rows="region", matrix_columns="product",
                             matrix_values="price", matrix_agg="mean",
                             totals="average")
        plan = tt.plan_from_rules(rules_from_style(out["style"]),
                                  out["table"])
        layout = tt.build_layout(out["table"], plan,
                                 grand=out["style"]["grand"])
        total = layout.specials[0]
        # a: north 1.5, south 2.0 and 4.0 -> the mean of the rows is 2.5;
        # the mean of the two cells (1.5, 3.0) would have said 2.25
        assert total.values["a"] == pytest.approx(2.5)

    def test_the_version_was_bumped(self, registry):
        assert registry.get("flograph.viz.show_table").version == "1.8"


class TestPaper:
    def test_the_report_lays_out_what_the_card_does(self):
        from flograph.core.table_html import frame_to_html
        style = style_payload({"format_rules": "price format $,.2f\n"
                                               "profit < 0 => fg red, on totals",
                               "totals": "sum", "mode": "grouped",
                               "group_by": "region",
                               "subtotals": "under the group"})
        html = frame_to_html(sales(), rules_from_style(style),
                             hidden_columns(style), shown_columns(style))
        assert "<th>region</th>" in html
        assert "north (2)" in html and "north Total" in html
        assert "$15.50" in html
        assert "color:#d9534f" in html          # -7 on the grand total

    def test_rows_written_into_the_table_are_not_printed_twice(self):
        from flograph.core.table_html import frame_to_html
        plan = tt.plan_from_rules(parse_rules("total sum"), sales())
        baked, added = tt.with_totals(sales(), plan)
        html = frame_to_html(baked, parse_rules("total sum"),
                             baked=added)
        assert html.count(">Total<") == 1


# ------------------------------------------------------------ the dialog

@pytest.fixture
def build(qtbot):
    from flograph.ui.properties.table_rule_wizard import RuleBuilder

    def make(rule=None):
        b = RuleBuilder(["region", "price", "profit"], rule=rule)
        qtbot.addWidget(b)
        return b
    return make


@pytest.mark.parametrize("line", [
    'total sum top "Grand total"', "price total average",
    'region total "All regions"', "group region closed",
    'subtotal below "Subtotal"', "total => bg blue, bold",
    "subtotal => fg red",
    "profit < 0 => fg red, bold, on totals",
])
def test_the_dialog_reopens_every_line_as_it_was(build, line):
    rule = parse_rules(line)[0]
    b = build(rule)
    again = parse_rules(b.line())[0]
    assert again == rule


def test_the_dialog_writes_text_colour_on_totals(build):
    from flograph.ui.properties.table_rule_wizard import K_HIGHLIGHT
    b = build()
    b._kind.setCurrentIndex(K_HIGHLIGHT)
    for i in range(b._col_list.count()):
        b._col_list.item(i).setSelected(b._col_list.item(i).text()
                                        == "profit")
    b._op.setCurrentIndex([b._op.itemData(i) for i in
                           range(b._op.count())].index("<"))
    b._val1.setText("0")
    b._fill.set_value("(none)")
    b._hl_fg.set_value("red")
    b._hl_on.setCurrentIndex(1)
    assert b.line() == "profit < 0 => fg red, on totals"
