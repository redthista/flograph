"""Input controls that hold a change until Apply — `core.control_apply` and
`ui.control_binding`, and the Action Button that applies a whole form.

Asserted on the model (params, dirty flags, undo index, run count), not on
the widget: the widget showing the right thing was never the hard part.
"""
import pytest
from PySide6.QtCore import QSettings

from flograph.core import NodeRegistry, Page, Tile
from flograph.core import control_apply as ca
from flograph.ui import control_binding as cb
from flograph.ui import mainwindow as mod
from flograph.ui.commands import AddPageCommand, AddTileCommand, SetCodeCommand
from flograph.ui.mainwindow import MainWindow


@pytest.fixture(autouse=True)
def _isolated_settings(tmp_path, monkeypatch):
    ini_path = str(tmp_path / "test_settings.ini")
    monkeypatch.setattr(
        mod, "QSettings",
        lambda *a, **k: QSettings(ini_path, QSettings.IniFormat))


@pytest.fixture(scope="module")
def registry():
    reg = NodeRegistry()
    reg.load_builtins()
    return reg


@pytest.fixture
def window(qtbot, registry):
    win = MainWindow(registry)
    win.confirm_close = False
    qtbot.addWidget(win)
    return win


def slider(window, **params):
    node = window.graph.add_node(
        window.registry.instantiate("flograph.input.slider"))
    for name, value in params.items():
        window.graph.set_param(node.id, name, value)
    return node


def doubler(window, source):
    node = window.graph.add_node(window.registry.instantiate(
        "flograph.scripting.python_script"))
    window.undo_stack.push(SetCodeCommand(
        window.graph, node.id,
        'NODE = {"label": "Double", "category": "Test",\n'
        '        "inputs": [("in1", "any")],\n'
        '        "outputs": [("out1", "any")]}\n'
        "def run(ctx, in1):\n    return in1 * 2\n"))
    window.graph.connect(source.id, "value", node.id, "in1")
    return node


def run_all(qtbot, window):
    with qtbot.waitSignal(window.engine.run_finished, timeout=20000):
        window.engine.run_all()


def out(window, node, port="out1"):
    entry = window.engine.cache.get(node.id)
    return entry.outputs.get(port) if entry else None


class TestSpec:
    def test_every_control_gets_the_behaviour_params(self, registry):
        controls = [s for s in registry.all() if s.card == "control"]
        assert len(controls) >= 7
        for spec in controls:
            names = {p.name for p in spec.params}
            assert {"apply", "draft", "show_reset"} <= names, spec.type_id

    def test_other_nodes_do_not(self, registry):
        spec = registry.get("flograph.util.action_button")
        assert "draft" not in {p.name for p in spec.params}

    def test_draft_marks_nothing_dirty(self, registry):
        spec = registry.get("flograph.input.slider")
        assert spec.param("draft").cosmetic and spec.param("draft").hidden
        assert spec.param("apply").cosmetic


class TestRules:
    def test_a_blank_draft_is_none_but_an_emptied_text_is_one(self):
        assert ca.decode("") == (False, None)
        assert ca.decode(ca.encode("")) == (True, "")

    def test_shown_params_swap_in_the_draft(self):
        shown = ca.shown_params({"value": 10, "draft": ca.encode(40)})
        assert shown["value"] == 40

    def test_an_unreadable_draft_is_ignored(self):
        assert ca.shown_params({"value": 10, "draft": "{nope"})["value"] == 10


class TestHeld:
    def test_live_is_unchanged(self, window):
        node = slider(window, value=10)
        assert cb.commit_value(window.graph, window.undo_stack, node.id, 30)
        assert node.params["value"] == 30 and not ca.has_draft(node)

    def test_held_change_goes_to_the_draft_and_dirties_nothing(
            self, qtbot, window):
        node = slider(window, value=10, apply=ca.BUTTON)
        down = doubler(window, node)
        run_all(qtbot, window)
        assert out(window, down) == 20
        assert not cb.commit_value(window.graph, window.undo_stack,
                                   node.id, 30)
        assert node.params["value"] == 10
        assert ca.decode(node.params["draft"]) == (True, 30)
        assert not window.graph.nodes[down.id].dirty

    def test_moving_back_drops_the_draft(self, window):
        node = slider(window, value=10, apply=ca.WAIT)
        cb.commit_value(window.graph, window.undo_stack, node.id, 30)
        cb.commit_value(window.graph, window.undo_stack, node.id, 10)
        assert not ca.has_draft(node)

    def test_apply_is_one_undo_step(self, window):
        node = slider(window, value=10, apply=ca.BUTTON)
        cb.commit_value(window.graph, window.undo_stack, node.id, 30)
        before = window.undo_stack.index()
        assert cb.apply(window.graph, window.undo_stack, node.id)
        assert node.params["value"] == 30 and not ca.has_draft(node)
        assert window.undo_stack.index() == before + 1
        window.undo_stack.undo()
        assert node.params["value"] == 10
        assert ca.decode(node.params["draft"]) == (True, 30)

    def test_discard_keeps_the_flow_value(self, window):
        node = slider(window, value=10, apply=ca.BUTTON)
        cb.commit_value(window.graph, window.undo_stack, node.id, 30)
        assert not cb.discard(window.graph, window.undo_stack, node.id)
        assert node.params["value"] == 10 and not ca.has_draft(node)

    def test_reset_goes_back_to_the_script_default(self, window):
        node = slider(window, value=10)
        assert cb.reset(window.graph, window.undo_stack, node.id)
        assert node.params["value"] == ca.default_value(node) == 50.0

    def test_a_held_reset_is_held_too(self, window):
        node = slider(window, value=10, apply=ca.WAIT)
        assert not cb.reset(window.graph, window.undo_stack, node.id)
        assert node.params["value"] == 10
        assert ca.shown_value(node) == 50.0


