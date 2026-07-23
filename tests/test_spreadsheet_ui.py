"""Spreadsheet widgets: model roles, editing, clipboard, card undo
granularity, and the pop-out editor dialog."""
import json

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QUndoStack
from PySide6.QtWidgets import QApplication

from flograph.core import Graph, NodeRegistry
from flograph.core.sheet import sheet_to_json
from flograph.ui.spreadsheet import (MIME_CELLS, SheetEditorDialog, SheetModel,
                                     SpreadsheetView, block_to_tsv,
                                     parse_paste_text)


def make_model(columns=None, rows=None, types=None):
    columns = columns or ["A", "B"]
    types = types or ["auto"] * len(columns)
    rows = rows or [["", ""] for _ in range(2)]
    return SheetModel({
        "version": 2,
        "columns": [{"name": n, "type": t} for n, t in zip(columns, types)],
        "rows": rows,
    })


class TestSheetModel:
    def test_display_shows_computed_edit_shows_source(self, qtbot):
        model = make_model(rows=[["2", "=A1*3"]])
        index = model.index(0, 1)
        assert index.data(Qt.DisplayRole) == "6"
        assert index.data(Qt.EditRole) == "=A1*3"
        assert index.data(Qt.ToolTipRole) == "=A1*3"

    def test_error_cell_role_and_tooltip(self, qtbot):
        model = make_model(rows=[["=1/0", ""]])
        index = model.index(0, 0)
        assert index.data(Qt.DisplayRole) == "#DIV/0!"
        assert "#DIV/0!" in index.data(Qt.ToolTipRole)

    def test_invalid_typed_entry_flags_background(self, qtbot):
        model = make_model(types=["integer", "auto"], rows=[["3.7", ""]])
        assert model.index(0, 0).data(Qt.BackgroundRole) is not None
        assert model.index(0, 1).data(Qt.BackgroundRole) is None
        assert "whole number" in model.index(0, 0).data(Qt.ToolTipRole)

    def test_bool_column_uses_checkboxes(self, qtbot):
        model = make_model(types=["bool", "auto"], rows=[["TRUE", ""]])
        index = model.index(0, 0)
        assert index.data(Qt.CheckStateRole) == Qt.Checked
        assert index.data(Qt.DisplayRole) == ""
        model.setData(index, Qt.Unchecked.value, Qt.CheckStateRole)
        assert model.cell_source(0, 0) == "FALSE"

    def test_setdata_recalculates_dependents(self, qtbot):
        model = make_model(rows=[["2", "=A1+1"]])
        model.setData(model.index(0, 0), "10")
        assert model.index(0, 1).data(Qt.DisplayRole) == "11"

    def test_each_mutation_emits_sheet_edited_once(self, qtbot):
        model = make_model()
        seen = []
        model.sheet_edited.connect(seen.append)
        model.setData(model.index(0, 0), "x")
        model.insert_rows_at(1)
        model.set_cells((0, 0), [["a", "b"], ["c", "d"]])
        assert len(seen) == 3

    def test_insert_and_remove_at_arbitrary_index(self, qtbot):
        model = make_model(rows=[["1", "2"], ["3", "4"]])
        model.insert_rows_at(1)
        assert model.sheet.rows[1] == ["", ""]
        model.insert_columns_at(1)
        assert model.sheet.column_names() == ["A", "C", "B"]
        model.remove_columns_at([1])
        model.remove_rows_at([1])
        assert model.sheet.rows == [["1", "2"], ["3", "4"]]

    def test_never_removes_last_row_or_column(self, qtbot):
        model = make_model(columns=["A"], rows=[["x"]])
        model.remove_rows_at([0])
        model.remove_columns_at([0])
        assert model.rowCount() == 1 and model.columnCount() == 1

    def test_fill_down_translates_formulas(self, qtbot):
        model = make_model(rows=[["1", "=A1*2"], ["2", ""], ["3", ""]])
        model.fill_down(0, 2, [1])
        assert model.cell_source(1, 1) == "=A2*2"
        assert model.cell_source(2, 1) == "=A3*2"
        assert model.index(2, 1).data(Qt.DisplayRole) == "6"

    def test_set_cells_grows_grid(self, qtbot):
        model = make_model()
        model.set_cells((1, 1), [["a", "b"], ["c", "d"]])
        assert model.rowCount() == 3 and model.columnCount() == 3
        assert model.cell_source(2, 2) == "d"

    def test_sort_by_column(self, qtbot):
        model = make_model(rows=[["10", "x"], ["2", "y"]])
        model.sort_by(0, ascending=True)
        assert [r[0] for r in model.sheet.rows] == ["2", "10"]

    def test_changing_column_to_date_normalizes_readable_values(self, qtbot):
        model = make_model(rows=[["23/07/2026", ""], ["Jul 5, 2026", ""],
                                 ["gibberish", ""]])
        model.set_column_type(0, "date")
        assert model.cell_source(0, 0) == "2026-07-23"
        assert model.cell_source(1, 0) == "2026-07-05"
        assert model.cell_source(2, 0) == "gibberish"   # stays, flagged red
        assert model.index(2, 0).data(Qt.BackgroundRole) is not None

    def test_set_column_widths_emits_once_and_skips_no_ops(self, qtbot):
        model = make_model()
        seen = []
        model.sheet_edited.connect(seen.append)
        model.set_column_widths({0: 120, 1: 90})
        model.set_column_widths({0: 120, 1: 90})   # unchanged: no emit
        assert len(seen) == 1
        assert seen[0]["columns"][0]["width"] == 120

    def test_rename_column_rewrites_named_refs(self, qtbot):
        model = make_model(rows=[["2", "=[@A]*3"]])
        model.rename_column(0, "Price")
        assert model.cell_source(0, 1) == "=[@Price]*3"
        assert model.index(0, 1).data(Qt.DisplayRole) == "6"

    def test_fill_down_keeps_named_refs_stable(self, qtbot):
        model = make_model(rows=[["2", "=[@A]*2"], ["3", ""], ["4", ""]])
        model.fill_down(0, 2, [1])
        assert model.cell_source(2, 1) == "=[@A]*2"   # no positional shift
        assert model.index(2, 1).data(Qt.DisplayRole) == "8"

    def test_promote_row_to_header(self, qtbot):
        model = make_model(rows=[["Price", ""], ["1.5", "2"]])
        model.promote_row_to_header(0)
        assert model.sheet.column_names() == ["Price", "B"]   # blank keeps old
        assert model.sheet.rows == [["1.5", "2"]]

    def test_promote_last_row_clears_instead_of_removing(self, qtbot):
        model = make_model(rows=[["x", "y"]])
        model.promote_row_to_header(0)
        assert model.sheet.column_names() == ["x", "y"]
        assert model.sheet.rows == [["", ""]]

    def test_read_only_refuses_every_mutation(self, qtbot):
        model = make_model(rows=[["1", "2"]])
        model.set_read_only(True)
        seen = []
        model.sheet_edited.connect(seen.append)
        assert not model.setData(model.index(0, 0), "x")
        model.set_cells((0, 0), [["y"]])
        model.clear_cells([(0, 0)])
        model.insert_rows_at(0)
        model.remove_columns_at([0])
        model.sort_by(0)
        model.set_column_widths({0: 99})
        assert model.sheet.rows == [["1", "2"]]
        assert not seen
        assert not model.flags(model.index(0, 0)) & Qt.ItemIsEditable
        # set_sheet (sync-in from the linked input) still works
        model.set_sheet({"columns": ["Z"], "rows": [["9"]]})
        assert model.sheet.column_names() == ["Z"]

    def test_set_sheet_same_content_is_a_no_op(self, qtbot):
        model = make_model()
        seen = []
        model.modelReset.connect(lambda: seen.append(1))
        model.set_sheet(model.sheet_dict())
        assert not seen


