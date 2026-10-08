"""Cell notes: Excel's red corner and hover box. A note follows its cell
through sorts, moves, inserts and deletes, saves with the table, survives a
linked refresh, and never changes a value or what flows on."""
import json

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialogButtonBox

from flograph.core.sheet import ColumnSpec, Sheet, parse_sheet, sheet_to_dict
from flograph.core.sheet.engine import merge_linked_sheet
from flograph.ui.spreadsheet import SheetModel, SpreadsheetView
from flograph.ui.spreadsheet.note_dialog import NoteDialog
from flograph.ui.table_delegate import NOTE_ROLE


def _sheet():
    sheet = Sheet(columns=[ColumnSpec("Name"), ColumnSpec("N", "number"),
                           ColumnSpec("Z")],
                  rows=[["c", "3", "z1"], ["a", "1", "z2"], ["b", "2", "z3"]])
    sheet.set_note(0, 1, "three")       # on "3", row c
    sheet.set_note(2, 0, "bee")         # on "b"
    return sheet


def _where(sheet):
    """Each note against the value of the cell it sits on."""
    return {text: sheet.cell(r, c) for (r, c), text in sheet.notes.items()}


class TestCore:
    def test_set_and_clear(self):
        sheet = _sheet()
        assert sheet.note(0, 1) == "three"
        sheet.set_note(0, 1, "   ")
        assert (0, 1) not in sheet.notes
        sheet.set_note(9, 9, "off the grid")
        assert (9, 9) not in sheet.notes

    @pytest.mark.parametrize("op", [
        lambda s: s.sort_by(0),
        lambda s: s.sort_by(1, ascending=False),
        lambda s: s.sort_levels([(0, False, False)]),
        lambda s: s.move_rows([2], 0),
        lambda s: s.move_columns([0], 3),
        lambda s: s.insert_rows(1, 2),
        lambda s: s.insert_column(0),
        lambda s: s.set_rows([s.rows[2], s.rows[0], s.rows[1]]),
    ])
    def test_notes_follow_their_cells(self, op):
        sheet = _sheet()
        op(sheet)
        assert _where(sheet) == {"three": "3", "bee": "b"}

    def test_deleting_the_row_or_column_deletes_the_note(self):
        sheet = _sheet()
        sheet.remove_rows([0])
        assert _where(sheet) == {"bee": "b"}
        sheet = _sheet()
        sheet.remove_columns([0])
        assert _where(sheet) == {"three": "3"}
        sheet = _sheet()
        sheet.remove_rows([1])                  # a row between: shift up
        assert _where(sheet) == {"three": "3", "bee": "b"}

    def test_saved_and_read_back(self):
        sheet = _sheet()
        data = sheet_to_dict(sheet)
        assert data["notes"] == [[0, 1, "three"], [2, 0, "bee"]]
        assert parse_sheet(json.dumps(data)).notes == sheet.notes
        assert "notes" not in sheet_to_dict(Sheet([ColumnSpec("A")], [[""]]))
        assert sheet.copy().notes == sheet.notes

    def test_bad_notes_are_dropped_on_read(self):
        data = sheet_to_dict(_sheet())
        data["notes"] += [[99, 0, "gone"], [0, 0, ""], ["x", 0, "no"],
                          [True, 0, "bool"], [0, 0]]
        assert set(parse_sheet(data).notes) == {(0, 1), (2, 0)}

    def test_linked_refresh_keeps_notes_by_column_name(self):
        stored = _sheet()
        base = Sheet(columns=[ColumnSpec("N"), ColumnSpec("Name")],
                     rows=[["3", "c"], ["1", "a"]])
        merged = merge_linked_sheet(base, stored)
        # "three" was on N, row 0 -> N is now column 0; "bee" was on row 2,
        # which the refreshed table no longer has
        assert merged.notes == {(0, 0): "three"}


DATA = {"version": 2,
        "columns": [{"name": "Item"}, {"name": "Price", "type": "number"}],
        "rows": [["Pen", "2"], ["Pad", "=1/0"], ["Ink", "4"]]}


@pytest.fixture
def view(qtbot):
    model = SheetModel(json.dumps(DATA))
    view = SpreadsheetView()
    model.setParent(view)
    view.setModel(model)
    qtbot.addWidget(view)
    return view


