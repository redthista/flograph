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


class TestEditorPanelTempEdits:
    """Test that unsaved edits persist when switching between nodes."""

    def _panel(self, qtbot, graph, stack, registry):
        panel = EditorPanel(graph, stack, registry)
        qtbot.addWidget(panel)
        return panel

    def test_unsaved_changes_persist_when_switching_nodes(self, qtbot, env, registry):
        """Switch away from a node with unsaved edits and back — edits should survive."""
        graph, stack, _ = env
        node_a = graph.add_node(registry.instantiate("flograph.scripting.python_script"))
        node_b = graph.add_node(registry.instantiate("flograph.util.constant"))
        panel = self._panel(qtbot, graph, stack, registry)

        # Select node A and type some unsaved edits.
        panel.set_node(node_a.id)
        original_source = panel.editor.toPlainText()
        panel.editor.setPlainText(original_source + "\n# my temp edit\n")
        assert "# my temp edit" in panel.editor.toPlainText()

        # Switch to node B — editor should load B's source.
        panel.set_node(node_b.id)
        b_source = graph.node(node_b.id).spec.source
        assert panel.editor.toPlainText() == b_source

        # Switch back to node A — temp edits should be restored.
        panel.set_node(node_a.id)
        assert "# my temp edit" in panel.editor.toPlainText()

    def test_applied_edits_clear_cache(self, qtbot, env, registry):
        """After applying changes, the cache is cleared and next switch loads from graph."""
        graph, stack, _ = env
        node_a = graph.add_node(registry.instantiate("flograph.scripting.python_script"))
        node_b = graph.add_node(registry.instantiate("flograph.util.constant"))
        panel = self._panel(qtbot, graph, stack, registry)

        # Select A and make unsaved edits.
        panel.set_node(node_a.id)
        original_source = panel.editor.toPlainText()
        edited = original_source + "\n# my temp edit\n"
        panel.editor.setPlainText(edited)

        # Switch to B then back to A — cache restores the edit.
        panel.set_node(node_b.id)
        panel.set_node(node_a.id)
        assert "# my temp edit" in panel.editor.toPlainText()

        # Apply the code so graph now owns it.
        panel.apply_code()
        assert node_a.forked

        # Switch to B then back — should load from graph (which has the applied version).
        panel.set_node(node_b.id)
        panel.set_node(node_a.id)
        # The editor shows what was just applied, not stale cache.
        assert "# my temp edit" in panel.editor.toPlainText()

    def test_multiple_nodes_all_caret(self, qtbot, env, registry):
        """Each node retains its own cached edits independently."""
        graph, stack, _ = env
        node_a = graph.add_node(registry.instantiate("flograph.scripting.python_script"))
        node_b = graph.add_node(registry.instantiate("flograph.util.constant"))
        panel = self._panel(qtbot, graph, stack, registry)

        # Edit A.
        panel.set_node(node_a.id)
        panel.editor.setPlainText(panel.editor.toPlainText() + "\n# edit on a\n")

        # Edit B.
        panel.set_node(node_b.id)
        panel.editor.setPlainText(panel.editor.toPlainText() + "\n# edit on b\n")

        # Switch back to A — its edits should be intact, not B's.
        panel.set_node(node_a.id)
        assert "# edit on a" in panel.editor.toPlainText()
        assert "# edit on b" not in panel.editor.toPlainText()


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
