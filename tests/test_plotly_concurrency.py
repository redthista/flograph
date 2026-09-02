"""Building Plotly figures side by side.

Node bodies share the process, so two nodes can be inside `px.bar()` at the
same moment. That is not safe: px resolves an unset palette by reading the
trace defaults off the shared template singleton, and stamping a template
onto a figure re-parents that same object — so one node's build corrupts
the other's, and plotly raises a bare `ValueError: Invalid value` from
`BaseFigure._index_is` on whichever lost the race.

Found on the chart-gallery example, which is the first flow with eight
plotly nodes ready at once: two runs in five failed at the default worker
count, none in three at a single worker. `plotly_spec.FIGURE_LOCK` closes
it.
"""
import threading

import pandas as pd
import pytest

from flograph.core import NodeRegistry, compile_run, plotly_spec
from tests.conftest import FakeContext

pytest.importorskip("plotly")


@pytest.fixture(scope="module")
def registry():
    reg = NodeRegistry()
    reg.load_builtins()
    return reg


@pytest.fixture
def table():
    return pd.DataFrame({
        "region": ["North", "South", "East"] * 4,
        "category": ["Tools", "Paint"] * 6,
        "revenue": [100.0 + i for i in range(12)],
        "cost": [50.0 + i for i in range(12)],
    })


def test_the_lock_exists_and_is_a_real_lock():
    assert isinstance(plotly_spec.FIGURE_LOCK, type(threading.Lock()))


def _code_only(source: str) -> str:
    """The source with comments removed.

    Show Web View's docstring-and-comment example shows a `px.line(...)`
    call it never makes, and a sweep matching raw text believes it.
    """
    import io
    import tokenize

    lines = source.splitlines()
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type != tokenize.COMMENT:
            continue
        row = token.start[0] - 1
        start, end = token.start[1], token.end[1]
        lines[row] = lines[row][:start] + " " * (end - start) + \
            lines[row][end:]
    return "\n".join(lines)


def test_every_figure_building_node_takes_it(registry):
    """A sweep, not a list: a plotly node added later has to make the same
    call deliberately rather than inheriting the bug."""
    builders, unguarded = [], []
    for spec in registry.all():
        source = _code_only(spec.source)
        if "import plotly" not in source:
            continue
        if not any(mark in source for mark in ("go.Figure(", "px,", "px.")):
            continue
        builders.append(spec.type_id)
        if "FIGURE_LOCK" not in source:
            unguarded.append(spec.type_id)
    assert builders, "no plotly nodes found — has the sweep gone stale?"
    assert unguarded == []


def test_the_sweep_finds_the_nodes_it_should(registry):
    """Guards the guard: a sweep that silently matched nothing would pass
    the test above for the wrong reason."""
    found = {spec.type_id for spec in registry.all()
             if "FIGURE_LOCK" in _code_only(spec.source)}
    assert found >= {"flograph.viz.show_plotly",
                     "flograph.viz.chart_per_value_plotly",
                     "flograph.viz.plotly_style",
                     "flograph.viz.plotly_table",
                     "flograph.viz.gantt"}


