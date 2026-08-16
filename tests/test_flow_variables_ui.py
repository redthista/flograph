"""The UI and CLI surfaces of flow variables: the secrets dialog, the
properties-panel annotation, and headless --var."""
from types import SimpleNamespace

import pytest
from PySide6.QtGui import QUndoStack

from flograph.core import Graph, dotenv, varlinks
from flograph.engine import headless
from flograph.ui.canvas.appearance_dialog import AppearanceDialog
from flograph.ui.canvas.node_item import card_kind, compact_on, renders_plain
from flograph.ui.env_dialog import EnvDialog, MASK, usage_counts
from flograph.ui.properties.params_panel import ParamsPanel

VARS = "flograph.util.variables"
CONST = "flograph.util.constant"


@pytest.fixture
def flow(registry):
    graph = Graph()
    variables = graph.add_node(registry.instantiate(VARS))
    consumer = graph.add_node(registry.instantiate(CONST))
    graph.set_param(variables.id, "assignments", "region = North")
    graph.set_param(consumer.id, "value", "${region}")
    return graph, variables, consumer


class TestDescribe:
    def test_a_declared_value_is_reported(self, flow):
        graph, _variables, consumer = flow
        assert varlinks.describe(graph, consumer) == ["${region} = North"]

    def test_an_undefined_name_says_so(self, registry):
        graph = Graph()
        node = graph.add_node(registry.instantiate(CONST))
        graph.set_param(node.id, "value", "${nope}")
        assert "not defined" in varlinks.describe(graph, node)[0]

    def test_a_secret_never_reports_its_value(self, registry):
        graph = Graph()
        node = graph.add_node(registry.instantiate(CONST))
        graph.set_param(node.id, "value", "${env:TOKEN}")
        graph.env = {"TOKEN": "s3cret"}
        described = varlinks.describe(graph, node)[0]
        assert "s3cret" not in described
        assert "set in the secrets file" in described


class TestParamsPanel:
    def test_a_reference_is_marked_and_explained(self, qtbot, flow):
        graph, _variables, consumer = flow
        stack = QUndoStack()
        panel = ParamsPanel(graph, stack)
        qtbot.addWidget(panel)
        panel.set_node(consumer.id)
        rows = {panel.tree.topLevelItem(i).text(0): panel.tree.topLevelItem(i)
                for i in range(panel.tree.topLevelItemCount())}
        item = rows["Value"]
        assert item.font(0).italic()
        assert "${region} = North" in item.toolTip(0)
        stack.clear()

    def test_an_ordinary_param_is_left_alone(self, qtbot, flow):
        graph, _variables, consumer = flow
        graph.set_param(consumer.id, "value", "plain text")
        stack = QUndoStack()
        panel = ParamsPanel(graph, stack)
        qtbot.addWidget(panel)
        panel.set_node(consumer.id)
        rows = {panel.tree.topLevelItem(i).text(0): panel.tree.topLevelItem(i)
                for i in range(panel.tree.topLevelItemCount())}
        assert not rows["Value"].font(0).italic()
        stack.clear()


class TestLooksLikeAnOrdinaryNode:
    """The `vars` card marks *identity*, not rendering. The node draws
    nothing of its own, so it must keep the square, the marks and the full
    Appearance dialog every other Util node has."""

    def test_it_keeps_its_identity_marker(self, flow):
        _graph, variables, _consumer = flow
        assert card_kind(variables) == "vars"

    def test_but_renders_as_a_plain_node(self, flow):
        _graph, variables, _consumer = flow
        assert renders_plain(variables)

    def test_so_it_can_draw_as_the_compact_square(self, flow):
        _graph, variables, _consumer = flow
        scene = SimpleNamespace(compact_nodes=True)
        assert compact_on(variables, scene)

    def test_a_real_card_still_cannot(self, registry):
        graph = Graph()
        slicer = graph.add_node(registry.instantiate("flograph.viz.slicer"))
        scene = SimpleNamespace(compact_nodes=True)
        assert not renders_plain(slicer)
        assert not compact_on(slicer, scene)

    def test_the_appearance_dialog_offers_shape_and_mark(self, qtbot, flow):
        graph, variables, _consumer = flow
        scene = SimpleNamespace(graph=graph, compact_nodes=True,
                                node_items={}, undo_stack=QUndoStack())
        dialog = AppearanceDialog(scene, variables.id)
        qtbot.addWidget(dialog)
        assert dialog._plain


