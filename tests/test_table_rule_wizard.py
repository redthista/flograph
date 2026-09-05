"""The Rules dialog — the builder produces parseable DSL, the manager
round-trips a rules box."""
import pytest

from flograph.core.table_format import parse_rules
from flograph.ui.properties.table_rule_wizard import (
    ColorChoice, RuleBuilder, RuleManager,
)

COLUMNS = ["revenue", "units", "status", "sla", "gross margin"]


@pytest.fixture
def build(qtbot):
    def make(rule=None):
        b = RuleBuilder(COLUMNS, rule=rule)
        qtbot.addWidget(b)
        return b
    return make


def _select(b, *names):
    b._col_list.clearSelection()
    for i in range(b._col_list.count()):
        if b._col_list.item(i).text() in names:
            b._col_list.item(i).setSelected(True)


def _valid(line):
    assert line
    rules = parse_rules(line)          # must not raise
    assert rules
    return rules[0]


def test_colour_scale(build):
    b = build()
    b._kind.setCurrentIndex(0)
    _select(b, "revenue")
    assert _valid(b.line()).mode == "color_scale"


def test_data_bars_multiple_columns(build):
    b = build()
    b._kind.setCurrentIndex(1)
    _select(b, "revenue", "units")
    rule = _valid(b.line())
    assert rule.mode == "data_bar" and rule.columns == ["revenue", "units"]


def test_highlight_between_bold(build):
    b = build()
    b._kind.setCurrentIndex(2)
    _select(b, "units")
    idx = [b._op.itemData(i) for i in range(b._op.count())].index("between")
    b._op.setCurrentIndex(idx)
    b._val1.setText("10")
    b._val2.setText("20")
    b._bold.setChecked(True)
    rule = _valid(b.line())
    assert rule.op == "between" and rule.value == [10, 20] and rule.bold


def test_whole_row_highlight(build):
    b = build()
    b._kind.setCurrentIndex(2)
    _select(b, "status")
    b._op.setCurrentIndex(4)          # equals
    b._val1.setText("fail")
    b._scope.setCurrentIndex(1)
    assert _valid(b.line()).scope == "row"


def test_icons_reverse(build):
    b = build()
    b._kind.setCurrentIndex(3)
    _select(b, "units")
    b._icon_reverse.setChecked(True)
    assert _valid(b.line()).reverse is True


def test_iconmap(build):
    b = build()
    b._kind.setCurrentIndex(3)                # Icons
    b._icon_style.setCurrentIndex(1)          # Map exact values to icons
    _select(b, "units")
    _pick_other(b._icon_by, "sla")
    b._map.item(0, 0).setText("breach")
    b._map.cellWidget(0, 1).setText("x")
    b._map.cellWidget(0, 2).set_value("red")
    rule = _valid(b.line())
    assert rule.mode == "icon_map" and rule.source == "sla"
    assert rule.mapping["breach"][0] == "x"


def test_iconmap_free_text_glyph_and_custom_hex_colour(build):
    b = build()
    b._kind.setCurrentIndex(3)
    b._icon_style.setCurrentIndex(1)
    _select(b, "units")
    _pick_other(b._icon_by, "sla")
    b._map.item(0, 0).setText("warn")
    b._map.cellWidget(0, 1).setText("🙂")
    b._map.cellWidget(0, 2).set_value("#ff8800")
    rule = _valid(b.line())
    assert rule.mapping["warn"] == ["🙂", "#ff8800"]


def test_number_format(build):
    b = build()
    b._kind.setCurrentIndex(4)
    _select(b, "revenue")
    b._numfmt.setCurrentText("$,.0f")
    assert _valid(b.line()).number_spec == "$,.0f"


def test_hide_quotes_a_spaced_name(build):
    b = build()
    b._kind.setCurrentIndex(5)
    _select(b, "gross margin")
    assert b.line() == 'hide "gross margin"'


def test_builder_prefills_from_a_rule(build):
    rule = parse_rules("units icons check reverse")[0]
    b = build(rule)
    assert b._kind.currentIndex() == 3
    assert b._chosen_columns() == ["units"]
    assert b._iconset.currentData() == "check"
    assert b._icon_reverse.isChecked() is True
    assert b.line() == "units icons check reverse"


def test_builder_prefills_a_highlight(build):
    rule = parse_rules("status = fail => row red")[0]
    b = build(rule)
    assert b._op.currentData() == "=" and b._val1.text() == "fail"
    assert b._scope.currentIndex() == 1


class TestManager:
    @pytest.fixture
    def mgr(self, qtbot):
        text = ("revenue scale green\n# a note\n"
                "status = fail => row red\nbroken !\nhide sla")
        m = RuleManager(text, COLUMNS)
        qtbot.addWidget(m)
        m._text = text
        return m

    def test_lists_rules_notes_and_errors(self, mgr):
        kinds = [e[1].mode if e[1] else ("err" if e[2] else "note")
                 for e in mgr._entries]
        assert kinds == ["color_scale", "note", "highlight", "err", "hide"]

    def test_unchanged_round_trips_exactly(self, mgr):
        assert mgr.result_text() == mgr._text

    def test_remove_a_rule(self, mgr):
        mgr._list.setCurrentRow(0)
        mgr._remove()
        assert "revenue scale green" not in mgr.result_text()
        assert "# a note" in mgr.result_text()      # note untouched

    def test_reorder(self, mgr):
        mgr._list.setCurrentRow(2)                  # the highlight
        mgr._move(-1)
        lines = mgr.result_text().splitlines()
        assert lines.index("status = fail => row red") < lines.index("# a note")

    def test_add_appends_a_line(self, mgr):
        mgr._entries.append(mgr._entry_for("units bar blue"))
        mgr._reload()
        assert mgr.result_text().splitlines()[-1] == "units bar blue"

    def test_edit_button_disabled_on_a_note(self, mgr):
        mgr._list.setCurrentRow(1)                  # the comment
        assert not mgr._edit_btn.isEnabled()