class TestModelAndView:
    def test_set_note_is_one_edit_and_shows(self, view):
        model = view.model()
        edits = []
        model.sheet_edited.connect(edits.append)
        model.set_note(0, 1, "Agreed on 3 Oct")
        assert len(edits) == 1
        assert edits[0]["notes"] == [[0, 1, "Agreed on 3 Oct"]]
        index = model.index(0, 1)
        assert index.data(NOTE_ROLE) == "Agreed on 3 Oct"
        assert "Agreed on 3 Oct" in index.data(Qt.ToolTipRole)
        assert model.cell_source(0, 1) == "2"     # the value is untouched
        model.set_note(0, 1, "Agreed on 3 Oct")   # unchanged: no edit
        assert len(edits) == 1

    def test_note_and_error_share_the_tooltip(self, view):
        model = view.model()
        model.set_note(1, 1, "<check> this")
        tip = model.index(1, 1).data(Qt.ToolTipRole)
        assert "&lt;check&gt; this" in tip and "<hr>" in tip

    def test_sorting_carries_the_note(self, view):
        model = view.model()
        model.set_note(2, 0, "ink note")
        model.sort_by(0)                            # Ink, Pad, Pen
        assert model.note(0, 0) == "ink note"

    def test_undo_restores_notes(self, view):
        model = view.model()
        model.set_note(0, 0, "x")
        before = model.sheet_dict()
        model.delete_notes([(0, 0)])
        assert model.note_cells() == []
        model.set_sheet(before)                     # what undo does
        assert model.note(0, 0) == "x"

    def test_delete_and_next_note_actions(self, view):
        model = view.model()
        model.set_note(0, 0, "first")
        model.set_note(2, 1, "second")
        view.setCurrentIndex(model.index(0, 1))
        view.actions.refresh()
        assert view.actions["note_next"].isEnabled()
        view.actions["note_next"].trigger()
        assert (view.currentIndex().row(), view.currentIndex().column()) \
            == (2, 1)
        view.actions["note_next"].trigger()          # wraps round
        assert view.currentIndex().row() == 0
        view.select_special("notes")
        assert view.note_targets() == [(0, 0), (2, 1)]
        view.actions["note_delete"].trigger()
        assert model.note_cells() == []

    def test_shortcut(self, view):
        assert view.actions["note_edit"].shortcut().toString() == "Shift+F2"


class TestDialog:
    def test_new_note(self, view, qtbot):
        model = view.model()
        dialog = NoteDialog(view, 0, 1)
        qtbot.addWidget(dialog)
        assert dialog.windowTitle() == "New Note — Price, row 1"
        dialog.text.setPlainText("  Ask Sam  ")
        dialog.buttons.button(QDialogButtonBox.Save).click()
        assert dialog.chosen() == "Ask Sam"
        model.set_note(0, 1, dialog.chosen())
        assert model.note(0, 1) == "Ask Sam"

    def test_edit_and_delete(self, view, qtbot):
        model = view.model()
        model.set_note(0, 1, "old")
        dialog = NoteDialog(view, 0, 1)
        qtbot.addWidget(dialog)
        assert dialog.windowTitle().startswith("Edit Note")
        assert dialog.text.toPlainText() == "old"
        delete = [b for b in dialog.buttons.buttons()
                  if b.text() == "Delete Note"][0]
        delete.click()
        assert dialog.result() and dialog.chosen() == ""

    def test_ribbon_has_a_notes_group(self, qtbot):
        from flograph.ui.spreadsheet import SheetWorkbench
        from flograph.ui.spreadsheet.ribbon import RibbonButton
        bench = SheetWorkbench(SheetModel(json.dumps(DATA)))
        qtbot.addWidget(bench)
        labels = {b.text() for b in bench.ribbon.findChildren(RibbonButton)}
        assert {"New Note", "Delete Note", "Next Note"} <= labels

    def test_every_tab_fits_the_full_editor(self, qtbot):
        """The ribbon switches to one line of icons when its widest tab
        doesn't fit; the full editor (and a wide tile) should get labels."""
        from flograph.ui.spreadsheet import SheetWorkbench
        bench = SheetWorkbench(SheetModel(json.dumps(DATA)))
        qtbot.addWidget(bench)
        stack = bench.ribbon._stacks["full"]
        widths = [stack.widget(i).sizeHint().width()
                  for i in range(stack.count())]
        assert max(widths) <= 1100, widths
