"""Idea #15: stacking order — bring to front, send to back, and friends.

Nodes, frames and dashboard tiles each carry a place in a back-to-front
order of their own kind. The rule itself lives in core.layers as a pure
function; the canvases turn a selection plus an action into one undoable
restack, and Qt z-values are derived from the model rather than stored.
"""
import json
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QKeyEvent, QUndoStack

from flograph.core import Frame, Graph, NodeRegistry, Page, Tile
from flograph.core.layers import next_z, order_of, restack
from flograph.core.serialization import graph_from_dict, graph_to_dict
from flograph.ui.canvas import NodeGraphScene
from flograph.ui.canvas.stacking import (
    FRAME_Z, FULLSCREEN_TILE_Z, WIRE_Z, layer_action_for,
)


@pytest.fixture(scope="module")
def registry():
    reg = NodeRegistry()
    reg.load_builtins()
    return reg


class TestTheRule:
    """core.layers.restack, on plain lists — back-to-front, so the last
    entry is the one on top."""

    def test_front_and_back(self):
        assert restack(list("abc"), {"a"}, "front") == list("bca")
        assert restack(list("abc"), {"c"}, "back") == list("cab")

    def test_forward_and_backward_step_one_place(self):
        assert restack(list("abc"), {"a"}, "forward") == list("bac")
        assert restack(list("abc"), {"c"}, "backward") == list("acb")

    def test_a_selection_travels_as_a_block(self):
        """Two selected items keep their own order and step past the one
        between them together — otherwise repeated presses shuffle them."""
        assert restack(list("abc"), {"a", "b"}, "forward") == list("cab")
        assert restack(list("abc"), {"b", "c"}, "backward") == list("bca")

    def test_a_gapped_selection_keeps_its_relative_order(self):
        assert restack(list("abcd"), {"a", "c"}, "front") == list("bdac")
        assert restack(list("abcd"), {"a", "c"}, "back") == list("acbd")

    def test_already_at_the_end_is_a_no_op(self):
        for action in ("front", "forward"):
            assert restack(list("abc"), {"c"}, action) == list("abc")
        for action in ("back", "backward"):
            assert restack(list("abc"), {"a"}, action) == list("abc")

    def test_selecting_everything_cannot_move_anything(self):
        assert restack(list("abc"), set("abc"), "front") == list("abc")

    def test_unknown_ids_and_actions(self):
        assert restack(list("abc"), {"zz"}, "front") == list("abc")
        with pytest.raises(ValueError, match="unknown restack action"):
            restack(list("abc"), {"a"}, "sideways")

    def test_order_of_breaks_ties_without_losing_anyone(self):
        """Undoing a delete can restore a node onto a z another has taken;
        the order still has to be total."""
        items = [SimpleNamespace(id="a", z=1), SimpleNamespace(id="b", z=1),
                 SimpleNamespace(id="c", z=None)]
        assert order_of(items) == ["c", "a", "b"]

    def test_next_z_puts_new_things_on_top(self):
        assert next_z([]) == 0
        assert next_z([SimpleNamespace(id="a", z=4)]) == 5


class TestTheModel:

    @pytest.fixture
    def env(self, registry):
        graph = Graph()
        ids = {name: graph.add_node(
            registry.instantiate("flograph.util.constant")).id
            for name in "ABC"}
        return graph, ids

    def named(self, graph, ids):
        rev = {v: k for k, v in ids.items()}
        return [rev[i] for i in graph.stacking_order("node")]

    def test_nodes_stack_in_the_order_they_were_added(self, env):
        graph, ids = env
        assert self.named(graph, ids) == ["A", "B", "C"]

    def test_restack_normalizes_z_across_the_whole_kind(self, env):
        """Only the order carries meaning, so the numbers are rewritten
        0..n-1 every time — otherwise repeated restacks drift."""
        graph, ids = env
        graph.restack("node", [ids["C"], ids["A"], ids["B"]])
        assert [graph.nodes[ids[n]].z for n in "ABC"] == [1, 2, 0]

    def test_an_id_missing_from_the_order_is_not_dropped(self, env):
        graph, ids = env
        graph.restack("node", [ids["C"], ids["A"]])
        assert self.named(graph, ids) == ["B", "C", "A"]

    def test_a_restack_announces_itself(self, env):
        graph, ids = env
        seen = []
        graph.events.restacked.connect(lambda k, p: seen.append((k, p)))
        graph.restack("node", list(ids.values()))
        assert seen == [("node", None)]

    def test_frames_and_tiles_stack_separately(self, env, registry):
        graph, _ids = env
        graph.add_frame(Frame(id="f1"))
        graph.add_frame(Frame(id="f2"))
        graph.add_page(Page(id="p1"))
        graph.add_tile("p1", Tile(id="t1", node_id="x"))
        assert graph.stacking_order("frame") == ["f1", "f2"]
        assert graph.stacking_order("tile", "p1") == ["t1"]
        # a frame restack leaves the nodes alone
        before = graph.stacking_order("node")
        graph.restack("frame", ["f2", "f1"])
        assert graph.stacking_order("node") == before

    def test_an_unknown_kind_is_refused(self, env):
        from flograph.core.graph import GraphError
        graph, _ids = env
        with pytest.raises(GraphError, match="no stacking order"):
            graph.stacking_order("wire")


