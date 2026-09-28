"""Bypass: a node skipped with its inputs handed straight on.

The fourth run state beside active, frozen and manual, and the one the other
three could not say: Deactivate takes the branch below out, Freeze serves the
last result, Bypass runs the branch below *as if the node were not there*.
Which input feeds which output is core.bypass's to decide — declared, then
same name, then same type — and an output nothing feeds is None, so a node
below that needs it fails loudly rather than being quietly skipped.
"""
from __future__ import annotations

import pytest
from PySide6.QtGui import QUndoStack

from flograph.core import Graph, NodeInstance, NodeScriptError, parse_spec
from flograph.core.bypass import bypass_outputs, can_bypass, passthrough
from flograph.core.serialization import graph_from_dict, graph_to_dict
from flograph.engine import ExecutionEngine
from flograph.engine.cache_persistence import node_fingerprint
from flograph.engine.scheduler import build_plan, is_exclusive
from flograph.ui.commands import (SetActiveCommand, SetBypassCommand,
                                  SetFrozenCommand, SetManualCommand)

SOURCE = """
NODE = {"label": "Src", "category": "Test", "inputs": [],
        "outputs": [("table", "any")]}
PARAMS = [{"name": "value", "type": "int", "default": 3}]
def run(ctx):
    ctx.log("ran")
    return {"table": ctx.params["value"]}
"""

DOUBLE = """
NODE = {"label": "Double", "category": "Test",
        "inputs": [("table", "any")], "outputs": [("table", "any")]}
def run(ctx, table):
    ctx.log("ran")
    return {"table": table * 2}
"""

SHAPED = """
NODE = {"label": "Shaped", "category": "Test",
        "inputs": [("data", "dataframe"), ("n", "number"), ("s", "string")],
        "outputs": [("rows", "dataframe"), ("html", "string"),
                    ("count", "number"), ("fig", "figure")]}
def run(ctx, data, n, s):
    return {}
"""

NEEDY = """
NODE = {"label": "Needy", "category": "Test",
        "inputs": [("value", "any")], "outputs": [("out", "any")]}
def run(ctx, value):
    ctx.log("ran")
    if value is None:
        raise ValueError("needs a value")
    return {"out": value}
"""

TWO_OUT = """
NODE = {"label": "Split", "category": "Test",
        "inputs": [("table", "any")],
        "outputs": [("table", "any"), ("html", "string")]}
def run(ctx, table):
    return {"table": table, "html": "<p/>"}
"""


def _node(source: str, type_id: str) -> NodeInstance:
    return NodeInstance.create(parse_spec(source, type_id))


# ------------------------------------------------------------ the mapping

class TestPassthrough:
    def test_same_name_wins(self):
        assert passthrough(parse_spec(DOUBLE, "t.d")) == {"table": "table"}

    def test_then_same_type_and_otherwise_nothing(self):
        mapping = passthrough(parse_spec(SHAPED, "t.s"))
        assert mapping == {"rows": "data", "html": "s", "count": "n",
                           "fig": None}

    def test_an_any_output_takes_the_first_input(self):
        spec = parse_spec(NEEDY, "t.n")
        assert passthrough(spec) == {"out": "value"}

    def test_the_script_can_say(self):
        spec = parse_spec(SHAPED.replace(
            '"category": "Test",',
            '"category": "Test", "bypass": {"html": None, "count": "n"},'),
            "t.s")
        mapping = passthrough(spec)
        assert mapping["html"] is None and mapping["count"] == "n"
        assert mapping["rows"] == "data"      # the rest still matched

    def test_the_script_can_refuse(self):
        spec = parse_spec(DOUBLE.replace(
            '"category": "Test",', '"category": "Test", "bypass": False,'),
            "t.d")
        assert not can_bypass(spec)

    @pytest.mark.parametrize("decl, why", [
        ('"bypass": "yes",', "must be False or a dict"),
        ('"bypass": {"nope": "table"},', "does not have"),
        ('"bypass": {"table": "nope"},', "not one of the node's inputs"),
    ])
    def test_a_bad_declaration_is_a_script_error(self, decl, why):
        with pytest.raises(NodeScriptError, match=why):
            parse_spec(DOUBLE.replace('"category": "Test",',
                                      f'"category": "Test", {decl}'), "t.d")

    def test_a_source_cannot_be_bypassed(self):
        assert not can_bypass(parse_spec(SOURCE, "t.src"))

    def test_outputs_come_from_the_values_given(self):
        node = _node(SHAPED, "t.s")
        out = bypass_outputs(node, {"data": "D", "n": 4})
        assert out == {"rows": "D", "html": None, "count": 4, "fig": None}

    def test_most_of_the_library_can_be_bypassed(self, registry):
        """Not a rule, a sanity check on the matching: if a change to it
        left most transforms unbypassable, it went wrong somewhere."""
        transforms = [s for s in registry.all()
                      if s.category.lower().startswith("transform")]
        assert transforms
        ok = sum(1 for s in transforms if can_bypass(s))
        assert ok / len(transforms) > 0.8


