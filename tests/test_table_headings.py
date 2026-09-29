"""Show Table column headings — core/table_bands.py, the `heading` rule
lines, the card's model and header, the printed table, a matrix's own
headings — and sparks drawn on total and group rows."""
import re

import pandas as pd
import pytest
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent

from flograph.core import compile_run
from flograph.core import table_bands as tb
from flograph.core import table_totals as tt
from flograph.core.table_format import (
    parse_rules, parse_rules_lenient, rule_summary, style_payload,
    style_report)
from tests.conftest import FakeContext


def months():
    return pd.DataFrame({
        "region": ["north", "south"],
        "jan": [10, 20], "feb": [11, 21], "mar": [12, None],
        "apr": [5, 6], "q2_total": [50, 60], "note": ["ok", "late"],
    })


RULES = '''jan, feb, mar heading "2024 › Q1" sum
apr, q2_total heading "2024 › Q2" folded keep q2_total
total sum'''


def model_for(df, text, parent=None):
    from flograph.ui.inspector.pandas_model import styled_model
    return styled_model(df, style_payload({"format_rules": text}),
                        parent=parent)


def headers(model):
    return [model.headerData(c, Qt.Horizontal)
            for c in range(model.columnCount())]


def run_show_table(registry, table, **params):
    spec = registry.get("flograph.viz.show_table")
    values = spec.default_params()
    values.update(params)
    run = compile_run(spec.source, "test-show-table")
    return run(FakeContext(params=values), table)


# ------------------------------------------------------------- rule lines

class TestRuleLines:
    def test_columns_go_under_a_quoted_heading(self):
        rule = parse_rules('jan, feb, mar heading "Q1"')[0]
        assert (rule.mode, rule.columns, rule.label) == (
            "heading", ["jan", "feb", "mar"], "Q1")

    def test_start_state_and_fold(self):
        rule = parse_rules('apr* heading "2024 › Q2" folded average')[0]
        assert (rule.total_place, rule.total_agg) == ("closed", "average")

    def test_keep_names_a_column(self):
        rule = parse_rules('heading "Q1" keep q1_total')[0]
        assert (rule.columns, rule.total_agg, rule.source) == (
            [], "keep", "q1_total")

    def test_headings_alone_sets_every_heading(self):
        rule = parse_rules("headings folded sum")[0]
        assert (rule.label, rule.total_place, rule.total_agg) == (
            None, "closed", "sum")

    def test_a_column_called_heading_keeps_its_old_meaning(self):
        rule = parse_rules("heading scale green")[0]
        assert (rule.mode, rule.columns) == ("color_scale", ["heading"])

    def test_columns_with_no_heading_name_is_an_error_that_says_so(self):
        _rules, errors = parse_rules_lenient("a, b heading")
        assert errors and "name the heading" in errors[0]

    def test_the_manager_summarises_it(self):
        rule = parse_rules('jan, feb heading "Q1" folded sum')[0]
        assert rule_summary(rule) == (
            "jan, feb under “Q1”  ·  starts folded, folded shows the sum")

    def test_a_heading_line_is_not_a_cell_rule(self):
        from flograph.core.table_format import column_layout, split_rules
        rules = parse_rules('jan heading "Q1"')
        assert split_rules(rules) == ([], [])
        assert column_layout(rules, ["jan"]) == {}


# ------------------------------------------------------------------- core

