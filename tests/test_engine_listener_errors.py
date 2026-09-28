"""A view that falls over must not take the run with it.

Seen on a large flow: a node went green, the one after it went orange and
stayed there, and the run never ended. A subscriber to the graph's events
had raised as the first node went DONE, and core.events.Event let that
unwind the scheduler's completion slot before it released the next node.
Being a queued slot, the exception was printed and dropped, so nothing on
screen said anything had gone wrong.
"""
import sys

import pytest

from flograph.core import Graph, NodeInstance, NodeStatus, parse_spec
from flograph.core.events import Event
from flograph.engine import ExecutionEngine

SRC = """
NODE = {"label": "N", "category": "Test",
        "inputs": [("a", "any", {"optional": True})],
        "outputs": [("value", "any")]}
def run(ctx, a=None):
    return {"value": 1}
"""


@pytest.fixture
def reported(monkeypatch):
    """What reached sys.excepthook, instead of pytest-qt failing the test
    on the error it is deliberately provoking."""
    seen = []
    monkeypatch.setattr(sys, "excepthook",
                        lambda kind, value, tb: seen.append(value))
    return seen


def chain(length=3):
    graph = Graph()
    spec = parse_spec(SRC, "test.n")
    nodes = []
    for _ in range(length):
        node = NodeInstance.create(spec)
        graph.add_node(node)
        if nodes:
            graph.connect(nodes[-1].id, "value", node.id, "a")
        nodes.append(node)
    return graph, nodes


def run_all(qtbot, engine):
    with qtbot.waitSignal(engine.run_finished, timeout=10000) as blocker:
        engine.run_all()
    return blocker.args[0]


class TestAnEventTellsEveryone:
    def test_a_raising_subscriber_does_not_stop_the_rest(self, reported):
        event, heard = Event(), []

        def falls_over(value):
            raise RuntimeError("a view fell over")

        event.connect(falls_over)
        event.connect(heard.append)
        event.emit(1)                   # returns, rather than raising
        assert heard == [1]
        assert [str(e) for e in reported] == ["a view fell over"]


class TestTheRunCarriesOn:
    def test_a_listener_raising_at_done_does_not_strand_the_next_node(
            self, qtbot, reported):
        graph, (a, b, c) = chain()

        def falls_over(node_id, status, message):
            if node_id == a.id and status is NodeStatus.DONE:
                raise RuntimeError("a card fell over")

        graph.events.status_changed.connect(falls_over)
        engine = ExecutionEngine(graph)
        assert run_all(qtbot, engine)
        assert [n.status for n in (a, b, c)] == [NodeStatus.DONE] * 3
        assert not engine.active
        assert any("a card fell over" in str(e) for e in reported)

    def test_the_engine_failing_its_own_bookkeeping_still_ends_the_run(
            self, qtbot, reported, monkeypatch):
        """Belt and braces in the scheduler itself: the node says what went
        wrong, and the ones below it are let go rather than left QUEUED."""
        graph, (a, b, c) = chain()
        engine = ExecutionEngine(graph)
        real_set = engine.cache.set

        def set_but_not_for_a(node_id, *args, **kwargs):
            if node_id == a.id:
                raise MemoryError("no room for it")
            return real_set(node_id, *args, **kwargs)

        monkeypatch.setattr(engine.cache, "set", set_but_not_for_a)
        assert not run_all(qtbot, engine)
        assert not engine.active
        assert a.status is NodeStatus.ERROR
        assert "could not be kept: no room for it" in a.status_message
        # not their fault: quiet, as for any upstream that produced nothing
        assert b.status is NodeStatus.IDLE and c.status is NodeStatus.IDLE
        assert any("no room for it" in str(e) for e in reported)
