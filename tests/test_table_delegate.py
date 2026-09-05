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
