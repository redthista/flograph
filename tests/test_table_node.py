"""The Table card: an on-canvas editable spreadsheet with a DataFrame out."""
import json

import pandas as pd
import pytest
from PySide6.QtGui import QUndoStack

from flograph.core import Graph, NodeRegistry
from flograph.ui.canvas import NodeGraphScene


@pytest.fixture(scope="module")
def registry():
    reg = NodeRegistry()
    reg.load_builtins()
    return reg


@pytest.fixture
def env(qtbot, registry):
    graph = Graph()
    stack = QUndoStack()
    scene = NodeGraphScene(graph, stack, registry=registry)
    return graph, stack, scene


def test_table_is_registered_with_optional_input_and_one_output(registry):
    spec = registry.get("flograph.io.table")
    # "helper" is the empty slot helper tables grow from (flograph issue #108)
    assert [p.name for p in spec.inputs] == ["table", "helper"]
    assert spec.inputs[0].optional   # runs fine unconnected
    assert spec.inputs[1].spare
    assert [p.name for p in spec.outputs] == ["table"]
    assert spec.param("data") is not None
    assert spec.param("width") is not None
    assert spec.param("height") is not None


def test_table_item_embeds_a_grid_widget(env, registry):
    graph, stack, scene = env
    node = graph.add_node(registry.instantiate("flograph.io.table"))
    item = scene.node_items[node.id]
    assert item.table
    assert item._table_widget is not None
    assert item._table_widget.model().rowCount() == 2
    assert item._table_widget.model().columnCount() == 2
    assert list(item.output_ports) == ["table"]
    assert list(item.input_ports) == ["table", "helper"]


def test_table_runs_and_emits_dataframe(qtbot, env, registry):
    graph, stack, scene = env
    node = graph.add_node(registry.instantiate("flograph.io.table"))
    graph.set_param(node.id, "data", json.dumps({
        "columns": ["a", "b"],
        "rows": [["1", "2"], ["3", "4"]],
    }))
    from flograph.engine import ExecutionEngine
    engine = ExecutionEngine(graph)
    with qtbot.waitSignal(engine.run_finished, timeout=5000) as blocker:
        engine.run_all()
    assert blocker.args[0]
    out = engine.cache.outputs_for(node.id)["table"]
    assert isinstance(out, pd.DataFrame)
    assert list(out.columns) == ["a", "b"]
    assert out["a"].tolist() == [1, 3]  # numeric coercion


def test_table_keeps_non_numeric_column_as_strings(registry):
    from flograph.core import compile_run
    from tests.conftest import FakeContext

    spec = registry.get("flograph.io.table")
    run = compile_run(spec.source, "test-table")
    params = spec.default_params()
    params["data"] = json.dumps({
        "columns": ["name", "n"],
        "rows": [["north", "1"], ["south", "2"]],
    })
    out = run(FakeContext(params=params))
    assert out["name"].tolist() == ["north", "south"]
    assert out["n"].tolist() == [1, 2]


def test_table_edit_commits_and_is_undoable(env, registry):
    graph, stack, scene = env
    node = graph.add_node(registry.instantiate("flograph.io.table"))
    item = scene.node_items[node.id]
    model = item._table_model
    model.setData(model.index(0, 0), "hello")
    assert json.loads(graph.node(node.id).params["data"])["rows"][0][0] == "hello"
    stack.undo()
    assert json.loads(graph.node(node.id).params["data"])["rows"][0][0] != "hello"


def test_table_add_and_remove_row_and_column(env, registry):
    graph, stack, scene = env
    node = graph.add_node(registry.instantiate("flograph.io.table"))
    item = scene.node_items[node.id]

    item._table_add_row()
    data = json.loads(graph.node(node.id).params["data"])
    assert len(data["rows"]) == 3

    item._table_add_column()
    data = json.loads(graph.node(node.id).params["data"])
    assert len(data["columns"]) == 3
    assert all(len(row) == 3 for row in data["rows"])

    item._table_remove_column()
    item._table_remove_row()
    data = json.loads(graph.node(node.id).params["data"])
    assert len(data["columns"]) == 2
    assert len(data["rows"]) == 2


