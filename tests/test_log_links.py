"""Log lines carry a severity mark besides their colour, and a line's node
name is a link that asks to go to that node (#122)."""
from PySide6.QtCore import QEvent, QObject, QPointF, Qt, Signal
from PySide6.QtGui import QMouseEvent

from flograph.core import Graph, NodeRegistry
from flograph.ui.console.log_dock import LogConsole


class _Engine(QObject):
    """Just the signals LogConsole listens to."""
    node_log = Signal(str, str, str)
    node_failed = Signal(str, object)
    run_started = Signal()
    run_finished = Signal(bool)


def _console(qtbot):
    reg = NodeRegistry()
    reg.load_builtins()
    graph = Graph()
    node = graph.add_node(reg.instantiate("flograph.io.table"))
    engine = _Engine()
    console = LogConsole(graph, engine)
    qtbot.addWidget(console)
    console.resize(600, 200)
    console.show()
    return console, engine, node


def test_lines_carry_a_mark_as_well_as_a_colour(qtbot):
    console, engine, node = _console(qtbot)
    engine.node_log.emit(node.id, "boom", "error")
    engine.node_log.emit(node.id, "careful", "stderr")
    text = console._text.toPlainText()
    assert "✕" in text.splitlines()[0]
    assert "!" in text.splitlines()[1]


def test_clicking_the_node_name_asks_for_the_node(qtbot):
    console, engine, node = _console(qtbot)
    engine.node_log.emit(node.id, "hello", "log")
    viewport = console._text.viewport()
    cursor = console._text.document().find("[Table]")
    assert not cursor.isNull()
    cursor.setPosition(cursor.selectionStart() + 2)
    pos = console._text.cursorRect(cursor).center()
    with qtbot.waitSignal(console.node_requested, timeout=1000) as blocker:
        for kind in (QEvent.MouseButtonPress, QEvent.MouseButtonRelease):
            console.eventFilter(viewport, QMouseEvent(
                kind, QPointF(pos), QPointF(viewport.mapToGlobal(pos)),
                Qt.LeftButton, Qt.LeftButton, Qt.NoModifier))
    assert blocker.args == [node.id]
