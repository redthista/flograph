"""Flo writes node code, and nothing runs it until the user has read it.

The rule under test: code a model wrote is *text* until the user presses
Apply. Checking it must not execute it (`read_spec`, never `parse_spec`),
the tool must not apply it (it goes to the editor as an unapplied edit),
and a turn that only wrote code has no undo step of its own to undo.
"""
import json

import pytest
from PySide6.QtGui import QUndoStack

from flograph.core import ai_disclosure as disc
from flograph.core.ai_disclosure import ColumnRule, Disclosure, Privacy
from flograph.core.graph import Graph
from flograph.core.script import NodeScriptError, UnreadableSpec, read_spec
from flograph.flo.tools import ACT, ADVISE, Toolbox
from flograph.llm.toolcall import ToolCall

SCRIPT = "flograph.scripting.python_script"
CSV = "flograph.io.read_csv"

GOOD = '''"""Doubles a number."""
NODE = {
    "label": "Double",
    "category": "Scripting",
    "inputs": [("x", "number")],
    "outputs": [("y", "number")],
}
PARAMS = [{"name": "factor", "type": "int", "default": 2}]


def run(ctx, x):
    return {"y": x * ctx.params["factor"]}
'''


@pytest.fixture
def stack(qapp):
    return QUndoStack()


def _box(registry, stack, *, level=disc.PROFILE, autonomy=ACT, privacy=None,
         suggest=True):
    graph = Graph()
    node = registry.instantiate(SCRIPT, (0, 0))
    graph.add_node(node)
    sent = []
    box = Toolbox(graph, registry, stack,
                  disclosure=Disclosure(level, privacy), autonomy=autonomy,
                  suggest_code=(lambda nid, code: sent.append((nid, code)))
                  if suggest else None)
    box.handle(node.id)                       # n1
    return box, node, sent


def _call(box, name, **args):
    return json.loads(box.execute(ToolCall("a", name, args)))


# -- read_spec: checked, never run ---------------------------------------------

def test_read_spec_runs_nothing(tmp_path):
    marker = tmp_path / "ran"
    code = f"open({str(marker)!r}, 'w').write('x')\n" + GOOD
    spec = read_spec(code, "user.double")
    assert spec.label == "Double" and [p.name for p in spec.inputs] == ["x"]
    assert [p.name for p in spec.params] == ["factor"]
    assert not marker.exists()


def test_read_spec_applies_the_same_checks():
    with pytest.raises(NodeScriptError, match="unknown port type"):
        read_spec(GOOD.replace('"number")]', '"numbr")]', 1), "x")
    with pytest.raises(NodeScriptError, match="run"):
        read_spec(GOOD.split("def run")[0], "x")
    with pytest.raises(NodeScriptError, match="syntax error"):
        read_spec(GOOD + "\ndef broken(:\n", "x")


def test_settings_built_by_code_wait_for_apply():
    code = GOOD.replace('PARAMS = [{"name"', 'PARAMS = list([{"name"').replace(
        '"default": 2}]', '"default": 2}])')
    with pytest.raises(UnreadableSpec):
        read_spec(code, "x")
    # ...but a missing run() is still caught before that
    with pytest.raises(NodeScriptError, match="run") as caught:
        read_spec(code.split("def run")[0], "x")
    assert not isinstance(caught.value, UnreadableSpec)


def test_ask_ai_checks_without_running(monkeypatch, tmp_path):
    from flograph import ai
    marker = tmp_path / "ran"
    reply = f"```python\nopen({str(marker)!r}, 'w')\n{GOOD}```"
    monkeypatch.setattr(ai, "chat_completion", lambda messages, config: reply)
    code = ai.suggest_node_update("old", "double it")
    assert "def run" in code and not marker.exists()


# -- the tools -----------------------------------------------------------------

