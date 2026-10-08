"""The Table's spreadsheet experience: the ribbon, Submit (edits held until
asked), the shared commands behind the ribbon / menus / keyboard, and the
grid features they reach — dropdown lists, freeze panes, filtering, find
and replace, moving rows and columns."""
import json

import pytest
from PySide6.QtCore import QItemSelectionModel, QPoint, Qt
from PySide6.QtGui import QKeyEvent, QUndoStack
from PySide6.QtCore import QEvent

from flograph.core import Graph, NodeRegistry
from flograph.ui.canvas import NodeGraphScene
from flograph.ui.spreadsheet import (SheetModel, SheetRibbon, SheetWorkbench,
                                     SpreadsheetView, binding)


@pytest.fixture(scope="module")
def registry():
    reg = NodeRegistry()
    reg.load_builtins()
    return reg


def _data(rows=None, columns=("a", "b", "c")):
    rows = rows if rows is not None else [
        ["1", "x", ""], ["2", "y", ""], ["3", "z", ""], ["4", "w", ""]]
    return {"version": 2,
            "columns": [{"name": n, "type": "auto"} for n in columns],
            "rows": rows}


@pytest.fixture
def env(qtbot, registry):
    graph = Graph()
    stack = QUndoStack()
    scene = NodeGraphScene(graph, stack, registry=registry)
    yield graph, stack, scene
    stack.clear()


def _table(graph, registry, data=None, mode="live"):
    node = graph.add_node(registry.instantiate("flograph.io.table"))
    graph.set_param(node.id, "data", json.dumps(data or _data()))
    graph.set_param(node.id, "apply", mode)
    return node


def _view(qtbot, data=None):
    model = SheetModel(data or _data())
    view = SpreadsheetView()
    model.setParent(view)
    view.setModel(model)
    view.resize(500, 300)
    qtbot.addWidget(view)
    return view, model


def _pick(view, rows, cols):
    model = view.model()
    sel = view.selectionModel()
    sel.clearSelection()
    sel.setCurrentIndex(model.index(rows[0], cols[0]),
                        QItemSelectionModel.NoUpdate)
    for r in rows:
        for c in cols:
            sel.select(model.index(r, c), QItemSelectionModel.Select)


def _key(key, mods=Qt.NoModifier, text=""):
    return QKeyEvent(QEvent.KeyPress, key, mods, text)


# --------------------------------------------------------------- submit

