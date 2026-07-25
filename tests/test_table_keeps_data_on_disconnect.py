"""Idea #8: a linked Table keeps its contents when you cut the input.

A linked Table's grid is a *merge* — upstream columns refreshed on every
run, the user's own columns stored in the node. Only the user's half is
persisted, so cutting the wire used to collapse the grid back to those few
columns and throw the data away. Disconnecting now freezes what the card is
showing into the node's own sheet first, in the same undo step.
"""
import json
from types import SimpleNamespace

import pandas as pd
import pytest
from PySide6.QtCore import QPointF
from PySide6.QtGui import QUndoStack

from flograph.core import Graph, NodeRegistry
from flograph.engine.cache import OutputCache
from flograph.engine.introspect import orphaned_table_sheets
from flograph.ui.canvas import NodeGraphScene

UPSTREAM = pd.DataFrame({"qty": [1, 2, 3]})

# a stored sheet with one column of the user's own alongside the input's
STORED = json.dumps({
    "version": 2,
    "columns": [{"name": "qty", "type": "integer"},
                {"name": "double", "type": "auto"}],
    "rows": [["ignored", "=A1*2"]],
})


@pytest.fixture(scope="module")
def registry():
    reg = NodeRegistry()
    reg.load_builtins()
    return reg


@pytest.fixture
def env(qtbot, registry):
    """A source node feeding a Table, with the source's output cached — the
    state you are in after a run, which is when there is anything to lose."""
    graph = Graph()
    stack = QUndoStack()
    scene = NodeGraphScene(graph, stack, registry=registry)
    scene.output_cache = OutputCache()
    source = graph.add_node(registry.instantiate("flograph.io.table"))
    table = graph.add_node(registry.instantiate("flograph.io.table"))
    graph.set_param(table.id, "data", STORED)
    conn, _ = graph.connect(source.id, "table", table.id, "table")
    scene.output_cache.set(source.id, {"table": UPSTREAM}, 0.01)
    return SimpleNamespace(graph=graph, stack=stack, scene=scene,
                           cache=scene.output_cache, source=source,
                           table=table, conn=conn)


def sheet_of(graph, node_id) -> dict:
    return json.loads(graph.node(node_id).params["data"])


def assert_kept(graph, node_id) -> None:
    """The card's merged view is now the node's own sheet: upstream rows
    materialised, the user's formula column filled down beside them."""
    sheet = sheet_of(graph, node_id)
    assert [c["name"] for c in sheet["columns"]] == ["qty", "double"]
    assert [r[0] for r in sheet["rows"]] == ["1", "2", "3"]
    assert [r[1] for r in sheet["rows"]] == ["=A1*2", "=A2*2", "=A3*2"]


class TestWhichTablesLoseTheirInput:
    """orphaned_table_sheets is the decision; the scene just pushes it."""

    def test_a_cut_wire_snapshots_the_table_it_fed(self, env):
        snaps = orphaned_table_sheets(env.graph, env.cache,
                                      conn_ids=[env.conn.id])
        assert [node_id for node_id, _ in snaps] == [env.table.id]

    def test_deleting_the_source_node_also_orphans_it(self, env):
        snaps = orphaned_table_sheets(env.graph, env.cache,
                                      node_ids=[env.source.id])
        assert [node_id for node_id, _ in snaps] == [env.table.id]

    def test_a_table_going_away_itself_needs_no_snapshot(self, env):
        assert orphaned_table_sheets(
            env.graph, env.cache, conn_ids=[env.conn.id],
            node_ids=[env.source.id, env.table.id]) == []

    def test_an_unrun_link_has_nothing_to_preserve(self, env):
        """Writing the empty merge would *delete* the user's columns —
        the opposite of the point."""
        env.cache.clear()
        assert orphaned_table_sheets(env.graph, env.cache,
                                     conn_ids=[env.conn.id]) == []
        assert sheet_of(env.graph, env.table.id)["columns"][1]["name"] \
            == "double"

    def test_an_untouched_wire_is_left_alone(self, env):
        assert orphaned_table_sheets(env.graph, env.cache) == []

    def test_a_wire_into_a_non_grid_node_is_ignored(self, env, registry):
        sort = env.graph.add_node(registry.instantiate("flograph.transform.sort"))
        conn, _ = env.graph.connect(env.source.id, "table", sort.id, "table")
        assert orphaned_table_sheets(env.graph, env.cache,
                                     conn_ids=[conn.id]) == []

    def test_snapshotting_the_same_thing_twice_is_not_an_edit(self, env):
        """Once the sheet already holds the merge — after "Import input into
        table", say — cutting the wire must not add a pointless undo step."""
        _, data = orphaned_table_sheets(env.graph, env.cache,
                                        conn_ids=[env.conn.id])[0]
        env.graph.set_param(env.table.id, "data", data)
        assert orphaned_table_sheets(env.graph, env.cache,
                                     conn_ids=[env.conn.id]) == []