def test_write_node_code_is_act_only_and_needs_an_editor(registry, stack):
    names = lambda box: {t.name for t in box.specs()}         # noqa: E731
    assert "write_node_code" in names(_box(registry, stack)[0])
    assert "write_node_code" not in names(_box(registry, stack, autonomy=ADVISE)[0])
    assert "write_node_code" not in names(_box(registry, stack, suggest=False)[0])
    assert "get_node_code" in names(_box(registry, stack, autonomy=ADVISE)[0])


def test_written_code_goes_to_the_editor_and_is_not_applied(registry, stack):
    box, node, sent = _box(registry, stack)
    before = node.source
    box.begin_turn("write me a doubling node")
    out = _call(box, "write_node_code", node="n1", code=f"```python\n{GOOD}```")
    box.end_turn()
    assert sent == [(node.id, GOOD)]            # unfenced, as the editor shows it
    assert node.source == before and not node.forked
    assert "NOT applied" in out["status"]
    assert stack.count() == 0 and not box.pushed
    action, = box.actions
    assert action.tool == "write_node_code" and action.code == GOOD


def test_code_that_does_not_load_comes_back_to_the_model(registry, stack):
    box, node, sent = _box(registry, stack)
    out = _call(box, "write_node_code", node="n1", code="def run(:\n")
    assert "does not load as a node" in out["error"] and not sent


def test_a_locked_node_keeps_its_code(registry, stack):
    box, node, sent = _box(registry, stack)
    node.locked = True
    out = _call(box, "write_node_code", node="n1", code=GOOD)
    assert "locked" in out["error"] and not sent


def test_wires_an_apply_would_drop_are_named(registry, stack):
    box, node, sent = _box(registry, stack)
    reader = registry.instantiate(CSV, (-300, 0))
    box.graph.add_node(reader)
    box.graph.connect(reader.id, "table", node.id, "in1")
    out = _call(box, "write_node_code", node="n1", code=GOOD)
    assert out["wires_lost_on_apply"] == ["in1"]


def test_library_code_is_readable_at_nothing(registry, stack):
    box, node, _ = _box(registry, stack, level=disc.STRUCTURE)
    out = _call(box, "get_node_code", node="n1")
    assert "def run" in out["code"] and out["library_code"]


def test_your_own_code_is_withheld_at_nothing(registry, stack):
    box, node, _ = _box(registry, stack, level=disc.STRUCTURE)
    node.code_override = GOOD.replace("x * ", "'Jane Smith' and x * ")
    out = _call(box, "get_node_code", node="n1")
    assert "Jane" not in json.dumps(out) and "not shared" in out["code"]


def test_your_own_code_hides_hidden_columns(registry, stack):
    privacy = Privacy(columns={"salary": ColumnRule(mode=disc.HIDDEN)})
    box, node, _ = _box(registry, stack, level=disc.SCHEMA, privacy=privacy)
    box.disclosure.learn(["salary", "region"])
    node.code_override = GOOD.replace("return", "t = 'salary', 'region'\n    return")
    code = _call(box, "get_node_code", node="n1")["code"]
    assert "salary" not in code and "region" in code


def test_the_receipt_counts_your_own_code(registry, stack):
    from flograph.flo import receipt
    box, node, _ = _box(registry, stack)
    library = {"messages": [{"role": "tool", "content": box.execute(
        ToolCall("a", "get_node_code", {"node": "n1"}))}]}
    node.code_override = GOOD
    own = {"messages": [{"role": "tool", "content": box.execute(
        ToolCall("b", "get_node_code", {"node": "n1"}))}]}
    assert receipt.build([library], [], box.disclosure, destination="x",
                         local=False).code_nodes == 0
    made = receipt.build([own], [], box.disclosure, destination="x", local=False)
    assert made.code_nodes == 1
    assert any("Code you wrote" in line for line in made.details())


# -- the editor ----------------------------------------------------------------