class TestSubmit:
    def test_held_edit_goes_to_the_draft_and_dirties_nothing(self, env,
                                                             registry):
        graph, stack, scene = env
        node = _table(graph, registry, mode="submit")
        graph.nodes[node.id].dirty = False
        before = node.params["data"]
        item = scene.node_items[node.id]
        item._table_model.setData(item._table_model.index(0, 0), "99")
        assert node.params["data"] == before         # the flow is untouched
        assert json.loads(node.params["draft"])["rows"][0][0] == "99"
        assert not graph.nodes[node.id].dirty         # nothing to re-run
        assert binding.describe_pending(node) == "1 change not submitted"

    def test_submit_moves_the_draft_in_as_one_undo_step_and_asks_to_run(
            self, env, registry):
        graph, stack, scene = env
        node = _table(graph, registry, mode="submit")
        item = scene.node_items[node.id]
        model = item._table_model
        model.setData(model.index(0, 0), "99")
        model.setData(model.index(1, 0), "98")
        asked = []
        scene.sheet_submitted.connect(asked.append)
        item._table_widget.actions["submit"].trigger()
        rows = json.loads(node.params["data"])["rows"]
        assert [r[0] for r in rows[:2]] == ["99", "98"]
        assert node.params["draft"] == ""
        assert asked == [node.id]
        stack.undo()                       # one step takes the submit back
        assert json.loads(node.params["data"])["rows"][0][0] == "1"
        assert json.loads(node.params["draft"])["rows"][1][0] == "98"

    def test_discard_goes_back_to_the_submitted_table(self, env, registry):
        graph, stack, scene = env
        node = _table(graph, registry, mode="submit")
        item = scene.node_items[node.id]
        item._table_model.setData(item._table_model.index(0, 0), "99")
        item._table_widget.actions["discard"].trigger()
        assert node.params["draft"] == ""
        assert item._table_model.cell_source(0, 0) == "1"

    def test_typing_back_to_the_submitted_value_clears_the_draft(
            self, env, registry):
        graph, stack, scene = env
        node = _table(graph, registry, mode="submit")
        model = scene.node_items[node.id]._table_model
        model.setData(model.index(0, 0), "99")
        model.setData(model.index(0, 0), "1")
        assert node.params["draft"] == ""

    def test_turning_auto_apply_on_submits_whats_waiting(self, env,
                                                         registry):
        graph, stack, scene = env
        node = _table(graph, registry, mode="submit")
        item = scene.node_items[node.id]
        item._table_model.setData(item._table_model.index(0, 0), "99")
        asked = []
        scene.sheet_submitted.connect(asked.append)
        item._table_widget.actions["auto"].setChecked(True)
        assert node.params["apply"] == "live"
        assert json.loads(node.params["data"])["rows"][0][0] == "99"
        assert asked == [node.id]

    def test_live_edits_still_go_straight_in(self, env, registry):
        graph, stack, scene = env
        node = _table(graph, registry)
        model = scene.node_items[node.id]._table_model
        model.setData(model.index(0, 0), "99")
        assert json.loads(node.params["data"])["rows"][0][0] == "99"
        assert node.params["draft"] == ""

    def test_the_card_shows_the_draft_after_a_rebuild(self, env, registry):
        graph, stack, scene = env
        draft = _data()
        draft["rows"][0][0] = "77"
        node = _table(graph, registry, mode="submit")
        graph.set_param(node.id, "draft", json.dumps(draft))
        assert scene.node_items[node.id]._table_model.cell_source(0, 0) == "77"

    def test_ribbon_shows_submit_only_while_held(self, env, registry, qtbot):
        graph, stack, scene = env
        live = _table(graph, registry)
        held = _table(graph, registry, mode="submit")
        live_ribbon = scene.node_items[live.id]._table_ribbon
        held_item = scene.node_items[held.id]
        assert isinstance(live_ribbon, SheetRibbon)
        assert live_ribbon._submit.isHidden()
        held_item._table_model.setData(held_item._table_model.index(0, 0), "5")
        ribbon = held_item._table_ribbon
        assert not ribbon._submit.isHidden()
        assert not ribbon._pending.isHidden()
        assert "1 change not submitted" in ribbon._pending_text.text()
        assert held_item._table_widget.actions["auto"].iconText() == \
            "Auto-apply: Off"

    def test_f9_submits(self, env, registry):
        graph, stack, scene = env
        node = _table(graph, registry, mode="submit")
        item = scene.node_items[node.id]
        item._table_model.setData(item._table_model.index(0, 0), "99")
        item._table_widget.keyPressEvent(_key(Qt.Key_F9))
        assert node.params["draft"] == ""


# ------------------------------------------------------------- commands

