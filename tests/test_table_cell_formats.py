"""Per-cell formatting: bold, italic, underline, fill, font colour and
alignment on any cell — Home ▸ Font, Ctrl+B/I/U. A format follows its cell,
saves with the table, travels with an in-app copy/paste, and never changes
a value or what flows on."""
import json

import pytest
from PySide6.QtCore import QItemSelection, QItemSelectionModel, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication

from flograph.core.sheet import ColumnSpec, Sheet, parse_sheet, sheet_to_dict
from flograph.core.sheet.cellfmt import clean, merged
from flograph.ui.spreadsheet import SheetModel, SpreadsheetView


class TestCore:
    def test_clean(self):
        assert clean({"b": True, "i": False, "fill": "#FDE68A",
                      "color": "red", "align": "middle", "x": 1}) == {
            "b": True, "fill": "#fde68a"}
        assert clean({}) is None and clean("bold") is None

    def test_merged(self):
        assert merged({"b": True}, {"i": True}) == {"b": True, "i": True}
        assert merged({"b": True}, {"b": False}) is None
        assert merged({"fill": "#ffffff"}, {"fill": None,
                                             "align": "center"}) == {
            "align": "center"}

    def test_follows_cells_and_saves(self):
        sheet = Sheet(columns=[ColumnSpec("A"), ColumnSpec("B")],
                      rows=[["b", "1"], ["a", "2"]])
        sheet.set_cell_format(0, 0, {"b": True})
        sheet.sort_by(0)
        assert sheet.styles == {(1, 0): {"b": True}}
        sheet.insert_column(0)
        assert sheet.styles == {(1, 1): {"b": True}}
        data = sheet_to_dict(sheet)
        assert data["styles"] == [[1, 1, {"b": True}]]
        assert parse_sheet(json.dumps(data)).styles == sheet.styles
        sheet.remove_rows([1])
        assert sheet.styles == {}

    def test_bad_styles_dropped(self):
        data = {"columns": ["A"], "rows": [["1"]],
                "styles": [[0, 0, {"b": True}], [5, 0, {"b": True}],
                           [0, 0], [0, 0, {"fill": "nope"}]]}
        assert parse_sheet(data).styles == {(0, 0): {"b": True}}


DATA = {"version": 2,
        "columns": [{"name": "Item"}, {"name": "Price", "type": "number"}],
        "rows": [["Pen", "2"], ["Pad", "5"], ["Ink", "-4"]]}


@pytest.fixture
def view(qtbot):
    model = SheetModel(json.dumps(DATA))
    view = SpreadsheetView()
    model.setParent(view)
    view.setModel(model)
    qtbot.addWidget(view)
    return view


def _select(view, r0, c0, r1, c1):
    model = view.model()
    view.setCurrentIndex(model.index(r0, c0))
    view.selectionModel().select(
        QItemSelection(model.index(r0, c0), model.index(r1, c1)),
        QItemSelectionModel.ClearAndSelect)


def _key(key, mods=Qt.NoModifier):
    return QKeyEvent(QKeyEvent.KeyPress, key, mods)


class TestModel:
    def test_roles(self, view):
        model = view.model()
        model.format_cells([(0, 0)], b=True, i=True, color="#3b82f6",
                           align="center")
        index = model.index(0, 0)
        font = index.data(Qt.FontRole)
        assert font.bold() and font.italic() and not font.underline()
        assert index.data(Qt.ForegroundRole).color().name() == "#3b82f6"
        assert index.data(Qt.TextAlignmentRole) == int(
            Qt.AlignHCenter | Qt.AlignVCenter)
        assert model.cell_source(0, 0) == "Pen"     # value untouched

    def test_fill_gets_readable_text(self, view):
        model = view.model()
        model.format_cells([(1, 1)], fill="#fde68a")
        index = model.index(1, 1)
        assert index.data(Qt.BackgroundRole).color().name() == "#fde68a"
        ink = index.data(Qt.ForegroundRole).color()
        assert ink.lightness() < 80                  # dark text on yellow

    def test_negative_red_still_wins_over_a_font_colour(self, view):
        model = view.model()
        model.set_column_format([1], {"kind": "number", "decimals": 0,
                                      "negative": "red"})
        model.format_cells([(2, 1)], color="#3b82f6")
        ink = model.index(2, 1).data(Qt.ForegroundRole).color().name()
        assert ink != "#3b82f6"

    def test_one_edit_and_clear(self, view):
        model = view.model()
        edits = []
        model.sheet_edited.connect(edits.append)
        model.format_cells([(0, 0), (1, 0)], b=True)
        assert len(edits) == 1
        model.format_cells([(0, 0), (1, 0)], b=True)   # no change
        assert len(edits) == 1
        model.clear_formats([(0, 0), (1, 0)])
        assert model.cell_format(0, 0) == {}