class TestCuttingTheWireOnTheCanvas:

    def test_deleting_the_wire_keeps_the_contents(self, env):
        env.scene.connection_items[env.conn.id].setSelected(True)
        env.scene.delete_selection()
        assert not env.graph.connections
        assert_kept(env.graph, env.table.id)

    def test_deleting_the_source_node_keeps_the_contents(self, env):
        env.scene.node_items[env.source.id].setSelected(True)
        env.scene.delete_selection()
        assert env.source.id not in env.graph.nodes
        assert_kept(env.graph, env.table.id)

    def test_dragging_the_wire_off_keeps_the_contents(self, env):
        port = env.scene.node_items[env.table.id].input_ports["table"]
        env.scene.begin_wire_drag(port)
        env.scene.finish_wire_drag(QPointF(90_000, 90_000))
        assert not env.graph.connections
        assert_kept(env.graph, env.table.id)

    def test_moving_the_wire_to_another_table_keeps_the_contents(
            self, env, registry):
        other = env.graph.add_node(registry.instantiate("flograph.io.table"))
        port = env.scene.node_items[env.table.id].input_ports["table"]
        env.scene.begin_wire_drag(port)
        target = env.scene.node_items[other.id].input_ports["table"]
        env.scene.finish_wire_drag(target.scenePos())

        assert env.graph.input_connection(other.id, "table") is not None
        assert env.graph.input_connection(env.table.id, "table") is None
        assert_kept(env.graph, env.table.id)

    def test_one_undo_restores_the_wire_and_the_old_sheet(self, env):
        env.scene.connection_items[env.conn.id].setSelected(True)
        env.scene.delete_selection()
        env.stack.undo()
        assert env.graph.input_connection(env.table.id, "table") is not None
        assert env.graph.node(env.table.id).params["data"] == STORED
        assert env.stack.canUndo() is False   # nothing left behind it

    def test_redo_puts_the_snapshot_back(self, env):
        env.scene.connection_items[env.conn.id].setSelected(True)
        env.scene.delete_selection()
        env.stack.undo()
        env.stack.redo()
        assert not env.graph.connections
        assert_kept(env.graph, env.table.id)

    def test_a_reroute_is_not_a_disconnect(self, env):
        """Splitting the wire with a reroute dot keeps the table fed, so
        freezing its contents there would be wrong — and would stop the
        next run refreshing them."""
        env.scene.insert_reroute(env.conn, QPointF(120.0, 40.0))
        assert env.graph.input_connection(env.table.id, "table") is not None
        assert env.graph.node(env.table.id).params["data"] == STORED

    def test_the_card_shows_what_was_kept(self, env):
        item = env.scene.node_items[env.table.id]
        env.scene.connection_items[env.conn.id].setSelected(True)
        env.scene.delete_selection()
        model = item._table_model
        assert model.columnCount() == 2
        assert model.rowCount() == 3
        assert [model.index(r, 0).data() for r in range(3)] == ["1", "2", "3"]

    def test_it_announces_the_tables_it_rewrote(self, env, qtbot):
        """Silently editing someone's sheet is the one thing this feature
        does behind their back, so the window gets told and says so."""
        env.scene.connection_items[env.conn.id].setSelected(True)
        with qtbot.waitSignal(env.scene.tables_kept, timeout=1000) as kept:
            env.scene.delete_selection()
        assert kept.args[0] == [env.table.id]

    def test_nothing_is_announced_when_nothing_was_kept(self, env, qtbot):
        env.cache.clear()
        env.scene.connection_items[env.conn.id].setSelected(True)
        with qtbot.assertNotEmitted(env.scene.tables_kept):
            env.scene.delete_selection()

    def test_no_cache_no_snapshot(self, env):
        """A scene with no engine behind it (tests, headless tooling) must
        still delete wires rather than fall over."""
        env.scene.output_cache = None
        env.scene.connection_items[env.conn.id].setSelected(True)
        env.scene.delete_selection()
        assert not env.graph.connections
        assert env.graph.node(env.table.id).params["data"] == STORED


class TestTheLinkedViewSurvivesParamEdits:
    """A linked card shows the merge, but only the user's columns are
    *stored* — so anything that re-syncs the grid from params has to
    re-derive the merge or the data vanishes until the next run."""

    @pytest.fixture
    def populated(self, env):
        from flograph.engine.introspect import merged_linked_sheet
        item = env.scene.node_items[env.table.id]
        item.show_linked_sheet(
            merged_linked_sheet(env.graph, env.cache, env.table.id))
        return item._table_model

    def shown(self, model) -> list:
        return [model.index(r, 0).data() for r in range(model.rowCount())]

    def test_the_run_populates_the_card(self, populated):
        assert self.shown(populated) == ["1", "2", "3"]

    def test_resizing_the_card_does_not_revert_it(self, env, populated):
        # exactly what dragging the card's corner writes
        env.graph.set_param(env.table.id, "width", 480)
        env.graph.set_param(env.table.id, "height", 400)
        assert self.shown(populated) == ["1", "2", "3"]

    def test_reconnecting_shows_the_merge_without_waiting_for_a_run(
            self, env, populated):
        env.graph.disconnect(env.conn.id)
        assert self.shown(populated) != ["1", "2", "3"]   # back to stored
        env.graph.connect(env.source.id, "table", env.table.id, "table")
        assert self.shown(populated) == ["1", "2", "3"]


def test_the_kept_sheet_runs_standalone(env, registry):
    """The point of the whole exercise: after disconnecting, the node
    produces the same frame on its own."""
    from flograph.core import compile_run

    from tests.conftest import FakeContext

    env.scene.connection_items[env.conn.id].setSelected(True)
    env.scene.delete_selection()

    run = compile_run(registry.get("flograph.io.table").source, "test-table")
    params = dict(env.graph.node(env.table.id).params)
    out = run(FakeContext(params=params))
    assert list(out.columns) == ["qty", "double"]
    assert out["qty"].tolist() == [1, 2, 3]
    assert out["double"].tolist() == [2, 4, 6]