def _pick_other(box, name):
    box.setCurrentIndex([box.itemData(i) for i in range(box.count())].index(name))


def test_scale_by_another_column(build):
    b = build()
    b._kind.setCurrentIndex(0)
    _select(b, "status")
    _pick_other(b._scale_by, "revenue")
    rule = _valid(b.line())
    assert rule.mode == "color_scale" and rule.columns == ["status"]
    assert rule.source == "revenue"


def test_data_bar_sized_by_another_column(build):
    b = build()
    b._kind.setCurrentIndex(1)
    _select(b, "status")
    _pick_other(b._bar_by, "units")
    assert _valid(b.line()).source == "units"


def test_icons_ranked_by_another_column(build):
    b = build()
    b._kind.setCurrentIndex(3)
    _select(b, "status")
    _pick_other(b._icon_by, "revenue")
    b._icon_reverse.setChecked(True)
    rule = _valid(b.line())
    assert rule.source == "revenue" and rule.reverse is True


def test_highlight_tested_on_another_column(build):
    b = build()
    b._kind.setCurrentIndex(2)
    _select(b, "gross margin")
    _pick_other(b._hl_test, "revenue")
    b._op.setCurrentIndex(2)              # is less than
    b._val1.setText("0")
    rule = _valid(b.line())
    assert rule.mode == "highlight" and rule.columns == ["gross margin"]
    assert rule.source == "revenue" and rule.op == "<" and rule.value == 0


def test_by_clause_round_trips_through_the_builder(build):
    rule = parse_rules("units icons traffic by revenue")[0]
    b = build(rule)
    assert b._icon_by.currentData() == "revenue"
    assert b.line() == "units icons traffic by revenue"


def test_if_clause_round_trips_through_the_builder(build):
    rule = parse_rules("status if revenue < 0 => bg red")[0]
    b = build(rule)
    assert b._hl_test.currentData() == "revenue"
    assert _valid(b.line()).source == "revenue"


def test_column_pattern_typed_alongside_the_list(build):
    b = build()
    b._kind.setCurrentIndex(0)
    _select(b, "revenue")
    b._col_edit.setText("Q?_*, units")
    rule = _valid(b.line())
    assert rule.mode == "color_scale"
    assert rule.columns == ["revenue", "Q?_*", "units"]


def test_builder_prefills_a_pattern_into_the_field(build):
    rule = parse_rules("20* bar blue")[0]
    b = build(rule)
    assert b._kind.currentIndex() == 1
    assert b._col_edit.text() == "20*"
    assert b.line() == "20* bar blue"


def test_color_choice_presets_and_custom_hex(qtbot):
    cc = ColorChoice([("Red", "red", "#c00"), ("Blue", "blue", "#00c")])
    qtbot.addWidget(cc)
    cc.set_value("blue")
    assert cc.value() == "blue"
    cc.set_value("#ff8800")            # a hex it has no preset for
    assert cc.value() == "#ff8800"
    cc.set_value("red")
    assert cc.value() == "red"


def test_highlight_fill_accepts_a_custom_hex(build):
    rule = parse_rules("score >= 90 => bg #123456")[0]
    b = build(rule)
    assert b._fill.value() == "#123456"
    assert _valid(b.line()).bg == "#123456"


def test_manager_duplicate_copies_the_selected_rule(qtbot):
    m = RuleManager("revenue scale green\nunits bar blue", COLUMNS)
    qtbot.addWidget(m)
    m._list.setCurrentRow(0)
    m._duplicate()
    lines = m.result_text().splitlines()
    assert lines == ["revenue scale green", "revenue scale green", "units bar blue"]
    assert m._list.currentRow() == 1


def test_manager_duplicate_disabled_on_a_note(qtbot):
    m = RuleManager("# just a note", COLUMNS)
    qtbot.addWidget(m)
    m._list.setCurrentRow(0)
    assert not m._dup_btn.isEnabled()


def test_free_text_columns_when_none_known(qtbot):
    b = RuleBuilder([])
    qtbot.addWidget(b)
    b._kind.setCurrentIndex(0)
    b._col_edit.setText("a, b")
    assert b.line() == "a, b scale green"


class TestValueHidden:
    """The `only` tickbox on the scale, bar and icon pages."""

    def test_a_bar_only_rule_is_written(self, build):
        b = build()
        b._kind.setCurrentIndex(1)
        _select(b, "units")
        b._bar_only.setChecked(True)
        assert b.line() == "units bar blue only"
        assert _valid(b.line()).hide_value

    def test_an_icon_map_puts_only_before_the_mapping(self, build):
        """A trailing one would be read as the last pair's colour."""
        b = build()
        b._kind.setCurrentIndex(3)                # Icons
        b._icon_style.setCurrentIndex(1)          # Map exact values to icons
        _select(b, "units")
        _pick_other(b._icon_by, "sla")
        b._map.item(0, 0).setText("breach")
        b._map.cellWidget(0, 1).setText("✗")
        b._icon_only.setChecked(True)
        assert b.line() == "units iconmap only sla: breach=✗"
        assert _valid(b.line()).hide_value

    def test_it_round_trips_through_the_builder(self, build):
        rule = parse_rules("score icons traffic only")[0]
        b = build(rule)
        assert b._icon_only.isChecked()
        assert b.line() == "score icons traffic only"

    def test_an_ordinary_rule_leaves_it_off(self, build):
        rule = parse_rules("units bar blue")[0]
        b = build(rule)
        assert not b._bar_only.isChecked()
        assert b.line() == "units bar blue"
