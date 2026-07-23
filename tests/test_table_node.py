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
    assert [p.name for p in spec.inputs] == ["table"]
    assert spec.inputs[0].optional   # runs fine unconnected
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
    assert list(item.input_ports) == ["table"]


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