class TestCommands:
    def test_every_action_explains_itself(self, qtbot):
        view, _model = _view(qtbot)
        for name in view.actions.names():
            action = view.actions[name]
            assert action.toolTip(), name
            assert action.property("explanation"), name

    def test_every_ribbon_button_has_a_tooltip(self, qtbot):
        model = SheetModel(_data())
        bench = SheetWorkbench(model)
        qtbot.addWidget(bench)
        from flograph.ui.spreadsheet.ribbon import RibbonButton
        buttons = bench.ribbon.findChildren(RibbonButton)
        assert len(buttons) > 40
        for button in buttons:
            assert button.toolTip(), button.text()

    @pytest.mark.parametrize("key,mods,name", [
        (Qt.Key_F9, Qt.NoModifier, "submit"),
        (Qt.Key_R, Qt.ControlModifier, "fill_right"),
        (Qt.Key_D, Qt.ControlModifier, "fill_down"),
        (Qt.Key_Equal, Qt.ControlModifier | Qt.ShiftModifier, "insert_smart"),
        (Qt.Key_Plus, Qt.ControlModifier | Qt.ShiftModifier, "insert_smart"),
        (Qt.Key_Minus, Qt.ControlModifier, "delete_smart"),
        (Qt.Key_Space, Qt.ShiftModifier, "select_row"),
        (Qt.Key_Space, Qt.ControlModifier, "select_col"),
        (Qt.Key_Up, Qt.AltModifier | Qt.ShiftModifier, "row_up"),
        (Qt.Key_F, Qt.ControlModifier, "find"),
        (Qt.Key_V, Qt.ControlModifier | Qt.ShiftModifier, "paste_values"),
    ])
    def test_keys_reach_their_action(self, qtbot, key, mods, name):
        view, _model = _view(qtbot)
        action = view.actions.for_key(_key(key, mods))
        assert action is view.actions[name]

    def test_insert_rows_adds_as_many_as_selected(self, qtbot):
        view, model = _view(qtbot)
        _pick(view, [1, 2], [0])
        view.insert_rows(below=False)
        assert model.rowCount() == 6
        assert [r[0] for r in model.sheet.rows] == ["1", "", "", "2", "3", "4"]

    def test_whole_row_selected_column_commands_mean_this_column(
            self, qtbot):
        view, model = _view(qtbot)
        view.setCurrentIndex(model.index(0, 1))
        view.select_rows([0])
        view.insert_columns(right=True)
        assert model.columnCount() == 4      # one column, not three
        assert model.sheet.column_names()[:2] == ["a", "b"]

    def test_delete_rows_shifts_formulas_like_excel(self, qtbot):
        view, model = _view(qtbot, _data(rows=[["1", "=A3", ""],
                                               ["2", "", ""],
                                               ["3", "", ""]]))
        _pick(view, [1], [0])
        view.delete_rows()
        assert model.cell_source(0, 1) == "=A2"
        assert model.value_text(0, 1) == "3"

    def test_move_rows_keeps_them_selected(self, qtbot):
        view, model = _view(qtbot)
        view.select_rows([2])
        view.actions["row_up"].trigger()
        assert [r[0] for r in model.sheet.rows] == ["1", "3", "2", "4"]
        assert view.selected_rows() == [1]
        view.actions["row_up"].trigger()
        assert [r[0] for r in model.sheet.rows] == ["3", "1", "2", "4"]

    def test_move_columns(self, qtbot):
        view, model = _view(qtbot)
        view.select_columns([0])
        view.actions["col_move_right"].trigger()
        assert model.sheet.column_names() == ["b", "a", "c"]
        assert view.selected_columns() == [1]

    def test_fill_right_shifts_references(self, qtbot):
        view, model = _view(qtbot, _data(rows=[["=A2", "", ""],
                                               ["5", "6", "7"]]))
        _pick(view, [0], [0, 1, 2])
        view.fill_right_selection()
        assert [model.cell_source(0, c) for c in range(3)] == [
            "=A2", "=B2", "=C2"]

    def test_jump_goes_to_the_edge_of_the_data(self, qtbot):
        view, model = _view(qtbot, _data(rows=[["1", "", ""], ["2", "", ""],
                                               ["", "", ""], ["4", "", ""]]))
        view.setCurrentIndex(model.index(0, 0))
        view.jump(1, 0)
        assert view.currentIndex().row() == 1
        view.jump(1, 0)
        assert view.currentIndex().row() == 3

    def test_labels_count_what_they_act_on(self, qtbot):
        view, _model = _view(qtbot)
        view.select_rows([0, 1, 2])
        view.actions.refresh()
        assert view.actions["row_delete"].text() == "Delete 3 Rows"
        view.select_rows([0])
        view.actions.refresh()
        assert view.actions["row_delete"].text() == "Delete Row"

    def test_menus_build_for_cells_rows_and_columns(self, qtbot, monkeypatch):
        from flograph.ui.spreadsheet import menus
        shown = []
        monkeypatch.setattr(menus, "exec_menu",
                            lambda menu, w, p: shown.append(menu))
        view, _model = _view(qtbot)
        view.setCurrentIndex(view.model().index(0, 0))
        menus.cell_menu(view, view.viewport(), QPoint(5, 5))
        menus.row_menu(view, view.verticalHeader(), QPoint(5, 5))
        menus.column_menu(view, view.horizontalHeader(), QPoint(5, 5))
        assert len(shown) == 3
        texts = [a.text() for a in shown[0].actions()]
        assert "Paste Values" in texts and "Fill Down" in texts


# --------------------------------------------------------------- features