class TestClipboardHelpers:
    def test_tsv_round_trip_with_special_cells(self):
        rows = [["plain", "with\ttab"], ["with\nnewline", 'with "quote"']]
        assert parse_paste_text(block_to_tsv(rows)) == rows

    def test_excel_trailing_newline_and_crlf(self):
        assert parse_paste_text("a\tb\r\nc\td\r\n") == [["a", "b"], ["c", "d"]]

    def test_ragged_rows_are_squared_off(self):
        assert parse_paste_text("a\tb\nc") == [["a", "b"], ["c", ""]]


@pytest.fixture
def view(qtbot):
    view = SpreadsheetView()
    model = make_model(columns=["A", "B", "C"],
                       rows=[["1", "2", "=A1+B1"], ["4", "5", ""]])
    model.setParent(view)   # keep C++ destruction ordered at teardown
    view.setModel(model)
    qtbot.addWidget(view)
    return view


def select_rect(view, r0, c0, r1, c1):
    model = view.model()
    view.setCurrentIndex(model.index(r0, c0))
    selection = view.selectionModel()
    selection.clearSelection()
    from PySide6.QtCore import QItemSelection, QItemSelectionModel
    selection.select(QItemSelection(model.index(r0, c0), model.index(r1, c1)),
                     QItemSelectionModel.Select)