class TestPersistence:

    def test_z_round_trips(self, registry):
        graph = Graph()
        ids = [graph.add_node(
            registry.instantiate("flograph.util.constant")).id
            for _ in range(3)]
        graph.add_frame(Frame(id="f1"))
        graph.add_frame(Frame(id="f2"))
        graph.add_page(Page(id="p1"))
        graph.add_tile("p1", Tile(id="t1", node_id=ids[0]))
        graph.add_tile("p1", Tile(id="t2", node_id=ids[1]))
        graph.restack("node", [ids[2], ids[0], ids[1]])
        graph.restack("frame", ["f2", "f1"])
        graph.restack("tile", ["t2", "t1"], "p1")

        data = json.loads(json.dumps(graph_to_dict(graph)))
        loaded = graph_from_dict(data, registry)
        assert loaded.stacking_order("node") == [ids[2], ids[0], ids[1]]
        assert loaded.stacking_order("frame") == ["f2", "f1"]
        assert loaded.stacking_order("tile", "p1") == ["t2", "t1"]

    def test_a_file_written_before_layering_keeps_its_old_stacking(
            self, registry):
        """No z anywhere means "however these were listed" — which is
        exactly the insertion-order stacking those files rendered with."""
        graph = Graph()
        ids = [graph.add_node(
            registry.instantiate("flograph.util.constant")).id
            for _ in range(3)]
        graph.add_page(Page(id="p1"))
        graph.add_tile("p1", Tile(id="t1", node_id=ids[0]))
        graph.add_tile("p1", Tile(id="t2", node_id=ids[1]))

        data = json.loads(json.dumps(graph_to_dict(graph)))
        for entry in data["graph"]["nodes"]:
            del entry["z"]
        for tile in data["graph"]["pages"][0]["tiles"]:
            del tile["z"]

        loaded = graph_from_dict(data, registry)
        assert loaded.stacking_order("node") == ids
        assert loaded.stacking_order("tile", "p1") == ["t1", "t2"]
        assert all(n.z is not None for n in loaded.nodes.values())


