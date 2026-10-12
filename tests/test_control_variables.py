"""Input controls as flow variables, and typed params bound to a variable.

A control with a Variable name is a provider exactly as a Variables node
is: a derived edge, so ordering, dirtying and re-runs come with it. Typed
params (number, tick box, dropdown, date) take a `${name}` as their whole
value and get it coerced at dispatch.
"""
import pytest

from flograph.core import Graph, NodeInstance, parse_spec
from flograph.core import varlinks
from flograph.core.varlinks import VariableError, coerce_bound, var_problem
from flograph.engine import ExecutionEngine
from flograph.engine.headless import apply_overrides

TYPED = """
NODE = {"label": "Typed", "category": "Test", "inputs": [],
        "outputs": [("value", "any")]}
PARAMS = [
    {"name": "text", "type": "string", "default": ""},
    {"name": "count", "type": "int", "default": 0, "min": 0, "max": 100},
    {"name": "ratio", "type": "float", "default": 0.0},
    {"name": "flag", "type": "bool", "default": False},
    {"name": "mode", "type": "choice", "options": ["a", "b"], "default": "a"},
    {"name": "when", "type": "date", "default": ""},
    {"name": "width", "type": "int", "default": 10, "cosmetic": True},
]
def run(ctx):
    p = ctx.params
    return {"value": (p["text"], p["count"], p["ratio"], p["flag"],
                      p["mode"], p["when"])}
"""


def typed(graph):
    return graph.add_node(NodeInstance.create(parse_spec(TYPED, "test.typed")))


def control(graph, registry, kind, **params):
    node = graph.add_node(registry.instantiate(f"flograph.input.{kind}"))
    for name, value in params.items():
        graph.set_param(node.id, name, value)
    return node


def wait_run(qtbot, engine, trigger=None, timeout=8000):
    with qtbot.waitSignal(engine.run_finished, timeout=timeout) as blocker:
        (trigger or engine.run_all)()
    return blocker.args[0]


def out(engine, node):
    return engine.cache.outputs_for(node.id)["value"]


class TestPublishing:
    def test_a_named_control_is_a_provider(self, registry):
        graph = Graph()
        slider = control(graph, registry, "slider", variable="threshold")
        assert varlinks.provided_names(slider) == ["threshold"]
        assert varlinks.providers(graph) == {"threshold": [slider.id]}

    def test_no_name_publishes_nothing(self, registry):
        graph = Graph()
        control(graph, registry, "slider")
        control(graph, registry, "slider", variable="not a name")
        assert varlinks.providers(graph) == {}

    def test_a_reference_makes_an_edge(self, registry):
        graph = Graph()
        slider = control(graph, registry, "slider", variable="threshold")
        consumer = typed(graph)
        graph.set_param(consumer.id, "text", "price > ${threshold}")
        assert graph.var_sources(consumer.id) == [slider.id]

    def test_naming_after_the_reference_still_links(self, registry):
        graph = Graph()
        consumer = typed(graph)
        graph.set_param(consumer.id, "text", "${threshold}")
        assert var_problem(graph, consumer.id)
        slider = control(graph, registry, "slider")
        graph.set_param(slider.id, "variable", "threshold")
        assert graph.var_sources(consumer.id) == [slider.id]
        assert var_problem(graph, consumer.id) is None

    def test_a_name_used_twice_is_a_problem(self, registry):
        graph = Graph()
        control(graph, registry, "slider", variable="x")
        variables = graph.add_node(registry.instantiate("flograph.util.variables"))
        graph.set_param(variables.id, "assignments", "x = 1")
        consumer = typed(graph)
        graph.set_param(consumer.id, "text", "${x}")
        assert "more than one" in var_problem(graph, consumer.id)

    def test_completion_offers_the_control(self, registry):
        graph = Graph()
        control(graph, registry, "slider", variable="threshold", value=30)
        assert "threshold" in varlinks.completion_names(graph)
        assert varlinks.declared_values(graph)["threshold"] == "30"

    def test_between_publishes_low_high_and_the_pair(self, registry):
        graph = Graph()
        between = control(graph, registry, "between_slider", variable="price")
        assert set(varlinks.provided_names(between)) == {
            "price", "price_low", "price_high"}