class TestSpreadsheetView:
    def test_copy_puts_values_and_sources_on_clipboard(self, view):
        select_rect(view, 0, 0, 0, 2)
        view.copy_selection()
        mime = QApplication.clipboard().mimeData()
        assert mime.text() == "1\t2\t3"   # computed values for the outside world
        assert mime.hasFormat(MIME_CELLS)
        payload = json.loads(bytes(mime.data(MIME_CELLS).data()).decode())
        assert payload["cells"] == [["1", "2", "=A1+B1"]]

    def test_internal_paste_shifts_relative_refs(self, view):
        select_rect(view, 0, 2, 0, 2)   # the =A1+B1 cell
        view.copy_selection()
        select_rect(view, 1, 2, 1, 2)
        view.paste_clipboard()
        model = view.model()
        assert model.cell_source(1, 2) == "=A2+B2"
        assert model.index(1, 2).data(Qt.DisplayRole) == "9"

    def test_plain_text_paste_grows_grid(self, view):
        QApplication.clipboard().setText("x\ty\nz\tw\n")
        select_rect(view, 1, 2, 1, 2)
        view.paste_clipboard()
        model = view.model()
        assert model.rowCount() == 3 and model.columnCount() == 4
        assert model.cell_source(2, 3) == "w"

    def test_single_cell_paste_replicates_over_selection(self, view):
        QApplication.clipboard().setText("9")
        select_rect(view, 0, 0, 1, 1)
        view.paste_clipboard()
        model = view.model()
        assert [model.cell_source(r, c) for r in (0, 1) for c in (0, 1)] == ["9"] * 4

    def test_delete_clears_selection(self, view):
        select_rect(view, 0, 0, 1, 1)
        view.delete_selection()
        model = view.model()
        assert model.cell_source(0, 0) == "" and model.cell_source(1, 1) == ""
        assert model.cell_source(0, 2) == "=A1+B1"   # untouched

    def test_fill_down_selection(self, view):
        select_rect(view, 0, 2, 1, 2)
        view.fill_down_selection()
        assert view.model().cell_source(1, 2) == "=A2+B2"

    def test_autosize_columns_fits_content_and_header(self, view):
        model = view.model()
        model.setData(model.index(0, 0), "a much longer cell value here")
        model.rename_column(1, "a rather long column header")
        view.setColumnWidth(0, 40)
        view.setColumnWidth(1, 40)
        view.autosize_columns()
        assert view.columnWidth(0) > 40
        assert view.columnWidth(1) > 40   # header text counts too

    def test_autosize_from_border_double_click_uses_selection(self, view):
        select_rect(view, 0, 0, 1, 1)
        view.setColumnWidth(0, 40)
        view.setColumnWidth(1, 40)
        view.model().setData(view.model().index(0, 1), "wide wide wide wide")
        view._autosize_from_handle(0)   # border of a selected column
        assert view.columnWidth(1) > 40

    def test_manual_resize_persists_width_into_sheet(self, view):
        view.setColumnWidth(0, 137)
        view._persist_pending_widths()   # what the debounce timer fires
        assert view.model().sheet.columns[0].width == 137
        assert view.model().sheet_dict()["columns"][0]["width"] == 137

    def test_stored_widths_apply_on_load(self, qtbot, monkeypatch):
        from flograph.ui.spreadsheet import view as view_module
        monkeypatch.setattr(view_module, "autosize_default_enabled",
                            lambda: False)   # auto-fit (the default) skips stored widths
        fresh = SpreadsheetView()
        model = make_model()
        model.sheet.columns[0].width = 143
        model.setParent(fresh)
        fresh.setModel(model)
        qtbot.addWidget(fresh)
        assert fresh.columnWidth(0) == 143

    def test_date_formats_setting_reaches_the_core(self):
        from flograph.core.sheet import extra_date_formats, normalize_date
        from flograph.ui.spreadsheet import (date_formats_setting,
                                             set_date_formats_setting)
        previous = date_formats_setting()
        try:
            set_date_formats_setting("%Y.%m.%d, %d|%m|%Y")
            assert extra_date_formats() == ("%Y.%m.%d", "%d|%m|%Y")
            assert normalize_date("23|07|2026") == "2026-07-23"
        finally:
            set_date_formats_setting(previous)

    def test_autosize_button_persists_widths(self, view):
        view.model().setData(view.model().index(0, 0), "a long cell value here")
        view.autosize_columns()
        assert view.model().sheet.columns[0].width == view.columnWidth(0)

    def test_autosize_default_setting_overrides_stored_widths(self, qtbot, monkeypatch):
        from flograph.ui.spreadsheet import view as view_module
        monkeypatch.setattr(view_module, "autosize_default_enabled",
                            lambda: True)
        fresh = SpreadsheetView()
        model = make_model()
        model.sheet.columns[0].width = 400   # stored, but auto mode wins
        model.setParent(fresh)
        fresh.setModel(model)
        qtbot.addWidget(fresh)
        assert fresh.columnWidth(0) < 400
        # and the automatic fit did not write widths back
        assert model.sheet.columns[0].width == 400


