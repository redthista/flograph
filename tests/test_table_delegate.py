"""What the conditional-format delegate actually paints into a cell.

Assertions about pixels rather than about roles: the model can be perfectly
right about a rule and the cell still come out wrong, which is how an icon
ends up parked in a left margin of a column that has nothing else in it.
"""
import pandas as pd
import pytest
from PySide6.QtCore import QRect

from flograph.core.table_format import parse_rules
from flograph.ui.data_table import DataTableView
from flograph.ui.inspector.pandas_model import PandasModel

pytestmark = pytest.mark.usefixtures("qapp")

COLUMN_WIDTH = 160


def _cell_image(qtbot, rules_text):
    """The `flag` cell of row 0, and the image it was painted into.

    `flag` carries a value the rule hides, so what is left in the cell is
    the format and nothing else.
    """
    frame = pd.DataFrame({"sla": ["breach"], "flag": ["breach"]})
    view = DataTableView()
    view.setModel(PandasModel(frame, rules=parse_rules(rules_text)))
    view.setColumnWidth(1, COLUMN_WIDTH)
    view.resize(340, 90)
    qtbot.addWidget(view)
    # the viewport, not the widget: visualRect is in viewport coordinates
    return view.viewport().grab().toImage(), view.visualRect(
        view.model().index(0, 1))


def _ink_centre(image, cell: QRect):
    """The mean x of the marks in `cell`, as a fraction of its width."""
    background = image.pixel(cell.right() - 3, cell.top() + 2)
    xs = [x for x in range(cell.left() + 2, cell.right() - 2)
          for y in range(cell.top() + 2, cell.bottom() - 2)
          if image.pixel(x, y) != background]
    assert xs, "nothing was painted in the cell"
    return (sum(xs) / len(xs) - cell.left()) / cell.width()


class TestIconPlacement:
    def test_an_icon_beside_a_value_sits_in_the_left_margin(self, qtbot):
        image, cell = _cell_image(
            qtbot, "flag iconmap sla: breach=✗ red")
        assert _ink_centre(image, cell) < 0.35

    def test_an_icon_that_replaced_the_value_is_centred(self, qtbot):
        """With `only` there is no value beside it, so a left-margin icon
        would read as a stray mark rather than as the column's content."""
        image, cell = _cell_image(
            qtbot, "flag iconmap only sla: breach=✗ red")
        assert 0.4 < _ink_centre(image, cell) < 0.6


class TestAnIconFollowsTheColumnsAlign:
    """Centred is the *default*, not the only answer. An icon standing in
    for the value is the cell's whole content, so `align` moves it the way
    it would have moved the value — which the printed table already did
    (`core/table_html._cell`), leaving the card the odd one out.
    """

    ICONS = "flag iconmap only sla: breach=✗ red"

    def test_align_right_puts_it_on_the_right(self, qtbot):
        image, cell = _cell_image(qtbot, f"{self.ICONS}\nflag align right")
        assert _ink_centre(image, cell) > 0.65

    def test_align_left_puts_it_on_the_left(self, qtbot):
        image, cell = _cell_image(qtbot, f"{self.ICONS}\nflag align left")
        assert _ink_centre(image, cell) < 0.35

    def test_align_centre_is_what_it_already_did(self, qtbot):
        image, cell = _cell_image(qtbot, f"{self.ICONS}\nflag align centre")
        assert 0.4 < _ink_centre(image, cell) < 0.6

    def test_a_number_column_still_centres_its_icon(self, qtbot):
        """Numbers align right by their dtype, with nobody asking. That is
        not an `align` rule and must not move an icon that has been centred
        since icons existed."""
        frame = pd.DataFrame({"sla": ["breach"], "flag": [1]})
        view = DataTableView()
        view.setModel(PandasModel(
            frame, rules=parse_rules("flag iconmap only sla: breach=✗ red")))
        view.setColumnWidth(1, COLUMN_WIDTH)
        view.resize(340, 90)
        qtbot.addWidget(view)
        image = view.viewport().grab().toImage()
        cell = view.visualRect(view.model().index(0, 1))
        assert 0.4 < _ink_centre(image, cell) < 0.6

    def test_the_value_beside_an_icon_is_unaffected(self, qtbot):
        """Without `only` the value is still there and still owns the
        alignment; the icon keeps its margin."""
        image, cell = _cell_image(
            qtbot, "flag iconmap sla: breach=✗ red\nflag align right")
        assert _ink_centre(image, cell) > 0.4