def test_table_wont_remove_last_row_or_column(env, registry):
    graph, stack, scene = env
    node = graph.add_node(registry.instantiate("flograph.io.table"))
    item = scene.node_items[node.id]
    for _ in range(5):
        item._table_remove_row()
        item._table_remove_column()
    data = json.loads(graph.node(node.id).params["data"])
    assert len(data["rows"]) == 1
    assert len(data["columns"]) == 1


def _table_with_rows(graph, registry, rows):
    node = graph.add_node(registry.instantiate("flograph.io.table"))
    graph.set_param(node.id, "data", json.dumps({
        "columns": ["a", "b", "c"], "rows": rows}))
    return node


def _select(grid, rows, cols):
    from PySide6.QtCore import QItemSelectionModel
    model = grid.model()
    grid.selectionModel().clearSelection()
    for r in rows:
        for c in cols:
            grid.selectionModel().select(model.index(r, c),
                                         QItemSelectionModel.Select)


def test_minus_row_removes_the_selected_rows_not_the_last(env, registry):
    graph, stack, scene = env
    node = _table_with_rows(graph, registry,
                            [["1", "x", ""], ["2", "y", ""], ["3", "z", ""],
                             ["4", "w", ""]])
    item = scene.node_items[node.id]
    _select(item._table_widget, [1], [0])
    item._table_remove_row()
    rows = json.loads(graph.node(node.id).params["data"])["rows"]
    assert [r[0] for r in rows] == ["1", "3", "4"]

    # rows 0 and 2 picked with ctrl-click: both go, the one between stays
    _select(item._table_widget, [0, 2], [1])
    item._table_remove_row()
    rows = json.loads(graph.node(node.id).params["data"])["rows"]
    assert [r[0] for r in rows] == ["3"]


def test_minus_col_removes_the_selected_column(env, registry):
    graph, stack, scene = env
    node = _table_with_rows(graph, registry, [["1", "2", "3"]])
    item = scene.node_items[node.id]
    _select(item._table_widget, [0], [0])
    item._table_remove_column()
    columns = json.loads(graph.node(node.id).params["data"])["columns"]
    assert [c["name"] for c in columns] == ["b", "c"]


def test_plus_row_inserts_below_the_selection(env, registry):
    graph, stack, scene = env
    node = _table_with_rows(graph, registry,
                            [["1", "", ""], ["2", "", ""], ["3", "", ""]])
    item = scene.node_items[node.id]
    _select(item._table_widget, [0], [0])
    item._table_add_row()
    rows = json.loads(graph.node(node.id).params["data"])["rows"]
    assert [r[0] for r in rows] == ["1", "", "2", "3"]


def test_table_resize_updates_width_and_height(env, registry):
    graph, stack, scene = env
    node = graph.add_node(registry.instantiate("flograph.io.table"))
    item = scene.node_items[node.id]
    graph.set_param(node.id, "width", 500)
    graph.set_param(node.id, "height", 300)
    assert item.width == 500.0
    assert item.body_height == 300.0
    graph.set_param(node.id, "width", 10)   # clamped to minimum
    assert item.width == 220.0


def test_table_card_keeps_its_grid_inside_the_frame_when_short(env, registry):
    """Reported: dragging Table (or Show Table) short let the grid and the
    +Row/+Col buttons spill out through the card's edge."""
    from PySide6.QtWidgets import QGraphicsItem
    graph, _stack, scene = env
    node = graph.add_node(registry.instantiate("flograph.io.table"))
    item = scene.node_items[node.id]
    assert item._table_proxy.flags() & QGraphicsItem.ItemClipsToShape
    graph.set_param(node.id, "height", 10)   # clamped to the floor
    assert item.body_height >= 160


def test_table_card_fits_its_ribbon_and_never_spills_past_the_edge(
        env, registry):
    """Reported: the inner panel ran out past the card's right edge — the
    ribbon's tab row asked for more than the card's default width, and the
    proxy grew to its minimum. A new card is wide enough for the ribbon, and
    one dragged narrower keeps its panel inside the frame."""
    graph, _stack, scene = env
    node = graph.add_node(registry.instantiate("flograph.io.table"))
    item = scene.node_items[node.id]
    proxy = item._table_proxy
    assert proxy.widget().minimumSizeHint().width() <= item.width
    for width in (item.width, 250, 220):
        graph.set_param(node.id, "width", width)
        assert proxy.geometry().right() <= item.width + 0.5


