"""Can ▸ Propose: Flo's changes made for real but marked as a proposal.

New nodes are faded in a dashed outline and held from running, changed
ones outlined, until the user keeps or discards them. The marks are
runtime-only graph state (`Graph.proposed_new` / `proposed_changed`); the
run rule is `RunFlags.active`; Discard is the replies' own undo steps.
"""
import json

import pytest
from PySide6.QtGui import QUndoStack
from PySide6.QtWidgets import QLabel

from flograph.core import ai_disclosure as disc
from flograph.core.ai_disclosure import Disclosure
from flograph.core.graph import Graph
from flograph.engine.scheduler import build_plan
from flograph.flo.agent import Conversation
from flograph.flo.tools import ACT, PROPOSE, Toolbox
from flograph.llm import wire
from flograph.llm.toolcall import ToolCall
from flograph.ui.commands import SetAiPrivacyCommand

from tests.test_flo import BUILD, ScriptedModel
from tests.test_flo_panel import _panel, settings, user_dir  # noqa: F401

CSV = "flograph.io.read_csv"
PLOTLY = "flograph.viz.show_plotly"


@pytest.fixture
def stack(qapp):
    return QUndoStack()


def _pair(registry):
    graph = Graph()
    reader = registry.instantiate(CSV, (0, 0))
    chart = registry.instantiate(PLOTLY, (300, 0))
    graph.add_node(reader)
    graph.add_node(chart)
    graph.connect(reader.id, "table", chart.id, "table")
    return graph, reader, chart


# -- the marks, and the run rule -------------------------------------------------

def test_marks_are_told_and_go_with_the_node(registry):
    graph, reader, chart = _pair(registry)
    heard = []
    graph.events.proposed_changed.connect(lambda: heard.append(1))
    graph.propose(new=[chart.id], changed=[reader.id, chart.id])
    assert graph.proposed_new == {chart.id}
    assert graph.proposed_changed == {reader.id}     # new wins over changed
    graph.remove_node(chart.id)
    assert graph.proposed_new == set() and len(heard) == 2
    graph.clear_proposed()
    assert graph.proposed_changed == set() and len(heard) == 3


def test_a_proposed_node_and_what_it_feeds_dont_run(registry):
    graph, reader, chart = _pair(registry)
    assert build_plan(graph, [chart.id]) == [reader.id, chart.id]
    graph.propose(new=[reader.id])
    assert build_plan(graph, [chart.id]) == []
    graph.clear_proposed()
    assert build_plan(graph, [chart.id]) == [reader.id, chart.id]


def test_a_changed_node_still_runs(registry):
    graph, reader, chart = _pair(registry)
    graph.propose(changed=[reader.id])
    assert build_plan(graph, [chart.id]) == [reader.id, chart.id]


def test_marks_are_never_saved(registry):
    from flograph.core.serialization import graph_from_dict, graph_to_dict
    graph, reader, _ = _pair(registry)
    graph.propose(new=[reader.id])
    data = graph_to_dict(graph)
    assert "proposed" not in json.dumps(data)
    assert graph_from_dict(data, registry).proposed_new == set()


# -- the toolbox -------------------------------------------------------------------

def _box(registry, stack, graph=None, **kw):
    graph = graph or Graph()
    box = Toolbox(graph, registry, stack, disclosure=Disclosure(disc.SCHEMA),
                  autonomy=PROPOSE, **kw)
    for node_id in graph.nodes:
        box.handle(node_id)
    return box


def _call(box, name, **args):
    return json.loads(box.execute(ToolCall("a", name, args)))


def test_propose_offers_the_same_changes_as_act(registry, stack):
    proposing = {t.name for t in _box(registry, stack).specs()}
    acting = _box(registry, stack)
    acting.autonomy = ACT
    assert proposing == {t.name for t in acting.specs()}


def test_what_flo_adds_and_changes_is_marked_as_it_goes(registry, stack):
    graph, reader, chart = _pair(registry)
    box = _box(registry, stack, graph)          # n1 reader, n2 chart
    box.begin_turn("propose")
    added = _call(box, "add_node", type_id=PLOTLY, input_from="n1")
    _call(box, "set_params", node="n2", params={"title": "Sales"})
    box.end_turn()
    new_id = box._handles[added["node"]]
    assert graph.proposed_new == {new_id}
    assert graph.proposed_changed == {chart.id}   # n1 only feeds: unchanged
    assert stack.count() == 1