class TestOnTheCanvas:

    @pytest.fixture
    def env(self, qtbot, registry):
        graph = Graph()
        stack = QUndoStack()
        scene = NodeGraphScene(graph, stack, registry=registry)
        ids = {name: graph.add_node(
            registry.instantiate("flograph.util.constant")).id
            for name in "ABC"}
        return SimpleNamespace(graph=graph, stack=stack, scene=scene, ids=ids)

    def order(self, env):
        rev = {v: k for k, v in env.ids.items()}
        return [rev[i] for i in env.graph.stacking_order("node")]

    def select(self, env, *names):
        env.scene.clearSelection()
        for name in names:
            env.scene.node_items[env.ids[name]].setSelected(True)

    def test_the_selection_is_what_moves(self, env):
        self.select(env, "A")
        assert env.scene.restack_selection("front")
        assert self.order(env) == ["B", "C", "A"]

    def test_z_values_follow_the_model(self, env):
        self.select(env, "A")
        env.scene.restack_selection("front")
        z = {n: env.scene.node_items[env.ids[n]].zValue() for n in "ABC"}
        assert z["A"] > z["C"] > z["B"]

    def test_it_is_one_undo_step(self, env):
        self.select(env, "A")
        env.scene.restack_selection("front")
        assert env.stack.undoText() == "Bring to Front"
        env.stack.undo()
        assert self.order(env) == ["A", "B", "C"]
        env.stack.redo()
        assert self.order(env) == ["B", "C", "A"]

    def test_an_impossible_move_pushes_nothing(self, env):
        """Ctrl+] on something already on top must fall through, not bury
        the undo stack in no-ops."""
        self.select(env, "C")
        assert env.scene.restack_selection("front") is False
        assert env.stack.count() == 0

    def test_nothing_selected_moves_nothing(self, env):
        env.scene.clearSelection()
        assert env.scene.restack_selection("front") is False

    def test_nodes_and_frames_restack_within_their_own_kind(self, env):
        """A frame is a backdrop — "bring to front" on a mixed selection
        raises each among its peers rather than lifting a frame over a
        node, which no band arithmetic would allow anyway."""
        env.graph.add_frame(Frame(id="f1"))
        env.graph.add_frame(Frame(id="f2"))
        self.select(env, "A")
        env.scene.frame_items["f1"].setSelected(True)

        assert env.scene.restack_selection("front")
        assert self.order(env) == ["B", "C", "A"]
        assert env.graph.stacking_order("frame") == ["f2", "f1"]
        # ...and it is still a single undo step
        env.stack.undo()
        assert self.order(env) == ["A", "B", "C"]
        assert env.graph.stacking_order("frame") == ["f1", "f2"]

    def test_frames_stay_under_the_wires_whatever_the_user_does(self, env):
        env.graph.add_frame(Frame(id="f1"))
        env.graph.add_frame(Frame(id="f2"))
        env.scene.clearSelection()
        env.scene.frame_items["f1"].setSelected(True)
        env.scene.restack_selection("front")
        assert max(env.scene.frame_items[i].zValue()
                   for i in ("f1", "f2")) < WIRE_Z
        assert min(env.scene.node_items[i].zValue()
                   for i in env.ids.values()) > WIRE_Z

    def test_a_new_node_lands_on_top(self, env, registry):
        self.select(env, "A")
        env.scene.restack_selection("front")
        new = env.graph.add_node(
            registry.instantiate("flograph.util.constant"))
        assert env.graph.stacking_order("node")[-1] == new.id

    def test_an_undone_delete_returns_to_its_own_layer(self, env):
        from flograph.ui.commands import RemoveSelectionCommand
        self.select(env, "A")
        env.scene.restack_selection("front")     # A on top
        env.stack.push(RemoveSelectionCommand(env.graph, [env.ids["B"]]))
        env.stack.undo()
        assert self.order(env) == ["B", "C", "A"]

    def test_pasted_nodes_land_on_top(self, env):
        """Paste builds nodes with no z of its own, which is what puts the
        copy over the original rather than under it."""
        from flograph.core import NodeInstance
        original = env.graph.nodes[env.ids["A"]]
        copy = NodeInstance(id="pasted", spec=original.spec,
                            params=dict(original.params))
        env.graph.add_node(copy)
        assert env.graph.stacking_order("node")[-1] == "pasted"

    def test_the_frame_item_reads_its_own_band(self, env):
        env.graph.add_frame(Frame(id="f1"))
        assert env.scene.frame_items["f1"].zValue() == FRAME_Z


class TestTheShortcutMapping:

    def key(self, key, modifiers):
        return QKeyEvent(QKeyEvent.KeyPress, key, modifiers)

    def test_the_four_combinations(self):
        ctrl, shift = Qt.ControlModifier, Qt.ShiftModifier
        assert layer_action_for(
            self.key(Qt.Key_BracketRight, ctrl)) == "forward"
        assert layer_action_for(
            self.key(Qt.Key_BracketLeft, ctrl)) == "backward"
        assert layer_action_for(
            self.key(Qt.Key_BraceRight, ctrl | shift)) == "front"
        assert layer_action_for(
            self.key(Qt.Key_BraceLeft, ctrl | shift)) == "back"

    def test_layouts_that_report_the_unshifted_key(self):
        both = Qt.ControlModifier | Qt.ShiftModifier
        assert layer_action_for(self.key(Qt.Key_BracketRight, both)) == "front"
        assert layer_action_for(self.key(Qt.Key_BracketLeft, both)) == "back"

    def test_other_keys_are_left_alone(self):
        assert layer_action_for(
            self.key(Qt.Key_BracketRight, Qt.NoModifier)) is None
        assert layer_action_for(
            self.key(Qt.Key_F, Qt.ControlModifier)) is None


