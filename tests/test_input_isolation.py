"""A node cannot write into the value cached against the node upstream.

Outputs are cached and handed downstream by reference, and the node contract
has always said inputs are read-only. Nothing enforced it. A script that
wrote to its input instead — `table["pattern"] = ...`, `df.loc[:, c] = ...`,
`rename(inplace=True)` — reached back into the entry cached against the node
upstream and rewrote a value other branches had already been served.

Under copy-on-write that is silent rather than loud: a branch that took its
copy *before* the write keeps the old values, so a Filter downstream shows a
column sitting empty while the same column upstream is populated. Nothing
looks broken, the cache is not stale, and clearing it changes nothing —
re-running reproduces the same order and the same result.

Each node now receives its pandas inputs as a copy-on-write shallow copy,
which shares every block (so nothing is duplicated) but copies on the first
write (so the original is safe).
"""
import numpy as np
import pandas as pd
import pytest

from flograph.core import Graph, NodeRegistry
from flograph.engine.scheduler import ExecutionEngine

SCRIPT = "flograph.scripting.python_script"
FILTER = "flograph.transform.filter_rows"

SOURCE = """
NODE = {"label": "Source", "category": "Test",
        "inputs": [], "outputs": [("result", "any")]}
import pandas as pd
def run(ctx):
    return pd.DataFrame({"x": [1, 2, 3], "pattern": ["", "", ""]})
"""

# Every in-place idiom a data-modelling script reaches for by habit.
ASSIGN_COLUMN = """
NODE = {"label": "Assign", "category": "Test",
        "inputs": [("value", "any")], "outputs": [("result", "any")]}
def run(ctx, value):
    value["pattern"] = "//"
    return value
"""

LOC_WRITE = """
NODE = {"label": "Loc", "category": "Test",
        "inputs": [("value", "any")], "outputs": [("result", "any")]}
def run(ctx, value):
    value.loc[:, "pattern"] = "//"
    return value
"""

INPLACE_RENAME = """
NODE = {"label": "Rename", "category": "Test",
        "inputs": [("value", "any")], "outputs": [("result", "any")]}
def run(ctx, value):
    value.rename(columns={"x": "renamed"}, inplace=True)
    return value
"""

NEW_COLUMN = """
NODE = {"label": "NewCol", "category": "Test",
        "inputs": [("value", "any")], "outputs": [("result", "any")]}
def run(ctx, value):
    value["brand_new"] = 1
    return value
"""


@pytest.fixture(scope="module")
def registry():
    reg = NodeRegistry()
    reg.load_builtins()
    return reg


def run_graph(qtbot, graph):
    engine = ExecutionEngine(graph)
    with qtbot.waitSignal(engine.run_finished, timeout=20000):
        engine.run_all()
    return engine


class TestInputsAreIsolated:
    @pytest.mark.parametrize("code", [ASSIGN_COLUMN, LOC_WRITE, NEW_COLUMN,
                                      INPLACE_RENAME])
    def test_writing_to_an_input_leaves_the_upstream_cache_alone(
            self, qtbot, registry, code):
        graph = Graph()
        src = graph.add_node(registry.instantiate(SCRIPT))
        graph.set_code(src.id, SOURCE)
        writer = graph.add_node(registry.instantiate(SCRIPT))
        graph.set_code(writer.id, code)
        graph.connect(src.id, "result", writer.id, "value")

        engine = run_graph(qtbot, graph)
        cached = engine.cache.outputs_for(src.id)["result"]
        pd.testing.assert_frame_equal(
            cached, pd.DataFrame({"x": [1, 2, 3], "pattern": ["", "", ""]}))

    def test_the_writer_still_sees_its_own_change(self, qtbot, registry):
        """Isolation must not cost the node its own write."""
        graph = Graph()
        src = graph.add_node(registry.instantiate(SCRIPT))
        graph.set_code(src.id, SOURCE)
        writer = graph.add_node(registry.instantiate(SCRIPT))
        graph.set_code(writer.id, LOC_WRITE)
        graph.connect(src.id, "result", writer.id, "value")

        engine = run_graph(qtbot, graph)
        out = engine.cache.outputs_for(writer.id)["result"]
        assert list(out["pattern"]) == ["//", "//", "//"]

    def test_a_column_added_upstream_reaches_a_filter_downstream(
            self, qtbot, registry):
        """The chain case, which must keep working: a Filter fed by the node
        that added the column sees it populated."""
        graph = Graph()
        src = graph.add_node(registry.instantiate(SCRIPT))
        graph.set_code(src.id, SOURCE)
        writer = graph.add_node(registry.instantiate(SCRIPT))
        graph.set_code(writer.id, LOC_WRITE)
        filt = graph.add_node(registry.instantiate(FILTER))
        graph.set_param(filt.id, "query", "x > 0")
        graph.connect(src.id, "result", writer.id, "value")
        graph.connect(writer.id, "result", filt.id, "table")

        engine = run_graph(qtbot, graph)
        out = engine.cache.outputs_for(filt.id)["filtered"]
        assert list(out["pattern"]) == ["//", "//", "//"]

    def test_a_sibling_branch_is_not_rewritten_underneath(
            self, qtbot, registry):
        """The reported bug. Two branches off one source: one writes to its
        input in place, the other filters. The filter is not downstream of
        the writer, so it must see exactly what the source produced —
        before, it saw whichever version won the race."""
        graph = Graph()
        src = graph.add_node(registry.instantiate(SCRIPT))
        graph.set_code(src.id, SOURCE)
        filt = graph.add_node(registry.instantiate(FILTER))
        graph.set_param(filt.id, "query", "x > 0")
        writer = graph.add_node(registry.instantiate(SCRIPT))
        graph.set_code(writer.id, INPLACE_RENAME)
        graph.connect(src.id, "result", filt.id, "table")
        graph.connect(src.id, "result", writer.id, "value")

        engine = run_graph(qtbot, graph)
        filtered = engine.cache.outputs_for(filt.id)["filtered"]
        # the sibling's in-place rename must not have reached this branch
        assert list(filtered.columns) == ["x", "pattern"]

    def test_isolation_does_not_duplicate_the_data(self, qtbot, registry):
        """The guard has to be free, or it is not worth having: a shallow
        copy under copy-on-write shares its blocks with the original."""
        graph = Graph()
        src = graph.add_node(registry.instantiate(SCRIPT))
        graph.set_code(src.id, SOURCE)
        passthrough = graph.add_node(registry.instantiate(SCRIPT))
        graph.set_code(passthrough.id, """
NODE = {"label": "Pass", "category": "Test",
        "inputs": [("value", "any")], "outputs": [("result", "any")]}
def run(ctx, value):
    return value
""")
        graph.connect(src.id, "result", passthrough.id, "value")

        engine = run_graph(qtbot, graph)
        owned = engine.cache.outputs_for(src.id)["result"]
        served = engine.cache.outputs_for(passthrough.id)["result"]
        assert np.shares_memory(served["x"].values, owned["x"].values)
        # and a pass-through is still recognised as serving the upstream value
        assert engine.cache.get(passthrough.id).alias_of == src.id
        assert engine.cache.total_bytes() == \
            engine.cache.get(src.id).memory_bytes