class TestRunning:
    def test_text_substitution_and_rerun(self, qtbot, registry):
        graph = Graph()
        slider = control(graph, registry, "slider", variable="threshold",
                         value=30)
        consumer = typed(graph)
        graph.set_param(consumer.id, "text", "price > ${threshold}")
        engine = ExecutionEngine(graph)
        assert wait_run(qtbot, engine)
        assert out(engine, consumer)[0] == "price > 30"
        graph.set_param(slider.id, "value", 45)
        assert graph.nodes[consumer.id].dirty
        assert wait_run(qtbot, engine)
        assert out(engine, consumer)[0] == "price > 45"

    def test_typed_params_bind_and_coerce(self, qtbot, registry):
        graph = Graph()
        control(graph, registry, "slider", variable="n", value=42)
        control(graph, registry, "toggle", variable="on", value=True)
        control(graph, registry, "date", variable="day", value="2026-03-04")
        choice = control(graph, registry, "choice", variable="pick",
                         items="a\nb", value="b")
        consumer = typed(graph)
        for name, ref in (("count", "n"), ("ratio", "n"), ("flag", "on"),
                          ("mode", "pick"), ("when", "day")):
            graph.set_param(consumer.id, name, f"${{{ref}}}")
        assert len(graph.var_sources(consumer.id)) == 4
        engine = ExecutionEngine(graph)
        assert wait_run(qtbot, engine)
        assert out(engine, consumer)[1:] == (42, 42.0, True, "b",
                                             "2026-03-04")
        assert choice.id in graph.var_sources(consumer.id)

    def test_a_bad_coercion_fails_the_node_saying_why(self, qtbot, registry):
        graph = Graph()
        control(graph, registry, "text", variable="n", value="lots")
        consumer = typed(graph)
        graph.set_param(consumer.id, "count", "${n}")
        engine = ExecutionEngine(graph)
        failures = []
        engine.node_failed.connect(lambda nid, err: failures.append(err.message))
        assert not wait_run(qtbot, engine)
        assert "'count' is a number, got 'lots'" in failures[0]

    def test_a_cosmetic_int_is_not_bindable(self, registry):
        graph = Graph()
        consumer = typed(graph)
        spec = consumer.spec.param("width")
        assert not varlinks.bindable(consumer, spec)

    def test_a_held_change_does_not_reach_the_variable(self, qtbot, registry):
        from flograph.core import control_apply as ca
        graph = Graph()
        slider = control(graph, registry, "slider", variable="t", value=5,
                         apply=ca.BUTTON)
        consumer = typed(graph)
        graph.set_param(consumer.id, "count", "${t}")
        engine = ExecutionEngine(graph)
        assert wait_run(qtbot, engine)
        graph.set_param(slider.id, "draft", ca.encode(9))
        assert not graph.nodes[consumer.id].dirty
        assert out(engine, consumer)[1] == 5


class TestCoercion:
    @pytest.mark.parametrize("raw,expected", [
        ("true", True), ("No", False), (0, False), (1.0, True), ("", False)])
    def test_bool(self, raw, expected):
        spec = parse_spec(TYPED, "t").param("flag")
        assert coerce_bound(spec, raw) is expected

    def test_int_clamps_to_the_param_bounds(self):
        spec = parse_spec(TYPED, "t").param("count")
        assert coerce_bound(spec, "250") == 100

    def test_choice_must_be_offered(self):
        spec = parse_spec(TYPED, "t").param("mode")
        with pytest.raises(VariableError, match="no option 'z'"):
            coerce_bound(spec, "z")


class TestHeadless:
    def test_var_sets_a_named_control(self, registry):
        graph = Graph()
        slider = control(graph, registry, "slider", variable="threshold")
        apply_overrides(graph, {"threshold": "70"})
        assert slider.params["value"] == 70.0

    def test_unknown_is_still_an_error(self, registry):
        graph = Graph()
        with pytest.raises(ValueError):
            apply_overrides(graph, {"nope": "1"})


class TestPanel:
    def test_a_bound_param_shows_a_chip_and_unbinds(self, qtbot, registry):
        from PySide6.QtGui import QUndoStack
        from PySide6.QtWidgets import QLabel
        from flograph.ui.properties.params_panel import ParamsPanel

        graph = Graph()
        control(graph, registry, "slider", variable="n", value=7)
        consumer = typed(graph)
        graph.set_param(consumer.id, "count", "${n}")
        panel = ParamsPanel(graph, QUndoStack())
        qtbot.addWidget(panel)
        panel.set_node(consumer.id)
        widget = panel.tree.itemWidget(panel.rows()["Count"], 1)
        chip = widget.findChild(QLabel, "param_count_binding")
        assert chip is not None and "${n}" in chip.text() and "7" in chip.text()
        panel._commit("count", 3, merge=False)
        qtbot.wait(10)
        widget = panel.tree.itemWidget(panel.rows()["Count"], 1)
        assert widget.findChild(QLabel, "param_count_binding") is None
        assert consumer.params["count"] == 3