# ------------------------------------------------------------------- T1
#
# A cell holds a list of decorations now, each knowing its own place. The
# model can be perfectly right about all of that and the cell still come
# out wrong, so these are pixels again rather than roles.

def _table(qtbot, frame, rules_text, width=160):
    view = DataTableView()
    view.setModel(PandasModel(frame, rules=parse_rules(rules_text)))
    for col in range(view.model().columnCount()):
        view.setColumnWidth(col, width)
    view.resizeRowsToContents()
    view.resize(width * view.model().columnCount() + 40, 160)
    qtbot.addWidget(view)
    return view


def _marks(view, row, col):
    """(image, cell rect) for one cell of a laid-out view."""
    return (view.viewport().grab().toImage(),
            view.visualRect(view.model().index(row, col)))


def _painted(view, row=0, col=0):
    """How many pixels in the cell differ from its own background."""
    image, cell = _marks(view, row, col)
    background = image.pixel(cell.right() - 3, cell.top() + 2)
    return sum(1 for x in range(cell.left() + 2, cell.right() - 2)
               for y in range(cell.top() + 2, cell.bottom() - 2)
               if image.pixel(x, y) != background)


class TestWhereAMarkIsPainted:
    def test_a_right_placed_mark_paints_on_the_right(self, qtbot):
        frame = pd.DataFrame({"flag": ["breach"]})
        view = _table(qtbot, frame, "flag iconmap only right: breach=✗ red")
        image, cell = _marks(view, 0, 0)
        assert _ink_centre(image, cell) > 0.6

    def test_and_a_left_placed_one_on_the_left(self, qtbot):
        frame = pd.DataFrame({"flag": ["breach"]})
        view = _table(qtbot, frame, "flag iconmap left: breach=✗ red")
        image, cell = _marks(view, 0, 0)
        assert _ink_centre(image, cell) < 0.4

    def test_two_marks_both_reach_the_cell(self, qtbot):
        """The regression that matters most: before the list, the second
        rule painted nothing at all."""
        frame = pd.DataFrame({"flag": [1]})
        one = _table(qtbot, frame, "flag = 1 => icon ✓ green in")
        two = _table(qtbot, frame,
                     "flag = 1 => icon ✓ green in\n"
                     "flag = 1 => icon ✗ red right")
        assert _painted(two) > _painted(one)


class TestARowGrowsForTheCellThatAsked:
    def test_a_mark_above_makes_that_row_taller(self, qtbot):
        frame = pd.DataFrame({"late": [1, 0]})
        view = _table(qtbot, frame, "late = 1 => icon ! amber above")
        assert view.rowHeight(0) > view.rowHeight(1)

    def test_a_mark_beside_the_value_does_not(self, qtbot):
        frame = pd.DataFrame({"late": [1, 0]})
        view = _table(qtbot, frame, "late = 1 => icon ! amber right")
        assert view.rowHeight(0) == view.rowHeight(1)

    def test_only_the_matching_rows_pay(self, qtbot):
        """Per-cell, not table-wide — the decision Dan took. A rule that
        matches nothing must leave every row the height it was."""
        frame = pd.DataFrame({"late": [0, 0]})
        plain = _table(qtbot, frame, "")
        ruled = _table(qtbot, frame, "late = 1 => icon ! amber above")
        assert ruled.rowHeight(0) == plain.rowHeight(0)


class TestAPillIsPainted:
    def test_the_lozenge_puts_ink_in_the_cell(self, qtbot):
        frame = pd.DataFrame({"status": ["breach"]})
        bare = _table(qtbot, frame, "")
        potted = _table(qtbot, frame, "status colormap pill: breach=red")
        assert _painted(potted) > _painted(bare)

    def test_a_pill_does_not_flood_the_whole_cell(self, qtbot):
        """The difference from a plain fill: the lozenge stops at the text,
        so the cell's far edge keeps the table's own ground."""
        frame = pd.DataFrame({"status": ["ok"]})
        potted = _table(qtbot, frame, "status colormap pill: ok=red",
                        width=220)
        filled = _table(qtbot, frame, "status colormap: ok=red", width=220)
        pimg, pcell = _marks(potted, 0, 0)
        fimg, fcell = _marks(filled, 0, 0)
        edge = pimg.pixel(pcell.right() - 4, pcell.center().y())
        assert edge != fimg.pixel(fcell.right() - 4, fcell.center().y())
