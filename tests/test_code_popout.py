"""The Code panel's pop-out: a node's script in a window of its own, opening
with what the panel holds, where OK applies it the way Apply does."""
import pytest
from PySide6.QtGui import QUndoStack
from PySide6.QtWidgets import QDialog, QToolButton

from flograph.core import Graph, NodeRegistry
from flograph.ui.canvas import NodeGraphScene
from flograph.ui.editor.code_popout import CodePopOut, python_syntax_lint
from flograph.ui.editor.editor_dock import EditorPanel

VALID = """NODE = {"label": "Mine", "category": "Scripting",
        "inputs": [], "outputs": [("out1", "any")]}
def run(ctx):
    return 42
"""


@pytest.fixture(scope="module")
def registry():
    reg = NodeRegistry()
    reg.load_builtins()
    return reg


@pytest.fixture
def env(qtbot, registry):
    graph = Graph()
    stack = QUndoStack()
    scene = NodeGraphScene(graph, stack)
    node = graph.add_node(
        registry.instantiate("flograph.scripting.python_script"))
    panel = EditorPanel(graph, stack, registry)
    qtbot.addWidget(panel)
    panel.set_node(node.id)
    yield panel, graph, stack, node
    stack.clear()
    del scene


def _drive(monkeypatch, edit=None, accept=True):
    """Stand in for the modal exec: do `edit` to the open dialog, then close
    it with OK or Cancel."""
    seen = {}

    def fake_exec(self):
        seen["dialog"] = self
        seen["text"] = self.editor.toPlainText()
        seen["read_only"] = self.editor.isReadOnly()
        if edit is not None:
            edit(self)
        return QDialog.Accepted if accept else QDialog.Rejected

    monkeypatch.setattr(CodePopOut, "exec", fake_exec)
    return seen


def _open(panel):
    panel.findChild(QToolButton, "code_popout_button").click()


def _real_dialog(qtbot, text, type_id="flograph.scripting.python_script"):
    dialog = CodePopOut("t", text, type_id=type_id)
    # a dialog with edits asks before closing; pytest-qt's close would hang
    qtbot.addWidget(dialog, before_close_func=lambda d: d.done(QDialog.Rejected))
    return dialog


class TestCodePanelPopOut:
    def test_the_button_shows_once_a_node_is_bound(self, env):
        panel, _graph, _stack, _node = env
        button = panel.findChild(QToolButton, "code_popout_button")
        assert not button.isHidden()
        panel.set_node(None)
        assert button.isHidden()

    def test_it_opens_with_the_panels_unapplied_edits(self, env, monkeypatch):
        panel, _graph, _stack, _node = env
        panel.editor.setPlainText("x = 1\n")
        seen = _drive(monkeypatch, accept=False)
        _open(panel)
        assert seen["text"] == "x = 1\n"

    def test_ok_applies_as_one_undo_step(self, env, monkeypatch):
        panel, _graph, stack, node = env
        _drive(monkeypatch, lambda d: d.editor.setPlainText(VALID))
        _open(panel)
        assert node.forked and node.label == "Mine"
        assert panel.editor.toPlainText() == VALID
        stack.undo()
        assert not node.forked

    def test_cancel_changes_nothing(self, env, monkeypatch):
        panel, _graph, stack, node = env
        before = panel.editor.toPlainText()
        index = stack.index()
        _drive(monkeypatch, lambda d: d.editor.setPlainText(VALID),
               accept=False)
        _open(panel)
        assert panel.editor.toPlainText() == before
        assert stack.index() == index and not node.forked

    def test_a_locked_node_opens_read_only(self, env, monkeypatch):
        panel, graph, stack, node = env
        graph.set_locked(node.id, True)
        index = stack.index()
        seen = _drive(monkeypatch)
        _open(panel)
        assert seen["read_only"]
        assert stack.index() == index


class TestCodePopOut:
    def test_a_script_the_node_refuses_keeps_the_window_open(self, qtbot):
        dialog = _real_dialog(qtbot, "NODE = {}\ndef run(ctx):\n    pass\n")
        accepted = []
        dialog.accepted.connect(lambda: accepted.append(True))
        dialog.accept()
        assert not accepted
        assert "Not applied" in dialog.status.text()
        assert "label" in dialog.status.text()

        dialog.editor.setPlainText(VALID)
        dialog.accept()
        assert accepted

    def test_a_syntax_error_on_ok_marks_its_line(self, qtbot):
        dialog = _real_dialog(qtbot, "a = 1\nb = (\n")
        dialog.accept()
        assert dialog.editor.error_line == 2

    def test_syntax_is_checked_as_you_type(self, qtbot):
        assert python_syntax_lint(VALID) == []
        [found] = python_syntax_lint("x = 1\ndef f(:\n    pass\n")
        assert found.line == 2 and found.severity == "error"

        dialog = _real_dialog(qtbot, VALID)
        assert "No problems found" in dialog.status.text()
        assert "columns" not in dialog.status.text()
        dialog.editor.setPlainText("def f(:\n")
        dialog.run_lint()
        assert [d.line for d in dialog.editor._diagnostics] == [1]
        assert "1 error" in dialog.status.text()

    def test_it_completes_python_not_a_boxs_words(self, qtbot):
        from flograph.ui.editor.completion import CompletionController

        dialog = _real_dialog(qtbot, VALID)
        assert isinstance(dialog.completer, CompletionController)


class TestClosingDoesNotWaitForJedi:
    """Closing the pop-out used to wait, on the GUI thread, for whatever jedi
    call was in flight — the app froze until it returned."""

    @pytest.fixture
    def stuck_jedi(self, monkeypatch):
        """jedi that blocks until released, and records what it was asked."""
        import threading

        import jedi

        gate, started, asked = threading.Event(), threading.Event(), []

        class Stuck:
            def __init__(self, source):
                asked.append(source)
                started.set()
                gate.wait(10)

            def complete(self, *args):
                return []

            def get_signatures(self, *args):
                return []

        monkeypatch.setattr(jedi, "Script", Stuck)
        yield gate, started, asked
        gate.set()
        from flograph.ui.editor import completion
        for thread, _worker in completion._retiring:
            assert thread.wait(5000)
        completion._prune_retiring()

    def test_closing_mid_call_returns_at_once(self, qtbot, stuck_jedi):
        import time

        from PySide6.QtCore import QCoreApplication, QEvent

        from flograph.ui.editor import completion

        gate, started, _asked = stuck_jedi
        dialog = CodePopOut("t", VALID, type_id="x")
        controller = dialog.completer
        controller._request_completions.emit(0, "x", 1, 1)
        assert started.wait(5)
        began = time.perf_counter()
        dialog.done(QDialog.Rejected)
        dialog.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        assert time.perf_counter() - began < 1.0
        # still finishing its call, somewhere a teardown can't destroy it
        assert len(completion._retiring) == 1
        gate.set()

    def test_overtaken_requests_are_skipped(self, qtbot, stuck_jedi):
        gate, started, asked = stuck_jedi
        dialog = _real_dialog(qtbot, VALID)
        controller = dialog.completer
        controller._fire_request()
        assert started.wait(5)          # jedi is busy with the first...
        for _ in range(3):              # ...while three more queue up
            controller._fire_request()
        gate.set()
        qtbot.waitUntil(lambda: len(asked) >= 2, timeout=5000)
        qtbot.wait(100)
        # the three queued behind the first: only the newest reaches jedi
        assert len(asked) == 2
