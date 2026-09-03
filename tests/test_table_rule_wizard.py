"""The Rules dialog — the builder produces parseable DSL, the manager
round-trips a rules box."""
import pytest

from flograph.core.table_format import parse_rules
from flograph.ui.properties.table_rule_wizard import RuleBuilder, RuleManager

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
    b._kind.setCurrentIndex(4)
    _select(b, "units")
    b._map_source.setCurrentText("sla")
    b._map.item(0, 0).setText("breach")
    b._map.cellWidget(0, 1).setCurrentText("x")
    b._map.cellWidget(0, 2).setCurrentText("red")
    rule = _valid(b.line())
    assert rule.mode == "icon_map" and rule.source == "sla"


def test_number_format(build):
    b = build()
    b._kind.setCurrentIndex(5)
    _select(b, "revenue")
    b._numfmt.setCurrentText("$,.0f")
    assert _valid(b.line()).number_spec == "$,.0f"


def test_hide_quotes_a_spaced_name(build):
    b = build()
    b._kind.setCurrentIndex(6)
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


def test_free_text_columns_when_none_known(qtbot):
    b = RuleBuilder([])
    qtbot.addWidget(b)
    b._kind.setCurrentIndex(0)
    b._col_edit.setText("a, b")
    assert b.line() == "a, b scale green"
