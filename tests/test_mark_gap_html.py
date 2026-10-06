"""`gap N` on paper, on a web page and on the card."""
from flograph.core.table_format import CellStyle, Decoration
from flograph.core.table_html import (
    MARK_JOIN, WORD_JOINER, _decorate, _mark_gap,
)


def _style(gap, where="left"):
    return CellStyle(decorations=[Decoration(text="A", gap=gap, where=where),
                                  Decoration(text="B", gap=gap, where=where)])


def test_no_gap_is_the_ordinary_no_break_space():
    html = _decorate("v", _style(None))
    assert html == f"<span>A</span>{MARK_JOIN}<span>B</span>{MARK_JOIN}v"


def test_gap_zero_sets_the_marks_touching_but_not_the_value():
    html = _decorate("v", _style(0))
    assert html == f"<span>A</span>{WORD_JOINER}<span>B</span>{MARK_JOIN}v"


def test_on_paper_a_gap_is_counted_out_in_spaces():
    assert _mark_gap(Decoration(gap=8)) == MARK_JOIN * 2
    assert _mark_gap(Decoration(gap=1)) == "\u202f"


def test_on_a_web_page_a_gap_is_exact():
    spacer = _mark_gap(Decoration(gap=7), live=True)
    assert "width:7px" in spacer and spacer.startswith(WORD_JOINER)


def test_marks_on_the_right_take_their_gap_too():
    html = _decorate("", _style(0, "right"))
    assert f"<span>A</span>{WORD_JOINER}<span>B</span>" in html


def test_the_card_spaces_marks_by_their_gap():
    from flograph.ui.table_delegate import _ICON_GAP, _gap, _run_width
    a, b = Decoration(text="A", gap=0), Decoration(text="B", gap=0)
    widths = {id(a): 10, id(b): 10}
    assert _gap(a) == 0 and _gap(Decoration()) == _ICON_GAP
    # touching marks, then the ordinary gap off the value
    assert _run_width([a, b], widths) == 20 + _ICON_GAP
