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
write (so the original is safe). The same has to hold for whatever else a
node passes along: a step that adds an item to a list must show up after
that step and not before it. Lists, dicts, sets and bytearrays are rebuilt
one level deep, and numpy arrives read-only, since numpy has no
copy-on-write and duplicating an array is not free.
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


def emitter(value_expr: str) -> str:
    return f"""
NODE = {{"label": "Emit", "category": "Test",
        "inputs": [], "outputs": [("result", "any")]}}
import pandas as pd, numpy as np
def run(ctx):
    return {value_expr}
"""


def mutator(body: str) -> str:
    return f"""
NODE = {{"label": "Mutate", "category": "Test",
        "inputs": [("value", "any")], "outputs": [("result", "any")]}}
def run(ctx, value):
    {body}
    return value
"""


class TestPlainPythonValuesAreIsolatedToo:
    """The same guarantee for the values that are not frames.

    Each case runs one source and one node that mutates its input the way
    anyone would write it, then asserts the source's cached output — what
    every other branch reads, and what the inspector shows — is untouched.
    """

    @pytest.mark.parametrize("value_expr, body, before", [
        ("[1, 2, 3]", "value.append(4)", [1, 2, 3]),
        ("[3, 1, 2]", "value.sort()", [3, 1, 2]),
        ("[1, 2, 3]", "value[0] = 99", [1, 2, 3]),
        ("[1, 2, 3]", "del value[0]", [1, 2, 3]),
        ("{'a': 1}", "value['b'] = 2", {"a": 1}),
        ("{'a': 1}", "value.update(b=2)", {"a": 1}),
        ("{'a'}", "value.add('b')", {"a"}),
        ("bytearray(b'ab')", "value.extend(b'c')", bytearray(b"ab")),
    ], ids=["append", "sort", "setitem", "delitem", "dict-set",
            "dict-update", "set-add", "bytearray"])
    def test_mutating_an_input_leaves_the_upstream_cache_alone(
            self, qtbot, registry, value_expr, body, before):
        graph = Graph()
        src = graph.add_node(registry.instantiate(SCRIPT))
        graph.set_code(src.id, emitter(value_expr))
        writer = graph.add_node(registry.instantiate(SCRIPT))
        graph.set_code(writer.id, mutator(body))
        graph.connect(src.id, "result", writer.id, "value")

        engine = run_graph(qtbot, graph)
        assert engine.cache.outputs_for(src.id)["result"] == before
        # ...and the node making the change still sees it
        assert engine.cache.outputs_for(writer.id)["result"] != before

    def test_the_added_item_shows_downstream_of_the_step_that_added_it(
            self, qtbot, registry):
        """The other half: isolation must not stop a change propagating along
        the flow it belongs to."""
        graph = Graph()
        src = graph.add_node(registry.instantiate(SCRIPT))
        graph.set_code(src.id, emitter("[1, 2, 3]"))
        adder = graph.add_node(registry.instantiate(SCRIPT))
        graph.set_code(adder.id, mutator("value.append(4)"))
        reader = graph.add_node(registry.instantiate(SCRIPT))
        graph.set_code(reader.id, mutator("pass"))
        graph.connect(src.id, "result", adder.id, "value")
        graph.connect(adder.id, "result", reader.id, "value")

        engine = run_graph(qtbot, graph)
        assert engine.cache.outputs_for(reader.id)["result"] == [1, 2, 3, 4]

    def test_a_sibling_branch_does_not_see_the_item(self, qtbot, registry):
        """Two branches off one list: the one that appends must not change
        what the other one reads."""
        graph = Graph()
        src = graph.add_node(registry.instantiate(SCRIPT))
        graph.set_code(src.id, emitter("[1, 2, 3]"))
        adder = graph.add_node(registry.instantiate(SCRIPT))
        graph.set_code(adder.id, mutator("value.append(4)"))
        sibling = graph.add_node(registry.instantiate(SCRIPT))
        graph.set_code(sibling.id, mutator("value = list(value)"))
        graph.connect(src.id, "result", adder.id, "value")
        graph.connect(src.id, "result", sibling.id, "value")

        engine = run_graph(qtbot, graph)
        assert engine.cache.outputs_for(sibling.id)["result"] == [1, 2, 3]

    def test_a_frame_inside_a_list_is_guarded_as_well(self, qtbot, registry):
        """A list of frames is the one nested case that is free to protect —
        each item is a pandas value, so it gets the copy-on-write copy."""
        graph = Graph()
        src = graph.add_node(registry.instantiate(SCRIPT))
        graph.set_code(src.id, emitter("[pd.DataFrame({'x': [1, 2]})]"))
        writer = graph.add_node(registry.instantiate(SCRIPT))
        graph.set_code(writer.id, mutator("value[0]['added'] = 1"))
        graph.connect(src.id, "result", writer.id, "value")

        engine = run_graph(qtbot, graph)
        cached = engine.cache.outputs_for(src.id)["result"]
        assert list(cached[0].columns) == ["x"]

    def test_the_items_themselves_are_not_copied(self, qtbot, registry):
        """Rebuilding the container must stay a pointer copy: the items are
        the same objects, which is what keeps this cheap enough to do on
        every hop."""
        graph = Graph()
        src = graph.add_node(registry.instantiate(SCRIPT))
        graph.set_code(src.id, emitter("[{'a': 1}, {'b': 2}]"))
        passthrough = graph.add_node(registry.instantiate(SCRIPT))
        graph.set_code(passthrough.id, mutator("pass"))
        graph.connect(src.id, "result", passthrough.id, "value")

        engine = run_graph(qtbot, graph)
        owned = engine.cache.outputs_for(src.id)["result"]
        served = engine.cache.outputs_for(passthrough.id)["result"]
        assert served is not owned
        assert all(a is b for a, b in zip(served, owned))
        # a pass-through is still recognised as re-serving the upstream value
        assert engine.cache.get(passthrough.id).alias_of == src.id

    def test_reaching_through_an_input_is_still_the_contract(
            self, qtbot, registry):
        """The documented boundary. One level is rebuilt, not the items in
        it — rebuilding those would allocate a dict per row of a 100k-row
        record list on every hop. Writing *through* an input stays a contract
        violation, and this test exists so that stays a deliberate choice."""
        graph = Graph()
        src = graph.add_node(registry.instantiate(SCRIPT))
        graph.set_code(src.id, emitter("[{'a': 1}]"))
        writer = graph.add_node(registry.instantiate(SCRIPT))
        graph.set_code(writer.id, mutator("value[0]['a'] = 99"))
        graph.connect(src.id, "result", writer.id, "value")

        engine = run_graph(qtbot, graph)
        assert engine.cache.outputs_for(src.id)["result"] == [{"a": 99}]