class TestFormulaCompleter:
    @staticmethod
    def make(qtbot, text, columns=("Price", "Qty")):
        from PySide6.QtWidgets import QLineEdit
        from flograph.ui.spreadsheet import FormulaCompleter
        edit = QLineEdit()
        qtbot.addWidget(edit)
        completer = FormulaCompleter(edit, lambda: list(columns))
        edit.setText(text)
        edit.setCursorPosition(len(text))
        edit.textEdited.emit(text)   # what typing would fire
        return edit, completer

    def test_function_suggestions_after_two_letters(self, qtbot):
        edit, fc = self.make(qtbot, "=su")
        assert fc._completer.popup().isVisible()
        assert fc._completer.currentCompletion() == "SUM"

    def test_single_letter_stays_quiet(self, qtbot):
        edit, fc = self.make(qtbot, "=a")   # probably an A1 ref
        assert not fc._completer.popup().isVisible()

    def test_no_suggestions_outside_formulas(self, qtbot):
        edit, fc = self.make(qtbot, "supper")
        assert not fc._completer.popup().isVisible()

    def test_function_insert_appends_paren(self, qtbot):
        edit, fc = self.make(qtbot, "=1+su")
        fc._insert("SUM")
        assert edit.text() == "=1+SUM("
        assert edit.cursorPosition() == len("=1+SUM(")

    def test_true_inserts_bare(self, qtbot):
        edit, fc = self.make(qtbot, "=tr")
        fc._insert("TRUE")
        assert edit.text() == "=TRUE"

    def test_column_suggestions_inside_bracket(self, qtbot):
        edit, fc = self.make(qtbot, "=[@pr")
        assert fc._completer.popup().isVisible()
        fc._insert("Price")
        assert edit.text() == "=[@Price]"

    def test_plain_bracket_completes_whole_column(self, qtbot):
        edit, fc = self.make(qtbot, "=SUM([q")
        fc._insert("Qty")
        assert edit.text() == "=SUM([Qty]"

    def test_enter_on_popup_accepts_highlighted(self, qtbot):
        from PySide6.QtTest import QTest
        edit, fc = self.make(qtbot, "=su")
        popup = fc._completer.popup()
        assert popup.isVisible()
        QTest.keyClick(popup, Qt.Key_Return)
        assert edit.text() == "=SUM("
        assert not popup.isVisible()

    def test_tab_on_popup_accepts_highlighted(self, qtbot):
        from PySide6.QtTest import QTest
        edit, fc = self.make(qtbot, "=[@q")
        QTest.keyClick(fc._completer.popup(), Qt.Key_Tab)
        assert edit.text() == "=[@Qty]"