# ------------------------------------------------------------ the model

class TestModel:
    def test_off_by_default(self):
        assert _node(DOUBLE, "t.d").bypassed is False

    def test_setter_emits_and_dirties_below(self):
        graph = Graph()
        a, b = _node(DOUBLE, "t.d"), _node(DOUBLE, "t.d")
        graph.add_node(a)
        graph.add_node(b)
        graph.connect(a.id, "table", b.id, "table")
        graph.mark_clean(a.id)
        graph.mark_clean(b.id)
        seen = []
        graph.events.bypassed_changed.connect(
            lambda n, v: seen.append((n, v)))
        graph.set_bypassed(a.id, True)
        assert seen == [(a.id, True)]
        assert a.dirty and b.dirty

    def test_round_trips_and_stays_out_of_files_that_do_not_use_it(
            self, registry):
        graph = Graph()
        a, b = _node(DOUBLE, "t.d"), _node(DOUBLE, "t.d")
        graph.add_node(a)
        graph.add_node(b)
        graph.set_bypassed(a.id, True)
        data = graph_to_dict(graph)
        entries = {e["id"]: e for e in data["graph"]["nodes"]}
        assert entries[a.id]["bypassed"] is True
        assert "bypassed" not in entries[b.id]
        back = graph_from_dict(data, registry)
        assert back.nodes[a.id].bypassed and not back.nodes[b.id].bypassed

    def test_the_fingerprint_moves(self):
        graph = Graph()
        a = _node(DOUBLE, "t.d")
        graph.add_node(a)
        before = node_fingerprint(graph, a.id, {})
        graph.set_bypassed(a.id, True)
        assert node_fingerprint(graph, a.id, {}) != before

    def test_never_exclusive(self):
        node = _node(DOUBLE, "t.d")
        node.exclusive_override = True
        node.bypassed = True
        assert not is_exclusive(node)

    def test_stays_in_the_plan_even_if_frozen(self):
        """A file edited by hand can say both; bypass is what runs."""
        graph = Graph()
        a = _node(DOUBLE, "t.d")
        graph.add_node(a)
        a.frozen = True
        a.bypassed = True

        class _Cache:
            def has(self, _):
                return True
        assert build_plan(graph, [a.id], _Cache()) == [a.id]


# --------------------------------------------------------------- running

@pytest.fixture
def chain():
    """src -> double -> tail (another double), on a real engine."""
    graph = Graph()
    src = _node(SOURCE, "t.src")
    mid = _node(DOUBLE, "t.d")
    tail = _node(DOUBLE, "t.d")
    for node in (src, mid, tail):
        graph.add_node(node)
    graph.connect(src.id, "table", mid.id, "table")
    graph.connect(mid.id, "table", tail.id, "table")
    engine = ExecutionEngine(graph)
    ran: list[str] = []
    engine.node_log.connect(
        lambda nid, line, stream: ran.append(nid) if line == "ran" else None)
    return graph, (src, mid, tail), engine, ran


def _run(qtbot, engine, trigger=None, timeout=5000):
    with qtbot.waitSignal(engine.run_finished, timeout=timeout) as blocker:
        (trigger or engine.run_all)()
    return blocker.args[0]


class TestRunning:
    def test_the_branch_runs_as_if_the_node_were_not_there(
            self, qtbot, chain):
        graph, (src, mid, tail), engine, ran = chain
        graph.set_bypassed(mid.id, True)
        assert _run(qtbot, engine)
        assert mid.id not in ran
        assert engine.cache.outputs_for(tail.id)["table"] == 6   # 3 * 2 once

    def test_its_output_is_the_upstream_object_and_shares_its_entry(
            self, qtbot, chain):
        graph, (src, mid, tail), engine, ran = chain
        graph.set_bypassed(mid.id, True)
        _run(qtbot, engine)
        assert engine.cache.get(mid.id).alias_of == src.id
        assert (engine.cache.outputs_for(mid.id)["table"]
                is engine.cache.outputs_for(src.id)["table"])

    def test_turning_it_off_runs_it_again(self, qtbot, chain):
        graph, (src, mid, tail), engine, ran = chain
        graph.set_bypassed(mid.id, True)
        _run(qtbot, engine)
        ran.clear()
        graph.set_bypassed(mid.id, False)
        assert _run(qtbot, engine)
        assert set(ran) == {mid.id, tail.id}
        assert engine.cache.outputs_for(tail.id)["table"] == 12

    def test_an_output_nothing_feeds_fails_the_node_below_loudly(self, qtbot):
        graph = Graph()
        src = _node(SOURCE, "t.src")
        split = _node(TWO_OUT, "t.two")
        needy = _node(NEEDY, "t.needy")
        for node in (src, split, needy):
            graph.add_node(node)
        graph.connect(src.id, "table", split.id, "table")
        graph.connect(split.id, "html", needy.id, "value")
        engine = ExecutionEngine(graph)
        graph.set_bypassed(split.id, True)
        assert passthrough(split.spec)["html"] is None
        assert _run(qtbot, engine) is False
        assert "needs a value" in needy.status_message