class TestArrayInputsRefuseTheWrite:
    """numpy has no copy-on-write, so the only free guard is to say no.

    A duplicate of an array that may be gigabytes is a cost the engine should
    not impose silently; raising where the mistake is made is both correct
    and free, and the node's own copy is one line away.
    """

    def run_writer(self, qtbot, registry, body):
        graph = Graph()
        src = graph.add_node(registry.instantiate(SCRIPT))
        graph.set_code(src.id, emitter("np.arange(4)"))
        writer = graph.add_node(registry.instantiate(SCRIPT))
        graph.set_code(writer.id, mutator(body))
        graph.connect(src.id, "result", writer.id, "value")

        failures = []
        engine = ExecutionEngine(graph)
        engine.node_failed.connect(lambda nid, err: failures.append(err))
        with qtbot.waitSignal(engine.run_finished, timeout=20000):
            engine.run_all()
        return engine, failures, src.id, writer.id

    @pytest.mark.parametrize("body", ["value[0] = 99", "value += 1",
                                      "value.sort()"])
    def test_writing_through_an_array_input_fails_the_node(
            self, qtbot, registry, body):
        engine, failures, src_id, writer_id = self.run_writer(
            qtbot, registry, body)
        assert [err.node_id for err in failures] == [writer_id]
        # the array upstream is what it always was
        assert list(engine.cache.outputs_for(src_id)["result"]) == [0, 1, 2, 3]

    def test_the_failure_says_what_to_do_about_it(self, qtbot, registry):
        """numpy's own "assignment destination is read-only" never says why
        the array is read-only, which reads as a bug in the app."""
        failures = self.run_writer(qtbot, registry, "value[0] = 99")[1]
        assert "arr.copy()" in failures[0].message
        assert "read-only" in failures[0].message

    def test_reading_an_array_input_is_untouched(self, qtbot, registry):
        graph = Graph()
        src = graph.add_node(registry.instantiate(SCRIPT))
        graph.set_code(src.id, emitter("np.arange(4)"))
        reader = graph.add_node(registry.instantiate(SCRIPT))
        graph.set_code(reader.id, mutator("value = value + 1"))
        graph.connect(src.id, "result", reader.id, "value")

        engine = run_graph(qtbot, graph)
        assert list(engine.cache.outputs_for(reader.id)["result"]) == [1, 2, 3, 4]
        assert list(engine.cache.outputs_for(src.id)["result"]) == [0, 1, 2, 3]

    def test_a_frame_over_an_array_still_writes_freely(self, qtbot, registry):
        """The read-only view must not leak into pandas: a frame's blocks are
        guarded by copy-on-write, not by the writeable flag, so writing to a
        frame input keeps just working."""
        graph = Graph()
        src = graph.add_node(registry.instantiate(SCRIPT))
        graph.set_code(src.id, emitter("pd.DataFrame({'x': [1, 2, 3]})"))
        writer = graph.add_node(registry.instantiate(SCRIPT))
        graph.set_code(writer.id, mutator("value['x'] = 0"))
        graph.connect(src.id, "result", writer.id, "value")

        engine = run_graph(qtbot, graph)
        assert list(engine.cache.outputs_for(writer.id)["result"]["x"]) == [0, 0, 0]
        assert list(engine.cache.outputs_for(src.id)["result"]["x"]) == [1, 2, 3]