class TestCodeEditorCompletion:
    def test_enter_and_tab_insert_the_suggestion(self, qtbot):
        from PySide6.QtCore import QStringListModel
        from PySide6.QtTest import QTest
        from flograph.ui.editor.code_editor import CodeEditor
        from flograph.ui.editor.completion import CompletionController

        # torn down explicitly at the end (deleteLater + drain) — leaving
        # the jedi controller to the GC segfaults later tests
        editor = CodeEditor()
        controller = CompletionController(editor)
        try:
            for key, expected in ((Qt.Key_Return, "foo_bar"),
                                  (Qt.Key_Tab, "foo_bar")):
                editor.setPlainText("foo")
                cursor = editor.textCursor()
                cursor.movePosition(cursor.MoveOperation.End)
                editor.setTextCursor(cursor)
                controller._suffixes = {"foo_bar": "_bar"}
                controller._completer.setModel(
                    QStringListModel(["foo_bar"], controller._completer))
                controller._completer.setCompletionPrefix("foo")
                controller._completer.complete(editor.cursorRect())
                popup = controller._completer.popup()
                popup.setCurrentIndex(
                    controller._completer.completionModel().index(0, 0))
                assert popup.isVisible()
                QTest.keyClick(popup, key)
                # the fix: the suggestion lands instead of indent/newline
                assert editor.toPlainText() == expected
                assert not popup.isVisible()
        finally:
            controller.shutdown()
            editor.deleteLater()
            QApplication.processEvents()
            QApplication.processEvents()


@pytest.fixture(scope="module")
def registry():
    reg = NodeRegistry()
    reg.load_builtins()
    return reg


class TestCardIntegration:
    def test_cell_edits_are_separate_undo_steps(self, qtbot, registry):
        from flograph.ui.canvas import NodeGraphScene
        graph = Graph()
        stack = QUndoStack()
        scene = NodeGraphScene(graph, stack, registry=registry)
        node = graph.add_node(registry.instantiate("flograph.io.table"))
        model = scene.node_items[node.id]._table_model

        index_before = stack.index()
        model.setData(model.index(0, 0), "first")
        model.setData(model.index(0, 1), "second")
        assert stack.index() == index_before + 2   # merge=False held

        stack.undo()
        data = json.loads(graph.node(node.id).params["data"])
        assert data["rows"][0] == ["first", ""]
        stack.undo()
        data = json.loads(graph.node(node.id).params["data"])
        assert data["rows"][0] == ["", ""]
        # free the pushed commands while graph/scene are alive — leaving
        # them to ~QUndoStack at GC time double-frees under some GC orders
        stack.clear()

    def test_data_param_is_hidden_from_properties(self, registry):
        spec = registry.get("flograph.io.table")
        assert spec.param("data").hidden
        assert not spec.param("width").hidden


