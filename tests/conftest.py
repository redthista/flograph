from __future__ import annotations

import gc
import os

# Before flograph is imported, so every engine built in the suite reads it.
# The engine halves its worker limit when the machine is short of memory,
# which is right in the app and wrong here: several tests prove that nodes
# *do* run side by side, and they would fail on a busy machine for a reason
# that has nothing to do with what they are testing. Tests that want the
# throttle set engine.memory_adapt = True and drive engine.memory_probe.
os.environ.setdefault("FLOGRAPH_MEMORY_ADAPT", "0")

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

    def __init__(self, params=None, node_id="test-node", variables=None):
        self.params = params or {}
        self.vars = variables or {}
        self.node_id = node_id
        self.logs: list[str] = []
        self.fractions: list[float] = []

    def log(self, msg: str) -> None:
        self.logs.append(str(msg))

    def check_cancelled(self) -> None:
        pass

    def progress(self, fraction: float) -> None:
        # Unthrottled, unlike the real RunContext: a node test wants every
        # call it made, not the subset a GUI would have been shown.
        self.fractions.append(float(fraction))


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


def install_fake_weblib(monkeypatch, tmp_path, name="mermaid",
                        filename=None, source="/* stub */",
                        version="stub"):
    """Plant a web library in a throwaway store and return its directory.

    The suite must never reach a CDN — an install is a network call, and a
    test that needs one is a test that fails on a train. This writes what
    `weblibs.install()` would have written, so everything downstream of the
    download (resolution, markup, a node rendering) is exercised for real
    against files that were never fetched.
    """
    import json

    monkeypatch.setenv("FLOGRAPH_USER_DIR", str(tmp_path))
    from flograph import weblibs

    entry = weblibs.CATALOGUE.get(name)
    if entry is not None:
        version = entry.version
        # Every file the catalogue lists, not just the first: a library is
        # only installed when all of them are there (Leaflet is a script
        # *and* a stylesheet), so planting one would read as a half-install.
        names = [asset.filename for asset in entry.assets]
        if filename is not None:
            names = [filename]
    else:
        names = [filename or f"{name}.js"]

    directory = tmp_path / "weblibs" / name / version
    directory.mkdir(parents=True, exist_ok=True)
    for one in names:
        (directory / one).write_text(source, encoding="utf-8")
    (directory / "flograph-weblib.json").write_text(json.dumps({
        "name": name, "title": name, "version": version,
        "summary": "", "license": "", "homepage": "",
        "assets": [{"filename": one, "url": "", "sha256": "",
                    "size": len(source)} for one in names],
    }), encoding="utf-8")
    return directory
