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

    def test_order_of_application_a_later_cell_rule_beats_a_row_rule(self):
        df = pd.DataFrame({"status": ["fail", "fail"], "score": [95, 40]})
        # row red first, then a cell rule for the 95
        model = PandasModel(df, rules=parse_rules(
            "status = fail => row red\nscore >= 90 => bg green"))
        assert _bg(model, 0, 1) == QColor("#2e4d33")   # green wins (later)
        assert _bg(model, 1, 1) == QColor("#5c2b2b")   # 40 stays row red
        assert _bg(model, 0, 0) == QColor("#5c2b2b")   # status cell: row red

    def test_order_of_application_row_rule_last_wins(self):
        df = pd.DataFrame({"status": ["fail"], "score": [95]})
        model = PandasModel(df, rules=parse_rules(
            "score >= 90 => bg green\nstatus = fail => row red"))
        assert _bg(model, 0, 1) == QColor("#5c2b2b")   # red wins (later)

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


class TestHiddenColumns:
    def test_hidden_column_is_dropped_from_the_view(self):
        df = pd.DataFrame({"shown": [1, 2], "helper": ["a", "b"], "x": [3, 4]})
        model = PandasModel(df, hidden=["helper"])
        assert model.columnCount() == 2
        headers = [model.headerData(c, Qt.Horizontal, Qt.DisplayRole)
                   for c in range(2)]
        assert headers == ["shown", "x"]
        assert model.data(model.index(0, 1), Qt.DisplayRole) == "3"  # 'x'

    def test_iconmap_reads_a_hidden_column(self):
        df = pd.DataFrame({"growth": [0.1, 0.2],
                           "sla": ["breach", "ok"]})
        model = PandasModel(
            df, hidden=["sla"],
            rules=parse_rules("growth iconmap sla: breach=✗ red, ok=✓ green"))
        assert model.columnCount() == 1
        assert model.data(model.index(0, 0), ICON_ROLE)[0] == "✗"
        assert model.data(model.index(1, 0), ICON_ROLE)[0] == "✓"

    def test_dataframe_export_excludes_hidden(self):
        df = pd.DataFrame({"a": [1], "secret": [2]})
        model = PandasModel(df, hidden=["secret"])
        assert list(model.dataframe().columns) == ["a"]

    def test_sort_maps_through_the_projection(self):
        df = pd.DataFrame({"h": [9, 9], "val": [2, 1]})
        model = PandasModel(df, hidden=["h"])
        model.sort(0, Qt.AscendingOrder)          # visible col 0 == 'val'
        assert [model.data(model.index(r, 0), Qt.DisplayRole)
                for r in range(2)] == ["1", "2"]

    def test_hide_accepts_a_glob(self):
        df = pd.DataFrame({"name": [1], "_tmp_a": [2], "_tmp_b": [3]})
        model = PandasModel(df, hidden=["_tmp_*"])
        assert model.columnCount() == 1
        assert model.headerData(0, Qt.Horizontal, Qt.DisplayRole) == "name"


class TestWildcardRules:
    def test_a_glob_rule_paints_every_matching_column(self):
        df = pd.DataFrame({"2020": [0.0, 10.0], "2021": [0.0, 10.0],
                           "name": ["a", "b"]})
        model = PandasModel(df, rules=parse_rules("20* scale blue"))
        assert isinstance(_bg(model, 1, 0), QColor)   # 2020
        assert isinstance(_bg(model, 1, 1), QColor)   # 2021
        assert _bg(model, 1, 2) is None               # name — untouched


def test_set_rules_swaps_formatting_live():
    model = PandasModel(pd.DataFrame({"a": [1, 2, 3]}))
    assert _bg(model, 0, 0) is None
    model.set_rules(parse_rules("a >= 1 => bg red"))
    assert _bg(model, 0, 0) == QColor("#5c2b2b")
    model.set_rules([])
    assert model._cf_active is False and _bg(model, 0, 0) is None


class TestFormatOnly:
    """`only` takes the value off the display and nowhere else."""

    def _model(self, rules_text):
        return PandasModel(pd.DataFrame({"units": [10, 20]}),
                           rules=parse_rules(rules_text))

    def test_the_display_goes_blank(self):
        model = self._model("units bar blue only")
        assert model.data(model.index(0, 0), Qt.DisplayRole) == ""

    def test_the_value_is_still_there_to_copy(self):
        """EditRole is what a copy or an export reads — hiding a value must
        not quietly drop it out of the clipboard."""
        model = self._model("units bar blue only")
        assert str(model.data(model.index(0, 0), Qt.EditRole)) == "10"

    def test_the_bar_is_still_drawn(self):
        model = self._model("units bar blue only")
        assert model.data(model.index(1, 0), BAR_ROLE) is not None

    def test_without_only_the_value_shows(self):
        model = self._model("units bar blue")
        assert model.data(model.index(0, 0), Qt.DisplayRole) == "10"


class TestLayoutRules:
    """`align` and `label` reach the grid through the model; `width` and
    `wrap` are geometry and belong to the view."""

    def _model(self, rules_text):
        frame = pd.DataFrame({"region": ["North"], "revenue": [482000]})
        return PandasModel(frame, rules=parse_rules(rules_text))

    def _align(self, model, row, col):
        return model.data(model.index(row, col), Qt.TextAlignmentRole)

    def test_an_align_rule_beats_the_dtype(self):
        """A number is right-aligned by habit — the rule is an instruction,
        so it wins."""
        model = self._model("revenue align left")
        assert self._align(model, 0, 1) == int(Qt.AlignLeft | Qt.AlignVCenter)

    def test_text_can_be_pushed_right(self):
        model = self._model("region align right")
        assert self._align(model, 0, 0) == int(Qt.AlignRight | Qt.AlignVCenter)

    def test_the_header_follows_its_column(self):
        """Or a right-aligned money column sits under a centred title."""
        model = self._model("revenue align center")
        assert model.headerData(1, Qt.Horizontal, Qt.TextAlignmentRole) == int(
            Qt.AlignHCenter | Qt.AlignVCenter)

    def test_a_label_renames_the_header_on_screen(self):
        model = self._model('revenue label "Revenue (£)"')
        assert model.headerData(1, Qt.Horizontal, Qt.DisplayRole) == "Revenue (£)"

    def test_the_real_name_is_still_reachable(self):
        """Every rule, sort and export goes by the real name, so the tooltip
        has to say what it is."""
        model = self._model('revenue label "Money"')
        assert "revenue" in model.headerData(1, Qt.Horizontal, Qt.ToolTipRole)

    def test_layout_alone_does_not_switch_on_per_cell_formatting(self):
        """The expensive path exists for rules that paint cells. Shaping a
        column says nothing about any cell, so it must not turn it on."""
        model = self._model("revenue width 200\nregion align left\nwrap")
        assert model._cf_active is False

    def test_the_view_can_read_the_width_and_the_wrap(self):
        model = self._model("revenue width 200\nwrap")
        assert model.column_layout(1).width == 200
        assert model.column_layout(0) is None
        assert model.wraps_text() is True
