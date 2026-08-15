"""What the user is told when a node runs out of memory.

A bare MemoryError carries no message, so the obvious "{type}: {exc}" renders
as "MemoryError: " — a colon promising a detail that never comes. And the
error formatter itself allocates, which matters precisely here: if it raises,
the exception escapes the worker's catch-all, the pool thread dies without
reporting, and the node sits in Running forever.
"""
import pytest

from flograph.engine.errors import (
    build_node_error, memory_error_hint, readonly_input_hint,
)


class TestTheMessageSaysSomething:
    def test_bare_memory_error_is_not_just_a_colon(self):
        error = build_node_error("n1", "x = 1", MemoryError())
        assert error.message != "MemoryError: "
        assert not error.message.rstrip().endswith(":")
        assert "memory" in error.message.lower()

    def test_the_hint_is_actionable(self):
        hint = memory_error_hint(MemoryError())
        assert hint is not None
        # names things the user can actually do
        assert "Nodes to run at once" in hint
        assert "Reset Caches" in hint

    def test_a_memory_error_with_a_message_keeps_it(self):
        error = build_node_error("n1", "x = 1", MemoryError("allocation failed"))
        assert "allocation failed" in error.message

    def test_other_errors_get_no_memory_hint(self):
        assert memory_error_hint(ValueError("nope")) is None
        error = build_node_error("n1", "x = 1", ValueError("nope"))
        assert "Reset Caches" not in error.message

    def test_it_does_not_displace_the_existing_hints(self):
        exc = ValueError("array is read-only")
        assert readonly_input_hint(exc) is not None
        assert readonly_input_hint(exc) in build_node_error("n1", "x", exc).message

    def test_exc_type_still_identifies_it(self):
        assert build_node_error("n1", "x", MemoryError()).exc_type == "MemoryError"


class TestFormattingNeverTakesTheThreadDown:
    def test_a_failure_while_formatting_still_yields_an_error(self, monkeypatch):
        """If this raises, NodeRunnable's `except BaseException` is bypassed,
        no `failed` signal is emitted, and the node never leaves Running."""
        import flograph.engine.errors as errors

        def explode(*args, **kwargs):
            raise MemoryError()

        monkeypatch.setattr(errors, "_format_traceback", explode)

        error = build_node_error("n1", "x = 1", MemoryError())
        assert error.node_id == "n1"
        assert error.exc_type == "MemoryError"
        assert "memory" in error.message.lower()
        assert error.script_line is None

    def test_the_traceback_says_it_is_missing_rather_than_being_empty(
            self, monkeypatch):
        import flograph.engine.errors as errors
        monkeypatch.setattr(
            errors, "_format_traceback",
            lambda *a, **k: (_ for _ in ()).throw(MemoryError()))

        error = build_node_error("n1", "x = 1", MemoryError())
        assert "out of memory" in error.formatted_tb.lower()


class TestThroughTheWorker:
    def test_a_node_that_runs_out_of_memory_fails_cleanly(self, qtbot):
        """End to end: the node errors, the message is useful, the run
        finishes, and the app is still standing. No large allocation is
        involved — raising MemoryError takes the same path as hitting it."""
        from flograph.core import Graph, NodeInstance
        from flograph.core.script import parse_spec
        from flograph.engine.scheduler import ExecutionEngine

        graph = Graph()
        node = graph.add_node(NodeInstance.create(parse_spec("""
NODE = {"label": "Boom", "category": "Test",
        "inputs": [], "outputs": [("value", "any")]}
def run(ctx):
    raise MemoryError()
""", "test.oom")))

        engine = ExecutionEngine(graph)
        failures = []
        engine.node_failed.connect(lambda nid, err: failures.append(err))
        with qtbot.waitSignal(engine.run_finished, timeout=5000):
            engine.run_all()

        (error,) = failures
        assert error.exc_type == "MemoryError"
        assert error.message != "MemoryError: "
        assert "memory" in error.message.lower()
        assert "Reset Caches" in error.message
