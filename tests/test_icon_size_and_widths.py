"""An icon's own size, icons held together on a web page, and a column's
`width` rule held on a web page — plus the card sizing a column for every
mark in a cell, not the widest one."""
import pandas as pd

from flograph.core.table_format import CellStyle, Decoration, parse_rules
from flograph.core.table_html import (
    _cell_styles, _decorate, _row_padding, frame_to_html,
)


def style_frame(frame, rules):
    return _cell_styles(frame, frame, list(frame.columns), rules, False)


_PNG = ("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9Q"
        "DwADhgGAWjR9awAAAABJRU5ErkJggg==")


# ------------------------------------------------------------ icon size

def test_a_glyph_icon_keeps_its_size():
    rules = parse_rules("Owner = Alice => icon ✓ green 24px")
    styles = style_frame(pd.DataFrame({"Owner": ["Alice"]}), rules)
    (d,) = styles[(0, "Owner")].decorations
    assert d.text == "✓" and d.size == 24


def test_iconmap_sizes_every_glyph():
    rules = parse_rules("Tags iconmap all 20px: *a*=🔧, *b*=🧪")
    styles = style_frame(pd.DataFrame({"Tags": ["a b"]}), rules)
    assert [d.size for d in styles[(0, "Tags")].decorations] == [20, 20]


def test_a_sized_glyph_prints_at_its_size():
    style = CellStyle(decorations=[Decoration(text="✓", size=24)])
    assert "font-size:18pt" in _decorate("v", style)


def test_a_sized_glyph_makes_its_row_taller_on_paper():
    plain = {(0, "c"): CellStyle(decorations=[Decoration(text="✓")])}
    sized = {(0, "c"): CellStyle(decorations=[Decoration(text="✓",
                                                         size=40)])}
    # asked for a short row: the sized glyph's line is what is left
    assert (_row_padding(20, 0, ["c"], sized, 10)
            <= _row_padding(20, 0, ["c"], plain, 10))


def test_a_sized_glyph_grows_the_cards_row():
    from flograph.ui.table_delegate import _grown_px
    assert _grown_px([Decoration(text="✓", size=40)], 18) > 0
    assert _grown_px([Decoration(text="✓")], 18) == 0


# ------------------------------------------------ held together on a page

def test_a_live_run_of_marks_cannot_break():
    style = CellStyle(decorations=[Decoration(text="A"),
                                   Decoration(text="B")])
    html = _decorate("value", style, live=True)
    # the marks and the space onto the value are one unbreakable run
    assert html.startswith('<span style="white-space:nowrap">')
    assert html.endswith("</span>value")


def test_paper_keeps_its_no_break_spaces():
    style = CellStyle(decorations=[Decoration(text="A")])
    assert "nowrap" not in _decorate("value", style)


# ------------------------------------------------- `width` on a web page

def test_a_live_column_is_held_to_its_width_rule():
    frame = pd.DataFrame({"Note": ["a long note " * 5], "x": [1]})
    html = frame_to_html(frame, parse_rules("Note width 160"), live=True)
    assert "max-width:142px" in html            # 160 less the cell padding
    assert html.count('class="fg-fixed"') == 2  # the header and the cell
    assert "fg-fixed" not in frame_to_html(frame, parse_rules(
        "Note width 160"))                      # paper: Qt honours width=


# ------------------------------------------- the card sizes for every mark

def test_the_card_sizes_a_column_for_every_picture_in_it(qtbot):
    from flograph.ui.data_table import DataTableView
    from flograph.ui.inspector.pandas_model import PandasModel
    frame = pd.DataFrame({"Tags": ["a b c", "x"]})

    def width(rules):
        view = DataTableView()
        qtbot.addWidget(view)
        view.setModel(PandasModel(frame, rules=parse_rules(rules)))
        view.fit_columns_to_data()
        return view.columnWidth(0)

    rule = f"Tags contains {{}} => icon {_PNG} in"
    one = width(rule.format("a"))
    three = width("\n".join(rule.format(k) for k in "abc"))
    assert three > one + 20


# ----------------------------------------- emoji in the app's Web preview

def test_an_emoji_mark_names_its_font():
    """Qt WebEngine draws an emoji only in a font named for it."""
    from flograph.core.table_html import EMOJI_FONTS
    html = _decorate("v", CellStyle(decorations=[Decoration(text="🔧")]))
    assert f"font-family:{EMOJI_FONTS}" in html


def test_a_text_symbol_keeps_the_tables_font():
    for glyph in ("✓", "▲", "✗", "●"):
        html = _decorate("v", CellStyle(decorations=[Decoration(text=glyph)]))
        assert "font-family" not in html, glyph


# ------------------------------------------------ a float's digits on the card

def test_the_card_keeps_every_whole_digit_of_a_float():
    from flograph.ui.inspector.pandas_model import float_text
    assert float_text(100000.25) == "100000.25"     # was "100000"
    assert float_text(1234567.891) == "1234567.89"  # was "1.23457e+06"
    assert float_text(1234.5678901234) == "1234.57"  # still reads cleanly
    assert float_text(3.14159265) == "3.14159"
    assert float_text(5.0) == "5"
    assert float_text(0.1 + 0.2) == "0.3"


def test_the_model_shows_the_whole_number(qtbot):
    from PySide6.QtCore import Qt
    from flograph.ui.inspector.pandas_model import PandasModel
    model = PandasModel(pd.DataFrame({"Amount": [100000.25]}))
    assert model.data(model.index(0, 0), Qt.DisplayRole) == "100000.25"
