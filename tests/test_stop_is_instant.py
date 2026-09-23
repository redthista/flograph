"""AE5: Stop ends the run now, not when the slowest node lets it.

A thread cannot be killed, so a node stuck in one long call — a database
read, a big pandas op, a `time.sleep` — used to hold the whole run open
until it returned by itself. Stop now walks away from it: the run ends at
once, the node's late result is thrown away, and the node is not started
again until its old thread has gone."""
import threading
import time

from flograph.core import Graph, NodeInstance, NodeStatus, parse_spec
from flograph.engine import ExecutionEngine

# Blocks until the test lets it go, and never checks for Stop — the case
# cancellation cannot reach.
STUCK = '''
NODE = {"label": "Stuck", "category": "Test", "inputs": [],
        "outputs": [("value", "any")]}
PARAMS = [{"name": "key", "type": "string", "default": ""}]
def run(ctx):
    import flograph_test_gates as gates
    gates.wait(ctx.params["key"])
    return 42
'''

QUICK = '''
NODE = {"label": "Quick", "category": "Test", "inputs": [],
        "outputs": [("value", "any")]}
def run(ctx):
    return 7
'''


class _Gates:
    """Named events a node script can wait on, importable from its body."""

    def __init__(self):
        self.events: dict = {}
        self.entered: dict = {}

    def _event(self, table, key):
        return table.setdefault(key, threading.Event())

    def wait(self, key):
        self._event(self.entered, key).set()
        self._event(self.events, key).wait(20)

    def release(self, key):
        self._event(self.events, key).set()

    def has_entered(self, key):
        return self._event(self.entered, key).is_set()


def _install_gates(monkeypatch):
    import sys
    import types
    gates = _Gates()
    module = types.ModuleType("flograph_test_gates")
    module.wait = gates.wait
    monkeypatch.setitem(sys.modules, "flograph_test_gates", module)
    return gates


def add(graph, source, type_id, **params):
    node = NodeInstance.create(parse_spec(source, type_id))
    node.params.update(params)
    graph.add_node(node)
    return node


def test_stop_ends_the_run_at_once(qtbot, monkeypatch):
    gates = _install_gates(monkeypatch)
    graph = Graph()
    stuck = add(graph, STUCK, "test.stuck", key="a")
    engine = ExecutionEngine(graph)
    engine.run_all()
    qtbot.waitUntil(lambda: gates.has_entered("a"), timeout=5000)

    finished = []
    engine.run_finished.connect(lambda ok: finished.append(time.perf_counter()))
    started = time.perf_counter()
    engine.cancel()
    assert finished and finished[0] - started < 0.1
    assert not engine.active
    assert stuck.id in engine.abandoned_nodes
    # still running is the truth, and the light keeps saying so
    assert graph.node(stuck.id).status is NodeStatus.RUNNING

    gates.release("a")
    qtbot.waitUntil(lambda: not engine.abandoned_nodes, timeout=5000)
    assert graph.node(stuck.id).status is NodeStatus.IDLE   # nothing kept


def test_a_late_result_is_thrown_away(qtbot, monkeypatch):
    gates = _install_gates(monkeypatch)
    graph = Graph()
    stuck = add(graph, STUCK, "test.stuck", key="b")
    engine = ExecutionEngine(graph)
    succeeded = []
    engine.node_succeeded.connect(succeeded.append)
    engine.run_all()
    qtbot.waitUntil(lambda: gates.has_entered("b"), timeout=5000)
    engine.cancel()
    gates.release("b")
    qtbot.waitUntil(lambda: not engine.abandoned_nodes, timeout=5000)
    assert not engine.cache.has(stuck.id)
    assert succeeded == []
    assert graph.node(stuck.id).dirty


def test_a_new_run_waits_for_the_old_thread_of_the_same_node(
        qtbot, monkeypatch):
    """Two copies of one node's body at once would race on everything it
    touches — so the re-run waits, and then runs it properly."""
    gates = _install_gates(monkeypatch)
    graph = Graph()
    stuck = add(graph, STUCK, "test.stuck", key="c")
    engine = ExecutionEngine(graph)
    engine.run_all()
    qtbot.waitUntil(lambda: gates.has_entered("c"), timeout=5000)
    engine.cancel()

    entered_before = gates.entered["c"]
    gates.entered["c"] = threading.Event()      # watch for a second entry
    with qtbot.waitSignal(engine.run_finished, timeout=15000) as blocker:
        engine.run_all()
        assert engine.active
        # not started a second time while the first is still inside
        time.sleep(0.2)
        assert not gates.has_entered("c")
        gates.release("c")                       # both copies may pass now
    assert blocker.args[0]
    assert entered_before.is_set()
    assert engine.cache.has(stuck.id)
    assert graph.node(stuck.id).status is NodeStatus.DONE


def test_other_nodes_do_not_wait_for_an_abandoned_one(qtbot, monkeypatch):
    gates = _install_gates(monkeypatch)
    graph = Graph()
    add(graph, STUCK, "test.stuck", key="d")
    engine = ExecutionEngine(graph)
    engine.max_workers = 4
    engine.run_all()
    qtbot.waitUntil(lambda: gates.has_entered("d"), timeout=5000)
    engine.cancel()

    quick = add(graph, QUICK, "test.quick")
    with qtbot.waitSignal(engine.run_finished, timeout=10000):
        engine.run_targets([quick.id])
    assert engine.cache.has(quick.id)
    gates.release("d")
    qtbot.waitUntil(lambda: not engine.abandoned_nodes, timeout=5000)


def test_an_abandoned_thread_still_uses_a_worker(qtbot, monkeypatch):
    """With one worker and it still busy, a new run waits for it rather
    than oversubscribing the machine."""
    gates = _install_gates(monkeypatch)
    graph = Graph()
    add(graph, STUCK, "test.stuck", key="e")
    engine = ExecutionEngine(graph)
    engine.max_workers = 1
    engine.run_all()
    qtbot.waitUntil(lambda: gates.has_entered("e"), timeout=5000)
    engine.cancel()

    quick = add(graph, QUICK, "test.quick")
    with qtbot.waitSignal(engine.run_finished, timeout=10000):
        engine.run_targets([quick.id])
        qtbot.wait(150)
        assert not engine.cache.has(quick.id)   # waiting for the worker
        gates.release("e")
    assert engine.cache.has(quick.id)


def test_the_status_line_names_what_is_still_finishing(qtbot, monkeypatch,
                                                       tmp_path, registry):
    from PySide6.QtCore import QSettings

    from flograph.ui import mainwindow as mod
    from flograph.ui.mainwindow import MainWindow

    ini = str(tmp_path / "settings.ini")
    monkeypatch.setattr(mod, "QSettings",
                        lambda *a, **k: QSettings(ini, QSettings.IniFormat))
    gates = _install_gates(monkeypatch)
    win = MainWindow(registry)
    win.confirm_close = False
    qtbot.addWidget(win)
    add(win.graph, STUCK, "test.stuck", key="f")
    win.engine.run_all()
    qtbot.waitUntil(lambda: gates.has_entered("f"), timeout=5000)
    win.engine.cancel()
    assert "Stuck is still finishing" in win._status_label.text()

    gates.release("f")
    qtbot.waitUntil(lambda: not win.engine.abandoned_nodes, timeout=5000)
    assert "nothing from it was kept" in win._status_label.text()
