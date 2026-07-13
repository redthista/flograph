from __future__ import annotations

import gc

import pytest

from flograph.core import Graph, NodeInstance, NodeRegistry, parse_spec


@pytest.fixture(autouse=True)
def _drain_qt_after_each_test():
    """Destroy each test's Qt debris deterministically, right here.

    Windows/scenes/animations dropped by a test otherwise linger until
    Python's GC runs at some arbitrary later point — typically inside a
    *later* test's event processing, where a running timer (e.g. a node's
    status-pulse QVariantAnimation) fires into a half-deleted object and
    segfaults the suite. Collecting now, then draining deferred deletions
    while the interpreter state is coherent, keeps teardown ordered."""
    yield
    import sys
    app_module = sys.modules.get("PySide6.QtWidgets")
    app = app_module.QApplication.instance() if app_module else None
    gc.collect()
    if app is not None:
        app.processEvents()
        app.processEvents()  # deferred deletions posted by the first pass


class FakeContext:
    """Minimal stand-in for the engine's RunContext, for direct run() calls."""

    def __init__(self, params=None, node_id="test-node"):
        self.params = params or {}
        self.node_id = node_id
        self.logs: list[str] = []

    def log(self, msg: str) -> None:
        self.logs.append(str(msg))

    def check_cancelled(self) -> None:
        pass

    def progress(self, fraction: float) -> None:
        pass


PASSTHROUGH = """
NODE = {
    "label": "Pass",
    "category": "Test",
    "inputs": [("value", "any", {"optional": True})],
    "outputs": [("value", "any")],
}
def run(ctx, value):
    return value
"""


def make_node(source: str = PASSTHROUGH, type_id: str = "test.pass",
              pos=(0.0, 0.0)) -> NodeInstance:
    return NodeInstance.create(parse_spec(source, type_id), pos=pos)


@pytest.fixture
def fake_ctx():
    return FakeContext


@pytest.fixture(scope="session")
def registry() -> NodeRegistry:
    reg = NodeRegistry()
    reg.load_builtins()
    return reg


@pytest.fixture
def chain_graph() -> tuple[Graph, list[NodeInstance]]:
    """a -> b -> c passthrough chain."""
    graph = Graph()
    nodes = [make_node() for _ in range(3)]
    for node in nodes:
        graph.add_node(node)
    graph.connect(nodes[0].id, "value", nodes[1].id, "value")
    graph.connect(nodes[1].id, "value", nodes[2].id, "value")
    return graph, nodes