def test_a_new_table_cards_auto_apply_button_shows_at_once(env, registry):
    """Reported: the ⚡ Auto-apply button stayed hidden on a new Table card
    until it was resized — the ribbon asked its node before the card had a
    scene to find it in."""
    graph, _stack, scene = env
    node = graph.add_node(registry.instantiate("flograph.io.table"))
    item = scene.node_items[node.id]
    assert not item._table_ribbon._auto.isHidden()


def test_table_ribbon_wraps_rather_than_clipping(env, registry):
    """The card's compact ribbon wraps its icon row when the card is dragged
    narrow, rather than clipping buttons off the edge."""
    from flograph.ui.flow_layout import FlowLayout
    graph, _stack, scene = env
    node = graph.add_node(registry.instantiate("flograph.io.table"))
    item = scene.node_items[node.id]
    ribbon = item._table_ribbon
    page = ribbon._stacks["compact"].widget(0)
    layout = page.layout()
    assert isinstance(layout, FlowLayout)
    assert layout.hasHeightForWidth()
    assert layout.heightForWidth(120) > layout.heightForWidth(1000)


def test_table_serialization_round_trip(env, registry):
    from flograph.core.serialization import graph_from_dict, graph_to_dict
    graph, stack, scene = env
    node = graph.add_node(registry.instantiate("flograph.io.table"))
    graph.set_param(node.id, "data", json.dumps({
        "columns": ["x"], "rows": [["9"]],
    }))
    restored = graph_from_dict(graph_to_dict(graph), registry)
    assert json.loads(restored.nodes[node.id].params["data"]) == {
        "columns": ["x"], "rows": [["9"]],
    }


def _run_table(registry, data):
    from flograph.core import compile_run
    from tests.conftest import FakeContext

    spec = registry.get("flograph.io.table")
    run = compile_run(spec.source, "test-table")
    params = spec.default_params()
    params["data"] = json.dumps(data)
    return run(FakeContext(params=params))


def test_table_formulas_compute(registry):
    out = _run_table(registry, {
        "version": 2,
        "columns": [{"name": "Price", "type": "number"},
                    {"name": "Qty", "type": "integer"},
                    {"name": "Total", "type": "auto"}],
        "rows": [["10.5", "3", "=A1*B1"],
                 ["4", "5", "=A2*B2"],
                 ["", "", "=SUM(C1:C2)"]],
    })
    assert out["Total"].tolist() == [31.5, 20.0, 51.5]


def test_table_column_types_become_dtypes(registry):
    out = _run_table(registry, {
        "version": 2,
        "columns": [{"name": "n", "type": "number"},
                    {"name": "i", "type": "integer"},
                    {"name": "t", "type": "text"},
                    {"name": "d", "type": "date"},
                    {"name": "b", "type": "bool"}],
        "rows": [["1.5", "2", "007", "2026-01-02", "TRUE"],
                 ["", "", "", "", "false"]],
    })
    assert str(out["n"].dtype) == "Float64"
    assert str(out["i"].dtype) == "Int64"
    assert str(out["t"].dtype) == "string"
    assert str(out["d"].dtype).startswith("datetime64")
    assert str(out["b"].dtype) == "boolean"
    assert out["t"].tolist()[0] == "007"     # no silent 007 -> 7
    assert out["i"][0] == 2 and pd.isna(out["i"][1])
    assert out["b"].tolist() == [True, False]


def test_table_typed_mismatch_degrades_to_missing(registry):
    out = _run_table(registry, {
        "version": 2,
        "columns": [{"name": "i", "type": "integer"}],
        "rows": [["3"], ["oops"]],
    })
    assert out["i"][0] == 3
    assert pd.isna(out["i"][1])