# ------------------------------------------------------------ one choice

class TestOneChoice:
    @pytest.fixture
    def setup(self):
        graph = Graph()
        node = _node(DOUBLE, "t.d")
        graph.add_node(node)
        return graph, node, QUndoStack()

    def test_bypassing_clears_the_other_three_and_undo_restores_them(
            self, setup):
        graph, node, stack = setup
        node.active, node.frozen, node.manual = False, True, True
        stack.push(SetBypassCommand(graph, node.id, True))
        assert (node.bypassed, node.active, node.frozen, node.manual) == (
            True, True, False, False)
        stack.undo()
        assert (node.bypassed, node.active, node.frozen, node.manual) == (
            False, False, True, True)

    @pytest.mark.parametrize("command, attr, value", [
        (SetActiveCommand, "active", False),
        (SetFrozenCommand, "frozen", True),
        (SetManualCommand, "manual", True),
    ])
    def test_each_of_the_others_clears_bypass(self, setup, command, attr,
                                              value):
        graph, node, stack = setup
        graph.set_bypassed(node.id, True)
        stack.push(command(graph, node.id, value))
        assert getattr(node, attr) == value and not node.bypassed
        stack.undo()
        assert getattr(node, attr) != value and node.bypassed

    def test_leaving_the_normal_state_alone_does_not_touch_bypass(
            self, setup):
        graph, node, stack = setup
        graph.set_bypassed(node.id, True)
        stack.push(SetActiveCommand(graph, node.id, True))
        assert node.bypassed


# ---------------------------------------------------------------- canvas

class TestCanvas:
    def test_badge_line_and_fade_follow_the_flag(self, qtbot, registry):
        from flograph.ui.canvas import NodeGraphScene
        from flograph.ui.canvas.node_item import (BYPASSED_OPACITY,
                                                  DEACTIVATED_OPACITY)
        graph = Graph()
        node = _node(DOUBLE, "t.d")
        graph.add_node(node)
        scene = NodeGraphScene(graph, QUndoStack(), registry=registry)
        item = scene.node_items[node.id]
        assert not item._bypass_overlay.isVisible()
        assert item.opacity() == 1.0
        graph.set_bypassed(node.id, True)
        assert item._bypass_badge.isVisible()
        assert item._bypass_overlay.isVisible()
        assert item.opacity() == pytest.approx(BYPASSED_OPACITY)
        assert "Bypassed" in item.toolTip()
        # the line ignores the fade: it is the part still carrying data
        assert item._bypass_overlay.effectiveOpacity() == 1.0
        graph.set_active(node.id, False)      # deactivated reads stronger
        assert item.opacity() == pytest.approx(DEACTIVATED_OPACITY)
        graph.set_active(node.id, True)
        graph.set_bypassed(node.id, False)
        assert not item._bypass_badge.isVisible()
        assert item.opacity() == 1.0

    def test_the_line_does_not_hide_the_node_from_a_click(self, qtbot,
                                                          registry):
        """The view finds what a right-click is on with itemAt; the overlay
        covering the node answered instead, and a bypassed node had no
        context menu."""
        from flograph.ui.canvas import NodeGraphScene
        from flograph.ui.canvas.node_item import NodeItem
        graph = Graph()
        node = _node(DOUBLE, "t.d")
        graph.add_node(node)
        scene = NodeGraphScene(graph, QUndoStack(), registry=registry)
        graph.set_bypassed(node.id, True)
        item = scene.node_items[node.id]
        centre = item.mapToScene(item.boundingRect().center())
        hits = [i for i in scene.items(centre) if i.isVisible()]
        assert isinstance(hits[0], NodeItem) or (
            hits[0].parentItem() is item
            and not isinstance(hits[0], type(item._bypass_overlay)))

    def test_a_bypassed_node_loaded_from_a_file_is_drawn_bypassed(
            self, qtbot, registry):
        from flograph.ui.canvas import NodeGraphScene
        graph = Graph()
        node = _node(DOUBLE, "t.d")
        node.bypassed = True
        graph.add_node(node)
        scene = NodeGraphScene(graph, QUndoStack(), registry=registry)
        assert scene.node_items[node.id]._bypass_overlay.isVisible()