class TestOnADashboardPage:

    @pytest.fixture
    def env(self, qtbot, registry):
        from flograph.engine import ExecutionEngine
        from flograph.ui.dashboard.dashboard_scene import DashboardScene
        graph = Graph()
        stack = QUndoStack()
        engine = ExecutionEngine(graph)
        graph.add_page(Page(id="p1", title="Board"))
        for name in "XYZ":
            node = graph.add_node(
                registry.instantiate("flograph.viz.show_table"))
            graph.add_tile("p1", Tile(id=name, node_id=node.id, port="table"))
        scene = DashboardScene(graph, engine, stack, "p1")
        yield SimpleNamespace(graph=graph, stack=stack, scene=scene)
        scene.dispose()

    def select(self, env, *names):
        env.scene.clearSelection()
        for name in names:
            env.scene.tile_items[name].setSelected(True)

    def test_tiles_stack_in_the_order_they_were_placed(self, env):
        assert env.graph.stacking_order("tile", "p1") == ["X", "Y", "Z"]
        assert [env.scene.tile_items[t].zValue() for t in "XYZ"] == [0, 1, 2]

    def test_bring_to_front_and_undo(self, env):
        self.select(env, "X")
        assert env.scene.restack_selection("front")
        assert env.graph.stacking_order("tile", "p1") == ["Y", "Z", "X"]
        assert env.scene.tile_items["X"].zValue() == 2
        env.stack.undo()
        assert env.graph.stacking_order("tile", "p1") == ["X", "Y", "Z"]
        assert env.scene.tile_items["X"].zValue() == 0

    def test_an_impossible_move_pushes_nothing(self, env):
        self.select(env, "Z")
        assert env.scene.restack_selection("front") is False
        assert env.stack.count() == 0

    def test_a_maximized_tile_beats_every_stacking(self, env):
        """Maximizing puts one tile over the whole page — a tile stacked
        above it must not show through."""
        self.select(env, "X")
        env.scene.restack_selection("front")
        item = env.scene.tile_items["Y"]
        item.set_fullscreen_rect(QRectF(0, 0, 400, 300))
        assert item.zValue() == FULLSCREEN_TILE_Z
        assert item.zValue() > env.scene.tile_items["X"].zValue()
        item.clear_fullscreen()
        assert item.zValue() == 0

    def test_a_new_tile_lands_on_top(self, env, registry):
        self.select(env, "X")
        env.scene.restack_selection("front")
        node = env.graph.add_node(
            registry.instantiate("flograph.viz.show_table"))
        env.graph.add_tile("p1", Tile(id="new", node_id=node.id, port="table"))
        assert env.graph.stacking_order("tile", "p1")[-1] == "new"

    def test_duplicating_a_page_carries_the_stacking(self, env):
        from flograph.ui.commands import DuplicatePageCommand
        self.select(env, "X")
        env.scene.restack_selection("front")
        env.stack.push(DuplicatePageCommand(env.graph, "p1"))

        copy = next(p for p in env.graph.pages.values() if p.id != "p1")
        by_node = {t.node_id: t.z for t in copy.tiles.values()}
        source = env.graph.pages["p1"].tiles
        assert by_node == {t.node_id: t.z for t in source.values()}

    def test_another_pages_restack_is_ignored(self, env, registry):
        """Each page scene owns one page; a restack elsewhere must not
        renumber its items."""
        env.graph.add_page(Page(id="p2"))
        node = env.graph.add_node(
            registry.instantiate("flograph.viz.show_table"))
        env.graph.add_tile("p2", Tile(id="other", node_id=node.id))
        before = [env.scene.tile_items[t].zValue() for t in "XYZ"]
        env.graph.restack("tile", ["other"], "p2")
        assert [env.scene.tile_items[t].zValue() for t in "XYZ"] == before
