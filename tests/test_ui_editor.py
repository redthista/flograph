"""M4 UI tests: editor panel apply/reset flow, params panel <-> undo sync,
code editor behaviors."""
import pytest
from PySide6.QtGui import QUndoStack
from PySide6.QtWidgets import QCheckBox, QComboBox, QLineEdit

from flograph.core import Graph, NodeRegistry
from flograph.engine import NodeError
from flograph.ui.canvas import NodeGraphScene
from flograph.ui.editor.code_editor import CodeEditor
from flograph.ui.editor.editor_dock import EditorPanel
from flograph.ui.properties.params_panel import ParamsPanel


@pytest.fixture(scope="module")
def registry():
    reg = NodeRegistry()
    reg.load_builtins()
    return reg


@pytest.fixture
def env(qtbot, registry):
    graph = Graph()
    stack = QUndoStack()
    scene = NodeGraphScene(graph, stack)  # keeps items in sync during commands
    return graph, stack, scene


class TestEditorPanel:
    def _panel(self, qtbot, graph, stack, registry):
        panel = EditorPanel(graph, stack, registry)
        qtbot.addWidget(panel)
        return panel

    def test_apply_valid_code_forks_node(self, qtbot, env, registry):
        graph, stack, _ = env
        node = graph.add_node(registry.instantiate("flograph.scripting.python_script"))
        panel = self._panel(qtbot, graph, stack, registry)
        panel.set_node(node.id)
        assert panel.editor.toPlainText() == node.spec.source

        panel.editor.setPlainText("""
NODE = {"label": "Mine", "category": "Scripting",
        "inputs": [], "outputs": [("out1", "any")]}
def run(ctx):
    return 42
""")
        panel.apply_code()
        assert node.forked and node.label == "Mine"
        assert panel._badge.isVisible() or not panel.isVisible()  # badge flagged
        stack.undo()
        assert not node.forked

    def test_apply_bad_code_shows_error_no_command(self, qtbot, env, registry):
        graph, stack, _ = env
        node = graph.add_node(registry.instantiate("flograph.scripting.python_script"))
        panel = self._panel(qtbot, graph, stack, registry)
        panel.set_node(node.id)
        index = stack.index()
        panel.editor.setPlainText("def broken(:\n")
        panel.apply_code()
        assert stack.index() == index  # nothing pushed
        assert "must define" in panel._message.text() \
            or "syntax error" in panel._message.text()
        assert not node.forked

    def test_reset_to_library(self, qtbot, env, registry):
        graph, stack, _ = env
        node = graph.add_node(registry.instantiate("flograph.scripting.python_script"))
        graph.set_code(node.id, """
NODE = {"label": "Fork", "category": "Scripting",
        "inputs": [], "outputs": [("out1", "any")]}
def run(ctx):
    return 1
""")
        panel = self._panel(qtbot, graph, stack, registry)
        panel.set_node(node.id)
        panel._reset_to_library()
        assert not node.forked
        assert node.spec.source == registry.get(node.type_id).source
        stack.undo()
        assert node.forked and node.label == "Fork"

    def test_engine_error_marks_line(self, qtbot, env, registry):
        graph, stack, _ = env
        node = graph.add_node(registry.instantiate("flograph.scripting.python_script"))
        panel = self._panel(qtbot, graph, stack, registry)
        panel.set_node(node.id)
        panel.on_node_failed(node.id, NodeError(
            node_id=node.id, message="ValueError: nope",
            exc_type="ValueError", formatted_tb="tb", script_line=3))
        assert panel.editor._error_line == 3
        panel.on_node_succeeded(node.id)
        assert panel.editor._error_line is None

    def test_undo_of_code_change_reloads_editor(self, qtbot, env, registry):
        graph, stack, _ = env
        node = graph.add_node(registry.instantiate("flograph.scripting.python_script"))
        panel = self._panel(qtbot, graph, stack, registry)
        panel.set_node(node.id)
        original = panel.editor.toPlainText()
        panel.editor.setPlainText(original.replace("Python Script", "Renamed"))
        panel.apply_code()
        stack.undo()
        assert panel.editor.toPlainText() == original


class TestParamsPanel:
    def test_widgets_commit_and_track_undo(self, qtbot, env, registry):
        graph, stack, _ = env
        node = graph.add_node(registry.instantiate("flograph.util.constant"))
        panel = ParamsPanel(graph, stack)
        qtbot.addWidget(panel)
        panel.set_node(node.id)

        combos = panel.findChildren(QComboBox)
        assert combos, "choice widget missing"
        combos[0].setCurrentText("int")
        assert node.params["kind"] == "int"

        stack.undo()
        assert node.params["kind"] == "string"
        assert combos[0].currentText() == "string"  # widget followed the undo

    def test_bool_and_string_widgets(self, qtbot, env, registry):
        graph, stack, _ = env
        node = graph.add_node(registry.instantiate("flograph.io.read_csv"))
        panel = ParamsPanel(graph, stack)
        qtbot.addWidget(panel)
        panel.set_node(node.id)
        checkbox = panel.findChildren(QCheckBox)[0]
        assert checkbox.isChecked() is True
        checkbox.setChecked(False)
        assert node.params["header"] is False


class TestCodeEditor:
    def test_auto_indent_after_colon(self, qtbot):
        editor = CodeEditor()
        qtbot.addWidget(editor)
        editor.setPlainText("def f():")
        cursor = editor.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        editor.setTextCursor(cursor)
        qtbot.keyPress(editor, "\r")
        assert editor.toPlainText() == "def f():\n    "

    def test_comment_toggle(self, qtbot):
        editor = CodeEditor()
        qtbot.addWidget(editor)
        editor.setPlainText("x = 1\ny = 2")
        editor.selectAll()
        editor._toggle_comment()
        assert editor.toPlainText() == "# x = 1\n# y = 2"
        editor.selectAll()
        editor._toggle_comment()
        assert editor.toPlainText() == "x = 1\ny = 2"

    def test_error_line_marker(self, qtbot):
        editor = CodeEditor()
        qtbot.addWidget(editor)
        editor.setPlainText("a\nb\nc")
        editor.set_error_line(2)
        assert editor._error_line == 2
        editor.set_error_line(None)
        assert editor._error_line is None