def test_table_formula_error_fails_run_naming_cell(registry):
    with pytest.raises(ValueError, match=r"formula error in B1.*#DIV/0!"):
        _run_table(registry, {
            "version": 2,
            "columns": [{"name": "a", "type": "auto"},
                        {"name": "b", "type": "auto"}],
            "rows": [["1", "=A1/0"]],
        })


def test_table_mixed_auto_column_stays_text(registry):
    out = _run_table(registry, {
        "version": 2,
        "columns": [{"name": "m", "type": "auto"}],
        "rows": [["1"], ["abc"]],
    })
    assert out["m"].tolist() == ["1", "abc"]


def test_table_ports_accept_dataframe_wires(registry):
    """Both sides are dataframe-typed: the output feeds dataframe inputs and
    the optional input accepts dataframe outputs (the linked-table mode)."""
    from flograph.core import PortType, can_connect
    spec = registry.get("flograph.io.table")
    assert can_connect(PortType.DATAFRAME, spec.outputs[0].type)
    assert can_connect(PortType.DATAFRAME, spec.inputs[0].type)


def test_table_linked_input_mirrors_upstream_data(registry):
    from flograph.core import compile_run
    from tests.conftest import FakeContext

    spec = registry.get("flograph.io.table")
    run = compile_run(spec.source, "test-table")
    params = spec.default_params()   # stored cells stay dormant
    upstream = pd.DataFrame({
        "name": ["north", "south"],
        "qty": [3, 5],
        "price": [1.5, 2.0],
        "ok": [True, False],
    })
    out = run(FakeContext(params=params), table=upstream)
    assert list(out.columns) == ["name", "qty", "price", "ok"]
    assert str(out["qty"].dtype) == "Int64"
    assert str(out["price"].dtype) == "Float64"
    assert str(out["ok"].dtype) == "boolean"
    assert out["name"].tolist() == ["north", "south"]
    assert out["qty"].tolist() == [3, 5]


def test_table_refuses_a_linked_input_too_big_for_a_grid(registry):
    """A sheet is Python cells, not a frame: millions of rows cost gigabytes
    before anything is drawn, which took the app down. The node stops
    instead, and says where to look at data that size."""
    import pytest as _pytest
    from flograph.core import compile_run
    from flograph.core.sheet import MAX_LINKED_ROWS
    from tests.conftest import FakeContext

    spec = registry.get("flograph.io.table")
    run = compile_run(spec.source, "test-table")
    huge = pd.DataFrame({"n": range(MAX_LINKED_ROWS + 1)})
    with _pytest.raises(ValueError) as caught:
        run(FakeContext(params=spec.default_params()), table=huge)
    message = str(caught.value)
    assert f"{MAX_LINKED_ROWS:,}" in message and "Show Table" in message

    fine = pd.DataFrame({"n": range(10)})     # under it, nothing changes
    assert len(run(FakeContext(params=spec.default_params()),
                   table=fine)) == 10


def test_the_card_does_not_build_a_sheet_from_too_big_an_input(registry):
    """The same guard on the display side. merged_linked_sheet is what the
    canvas card, a dashboard tile and Import input into table all go
    through, and it runs on the UI thread."""
    from types import SimpleNamespace
    from flograph.core import Graph
    from flograph.core.sheet import MAX_LINKED_ROWS
    from flograph.engine.introspect import merged_linked_sheet

    graph = Graph()
    source = graph.add_node(registry.instantiate("flograph.io.table"))
    table = graph.add_node(registry.instantiate("flograph.io.table"))
    graph.connect(source.id, "table", table.id, "table")

    def cache_of(frame):
        entry = SimpleNamespace(outputs={"table": frame})
        return SimpleNamespace(get=lambda node_id: entry)

    assert merged_linked_sheet(
        graph, cache_of(pd.DataFrame({"n": range(3)})), table.id) is not None
    assert merged_linked_sheet(
        graph, cache_of(pd.DataFrame({"n": range(MAX_LINKED_ROWS + 1)})),
        table.id) is None