class TestArrange:
    def tree(self, text=RULES, columns=None):
        cols = columns or list(months().columns)
        return tb.resolve(tb.plan_from_rules(parse_rules(text)), cols, cols)

    def test_nested_spans_and_a_kept_face(self):
        tree = self.tree()
        arranged = tb.arrange(tree, list(months().columns))
        # Q2 starts folded: its kept column alone stands under it
        assert arranged.names == ["region", "jan", "feb", "mar",
                                  "q2_total", "note"]
        spans = {s.path: (s.start, s.end, s.folded) for s in arranged.spans}
        assert spans == {("2024",): (1, 5, False),
                         ("2024", "Q1"): (1, 4, False),
                         ("2024", "Q2"): (4, 5, True)}
        assert arranged.depth == 2

    def test_a_heading_gathers_its_columns_where_the_first_stood(self):
        tree = self.tree('jan, mar heading "Odd"',
                         ["jan", "feb", "mar"])
        assert tb.arrange(tree, ["jan", "feb", "mar"]).names == [
            "jan", "mar", "feb"]

    def test_folding_the_outer_heading_leaves_one_column(self):
        tree = self.tree()
        arranged = tb.arrange(tree, list(months().columns), {("2024",)})
        assert arranged.names == ["region", "2024", "note"]
        # the quarters' row of headings goes with them
        assert arranged.depth == 1

    def test_the_last_line_naming_a_column_wins(self):
        tree = self.tree('jan, feb heading "A"\nfeb heading "B"',
                         ["jan", "feb"])
        assert tree.member_of == {"jan": ("A",), "feb": ("B",)}

    def test_a_summary_sums_across_the_row(self):
        tree = self.tree()
        frame = tb.with_faces(months(), tree)
        assert frame["Q1"].tolist() == [33, 41]

    def test_a_parent_does_not_count_a_kept_total_twice(self):
        tree = self.tree()
        tb.with_faces(months(), tree)
        # 2024 is a stub here, but its sources say what a sum would read
        assert "q2_total" not in tree.headings[("2024",)].sources

    @pytest.mark.parametrize("how, expected", [
        ("average", [11.0, 20.5]), ("max", [12.0, 21.0]),
        ("count", [3, 2]), ("rows", [3, 3]), ("range", [2.0, 1.0])])
    def test_row_aggregates(self, how, expected):
        part = months()[["jan", "feb", "mar"]]
        assert tb.row_aggregate(part, how).tolist() == expected

    def test_a_missing_keep_column_folds_to_a_stub(self):
        tree = self.tree('jan heading "Q1" keep nowhere', ["jan"])
        assert tree.headings[("Q1",)].fold == tb.STUB


# ------------------------------------------------------------------- card

class TestModel:
    def test_opens_as_the_rules_say(self, qtbot):
        m = model_for(months(), RULES)
        assert headers(m) == ["region", "jan", "feb", "mar", "q2_total",
                              "note"]
        assert m.has_headings()

    def test_folding_removes_and_inserts_rather_than_resets(self, qtbot):
        m = model_for(months(), RULES)
        with qtbot.waitSignals([m.columnsRemoved, m.columnsInserted]):
            assert m.toggle_heading(("2024", "Q1"))
        # a summary is headed by how it was worked out
        assert headers(m) == ["region", "sum", "q2_total", "note"]
        assert m.column_name(1) == "Q1"
        assert m.data(m.index(0, 1)) == "33"

    def test_a_folded_summary_is_totalled_and_bold(self, qtbot):
        m = model_for(months(), RULES)
        m.toggle_heading(("2024", "Q1"))
        last = m.rowCount() - 1
        assert m.special_at(last).kind == "total"
        assert m.data(m.index(last, 1)) == "74"
        assert m.data(m.index(last, 1), Qt.FontRole).bold()

    def test_a_stub_has_a_quiet_header_and_blank_cells(self, qtbot):
        m = model_for(months(), 'jan, feb heading "Q1" folded')
        assert headers(m)[1] == tb.STUB_HEADER
        assert m.data(m.index(0, 1)) == ""

    def test_collapse_all_and_expand_all(self, qtbot):
        m = model_for(months(), RULES)
        m.set_all_headings(True)
        assert headers(m) == ["region", tb.STUB_HEADER, "note"]
        m.set_all_headings(False)
        assert "apr" in headers(m) and "jan" in headers(m)

    def test_a_rerun_keeps_the_readers_folds(self, qtbot):
        old = model_for(months(), RULES)
        old.toggle_heading(("2024", "Q1"))
        new = model_for(months(), RULES)
        new.carry_folds(old)
        assert headers(new) == headers(old)

    def test_the_output_table_is_untouched(self, registry):
        out = run_show_table(registry, months(), format_rules=RULES)
        assert list(out["table"].columns) == list(months().columns)

    def test_a_rule_on_a_summary_is_not_a_missing_column(self):
        style = style_payload({"format_rules": RULES + "\nQ1 scale green"})
        assert not [m for m in style_report(style, months()) if "Q1" in m]