class TestView:
    def test_bold_toggles_with_the_current_cell(self, view):
        model = view.model()
        _select(view, 0, 0, 1, 1)
        view.actions.refresh()
        bold = view.actions["fmt_b"]
        assert not bold.isChecked()
        bold.trigger()                                # on, for all four
        assert all(model.cell_format(r, c).get("b")
                   for r in (0, 1) for c in (0, 1))
        view.actions.refresh()
        assert bold.isChecked()
        bold.trigger()                                # and off again
        assert model.cell_format(0, 0) == {}

    @pytest.mark.parametrize("key,name", [(Qt.Key_B, "fmt_b"),
                                          (Qt.Key_I, "fmt_i"),
                                          (Qt.Key_U, "fmt_u")])
    def test_keys(self, view, key, name):
        assert view.actions.for_key(_key(key, Qt.ControlModifier)) \
            is view.actions[name]

    def test_align_and_colours(self, view):
        model = view.model()
        _select(view, 0, 0, 0, 0)
        view.actions["align_right"].trigger()
        assert model.cell_format(0, 0)["align"] == "right"
        view.actions.refresh()
        view.actions["align_right"].trigger()         # again: back to usual
        assert "align" not in model.cell_format(0, 0)
        view.set_fill("#86efac")
        view.set_ink("#111827")
        assert model.cell_format(0, 0) == {"fill": "#86efac",
                                           "color": "#111827"}
        view.actions["fill_color"].trigger()          # repeats the last
        view.set_fill(None)
        assert model.cell_format(0, 0) == {"color": "#111827"}

    def test_copy_paste_carries_formats(self, view):
        model = view.model()
        model.format_cells([(0, 0)], b=True, fill="#fde68a")
        _select(view, 0, 0, 0, 0)
        view.copy_selection()
        edits = []
        model.sheet_edited.connect(edits.append)
        _select(view, 2, 0, 2, 0)
        view.paste_clipboard()
        assert len(edits) == 1                        # text + format, one step
        assert model.cell_source(2, 0) == "Pen"
        assert model.cell_format(2, 0) == {"b": True, "fill": "#fde68a"}

    def test_plain_copy_clears_formats_paste_values_keeps(self, view):
        model = view.model()
        model.format_cells([(2, 0)], b=True)
        _select(view, 1, 0, 1, 0)
        view.copy_selection()
        _select(view, 2, 0, 2, 0)
        view.paste_values()
        assert model.cell_format(2, 0) == {"b": True}
        view.paste_clipboard()
        assert model.cell_format(2, 0) == {}

    def test_paste_special_formats_only(self, view):
        model = view.model()
        model.format_cells([(0, 0)], i=True)
        _select(view, 0, 0, 0, 0)
        view.copy_selection()
        _select(view, 1, 0, 2, 0)
        assert view.paste_special(what="formats")
        assert model.cell_source(1, 0) == "Pad"       # values untouched
        assert model.cell_format(2, 0) == {"i": True}

    def test_outside_paste_leaves_formats(self, view):
        model = view.model()
        model.format_cells([(0, 0)], b=True)
        QApplication.clipboard().setText("Cap")
        _select(view, 0, 0, 0, 0)
        view.paste_clipboard()
        assert model.cell_source(0, 0) == "Cap"
        assert model.cell_format(0, 0) == {"b": True}

    def test_ribbon_fits(self, qtbot):
        from flograph.ui.spreadsheet import SheetWorkbench
        bench = SheetWorkbench(SheetModel(json.dumps(DATA)))
        qtbot.addWidget(bench)
        stack = bench.ribbon._stacks["full"]
        assert max(stack.widget(i).sizeHint().width()
                   for i in range(stack.count())) <= 1100


class TestKeepsPlace:
    def test_current_cell_and_selection_survive_a_reset(self, view):
        """A paste, sort or insert resets the model; the grid used to drop
        the current cell, so the next paste landed at A1."""
        model = view.model()
        _select(view, 1, 0, 2, 1)
        QApplication.clipboard().setText("x")
        view.paste_values()
        assert (view.currentIndex().row(), view.currentIndex().column()) \
            == (1, 0)
        assert view._selection_rect() == (1, 0, 2, 1)
        model.remove_rows_at([1, 2])              # shrinks under the selection
        assert view.currentIndex().row() == 0