def test_a_wire_marks_only_the_node_it_feeds(registry, stack):
    graph, reader, chart = _pair(registry)
    other = registry.instantiate(PLOTLY, (600, 0))
    graph.add_node(other)
    box = _box(registry, stack, graph)
    box.begin_turn("wire")
    _call(box, "connect", from_node="n1", to_node="n3", to_port="table")
    box.end_turn()
    assert graph.proposed_changed == {other.id} and not graph.proposed_new


def test_acting_marks_nothing(registry, stack):
    box = _box(registry, stack)
    box.autonomy = ACT
    box.begin_turn("act")
    _call(box, "add_node", type_id=CSV)
    box.end_turn()
    assert not box.graph.proposed_new


def test_a_proposed_node_is_not_run(registry, stack):
    graph, reader, _ = _pair(registry)
    ran = []
    box = _box(registry, stack, graph,
               runner=lambda ids, cancelled: ran.append(ids) or "done")
    graph.propose(new=[reader.id])
    out = json.loads(box.execute_run(
        ToolCall("a", "run_nodes", {"nodes": ["n1"]}), lambda fn: fn(),
        lambda: False))
    assert "n1 is proposed" in out["error"] and ran == []
    note = _call(box, "get_output", node="n1")["note"]
    assert "it is proposed" in note


def test_proposed_code_waits_in_the_editor(registry, stack):
    """Apply Code It Writes is an Act choice: a proposal is looked at first."""
    graph = Graph()
    script = registry.instantiate("flograph.scripting.python_script", (0, 0))
    graph.add_node(script)
    sent = []
    box = _box(registry, stack, graph, apply_code=True,
               suggest_code=lambda nid, code: sent.append(nid))
    assert not box.applies_code
    spec = next(t for t in box.specs() if t.name == "write_node_code")
    assert "NOT applied" in spec.description
    from tests.test_flo_code import GOOD
    before = script.source
    out = _call(box, "write_node_code", node="n1", code=GOOD)
    assert "NOT applied" in out["status"] and sent == [script.id]
    assert script.source == before


def test_the_prompt_says_it_is_proposing(registry, stack):
    box = _box(registry, stack)
    chat = Conversation(wire.Connection(base_url="http://localhost:1/v1",
                                        model="m"), box)
    prompt = chat.system_prompt()
    assert "You are proposing" in prompt and "Keep or Discard" in prompt


# -- the panel: Keep, Discard -----------------------------------------------------

def _propose(qtbot, monkeypatch, registry, settings, steps=BUILD, panel=None):
    ScriptedModel(monkeypatch, list(steps))
    panel = panel or _panel(qtbot, registry, settings)
    panel.choose_autonomy(PROPOSE)
    assert panel.send("Bar chart of sales by region")
    qtbot.waitUntil(lambda: not panel._busy, timeout=5000)
    return panel


def _footer(panel, index=-1) -> str:
    return panel._turns[index]["footer"].text()


def test_a_proposing_reply_marks_and_offers_keep_or_discard(
        qtbot, monkeypatch, registry, settings, user_dir):
    panel = _propose(qtbot, monkeypatch, registry, settings)
    assert len(panel.graph.proposed_new) == 2
    footer = _footer(panel)
    assert "<b>Proposed</b>: adds 2 nodes, 1 wire" in footer
    assert 'href="keep:"' in footer and 'href="discard:"' in footer
    assert "undo:" not in footer


def test_keep_takes_the_marks_off_and_leaves_the_nodes(
        qtbot, monkeypatch, registry, settings, user_dir):
    panel = _propose(qtbot, monkeypatch, registry, settings)
    assert panel.keep_proposal()
    assert not panel.graph.proposed_new and len(panel.graph.nodes) == 2
    assert "Kept" in _footer(panel) and "keep:" not in _footer(panel)
    assert panel.undo_stack.count() == 1


def test_discard_takes_the_change_back(qtbot, monkeypatch, registry,
                                       settings, user_dir):
    panel = _propose(qtbot, monkeypatch, registry, settings)
    assert panel.discard_proposal()
    assert not panel.graph.nodes and not panel.graph.proposed_new
    assert "Discarded" in _footer(panel)