def test_sheet_from_dataframe_conversion(registry):
    from flograph.core.sheet import sheet_from_dataframe

    frame = pd.DataFrame({
        "when": pd.to_datetime(["2026-01-02", None]),
        "n": [1.5, float("nan")],
        "label": ["a", None],
    })
    sheet = sheet_from_dataframe(frame)
    # pandas infers the label column as its string dtype -> "text"
    assert [c.type for c in sheet.columns] == ["date", "number", "text"]
    assert sheet.rows[0] == ["2026-01-02", "1.5", "a"]
    assert sheet.rows[1] == ["", "", ""]   # NaT/NaN/None all become blank


def test_table_linked_card_stays_editable(env, registry):
    graph, stack, scene = env
    source = graph.add_node(registry.instantiate("flograph.io.table"))
    linked = graph.add_node(registry.instantiate("flograph.io.table"))
    model = scene.node_items[linked.id]._table_model

    graph.connect(source.id, "table", linked.id, "table")
    assert not model.read_only   # user columns are edited right on the card
    assert model.setData(model.index(0, 0), "mine")
    assert json.loads(
        graph.node(linked.id).params["data"])["rows"][0][0] == "mine"

    conn = next(iter(graph.connections.values()))
    graph.disconnect(conn.id)
    assert not model.read_only


def test_merge_linked_sheet_keeps_user_columns_and_fills_formulas(registry):
    from flograph.core.sheet import (ColumnSpec, Sheet, merge_linked_sheet,
                                     parse_sheet, sheet_to_dict)

    base = Sheet([ColumnSpec("qty", "integer")], [["1"], ["2"], ["3"]])
    stored = Sheet(
        [ColumnSpec("qty", "integer", 90), ColumnSpec("double", "auto"),
         ColumnSpec("empty", "auto")],
        [["9", "=A1*2", ""], ["9", "=A2*2", ""]])
    merged = merge_linked_sheet(base, stored)

    assert [c.name for c in merged.columns] == ["qty", "double"]
    assert merged.columns[0].width == 90        # user's width survives
    assert [r[0] for r in merged.rows] == ["1", "2", "3"]   # input wins
    # user formulas kept, and filled down for the new row
    assert [r[1] for r in merged.rows] == ["=A1*2", "=A2*2", "=A3*2"]

    # shrinking input trims the user column
    small = merge_linked_sheet(Sheet([ColumnSpec("qty")], [["7"]]), stored)
    assert [r[1] for r in small.rows] == ["=A1*2"]

    # round-trips through the persisted dict form
    assert merge_linked_sheet(base, parse_sheet(sheet_to_dict(stored))) == merged


def test_table_linked_run_evaluates_user_formula_columns(registry):
    from flograph.core import compile_run
    from tests.conftest import FakeContext

    spec = registry.get("flograph.io.table")
    run = compile_run(spec.source, "test-table")
    params = spec.default_params()
    params["data"] = json.dumps({
        "version": 2,
        "columns": [{"name": "qty", "type": "integer"},
                    {"name": "double", "type": "auto"}],
        "rows": [["9", "=A1*2"]],
    })
    upstream = pd.DataFrame({"qty": [3, 5, 7]})
    out = run(FakeContext(params=params), table=upstream)
    assert list(out.columns) == ["qty", "double"]
    assert out["qty"].tolist() == [3, 5, 7]     # refreshed from input
    assert out["double"].tolist() == [6, 10, 14]  # formula filled down


# ------------------------------------------- dropdown lists from helper tables
# flograph issue #108: wire any tables into the Table's empty "helper" port
# (it grows like Concatenate) and a column's dropdown list can read one of
# their columns.

def _helper_source(graph, registry, rows):
    """A Table node standing in for a helper table, holding `rows`."""
    helper = graph.add_node(registry.instantiate("flograph.io.table"))
    graph.set_param(helper.id, "data", json.dumps({
        "columns": ["Region", "Code"], "rows": rows}))
    return helper


def _run(qtbot, graph):
    from flograph.engine import ExecutionEngine
    engine = ExecutionEngine(graph)
    with qtbot.waitSignal(engine.run_finished, timeout=5000) as blocker:
        engine.run_all()
    assert blocker.args[0]
    return engine