class TestGridFeatures:
    def test_filter_hides_rows_but_not_from_the_table(self, qtbot):
        view, model = _view(qtbot)
        view.set_column_filter(1, {"x", "z"})
        assert [view.row_filtered(r) for r in range(4)] == [
            False, True, False, True]
        assert model.rowCount() == 4               # only the view changed
        assert view.is_column_filtered(1)
        view.clear_filters()
        assert not any(view.isRowHidden(r) for r in range(4))

    def test_deleting_filtered_selection_skips_hidden_rows(self, qtbot):
        view, model = _view(qtbot)
        view.set_column_filter(1, {"x", "z"})
        view.select_rows([0, 1, 2])
        view.delete_rows()
        assert [r[0] for r in model.sheet.rows] == ["2", "4"]

    def test_filter_popup_applies_the_ticked_values(self, qtbot):
        from flograph.ui.spreadsheet.filter import FilterPopup
        view, _model = _view(qtbot)
        popup = FilterPopup(view, 1)
        qtbot.addWidget(popup)
        for item in popup._values():
            if item.data(Qt.UserRole) == "y":
                item.setCheckState(Qt.Unchecked)
        popup._apply()
        assert view.column_filter(1) == {"x", "z", "w"}

    def test_freeze_makes_panes_and_saves_with_the_sheet(self, qtbot):
        view, model = _view(qtbot)
        view.setCurrentIndex(model.index(1, 1))
        view.freeze_panes()
        assert model.freeze == (1, 1)
        assert model.sheet_dict()["freeze"] == {"rows": 1, "cols": 1}
        panes = view.frozen_panes.panes()
        assert set(panes) == {"cols", "rows", "corner"}
        # the frozen cells are hidden in the grid and shown by the panes
        assert view.isRowHidden(0) and view.isColumnHidden(0)
        assert not panes["corner"].isRowHidden(0)
        assert view.frozen_panes.pane_for(model.index(0, 0)) is \
            panes["corner"]
        assert view.frozen_panes.pane_for(model.index(2, 0)) is panes["cols"]
        assert view.frozen_panes.pane_for(model.index(2, 2)) is None
        view.unfreeze()
        assert not view.isRowHidden(0) and not view.isColumnHidden(0)

    def test_arrow_keys_walk_into_frozen_rows(self, qtbot):
        view, model = _view(qtbot)
        view.freeze_top_row()
        view.setCurrentIndex(model.index(1, 1))
        index = view.moveCursor(view.CursorAction.MoveUp, Qt.NoModifier)
        assert (index.row(), index.column()) == (0, 1)

    def test_dropdown_list_and_strict_validation(self, qtbot, monkeypatch):
        view, model = _view(qtbot)
        model.set_column_choices(1, ["x", "y"], strict=True)
        assert model.column_choices(1) == (["x", "y"], True)
        assert model.index(2, 1).data(Qt.BackgroundRole) is not None  # "z"
        from flograph.ui.spreadsheet import dropdown
        picked = []
        monkeypatch.setattr(dropdown, "exec_menu",
                            lambda menu, w, p: picked.append(menu))
        view.setCurrentIndex(model.index(2, 1))
        view.open_cell_dropdown()
        menu = picked[0]
        choice = next(a for a in menu.actions() if a.text() == "y")
        choice.trigger()
        assert model.cell_source(2, 1) == "y"

    def test_find_and_replace(self, qtbot):
        view, model = _view(qtbot)
        assert view.find_next("z")
        assert (view.currentIndex().row(), view.currentIndex().column()) == \
            (2, 1)
        edits = []
        model.sheet_edited.connect(edits.append)
        assert model.replace_all("x", "X", match_case=True) == 1
        assert model.cell_source(0, 1) == "X"
        assert len(edits) == 1                  # one change, one undo step

    def test_show_formulas_is_a_view_setting(self, qtbot):
        view, model = _view(qtbot, _data(rows=[["2", "=A1*2", ""]]))
        view.actions["show_formulas"].setChecked(True)
        assert view.show_formulas
        assert view.itemDelegate().show_formulas
        assert "freeze" not in model.sheet_dict()
        assert model.value_text(0, 1) == "4"

    def test_paste_values_brings_shown_values(self, qtbot):
        from PySide6.QtWidgets import QApplication
        view, model = _view(qtbot, _data(rows=[["2", "=A1*2", ""],
                                               ["", "", ""]]))
        _pick(view, [0], [1])
        view.copy_selection()
        _pick(view, [1], [1])
        view.paste_values()
        assert model.cell_source(1, 1) == "4"
        QApplication.clipboard().clear()