class TestCard:
    def test_card_shows_the_draft_and_the_pending_dot(self, window):
        node = slider(window, value=10, apply=ca.BUTTON,
                      minimum=0, maximum=100)
        widget = window.scene.node_items[node.id]._control_widget
        widget._slider.setValue(40)
        assert node.params["value"] == 10
        assert ca.decode(node.params["draft"]) == (True, 40)
        assert widget.pending()
        assert not widget._apply_button.isHidden()
        assert widget._read() == 40

    def test_wait_mode_has_no_button_of_its_own(self, window):
        node = slider(window, value=10, apply=ca.WAIT, minimum=0, maximum=100)
        widget = window.scene.node_items[node.id]._control_widget
        widget._slider.setValue(40)
        assert widget.pending() and widget._apply_button.isHidden()

    def test_the_apply_button_applies_and_runs(self, qtbot, window):
        node = slider(window, value=10, apply=ca.BUTTON,
                      minimum=0, maximum=100)
        down = doubler(window, node)
        run_all(qtbot, window)
        widget = window.scene.node_items[node.id]._control_widget
        widget._slider.setValue(40)
        with qtbot.waitSignal(window.engine.run_finished, timeout=20000):
            widget._apply_button.click()
        assert out(window, down) == 80
        assert not widget.pending()

    def test_reset_button_shows_only_when_asked_and_away_from_default(
            self, window):
        node = slider(window, value=10)
        widget = window.scene.node_items[node.id]._control_widget
        assert widget._reset_button.isHidden()
        window.graph.set_param(node.id, "show_reset", True)
        window.scene.node_items[node.id].sync_control()
        assert not widget._reset_button.isHidden()
        widget._reset_button.click()
        assert node.params["value"] == 50.0
        assert widget._reset_button.isHidden()


class TestApplyButton:
    def _page_with(self, window, *nodes):
        window.undo_stack.push(
            AddPageCommand(window.graph, Page(id="p1", title="Form")))
        for i, node in enumerate(nodes):
            tile = Tile(id=f"t{i}", node_id=node.id, port=None,
                        rect=(0.0, i * 120.0, 200.0, 100.0))
            window.undo_stack.push(AddTileCommand(window.graph, "p1", tile))

    def test_apply_inputs_applies_the_page_in_one_step_and_one_run(
            self, qtbot, window):
        a = slider(window, value=1, apply=ca.WAIT)
        b = slider(window, value=2, apply=ca.WAIT)
        elsewhere = slider(window, value=3, apply=ca.WAIT)
        da, db = doubler(window, a), doubler(window, b)
        button = window.graph.add_node(
            window.registry.instantiate("flograph.util.action_button"))
        window.graph.set_param(button.id, "action", "Apply inputs")
        self._page_with(window, a, b, button)
        run_all(qtbot, window)
        for node, value in ((a, 10), (b, 20), (elsewhere, 30)):
            cb.commit_value(window.graph, window.undo_stack, node.id, value)
        before = window.undo_stack.index()
        runs = []
        window.engine.run_finished.connect(lambda *_: runs.append(1))
        with qtbot.waitSignal(window.engine.run_finished, timeout=20000):
            window._on_button_fired(button.id)
        qtbot.wait(200)
        assert (a.params["value"], b.params["value"]) == (10, 20)
        assert out(window, da) == 20 and out(window, db) == 40
        assert elsewhere.params["value"] == 3 and ca.has_draft(elsewhere)
        assert window.undo_stack.index() == before + 1
        assert len(runs) == 1

    def test_reset_inputs_named(self, window):
        a = slider(window, value=1)
        a.label_override = "Price"
        button = window.graph.add_node(
            window.registry.instantiate("flograph.util.action_button"))
        window.graph.set_param(button.id, "action", "Reset inputs")
        window.graph.set_param(button.id, "inputs_scope", "named inputs")
        window.graph.set_param(button.id, "input_names", "Price")
        window._on_button_fired(button.id)
        assert a.params["value"] == 50.0