def _editor(registry, stack, qtbot):
    from flograph.ui.editor.editor_dock import EditorPanel
    graph = Graph()
    node = registry.instantiate(SCRIPT, (0, 0))
    other = registry.instantiate(SCRIPT, (0, 200))
    graph.add_node(node)
    graph.add_node(other)
    panel = EditorPanel(graph, stack, registry)
    qtbot.addWidget(panel)
    return panel, node, other


def test_the_editor_holds_flos_code_unapplied(registry, stack, qtbot):
    panel, node, other = _editor(registry, stack, qtbot)
    panel.set_node(node.id)
    panel.suggest_code(node.id, GOOD)
    assert panel.editor.toPlainText() == GOOD
    assert node.source != GOOD and node._temp_edit
    assert "not applied" in panel._message.text()
    # away and back: still there, still marked as Flo's
    panel.set_node(other.id)
    panel.set_node(node.id)
    assert panel.editor.toPlainText() == GOOD
    assert "Flo wrote this code" in panel._message.text()
    panel.apply_code()
    assert node.source == GOOD and stack.count() == 1


def test_a_suggestion_for_another_node_waits_for_it(registry, stack, qtbot):
    panel, node, other = _editor(registry, stack, qtbot)
    panel.set_node(other.id)
    panel.suggest_code(node.id, GOOD)
    assert panel.editor.toPlainText() == other.source and node._temp_edit
    panel.set_node(node.id)
    assert panel.editor.toPlainText() == GOOD


def test_undoing_the_turn_takes_the_code_back(registry, stack, qtbot):
    panel, node, other = _editor(registry, stack, qtbot)
    panel.set_node(node.id)
    panel.suggest_code(node.id, GOOD)
    panel.discard_suggestion(node.id, GOOD)
    assert panel.editor.toPlainText() == node.source and not node._temp_edit
    # one the user has edited since is theirs, and stays
    panel.suggest_code(node.id, GOOD)
    panel.editor.setPlainText(GOOD + "\n# mine\n")
    panel.discard_suggestion(node.id, GOOD)
    assert panel.editor.toPlainText().endswith("# mine\n")


def test_the_tool_states_the_rules_the_check_applies(registry, stack):
    """Haiku learned PARAMS from three rejections in a row (tuples, a choice
    without options, type 'number'); the description now says them, from
    the check's own tables."""
    from flograph.core.params import PARAM_TYPES
    box, _, _ = _box(registry, stack)
    spec = next(t for t in box.specs() if t.name == "write_node_code")
    for name in PARAM_TYPES:
        assert name in spec.description
    assert '"options"' in spec.description and "dataframe" in spec.description
    assert "flow" not in spec.description.split("type one of")[1].split(".")[0]


# -- when the user lets Flo apply its own code ---------------------------------

def _applying(registry, stack):
    box, node, sent = _box(registry, stack, suggest=False)
    box.apply_code = True
    return box, node, sent


def test_applied_code_is_on_the_node_and_one_undo_step(registry, stack):
    box, node, _ = _applying(registry, stack)
    before = node.source
    box.begin_turn("write me a doubling node")
    out = _call(box, "write_node_code", node="n1", code=GOOD)
    box.end_turn()
    assert out["status"].startswith("applied")
    assert node.source == GOOD and node.spec.label == "Double"
    assert box.pushed and stack.count() == 1
    stack.undo()
    assert node.source == before


def test_applied_code_must_load(registry, stack):
    box, node, _ = _applying(registry, stack)
    out = _call(box, "write_node_code", node="n1", code="def run(:\n")
    assert "does not load as a node" in out["error"] and stack.count() == 0


def test_the_tool_says_whether_code_is_applied(registry, stack):
    box, _, _ = _box(registry, stack)
    held = next(t for t in box.specs() if t.name == "write_node_code")
    box.apply_code = True
    applied = next(t for t in box.specs() if t.name == "write_node_code")
    assert "NOT applied" in held.description
    assert "applied at once" in applied.description
    assert "{applied}" not in applied.description
