"""PandasModel honours a conditional-format rule list through data()."""
import pandas as pd
import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor

from flograph.core.table_format import parse_rules
from flograph.ui.inspector.pandas_model import (
    _BACKGROUND, _VALUE_ROLES, PandasModel,
)
from flograph.ui.table_delegate import BAR_ROLE, ICON_ROLE


def _bg(model, row, col):
    return model.data(model.index(row, col), _BACKGROUND)


class TestNoRules:
    def test_background_role_is_none_and_perf_contract_holds(self):
        model = PandasModel(pd.DataFrame({"a": [1, 2, 3]}))
        assert model._cf_active is False
        assert model._value_roles is _VALUE_ROLES
        assert _bg(model, 0, 0) is None

    def test_nan_still_grey_and_italic(self):
        model = PandasModel(pd.DataFrame({"a": [1.0, None]}),
                            rules=parse_rules("a scale green"))
        fg = model.data(model.index(1, 0), Qt.ForegroundRole)
        font = model.data(model.index(1, 0), Qt.FontRole)
        assert fg == QColor("#6b7280") and font.italic()


class TestRules:
    def test_colour_scale_paints_a_background(self):
        model = PandasModel(pd.DataFrame({"a": [0.0, 10.0]}),
                            rules=parse_rules("a scale blue"))
        assert model._cf_active is True
        assert isinstance(_bg(model, 0, 0), QColor)
        assert isinstance(_bg(model, 1, 0), QColor)

    def test_highlight_sets_bg_and_bold(self):
        model = PandasModel(pd.DataFrame({"score": [95, 40]}),
                            rules=parse_rules("score >= 90 => bg green, bold"))
        assert _bg(model, 0, 0) == QColor("#2e4d33")
        assert model.data(model.index(0, 0), Qt.FontRole).bold()
        assert _bg(model, 1, 0) is None

    def test_whole_row_highlight(self):
        df = pd.DataFrame({"status": ["ok", "closed"], "n": [1, 2]})
        model = PandasModel(df, rules=parse_rules("status = closed => row grey"))
        assert _bg(model, 1, 0) == QColor("#3a3d44")
        assert _bg(model, 1, 1) == QColor("#3a3d44")
        assert _bg(model, 0, 0) is None

    def test_data_bar_role(self):
        model = PandasModel(pd.DataFrame({"a": [0.0, 100.0]}),
                            rules=parse_rules("a bar blue"))
        assert model.data(model.index(0, 0), BAR_ROLE)[0] == pytest.approx(0.0)
        assert model.data(model.index(1, 0), BAR_ROLE)[0] == pytest.approx(1.0)

    def test_icon_role(self):
        model = PandasModel(pd.DataFrame({"a": list(range(9))}),
                            rules=parse_rules("a icons traffic"))
        assert model.data(model.index(0, 0), ICON_ROLE) == ("●", "#d9534f")
        assert model.data(model.index(8, 0), ICON_ROLE) == ("●", "#5cb85c")

    def test_number_format_overrides_display_only(self):
        model = PandasModel(pd.DataFrame({"a": [1234.5]}),
                            rules=parse_rules("a format ,.0f"))
        assert model.data(model.index(0, 0), Qt.DisplayRole) == "1,234"
        assert model.data(model.index(0, 0), Qt.EditRole) == repr(1234.5)


class TestSortSurvival:
    def test_colours_follow_values_across_a_sort(self):
        # row 0 holds the column max
        df = pd.DataFrame({"a": [100.0, 0.0, 50.0]})
        model = PandasModel(df, rules=parse_rules("a scale blue"))
        top = _bg(model, 0, 0)                       # colour of the max value
        model.sort(0, Qt.AscendingOrder)
        assert model.data(model.index(2, 0), Qt.DisplayRole) == "100"
        assert _bg(model, 2, 0) == top               # max is now last row
        model.sort(0, None)
        assert _bg(model, 0, 0) == top               # cleared -> original order


def test_set_rules_swaps_formatting_live():
    model = PandasModel(pd.DataFrame({"a": [1, 2, 3]}))
    assert _bg(model, 0, 0) is None
    model.set_rules(parse_rules("a >= 1 => bg red"))
    assert _bg(model, 0, 0) == QColor("#5c2b2b")
    model.set_rules([])
    assert model._cf_active is False and _bg(model, 0, 0) is None