def test_replies_in_a_row_are_one_proposal(qtbot, monkeypatch, registry,
                                           settings, user_dir):
    more = [[("add_node", {"type_id": CSV})], "And a second reader."]
    panel = _propose(qtbot, monkeypatch, registry, settings)
    _propose(qtbot, monkeypatch, registry, settings, steps=more, panel=panel)
    assert len(panel.graph.proposed_new) == 3
    assert panel._proposal["turns"] == [0, 1]
    assert panel.discard_proposal()
    assert not panel.graph.nodes
    assert all("Discarded" in _footer(panel, i) for i in (0, 1))


def test_an_edit_of_yours_in_between_keeps_the_last_one(
        qtbot, monkeypatch, registry, settings, user_dir):
    more = [[("add_node", {"type_id": CSV})], "And a second reader."]
    panel = _propose(qtbot, monkeypatch, registry, settings)
    panel.undo_stack.push(SetAiPrivacyCommand(panel.graph, {"level": 1}))
    assert not panel.discard_proposal()      # something came after it
    _propose(qtbot, monkeypatch, registry, settings, steps=more, panel=panel)
    assert "Kept" in _footer(panel, 0)
    assert panel._proposal["turns"] == [1]
    assert len(panel.graph.proposed_new) == 1


def test_acting_on_it_keeps_it_and_advice_leaves_it(
        qtbot, monkeypatch, registry, settings, user_dir):
    panel = _propose(qtbot, monkeypatch, registry, settings)
    ScriptedModel(monkeypatch, ["It reads a CSV and charts it."])
    panel.choose_autonomy("advise")
    assert panel.send("what does this do?")
    qtbot.waitUntil(lambda: not panel._busy, timeout=5000)
    assert panel._proposal is not None and panel.graph.proposed_new
    ScriptedModel(monkeypatch, [[("add_node", {"type_id": CSV})], "Added."])
    panel.choose_autonomy(ACT)
    assert panel.send("go ahead, and add another reader")
    qtbot.waitUntil(lambda: not panel._busy, timeout=5000)
    assert panel._proposal is None and not panel.graph.proposed_new
    assert "Kept" in _footer(panel, 0) and len(panel.graph.nodes) == 3


def test_ctrl_z_past_it_counts_as_undone(qtbot, monkeypatch, registry,
                                         settings, user_dir):
    panel = _propose(qtbot, monkeypatch, registry, settings)
    panel.undo_stack.undo()
    assert panel._proposal is None and not panel.graph.proposed_new
    assert "Undone" in _footer(panel)


def test_a_fresh_chat_keeps_what_is_there(qtbot, monkeypatch, registry,
                                          settings, user_dir):
    panel = _propose(qtbot, monkeypatch, registry, settings)
    panel.new_chat()
    assert len(panel.graph.nodes) == 2 and not panel.graph.proposed_new


def test_propose_is_on_the_can_menu(qtbot, registry, settings, user_dir):
    panel = _panel(qtbot, registry, settings)
    assert [a.text() for a in panel.autonomy_menu.actions()
            if a.isCheckable()][:3] == ["Advise", "Propose", "Act"]
    panel.choose_autonomy(PROPOSE)
    assert panel.can_btn.text().startswith("Can: Propose")


# -- the canvas ---------------------------------------------------------------------

def test_the_canvas_shows_a_proposal(registry):
    from flograph.ui.canvas import NodeGraphScene
    from flograph.ui.canvas.node_item import PROPOSED_OPACITY
    graph, reader, chart = _pair(registry)
    scene = NodeGraphScene(graph, QUndoStack(), registry=registry)
    graph.propose(new=[chart.id], changed=[reader.id])
    new, changed = scene.node_items[chart.id], scene.node_items[reader.id]
    assert new.opacity() == pytest.approx(PROPOSED_OPACITY)
    assert new._proposed_ring.isVisible() and new._proposed_ring.kind == "new"
    assert changed.opacity() == 1.0 and changed._proposed_ring.kind == "changed"
    assert "won't run until you keep it" in new.toolTip()
    [wire_item] = scene.connection_items.values()
    assert wire_item.opacity() == pytest.approx(PROPOSED_OPACITY)
    graph.clear_proposed()
    assert new.opacity() == 1.0 and not new._proposed_ring.isVisible()
    assert wire_item.opacity() == 1.0