class TestEnvDialog:
    def test_usage_counts_reference_nodes(self, registry):
        graph = Graph()
        for _ in range(2):
            node = graph.add_node(registry.instantiate(CONST))
            graph.set_param(node.id, "value", "${env:TOKEN}")
        assert usage_counts(graph) == {"TOKEN": 2}

    def test_it_lists_a_referenced_key_the_file_lacks(self, qtbot, registry,
                                                      tmp_path):
        graph = Graph()
        node = graph.add_node(registry.instantiate(CONST))
        graph.set_param(node.id, "value", "${env:TOKEN}")
        graph.env_path = str(tmp_path / ".env")
        dialog = EnvDialog(graph, None)
        qtbot.addWidget(dialog)
        assert dialog.values() == {"TOKEN": ""}

    def test_values_are_masked_until_asked_for(self, qtbot, registry, tmp_path):
        path = tmp_path / ".env"
        dotenv.save(path, {"TOKEN": "s3cret"})
        graph = Graph()
        graph.env_path = str(path)
        dialog = EnvDialog(graph, None)
        qtbot.addWidget(dialog)
        assert dialog._table.item(0, 1).text() == MASK
        # ...and masking is display-only: the value is still what is saved
        assert dialog.values() == {"TOKEN": "s3cret"}
        dialog._reveal.setChecked(True)
        assert dialog._table.item(0, 1).text() == "s3cret"

    def test_saving_points_the_graph_at_the_file_and_re_runs_readers(
            self, qtbot, registry, tmp_path):
        path = tmp_path / ".env"
        dotenv.save(path, {"TOKEN": "s3cret"})
        graph = Graph()
        node = graph.add_node(registry.instantiate(CONST))
        graph.set_param(node.id, "value", "${env:TOKEN}")
        graph.env_path = str(path)
        graph.mark_clean(node.id)

        dialog = EnvDialog(graph, None)
        qtbot.addWidget(dialog)
        dialog.apply_to_graph()
        assert graph.env["TOKEN"] == "s3cret"
        # the secret changed under it and no edge could have said so
        assert node.dirty

    def test_the_path_change_is_undoable(self, qtbot, registry, tmp_path):
        path = tmp_path / ".env"
        dotenv.save(path, {"A": "1"})
        graph = Graph()
        stack = QUndoStack()
        dialog = EnvDialog(graph, None, stack)
        qtbot.addWidget(dialog)
        dialog._path = path
        dialog.apply_to_graph()
        assert graph.env_path == str(path)
        stack.undo()
        assert graph.env_path == ""
        stack.clear()


class TestHeadlessVar:
    def test_parses_both_flag_forms(self):
        assert headless.parse_args(
            ["a.flograph", "--var", "x=1", "--var=y=2"]
        ) == ("a.flograph", {"x": "1", "y": "2"})

    def test_a_value_may_contain_equals(self):
        _, overrides = headless.parse_args(["a.flograph", "--var", "q=a=b"])
        assert overrides == {"q": "a=b"}

    @pytest.mark.parametrize("argv", [
        [], ["a", "b"], ["a", "--var"], ["a", "--var", "nope"], ["a", "--x"],
    ])
    def test_bad_arguments_are_refused(self, argv):
        with pytest.raises(ValueError):
            headless.parse_args(argv)

    def test_an_override_rewrites_the_declaration(self, flow):
        graph, variables, consumer = flow
        headless.apply_overrides(graph, {"region": "South"})
        assert varlinks.declared_values(graph) == {"region": "South"}
        # and the consumer is dirty again, exactly as if it had been typed
        assert consumer.dirty

    def test_an_unknown_override_is_refused(self, flow):
        graph, _variables, _consumer = flow
        with pytest.raises(ValueError, match="no variable named nope"):
            headless.apply_overrides(graph, {"nope": "x"})