class TestBuildingAtTheSameTime:
    """What the engine does when several chart nodes go ready together.

    Without the lock these fail intermittently; with it they cannot, so
    the test is not flaky in the direction that matters.
    """

    ROUNDS = 25

    def _runner(self, registry, type_id, params):
        spec = registry.get(type_id)
        values = spec.default_params()
        values.update(params)
        run = compile_run(spec.source, type_id)
        return lambda **inputs: run(FakeContext(params=dict(values)),
                                    **inputs)

    def test_charts_tables_and_styling_all_at_once(self, registry, table):
        show = self._runner(registry, "flograph.viz.show_plotly",
                            {"kind": "bar", "x": "region", "y": "revenue",
                             "color": "category"})
        box = self._runner(registry, "flograph.viz.show_plotly",
                           {"kind": "box", "x": "category", "y": "revenue",
                            "color": "category"})
        pie = self._runner(registry, "flograph.viz.show_plotly",
                           {"kind": "pie", "names": "category",
                            "values": "revenue"})
        table_node = self._runner(registry, "flograph.viz.plotly_table",
                                  {"template": "plotly_white"})
        style = self._runner(registry, "flograph.viz.plotly_style",
                             {"template": "plotly_dark",
                              "legend_pos": "top"})
        base = show(table=table)["figure"]

        errors = []
        start = threading.Barrier(6)

        def hammer(work):
            try:
                start.wait()
                for _ in range(self.ROUNDS):
                    work()
            except Exception as exc:            # noqa: BLE001 - reported
                errors.append(f"{type(exc).__name__}: {exc}")

        jobs = [
            lambda: show(table=table),
            lambda: box(table=table),
            lambda: pie(table=table),
            lambda: table_node(table=table),
            lambda: style(figure=base),
            lambda: style(figure=[base, base]),
        ]
        threads = [threading.Thread(target=hammer, args=(job,))
                   for job in jobs]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert errors == []

    def test_a_split_builds_its_stack_under_the_lock(self, registry, table):
        """Chart per Value takes the lock per chart, not per run — holding
        it across a forty-chart split would stall every other plotly node
        for the whole of it."""
        source = registry.get(
            "flograph.viz.chart_per_value_plotly").source
        body = source[source.index("for index, (value, group)"):]
        assert "with _figure_lock():" in body

        split = self._runner(registry,
                             "flograph.viz.chart_per_value_plotly",
                             {"split_by": "region", "kind": "bar",
                              "x": "category", "y": "revenue"})
        errors = []
        start = threading.Barrier(3)

        def hammer():
            try:
                start.wait()
                for _ in range(10):
                    split(table=table)
            except Exception as exc:            # noqa: BLE001 - reported
                errors.append(f"{type(exc).__name__}: {exc}")

        threads = [threading.Thread(target=hammer) for _ in range(3)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert errors == []


#: The nodes that must keep working when dropped into a user-nodes folder
#: on a flograph that predates `core.plotly_spec`. All four plotly-drawing
#: nodes are self-contained this way — Show Plotly and Chart per Value
#: (Plotly) each carry their own ~1000-line copy of the chart-kind
#: catalogue rather than sharing it, on the reasoning in the note above
#: `_figure_lock` in either file: a node script is meant to be readable
#: without a trip to `core/`. `test_plotly_spec.py` is what keeps the two
#: copies from drifting apart instead.
STANDALONE = ("flograph.viz.show_plotly", "flograph.viz.chart_per_value_plotly",
             "flograph.viz.plotly_table", "flograph.viz.plotly_style")


class TestStandalone:
    """These two import nothing from flograph that they cannot do without.

    A node script is executed on its own, so anything it imports has to be
    installed. These two are meant to be droppable into an older flograph,
    which means every `from flograph...` has to sit behind a fallback.
    """

    @pytest.mark.parametrize("type_id", STANDALONE)
    def test_no_unguarded_flograph_import(self, registry, type_id):
        import ast

        tree = ast.parse(registry.get(type_id).source)
        guarded = {node for handler in ast.walk(tree)
                   if isinstance(handler, ast.Try)
                   for node in ast.walk(handler.body[0] if handler.body
                                        else handler)}
        unguarded = []
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Import, ast.ImportFrom)):
                continue
            name = (node.names[0].name if isinstance(node, ast.Import)
                    else (node.module or ""))
            if name.split(".")[0] == "flograph" and node not in guarded:
                unguarded.append(f"line {node.lineno}: {name}")
        assert unguarded == []

    @pytest.mark.parametrize("type_id", STANDALONE)
    def test_it_uses_flographs_lock_when_there_is_one(self, registry,
                                                      type_id):
        """Preferred, so these queue behind the built-in chart nodes
        rather than beside them."""
        namespace = {}
        exec(compile(registry.get(type_id).source, type_id, "exec"),
             namespace)
        assert namespace["_figure_lock"]() is plotly_spec.FIGURE_LOCK

    @pytest.mark.parametrize("type_id", STANDALONE)
    def test_the_fallback_is_one_lock_for_everybody(self, registry,
                                                    monkeypatch, type_id):
        """The whole point: two node scripts get separate namespaces, so a
        module-level lock in each would not mutually exclude. The fallback
        parks one in sys.modules, which they do share."""
        import sys

        monkeypatch.delitem(sys.modules, "_flograph_plotly_figure_lock",
                            raising=False)
        monkeypatch.setitem(sys.modules, "flograph.core.plotly_spec", None)

        locks = []
        for _ in range(2):                      # two copies of the node
            namespace = {}
            exec(compile(registry.get(type_id).source, type_id, "exec"),
                 namespace)
            locks.append(namespace["_figure_lock"]())
        assert locks[0] is locks[1]
        assert locks[0] is not plotly_spec.FIGURE_LOCK

    def test_the_two_standalone_nodes_share_it_with_each_other(
            self, registry, monkeypatch):
        import sys

        monkeypatch.delitem(sys.modules, "_flograph_plotly_figure_lock",
                            raising=False)
        monkeypatch.setitem(sys.modules, "flograph.core.plotly_spec", None)

        locks = []
        for type_id in STANDALONE:
            namespace = {}
            exec(compile(registry.get(type_id).source, type_id, "exec"),
                 namespace)
            locks.append(namespace["_figure_lock"]())
        assert locks[0] is locks[1]
