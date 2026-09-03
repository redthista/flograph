"""The rule wizard — every rule type it builds must parse."""
import pytest

from flograph.core.table_format import parse_rules
from flograph.ui.properties.table_rule_wizard import RuleWizard

COLUMNS = ["revenue", "units", "status", "sla", "gross margin"]


@pytest.fixture
def wiz(qtbot):
    added: list[str] = []
    w = RuleWizard(COLUMNS, added.append)
    qtbot.addWidget(w)
    w._added_lines = added
    return w


def _select(w, *names):
    w._col_list.clearSelection()
    for i in range(w._col_list.count()):
        if w._col_list.item(i).text() in names:
            w._col_list.item(i).setSelected(True)


def _valid(line: str):
    assert line, "wizard produced no line"
    rules = parse_rules(line)          # must not raise
    assert rules
    return rules[0]


def test_colour_scale(wiz):
    wiz._kind.setCurrentIndex(0)
    _select(wiz, "revenue")
    assert _valid(wiz._line()).mode == "color_scale"


def test_data_bars_multiple_columns(wiz):
    wiz._kind.setCurrentIndex(1)
    _select(wiz, "revenue", "units")
    rule = _valid(wiz._line())
    assert rule.mode == "data_bar" and rule.columns == ["revenue", "units"]


def test_highlight_between_bold(wiz):
    wiz._kind.setCurrentIndex(2)
    _select(wiz, "units")
    wiz._op.setCurrentIndex([d for _, d in
                             [(wiz._op.itemText(i), wiz._op.itemData(i))
                              for i in range(wiz._op.count())]].index("between"))
    wiz._val1.setText("10")
    wiz._val2.setText("20")
    wiz._bold.setChecked(True)
    rule = _valid(wiz._line())
    assert rule.op == "between" and rule.value == [10, 20] and rule.bold


def test_whole_row_highlight(wiz):
    wiz._kind.setCurrentIndex(2)
    _select(wiz, "status")
    wiz._op.setCurrentIndex(4)          # equals
    wiz._val1.setText("fail")
    wiz._scope.setCurrentIndex(1)       # whole row
    rule = _valid(wiz._line())
    assert rule.scope == "row"


def test_icons(wiz):
    wiz._kind.setCurrentIndex(3)
    _select(wiz, "units")
    wiz._icon_reverse.setChecked(True)
    rule = _valid(wiz._line())
    assert rule.mode == "icons" and rule.reverse is True


def test_iconmap_from_another_column(wiz):
    wiz._kind.setCurrentIndex(4)
    _select(wiz, "units")
    wiz._map_source.setCurrentText("sla")
    wiz._map.item(0, 0).setText("breach")
    wiz._map.cellWidget(0, 1).setCurrentText("x")
    wiz._map.cellWidget(0, 2).setCurrentText("red")
    rule = _valid(wiz._line())
    assert rule.mode == "icon_map" and rule.source == "sla"
    assert rule.mapping["breach"][0] == "x"


def test_number_format(wiz):
    wiz._kind.setCurrentIndex(5)
    _select(wiz, "revenue")
    wiz._numfmt.setCurrentText("$,.0f")
    assert _valid(wiz._line()).number_spec == "$,.0f"


def test_hide_quotes_a_spaced_name(wiz):
    wiz._kind.setCurrentIndex(6)
    _select(wiz, "gross margin")
    line = wiz._line()
    assert line == 'hide "gross margin"'
    assert _valid(line).columns == ["gross margin"]


def test_add_calls_back_and_counts(wiz):
    wiz._kind.setCurrentIndex(0)
    _select(wiz, "revenue")
    wiz._append()
    assert wiz._added_lines == ["revenue scale green"]
    assert wiz.added() == 1


def test_free_text_columns_when_none_known(qtbot):
    w = RuleWizard([], lambda _l: None)
    qtbot.addWidget(w)
    w._kind.setCurrentIndex(0)
    w._col_edit.setText("a, b")
    assert w._line() == "a, b scale green"