def test_helper_tables_grow_ports_like_concatenate(env, registry):
    graph, stack, scene = env
    table = graph.add_node(registry.instantiate("flograph.io.table"))
    a = _helper_source(graph, registry, [["North", "1"]])
    b = _helper_source(graph, registry, [["South", "2"]])
    graph.connect(a.id, "table", table.id, "helper")
    graph.connect(b.id, "table", table.id, "helper")
    assert [p.name for p in graph.nodes[table.id].spec.inputs] == [
        "table", "in2", "in3", "helper"]
    assert list(scene.node_items[table.id].input_ports) == [
        "table", "in2", "in3", "helper"]


def test_dropdown_list_reads_a_helper_column(qtbot, env, registry):
    graph, stack, scene = env
    table = graph.add_node(registry.instantiate("flograph.io.table"))
    helper = _helper_source(graph, registry, [
        ["North", "1"], ["south", "2"], ["North", "3"], ["", "4"],
        ["East", "5"]])
    graph.connect(helper.id, "table", table.id, "helper")
    graph.set_param(table.id, "data", json.dumps({
        "columns": [{"name": "Where", "type": "text", "strict": True,
                     "choices_from": {"input": "in2", "column": "Region"}}],
        "rows": [["North"], ["Mars"]]}))
    engine = _run(qtbot, graph)

    from flograph.ui.spreadsheet.binding import shown_sheet
    from flograph.ui.spreadsheet.model import SheetModel
    model = SheetModel(shown_sheet(graph, engine.cache, table.id))
    # distinct, blanks dropped, in the helper's own order
    assert model.column_choices(0) == (["North", "south", "East"], True)
    assert model.column_choice_source(0) == {"input": "in2",
                                             "column": "Region"}
    assert model.helper_tables() == [{
        "input": "in2", "label": "Table", "columns": ["Region", "Code"]}]
    assert model.cell_problem(0, 0) is None
    assert model.cell_problem(1, 0)          # strict: Mars isn't listed

    # the flow's table is untouched by helpers
    out = engine.cache.outputs_for(table.id)["table"]
    assert out["Where"].tolist() == ["North", "Mars"]


def test_helper_list_follows_the_helper_and_survives_unwiring(
        qtbot, env, registry):
    graph, stack, scene = env
    table = graph.add_node(registry.instantiate("flograph.io.table"))
    helper = _helper_source(graph, registry, [["North", "1"]])
    graph.connect(helper.id, "table", table.id, "helper")
    item = scene.node_items[table.id]
    item._table_model.set_column_choices(
        0, [], strict=False, source={"input": "in2", "column": "Region"})
    stored = json.loads(graph.nodes[table.id].params["data"])
    assert stored["columns"][0]["choices_from"] == {"input": "in2",
                                                    "column": "Region"}

    engine = _run(qtbot, graph)
    scene.output_cache = engine.cache
    item.refresh_table_link()
    assert item._table_model.column_choices(0)[0] == ["North"]

    graph.set_param(helper.id, "data", json.dumps({
        "columns": ["Region"], "rows": [["West"], ["North"]]}))
    scene.output_cache = _run(qtbot, graph).cache
    item.refresh_table_link()
    assert item._table_model.column_choices(0)[0] == ["West", "North"]

    # unwired: the list keeps what it last read rather than vanishing
    scene.delete_items([], [c.id for c in graph.connections.values()
                            if c.dst_node == table.id], [], confirm=False)
    item.refresh_table_link()
    assert item._table_model.column_choices(0)[0] == ["West", "North"]
    assert item._table_model.helper_tables() == []
    # one undo brings the wire back and the snapshot goes with it
    stack.undo()
    assert graph.input_connection(table.id, "in2") is not None


def test_choice_source_round_trips_and_finds_a_moved_column():
    from flograph.core.sheet import parse_sheet, sheet_to_dict
    from flograph.core.sheet.choice_sources import resolve

    sheet = parse_sheet({"columns": [
        {"name": "A", "choices": ["x"], "strict": True,
         "choices_from": {"input": "in2", "column": "Region"}}],
        "rows": [[""]]})
    again = parse_sheet(sheet_to_dict(sheet))
    assert again.columns[0].choices_from == {"input": "in2",
                                             "column": "Region"}
    assert again.columns[0].strict and again.columns[0].choices == ["x"]
    assert again.copy().columns[0].choices_from == {"input": "in2",
                                                    "column": "Region"}

    # rewired into another port: the column is found by name
    frame = pd.DataFrame({"Region": ["a", None, "b", "a", 3.0]})
    resolve(again, {"in5": frame})
    assert again.columns[0].choices == ["a", "b", "3"]
    assert again.helpers == [{"input": "in5", "label": "in5",
                              "columns": ["Region"]}]
    assert "helpers" not in sheet_to_dict(again)


