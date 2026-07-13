"""Undo/redo integrity for dashboard page and tile commands: every command
must survive undo -> redo cycles with the graph JSON identical at each
equivalent point."""
import pytest
from PySide6.QtGui import QUndoStack

from flograph.core import Graph, Page, Tile
from flograph.core.serialization import graph_to_dict
from flograph.ui.commands import (
    AddPageCommand, AddTileCommand, MoveResizeTileCommand,
    RemovePageCommand, RemoveTileCommand, RenamePageCommand,
)


@pytest.fixture
def env(qtbot):
    return Graph(), QUndoStack()


def snapshot(graph):
    return graph_to_dict(graph)


def assert_undo_redo_stable(stack, graph, before, after):
    for _ in range(2):
        stack.undo()
        assert snapshot(graph) == before
        stack.redo()
        assert snapshot(graph) == after


def test_add_page(env):
    graph, stack = env
    empty = snapshot(graph)
    stack.push(AddPageCommand(graph, Page(id="p1", title="Sales")))
    full = snapshot(graph)
    assert graph.pages["p1"].title == "Sales"
    assert_undo_redo_stable(stack, graph, empty, full)


def test_remove_page_restores_tiles(env):
    graph, stack = env
    stack.push(AddPageCommand(graph, Page(id="p1")))
    stack.push(AddTileCommand(graph, "p1", Tile(id="t1", node_id="n1",
                                                port="table")))
    before = snapshot(graph)
    stack.push(RemovePageCommand(graph, "p1"))
    after = snapshot(graph)
    assert graph.pages == {}
    assert_undo_redo_stable(stack, graph, before, after)
    stack.undo()
    assert graph.pages["p1"].tiles["t1"].port == "table"


def test_rename_page(env):
    graph, stack = env
    stack.push(AddPageCommand(graph, Page(id="p1", title="Page 1")))
    before = snapshot(graph)
    stack.push(RenamePageCommand(graph, "p1", "Revenue"))
    after = snapshot(graph)
    assert graph.pages["p1"].title == "Revenue"
    assert_undo_redo_stable(stack, graph, before, after)


def test_add_and_remove_tile(env):
    graph, stack = env
    stack.push(AddPageCommand(graph, Page(id="p1")))
    before = snapshot(graph)
    stack.push(AddTileCommand(graph, "p1", Tile(id="t1", node_id="n1",
                                                port="figure",
                                                rect=(5, 5, 400, 300))))
    with_tile = snapshot(graph)
    assert_undo_redo_stable(stack, graph, before, with_tile)

    stack.push(RemoveTileCommand(graph, "p1", "t1"))
    removed = snapshot(graph)
    assert graph.pages["p1"].tiles == {}
    assert_undo_redo_stable(stack, graph, with_tile, removed)
    stack.undo()
    assert graph.pages["p1"].tiles["t1"].rect == (5.0, 5.0, 400.0, 300.0)


def test_move_resize_merges_within_one_drag(env):
    graph, stack = env
    stack.push(AddPageCommand(graph, Page(id="p1")))
    stack.push(AddTileCommand(graph, "p1", Tile(id="t1", node_id="n1",
                                                rect=(0, 0, 420, 320))))
    count = stack.count()
    stack.push(MoveResizeTileCommand(graph, "p1", "t1",
                                     (0, 0, 420, 320), (50, 0, 420, 320)))
    stack.push(MoveResizeTileCommand(graph, "p1", "t1",
                                     (50, 0, 420, 320), (100, 40, 500, 360)))
    assert stack.count() == count + 1  # merged
    assert graph.pages["p1"].tiles["t1"].rect == (100.0, 40.0, 500.0, 360.0)
    stack.undo()
    assert graph.pages["p1"].tiles["t1"].rect == (0.0, 0.0, 420.0, 320.0)


def test_moves_of_different_tiles_do_not_merge(env):
    graph, stack = env
    stack.push(AddPageCommand(graph, Page(id="p1")))
    stack.push(AddTileCommand(graph, "p1", Tile(id="t1", node_id="n1")))
    stack.push(AddTileCommand(graph, "p1", Tile(id="t2", node_id="n2")))
    count = stack.count()
    stack.push(MoveResizeTileCommand(graph, "p1", "t1",
                                     (0, 0, 420, 320), (10, 0, 420, 320)))
    stack.push(MoveResizeTileCommand(graph, "p1", "t2",
                                     (0, 0, 420, 320), (0, 10, 420, 320)))
    assert stack.count() == count + 2
