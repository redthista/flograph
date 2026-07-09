"""Canvas shortcuts (Delete/Backspace/F/arrows) must not steal keystrokes
from a focused in-canvas editor (note editor, table cell)."""
import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QUndoStack
from PySide6.QtTest import QTest

from flopy.core import Graph, NodeRegistry
from flopy.ui.canvas import NodeGraphScene
from flopy.ui.canvas.view import NodeGraphView


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
    view = NodeGraphView(scene)
    qtbot.addWidget(view)
    view.show()
    return graph, stack, scene, view


def test_backspace_in_note_editor_edits_text_not_delete_node(env, registry):
    graph, stack, scene, view = env
    note = graph.add_node(registry.instantiate("flopy.util.note"))
    item = scene.node_items[note.id]
    item.start_note_edit()
    editor = item._note_editor_widget
    editor.setFocus()
    editor.selectAll()

    QTest.keyClick(editor, Qt.Key_Backspace)

    assert note.id in graph.nodes
    assert editor.toPlainText() == ""


def test_letter_f_in_note_editor_types_not_frame(env, registry):
    graph, stack, scene, view = env
    note = graph.add_node(registry.instantiate("flopy.util.note"))
    item = scene.node_items[note.id]
    item.start_note_edit()
    editor = item._note_editor_widget
    editor.setFocus()
    editor.clear()

    QTest.keyClick(editor, Qt.Key_F)

    assert editor.toPlainText() == "f"


def test_arrow_keys_in_table_move_cell_cursor_not_node(env, registry):
    graph, stack, scene, view = env
    table = graph.add_node(registry.instantiate("flopy.io.table"))
    item = scene.node_items[table.id]
    grid = item._table_widget
    grid.setCurrentCell(0, 0)
    grid.setFocus()
    before_pos = item.pos()

    QTest.keyClick(grid, Qt.Key_Right)

    assert grid.currentColumn() == 1
    assert item.pos() == before_pos


def test_delete_key_still_removes_selected_node_when_nothing_focused(env, registry):
    graph, stack, scene, view = env
    note = graph.add_node(registry.instantiate("flopy.util.note"))
    item = scene.node_items[note.id]
    item.setSelected(True)
    view.setFocus()

    QTest.keyClick(view, Qt.Key_Backspace)

    assert note.id not in graph.nodes