class TestSheetEditorDialog:
    def test_dialog_local_undo_and_result(self, qtbot):
        sheet_json = sheet_to_json(make_model().sheet)
        dialog = SheetEditorDialog(sheet_json, title="t")
        qtbot.addWidget(dialog)
        model = dialog.model
        model.setData(model.index(0, 0), "hello")
        model.setData(model.index(0, 1), "world")
        assert dialog.sheet_dict()["rows"][0] == ["hello", "world"]

        dialog.undo_stack.undo()
        assert dialog.sheet_dict()["rows"][0] == ["hello", ""]
        dialog.undo_stack.undo()
        assert dialog.sheet_dict()["rows"][0] == ["", ""]
        dialog.undo_stack.redo()
        assert dialog.sheet_dict()["rows"][0] == ["hello", ""]

        # edit after undo: the before-snapshot must be the undone state
        model.setData(model.index(1, 0), "next")
        dialog.undo_stack.undo()
        assert dialog.sheet_dict()["rows"][0] == ["hello", ""]
        assert dialog.sheet_dict()["rows"][1] == ["", ""]

    def test_formula_bar_tracks_current_cell(self, qtbot):
        model = make_model(rows=[["2", "=A1*3"]])
        dialog = SheetEditorDialog(model.sheet_dict(), title="t")
        qtbot.addWidget(dialog)
        dialog.view.setCurrentIndex(dialog.model.index(0, 1))
        assert dialog._cell_label.text() == "B1"
        assert dialog._formula_edit.text() == "=A1*3"

    def test_fx_button_shows_formula_reference(self, qtbot):
        dialog = SheetEditorDialog(sheet_to_json(make_model().sheet), title="t")
        qtbot.addWidget(dialog)
        dialog._show_formula_reference()
        reference = dialog._reference_dialog
        assert reference is not None and reference.isVisible()
        browser = reference.layout().itemAt(0).widget()
        assert "SUM(A1:A10)" in browser.toPlainText()
        assert "IF(condition" in browser.toPlainText()
        # second click reuses the same window
        dialog._show_formula_reference()
        assert dialog._reference_dialog is reference

    def test_enter_while_editing_commits_cell_not_ok_button(self, qtbot):
        from PySide6.QtTest import QTest
        from PySide6.QtWidgets import QLineEdit

        dialog = SheetEditorDialog(sheet_to_json(make_model().sheet), title="t")
        qtbot.addWidget(dialog)
        dialog.show()
        index = dialog.model.index(0, 0)
        dialog.view.setCurrentIndex(index)
        dialog.view.edit(index)
        editor = dialog.view.findChild(QLineEdit)
        assert editor is not None
        QTest.keyClicks(editor, "42")
        QTest.keyClick(editor, Qt.Key_Return)
        assert dialog.isVisible()   # Enter must not "click" OK
        assert dialog.model.cell_source(0, 0) == "42"
        assert dialog.view.currentIndex().row() == 1   # and moved down
        dialog.close()

    def test_dialog_buttons_are_not_default_even_after_show(self, qtbot):
        dialog = SheetEditorDialog(sheet_to_json(make_model().sheet), title="t")
        qtbot.addWidget(dialog)
        dialog.show()   # QDialogButtonBox re-promotes OK to default on Show
        qtbot.waitUntil(lambda: not any(
            b.isDefault() or b.autoDefault() for b in dialog._buttons.buttons()))
        dialog.close()

    def test_stray_enter_never_closes_the_dialog(self, qtbot):
        from PySide6.QtTest import QTest
        dialog = SheetEditorDialog(sheet_to_json(make_model().sheet), title="t")
        qtbot.addWidget(dialog)
        dialog.show()
        # worst case: the key reaches the dialog itself unconsumed
        QTest.keyClick(dialog, Qt.Key_Return)
        QTest.keyClick(dialog, Qt.Key_Enter)
        assert dialog.isVisible()
        dialog.close()

    def test_apply_callback_receives_sheet(self, qtbot):
        dialog = SheetEditorDialog(sheet_to_json(make_model().sheet), title="t")
        qtbot.addWidget(dialog)
        seen = []
        dialog.on_apply = seen.append
        dialog.model.setData(dialog.model.index(0, 0), "x")
        dialog._apply()
        assert seen and seen[0]["rows"][0][0] == "x"