def test_dropdown_dialog_offers_helpers(qtbot, env, registry):
    from flograph.ui.spreadsheet.dropdown import DropdownListDialog
    from flograph.ui.spreadsheet.model import SheetModel
    from flograph.ui.spreadsheet.view import SpreadsheetView

    sheet = {"columns": [{"name": "A"}], "rows": [[""]]}
    from flograph.core.sheet import parse_sheet
    parsed = parse_sheet(sheet)
    parsed.helpers = [{"input": "in2", "label": "Regions",
                       "columns": ["Region", "Code"]}]
    model = SheetModel(parsed)
    view = SpreadsheetView()
    qtbot.addWidget(view)
    view.setModel(model)
    dialog = DropdownListDialog(view, 0)
    qtbot.addWidget(dialog)
    assert dialog.source() is None
    dialog.edit.setPlainText("typed")
    dialog.from_box.setCurrentIndex(dialog.from_box.findData("in2"))
    assert dialog.source() == {"input": "in2", "column": "Region"}
    assert dialog.edit.isReadOnly()
    dialog.column_box.setCurrentText("Code")
    assert dialog.source() == {"input": "in2", "column": "Code"}
    # back to typed: what was typed comes back
    dialog.from_box.setCurrentIndex(0)
    assert dialog.source() is None
    assert dialog.edit.toPlainText() == "typed"


def test_dropdown_dialog_runs_helpers_and_fills_at_once(qtbot, env, registry):
    """A helper that hasn't run offers Run Helpers; it runs only the helper,
    and the dialog fills its columns and values without closing — from the
    card and from the full editor alike (flograph issue #108)."""
    from flograph.engine import ExecutionEngine
    from flograph.core.node import NodeStatus
    from flograph.ui.spreadsheet.dialog import SheetEditorDialog
    from flograph.ui.spreadsheet.dropdown import DropdownListDialog

    graph, stack, scene = env
    table = graph.add_node(registry.instantiate("flograph.io.table"))
    helper = _helper_source(graph, registry, [["North", "1"], ["South", "2"]])
    graph.connect(helper.id, "table", table.id, "helper")
    engine = ExecutionEngine(graph)
    scene.output_cache = engine.cache
    scene.helpers_run_requested.connect(engine.run_targets)
    item = scene.node_items[table.id]
    item.refresh_table_link()

    # the full editor, over the card's host, as the card opens it
    editor = SheetEditorDialog(item._table_source(), host=item._table_widget.host)
    qtbot.addWidget(editor)
    dialog = DropdownListDialog(editor.view, 0)
    qtbot.addWidget(dialog)
    dialog.from_box.setCurrentIndex(dialog.from_box.findData("in2"))
    assert dialog.column_box.count() == 0          # not run: no columns yet
    assert dialog.run_button.isVisibleTo(dialog)
    assert "hasn't run" in dialog.hint.text()

    with qtbot.waitSignal(engine.run_finished, timeout=5000):
        dialog.run_button.click()
    qtbot.waitUntil(lambda: not dialog._poll.isActive(), timeout=3000)
    assert dialog.source() == {"input": "in2", "column": "Region"}
    assert dialog.values() == ["North", "South"]
    # only the helper ran; the table waits for its own run
    assert graph.nodes[helper.id].status == NodeStatus.DONE
    assert engine.cache.get(table.id) is None

    # a different column fills straight away, no OK needed
    dialog.column_box.setCurrentText("Code")
    assert dialog.values() == ["1", "2"]
    dialog.accept()
    editor.model.set_column_choices(0, dialog.values(), False,
                                    dialog.source())
    assert editor.model.column_choices(0)[0] == ["1", "2"]