class TestHeader:
    def view(self, qtbot, text=RULES):
        from flograph.ui.data_table import DataTableView
        view = DataTableView()
        qtbot.addWidget(view)
        view.setModel(model_for(months(), text, parent=view))
        view.resize(700, 240)
        view.show()
        return view

    def test_the_header_grows_a_row_per_level(self, qtbot):
        plain = self.view(qtbot, "")
        banded = self.view(qtbot)
        line = banded.horizontalHeader().heading_line()
        assert (banded.horizontalHeader().sizeHint().height()
                == plain.horizontalHeader().sizeHint().height() + 2 * line)

    def test_a_click_on_a_heading_folds_it_and_does_not_sort(self, qtbot):
        view = self.view(qtbot)
        header = view.horizontalHeader()
        line = header.heading_line()
        x = header.sectionViewportPosition(2) + 4
        at = QPointF(x, line + 3)            # the second row: Q1
        for kind in (QEvent.MouseButtonPress, QEvent.MouseButtonRelease):
            event = QMouseEvent(kind, at, at, Qt.LeftButton,
                                Qt.LeftButton if kind ==
                                QEvent.MouseButtonPress else Qt.NoButton,
                                Qt.NoModifier)
            view.eventFilter(header.viewport(), event)
        assert headers(view.model())[1] == "sum"
        assert view.model()._df is view.model()._source      # no sort

    def test_the_menu_offers_expand_and_collapse(self, qtbot):
        view = self.view(qtbot)
        seen = [action.text() for action in view.build_menu().actions()]
        assert "Collapse All Column Headings" in seen


# ------------------------------------------------------------------ paper

class TestPaper:
    def test_heading_rows_span_their_columns(self):
        from flograph.core.table_html import frame_to_html
        html = frame_to_html(months(), parse_rules(RULES))
        head = html[html.index("<thead>"):html.index("</thead>")]
        rows = re.findall(r"<tr>(.*?)</tr>", head)
        assert len(rows) == 3
        assert '<th rowspan="3">region</th>' in rows[0]
        assert 'colspan="4">2024</th>' in rows[0]
        assert 'colspan="3">Q1</th>' in rows[1]

    def test_the_page_fits_by_its_data_rows(self, qtbot):
        from PySide6.QtGui import QTextDocument, QTextTable

        from flograph.core.table_html import frame_to_html
        doc = QTextDocument()
        doc.setHtml(frame_to_html(months(), parse_rules(RULES)))
        table = next(f for f in doc.rootFrame().childFrames()
                     if isinstance(f, QTextTable))
        assert table.format().headerRowCount() == 3


# ----------------------------------------------------------------- matrix

def sales():
    return pd.DataFrame({
        "region": ["N", "N", "N", "S", "S", "N"],
        "year": [2024, 2024, 2025, 2024, 2025, 2024],
        "q": ["Q1", "Q2", "Q1", "Q1", "Q2", "Q1"],
        "rev": [10, 20, 30, 40, 50, 60]})


class TestMatrix:
    def build(self, **kw):
        from flograph.core.matrix import build_matrix
        return build_matrix(sales(), ["region"], ["year", "q"], ["rev"],
                            agg="mean", style={}, totals=True, **kw)

    def test_the_levels_become_headings(self, qtbot):
        m = model_for_style(self.build())
        assert headers(m) == ["region", "Q1", "Q2", "Q1", "Q2"]
        assert [s.label for s in m.headings().spans] == ["2024", "2025"]

    def test_a_folded_year_is_the_mean_of_its_rows(self, qtbot):
        m = model_for_style(self.build())
        m.toggle_heading(("2024",))
        assert headers(m)[1] == "average"
        # north 2024 is 10, 20 and 60: 30 — the mean of its two quarter
        # cells (35, 20) would have said 27.5
        assert m.data(m.index(0, 1)) == "30"

    def test_folded_values_ride_on_the_style_not_the_table(self):
        built = self.build()
        assert list(built.frame.columns) == ["region", "2024_Q1", "2024_Q2",
                                             "2025_Q1", "2025_Q2"]
        assert set(built.style["grand"]["faces"]) == {
            "2024 · average", "2025 · average"}

    def test_flat_turns_them_off(self):
        built = self.build(headings=False)
        assert not [r for r in built.style["rules"]
                    if r["mode"] == "heading"]

    def test_one_level_has_nothing_to_head(self):
        from flograph.core.matrix import build_matrix
        built = build_matrix(sales(), ["region"], ["year"], ["rev"],
                             style={})
        assert not [r for r in built.style["rules"]
                    if r["mode"] == "heading"]

    def test_the_node_passes_the_choice_on(self, registry):
        out = run_show_table(registry, sales(), mode="matrix",
                             matrix_rows="region",
                             matrix_columns="year, q", matrix_values="rev",
                             matrix_headings="flat")
        assert not [r for r in out["style"]["rules"]
                    if r["mode"] == "heading"]

    def test_the_version_was_bumped(self, registry):
        assert registry.get("flograph.viz.show_table").version == "1.9"