class TestRightClickReachesTheMenu:
    """Sent as real events, not by calling the builders — the cell menu was
    once wired to a signal a scroll area's viewport never emits."""

    def _right_click(self, widget, pos):
        from PySide6.QtCore import QCoreApplication
        from PySide6.QtGui import QContextMenuEvent
        event = QContextMenuEvent(QContextMenuEvent.Mouse, pos,
                                  widget.mapToGlobal(pos))
        QCoreApplication.sendEvent(widget, event)

    def test_cell_row_and_header(self, qtbot, monkeypatch):
        from flograph.ui.spreadsheet import menus
        shown = []
        monkeypatch.setattr(menus, "exec_menu",
                            lambda menu, w, p: shown.append(menu))
        view, model = _view(qtbot)
        view.show()
        qtbot.waitExposed(view)
        cell = view.visualRect(model.index(2, 1)).center()
        self._right_click(view.viewport(), cell)
        assert len(shown) == 1
        assert view.currentIndex().row() == 2      # the click moved there
        self._right_click(view.verticalHeader().viewport(), QPoint(5, 5))
        self._right_click(view.horizontalHeader().viewport(), QPoint(5, 5))
        assert len(shown) == 3

    def test_frozen_pane_cell(self, qtbot, monkeypatch):
        from flograph.ui.spreadsheet import menus
        shown = []
        monkeypatch.setattr(menus, "exec_menu",
                            lambda menu, w, p: shown.append(menu))
        view, model = _view(qtbot)
        view.show()
        qtbot.waitExposed(view)
        view.freeze_first_column()
        pane = view.frozen_panes.panes()["cols"]
        cell = pane.visualRect(model.index(1, 0)).center()
        self._right_click(pane.viewport(), cell)
        assert len(shown) == 1


class TestCardFormulaBar:
    def test_the_card_has_a_formula_bar_that_follows_the_cell(
            self, env, registry):
        graph, stack, scene = env
        node = _table(graph, registry, _data(rows=[["2", "=A1*3", ""]]))
        item = scene.node_items[node.id]
        bar = item._table_formula_bar
        assert bar is not None
        grid, model = item._table_widget, item._table_model
        grid.setCurrentIndex(model.index(0, 1))
        assert bar.cell_label.text() == "B1"
        assert bar.edit.text() == "=A1*3"
        # typing in the bar and committing writes the cell
        bar.edit.setText("=A1*4")
        bar.commit()
        assert json.loads(node.params["data"])["rows"][0][1] == "=A1*4"
        # an undo from elsewhere shows through
        stack.undo()
        assert bar.edit.text() == "=A1*3"


def test_right_click_offers_the_full_editor_on_a_card(env, registry,
                                                      monkeypatch):
    from flograph.ui.spreadsheet import menus
    shown = []
    monkeypatch.setattr(menus, "exec_menu",
                        lambda menu, w, p: shown.append(menu))
    graph, stack, scene = env
    node = _table(graph, registry)
    grid = scene.node_items[node.id]._table_widget
    grid.setCurrentIndex(grid.model().index(0, 0))
    menus.cell_menu(grid, grid.viewport(), QPoint(5, 5))
    menus.column_menu(grid, grid.horizontalHeader(), QPoint(5, 5))
    for menu in shown:
        assert grid.actions["open_editor"] in menu.actions()


def test_a_bare_grid_does_not_offer_an_editor_it_has_not_got(
        qtbot, monkeypatch):
    from flograph.ui.spreadsheet import menus
    shown = []
    monkeypatch.setattr(menus, "exec_menu",
                        lambda menu, w, p: shown.append(menu))
    view, _model = _view(qtbot)
    view.setCurrentIndex(view.model().index(0, 0))
    menus.cell_menu(view, view.viewport(), QPoint(5, 5))
    assert view.actions["open_editor"] not in shown[0].actions()


def test_an_auto_ribbon_lets_the_window_narrow_and_goes_compact(qtbot):
    """The full ribbon is wide; if its pages set the window's minimum width
    the window could never get narrow enough to switch, and the labels
    were squeezed to 'Fi…wn' instead."""
    bench = SheetWorkbench(SheetModel(_data()))
    qtbot.addWidget(bench)
    bench.resize(560, 400)
    bench.show()
    qtbot.waitExposed(bench)
    ribbon = bench.ribbon
    assert ribbon._stacks["full"].minimumSizeHint().width() == 0
    ribbon._choose_size()
    assert bench.width() == 560
    assert ribbon.active_size == "compact"
