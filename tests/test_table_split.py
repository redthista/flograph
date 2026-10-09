"""Text to Columns…: one column split into several, at a character or at
fixed positions, with a preview and one undo step."""
import json

import pytest
from PySide6.QtWidgets import QDialogButtonBox

from flograph.core.sheet import split as s
from flograph.ui.spreadsheet import SheetModel, SpreadsheetView
from flograph.ui.spreadsheet.split_dialog import SplitDialog


class TestCore:
    @pytest.mark.parametrize("text,seps,kw,want", [
        ("a,b,c", [","], {}, ["a", "b", "c"]),
        ("a, b ,c", [","], {}, ["a", "b", "c"]),
        ("a, b", [","], {"trim": False}, ["a", " b"]),
        ("a  b", [" "], {}, ["a", "", "b"]),
        ("a  b", [" "], {"merge": True}, ["a", "b"]),
        ("a;b,c", [",", ";"], {}, ["a", "b", "c"]),
        ("x - y - z", [" - "], {}, ["x", "y", "z"]),
        ('"Smith, J",42', [","], {}, ["Smith, J", "42"]),
        ('"Smith, J", 42', [","], {}, ["Smith, J", "42"]),
        ('"say ""hi""",x', [","], {}, ['say "hi"', "x"]),
        ('"Smith, J",42', [","], {"quote": ""}, ['"Smith', 'J"', "42"]),
        ("plain", [","], {}, ["plain"]),
        ("", [","], {}, [""]),
    ])
    def test_delimited(self, text, seps, kw, want):
        assert s.split_delimited(text, seps, **kw) == want

    def test_fixed(self):
        assert s.split_fixed("ABC12345XY", [3, 8]) == ["ABC", "12345", "XY"]
        assert s.split_fixed("AB", [3, 8]) == ["AB", "", ""]
        assert s.split_fixed("AB C", [2], trim=False) == ["AB", " C"]

    def test_parse_breaks(self):
        assert s.parse_breaks("8, 3 3") == [3, 8]
        assert isinstance(s.parse_breaks(""), str)
        assert isinstance(s.parse_breaks("x"), str)
        assert isinstance(s.parse_breaks("0, 2"), str)

    def test_split_values_pads(self):
        assert s.split_values(["a,b", "c", "", "d,e,f"]) == [
            ["a", "b", ""], ["c", "", ""], ["", "", ""], ["d", "e", "f"]]

    def test_at_most_max_parts(self):
        row = s.split_values([",".join("x" * 80)])[0]
        assert len(row) == s.MAX_PARTS

    def test_guess(self):
        assert s.guess_separator(["a;b", "c;d", "e"]) == ";"
        assert s.guess_separator(["Ann Lee", "Bob Ray"]) == " "
        assert s.guess_separator(["a,b c", "d,e f"]) == ","
        assert s.guess_separator(["one", "two"]) is None

    def test_new_names(self):
        assert s.new_names("Name", 3, ["Name", "Age"], keep=False) == [
            "Name", "Name 2", "Name 3"]
        assert s.new_names("Name", 2, ["Name", "Name 1"], keep=True) == [
            "Name 2", "Name 3"]


DATA = {"version": 2,
        "columns": [{"name": "Name"}, {"name": "Age", "type": "integer"},
                    {"name": "Label"}],
        "rows": [["Lee, Ann", "30", '=[@Name]&"!"'],
                 ["Ray, Bob", "41", "=B2*2"],
                 ["Solo", "7", ""]],
        "notes": [[0, 1, "age note"]]}


@pytest.fixture
def view(qtbot):
    model = SheetModel(json.dumps(DATA))
    view = SpreadsheetView()
    model.setParent(view)
    view.setModel(model)
    qtbot.addWidget(view)
    view.setCurrentIndex(model.index(0, 0))
    return view


class TestModel:
    def test_split_replacing_the_column(self, view):
        model = view.model()
        edits = []
        model.sheet_edited.connect(edits.append)
        parts = [["Lee", "Ann"], ["Ray", "Bob"], ["Solo", ""]]
        model.split_column(0, parts, ["Surname", "First"], keep=False)
        assert len(edits) == 1
        assert model.sheet.column_names() == ["Surname", "First", "Age",
                                              "Label"]
        assert [r[:2] for r in model.sheet.rows] == parts
        # formulas follow: the rename, and the A1 shift past the new column
        assert model.cell_source(0, 3) == '=[@Surname]&"!"'
        assert model.cell_source(1, 3) == "=C2*2"
        assert model.note(0, 2) == "age note"

    def test_split_keeping_the_column(self, view):
        model = view.model()
        model.split_column(0, [["Lee", "Ann"], ["Ray", "Bob"], ["Solo", ""]],
                           ["Name 1", "Name 2"], keep=True)
        assert model.sheet.column_names() == ["Name", "Name 1", "Name 2",
                                              "Age", "Label"]
        assert model.sheet.rows[0][:3] == ["Lee, Ann", "Lee", "Ann"]


class TestDialog:
    def test_guesses_and_previews(self, view, qtbot):
        dialog = SplitDialog(view, 0)
        qtbot.addWidget(dialog)
        assert dialog._seps["comma"].isChecked()
        assert dialog.names.text() == "Name, Name 2"
        assert "Makes 2 columns from 3 rows" in dialog.status.text()
        assert dialog.preview.item(0, 1).text() == "Ann"
        assert dialog.buttons.button(QDialogButtonBox.Ok).isEnabled()

    def test_typed_names_and_clash(self, view, qtbot):
        dialog = SplitDialog(view, 0)
        qtbot.addWidget(dialog)
        dialog.names.setText("Surname")
        dialog._names_edited("Surname")
        assert dialog.chosen_names(2) == ["Surname", "Name 2"]
        dialog.names.setText("Surname, Age")
        dialog._names_edited("")
        assert "already a column called “Age”" in dialog.status.text()
        assert not dialog.buttons.button(QDialogButtonBox.Ok).isEnabled()

    def test_fixed_and_nothing_to_split(self, view, qtbot):
        dialog = SplitDialog(view, 0)
        qtbot.addWidget(dialog)
        dialog.breaks.setText("3")                  # switches to fixed
        assert dialog.fixed.isChecked()
        assert dialog.preview.item(0, 0).text() == "Lee"
        dialog.breaks.setText("")
        assert "Type where to break" in dialog.status.text()
        dialog.delimited.setChecked(True)
        dialog._seps["comma"].setChecked(False)
        assert "at least one separator" in dialog.status.text()
        dialog._seps["tab"].setChecked(True)
        assert "Nothing to split" in dialog.status.text()
        assert not dialog.buttons.button(QDialogButtonBox.Ok).isEnabled()

    def test_ribbon_and_width(self, qtbot):
        from flograph.ui.spreadsheet import SheetWorkbench
        from flograph.ui.spreadsheet.ribbon import RibbonButton
        bench = SheetWorkbench(SheetModel(json.dumps(DATA)))
        qtbot.addWidget(bench)
        labels = {b.text() for b in bench.ribbon.findChildren(RibbonButton)}
        assert {"Text to Columns", "Rename"} <= labels
        stack = bench.ribbon._stacks["full"]
        assert max(stack.widget(i).sizeHint().width()
                   for i in range(stack.count())) <= 1100