def model_for_style(built):
    from flograph.ui.inspector.pandas_model import styled_model
    return styled_model(built.frame, built.style)


# ------------------------------------------------------ sparks on totals

def reps():
    return pd.DataFrame({
        "region": ["north", "north", "south"], "rep": ["a", "b", "c"],
        "jan": [10, 20, 30], "feb": [11, 25, 28], "mar": [15, 22, 26]})


def spark_on(style):
    return style is not None and any(
        getattr(d, "spark", None) is not None for d in style.decorations)


class TestSparksOnTotals:
    def test_the_word_puts_it_on_every_kind_of_row(self):
        rule = parse_rules("trend spark from jan..mar totals")[0]
        assert rule.rows_on == ["data", "total", "group", "subtotal"]
        rule = parse_rules("trend spark from jan..mar hide groups")[0]
        assert (rule.rows_on, rule.take_sources) == (
            ["data", "group"], "hide")

    def test_without_it_the_rows_are_left_alone(self):
        assert parse_rules("trend spark from jan..mar")[0].rows_on == []

    def test_a_group_row_draws_the_groups_months(self, qtbot):
        m = model_for(reps(), "group region\n"
                              "trend spark from jan..mar hide totals")
        trend = headers(m).index("trend")
        special = m.special_at(0)
        assert special.kind == "group"
        # the months print nothing on the group row, but feed its spark
        assert special.feeds == {"jan": 30, "feb": 36, "mar": 37}
        assert spark_on(m._style_of_special(special, "trend"))
        assert trend >= 0

    def test_a_printed_total_is_what_the_spark_reads(self):
        plan = tt.plan_from_rules(
            parse_rules("jan, feb, mar total average\n"
                        "trend spark from jan, feb, mar totals"), reps())
        assert plan.feeds == {}             # every month is totalled

    def test_without_the_word_no_spark_on_a_group_row(self, qtbot):
        m = model_for(reps(), "group region\n"
                              "trend spark from jan..mar hide")
        assert not spark_on(m._style_of_special(m.special_at(0), "trend"))

    def test_the_report_draws_them_too(self):
        from flograph.core.table_html import frame_to_html
        html = frame_to_html(reps(), parse_rules(
            "group region\ntrend spark from jan..mar hide totals"))
        body = html[html.index("<tbody>"):]
        rows = re.findall(r"<tr>.*?</tr>", body, re.S)
        assert all("<img" in row for row in rows)


# ----------------------------------------------------------- Rules… page

@pytest.fixture
def builder(qtbot):
    from flograph.ui.properties.table_rule_wizard import RuleBuilder

    def make(rule=None, columns=("region", "jan", "feb", "mar", "q1_total")):
        b = RuleBuilder(list(columns), rule=rule)
        qtbot.addWidget(b)
        return b
    return make


def _pick(b, *names):
    b._col_list.clearSelection()
    for i in range(b._col_list.count()):
        if b._col_list.item(i).text() in names:
            b._col_list.item(i).setSelected(True)


def _choose(box, data):
    box.setCurrentIndex(box.findData(data))


class TestBuilderPage:
    def test_columns_under_a_heading(self, builder):
        from flograph.ui.properties.table_rule_wizard import K_HEADINGS
        b = builder()
        b._kind.setCurrentIndex(K_HEADINGS)
        _pick(b, "jan", "feb", "mar")
        b._head_name.setText("2024 › Q1")
        _choose(b._head_fold, "sum")
        _choose(b._head_start, "folded")
        assert b.line() == 'jan, feb, mar heading "2024 › Q1" folded sum'
        rule = parse_rules(b.line())[0]
        assert (rule.mode, rule.label, rule.total_agg, rule.total_place) == (
            "heading", "2024 › Q1", "sum", "closed")

    def test_no_columns_or_no_name_is_no_line(self, builder):
        from flograph.ui.properties.table_rule_wizard import K_HEADINGS
        b = builder()
        b._kind.setCurrentIndex(K_HEADINGS)
        b._head_name.setText("Q1")
        assert b.line() == ""
        _pick(b, "jan")
        b._head_name.setText("")
        assert b.line() == ""

    def test_keep_a_column(self, builder):
        from flograph.ui.properties.table_rule_wizard import K_HEADINGS
        b = builder()
        b._kind.setCurrentIndex(K_HEADINGS)
        _choose(b._head_what, "heading")
        b._head_name.setText("Q1")
        _choose(b._head_fold, "keep")
        assert b._head_keep.isVisibleTo(b)
        _choose(b._head_keep, "q1_total")
        assert b.line() == 'heading "Q1" keep q1_total'

    def test_a_heading_line_says_stub_outright(self, builder):
        from flograph.ui.properties.table_rule_wizard import K_HEADINGS
        b = builder()
        b._kind.setCurrentIndex(K_HEADINGS)
        _choose(b._head_what, "heading")
        b._head_name.setText("Q1")
        assert b.line() == 'heading "Q1" stub'

    def test_every_heading(self, builder):
        from flograph.ui.properties.table_rule_wizard import K_HEADINGS
        b = builder()
        b._kind.setCurrentIndex(K_HEADINGS)
        _choose(b._head_what, "all")
        assert not b._col_list.isEnabled()
        assert not b._head_name.isVisibleTo(b)
        assert b.line() == ""
        _choose(b._head_start, "folded")
        _choose(b._head_fold, "average")
        assert b.line() == "headings folded average"

    @pytest.mark.parametrize("line", [
        'jan, feb, mar heading "2024 › Q1" folded sum',
        'heading "Q1" keep q1_total',
        'heading "Q1" folded stub',
        "headings folded",
    ])
    def test_a_line_opens_and_comes_back_the_same(self, builder, line):
        b = builder(rule=parse_rules(line)[0])
        assert parse_rules(b.line())[0].to_dict() == \
            parse_rules(line)[0].to_dict()

    def test_a_hidden_kept_column_survives_editing(self, builder):
        line = 'heading "2024" keep "2024 · average"'
        b = builder(rule=parse_rules(line)[0])
        assert parse_rules(b.line())[0].source == "2024 · average"

    def test_the_manager_edits_a_heading_line(self, qtbot, monkeypatch):
        from PySide6.QtWidgets import QDialog

        from flograph.ui.properties import table_rule_wizard as w
        m = w.RuleManager('jan, feb heading "Q1"', ["jan", "feb"])
        qtbot.addWidget(m)
        opened = []
        monkeypatch.setattr(w.RuleBuilder, "exec", lambda self: (
            opened.append(self._kind.currentIndex()), QDialog.Rejected)[1])
        m._list.setCurrentRow(0)
        m._edit()
        assert opened == [w.K_HEADINGS]


class TestSparkDrawOn:
    def test_the_spark_page_writes_the_word(self, builder):
        from flograph.ui.properties.table_rule_wizard import K_SPARK
        b = builder()
        b._kind.setCurrentIndex(K_SPARK)
        b._col_edit.setText("trend")
        _choose(b._spark_read, "pattern")
        b._spark_pattern.setText("m*")
        _choose(b._spark_on, "subtotals")
        rule = parse_rules(b.line())[0]
        assert rule.rows_on == ["data", "group", "subtotal"]

    def test_it_reads_back(self, builder):
        b = builder(rule=parse_rules("trend spark from jan..mar totals")[0])
        assert b._spark_on.currentData() == "totals"
