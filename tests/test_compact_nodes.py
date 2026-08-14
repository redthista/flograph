"""Compact ("square") plain nodes — Settings > Canvas > Compact nodes.

A node with no card kind draws as a fixed 60x60 square with its name above
and a status row below. The geometry is the contract here: everything else on
the canvas — wires, link lines, frames, align/distribute, fit, grid snap —
reads `width` and `body_height` off the item and assumes the origin is the
body's top-left, which is exactly where the old wide node's header started.
"""
import pytest
from PySide6.QtCore import QPointF
from PySide6.QtGui import QUndoStack

from flograph.core import Graph, NodeInstance, parse_spec
from flograph.ui.canvas import NodeGraphScene
from flograph.ui.canvas.node_item import (
    COMPACT_MIN_H, COMPACT_PORT_TOP, COMPACT_W, NODE_WIDTH, PortItem, ROW_H,
)

SORT = "flograph.transform.sort"          # 1 in, 1 out
JOIN = "flograph.transform.join"          # 2 in, 1 out
READ_CSV = "flograph.io.read_csv"         # 0 in, 1 out
SHOW_PLOT = "flograph.viz.show_plot"      # a figure card
REROUTE = "flograph.util.reroute"

THREE_PORT = '''
NODE = {
    "label": "Three Ports",
    "category": "Transform",
    "inputs": [("a", "any"), ("b", "any"), ("c", "any")],
    "outputs": [("out", "any")],
}
def run(ctx, a, b, c):
    return a
'''

FOUR_PORT = '''
NODE = {
    "label": "Four Ports",
    "category": "Transform",
    "inputs": [("a", "any"), ("b", "any"), ("c", "any"), ("d", "any")],
    "outputs": [("out", "any")],
}
def run(ctx, a, b, c, d):
    return a
'''


@pytest.fixture
def env(qtbot, registry):
    graph = Graph()
    scene = NodeGraphScene(graph, QUndoStack(), registry=registry)
    return graph, scene


def add(env, type_id, pos=(0.0, 0.0)):
    graph, scene = env
    node = env[1].registry.instantiate(type_id, pos=pos)
    graph.add_node(node)
    return node, scene.node_items[node.id]


def out_x(width: float) -> float:
    """Where an output pin sits for a node of this width — pins float clear
    of the edge rather than being centred on it (PORT_EDGE_GAP)."""
    return width + PortItem.RADIUS + 2.5


class TestSquareGeometry:
    def test_plain_node_is_a_fixed_square(self, env):
        _node, item = add(env, SORT)
        assert item._square
        assert (item.width, item.body_height) == (COMPACT_W, COMPACT_MIN_H)

    def test_port_count_does_not_change_the_size(self, env):
        _one, one_item = add(env, SORT)
        _two, two_item = add(env, JOIN, pos=(200, 0))
        _none, none_item = add(env, READ_CSV, pos=(400, 0))
        sizes = {(i.width, i.body_height)
                 for i in (one_item, two_item, none_item)}
        assert sizes == {(COMPACT_W, COMPACT_MIN_H)}

    def test_a_single_pin_sits_on_the_centre_line(self, env):
        middle = COMPACT_MIN_H / 2
        _node, item = add(env, SORT)
        assert item.input_ports["table"].pos() == QPointF(-8.0, middle)
        assert item.output_ports["table"].pos() == QPointF(out_x(COMPACT_W),
                                                          middle)

    def test_two_pins_straddle_the_centre_a_row_apart(self, env):
        _node, item = add(env, JOIN)
        ys = [item.input_ports[name].pos().y() for name in ("left", "right")]
        assert ys == [20.0, 40.0]
        assert ys[1] - ys[0] == ROW_H
        # the lone output stays on the centre line
        assert item.output_ports["joined"].pos().y() == COMPACT_MIN_H / 2

    def test_three_pins_fill_the_square(self, env):
        """The boundary: centred and top-anchored agree here, so there is no
        visible step where one rule takes over from the other."""
        graph, scene = env
        node = NodeInstance.create(parse_spec(THREE_PORT, "test.three"))
        graph.add_node(node)
        item = scene.node_items[node.id]
        ys = [item.input_ports[n].pos().y() for n in ("a", "b", "c")]
        assert ys == [COMPACT_PORT_TOP, 30.0, 50.0]
        assert max(ys) < item.body_height   # still inside the box

    def test_extra_pins_spill_below_without_growing_the_node(self, env):
        """The whole point of a fixed square: a node with more ports than it
        has room for runs them onto the canvas rather than getting taller,
        which is what card nodes have always done. Overflow goes *down* — the
        stack stops centring rather than creeping up into the node's name."""
        graph, scene = env
        node = NodeInstance.create(parse_spec(FOUR_PORT, "test.four"))
        graph.add_node(node)
        item = scene.node_items[node.id]
        assert (item.width, item.body_height) == (COMPACT_W, COMPACT_MIN_H)
        ys = [item.input_ports[n].pos().y() for n in ("a", "b", "c", "d")]
        assert ys == [10.0, 30.0, 50.0, 70.0]
        # never compressed, and the overflow goes down — never up into the
        # node's name
        assert all(b - a == ROW_H for a, b in zip(ys, ys[1:]))
        assert ys[-1] > item.body_height
        assert min(ys) > 0.0

    def test_bounding_rect_covers_the_name_above_and_status_below(self, env):
        _node, item = add(env, SORT)
        bounds = item.boundingRect()
        name = item._name_rect()
        status = item._status_rect()
        assert name.top() < 0 and status.bottom() > item.body_height
        assert bounds.contains(name) and bounds.contains(status)

    def test_shape_catches_the_name_but_not_the_gap(self, env):
        _node, item = add(env, SORT)
        shape = item.shape()
        name = item._name_rect()
        assert shape.contains(QPointF(COMPACT_W / 2, COMPACT_MIN_H / 2))
        assert shape.contains(name.center())
        # the air between the name and the box is not the node
        gap_y = name.bottom() + 1.0
        assert gap_y < 0.0
        assert not shape.contains(QPointF(COMPACT_W / 2, gap_y))


class TestNameAboveTheSquare:
    def test_a_short_name_is_one_line(self, env):
        _node, item = add(env, SORT)
        assert item._name_layout() == ("Sort",)

    def test_a_long_name_wraps_between_words(self, env):
        _node, item = add(env, "flograph.transform.string_manipulation")
        graph, _scene = env
        graph.set_label(_node.id, "Extremely Long Node Name Indeed")
        lines = item._name_layout()
        assert len(lines) == 2
        # broken at a space, not mid-word
        assert not lines[0].endswith(" ")
        assert lines[0].split()[-1] in "Extremely Long Node Name Indeed".split()

    def test_renaming_reflows_the_name(self, env):
        graph, _scene = env
        node, item = add(env, SORT)
        assert item._name_layout() == ("Sort",)
        graph.set_label(node.id, "Sort By Several Columns At Once Please")
        assert len(item._name_layout()) == 2

    def test_one_unbreakable_word_is_elided(self, env):
        graph, _scene = env
        node, item = add(env, SORT)
        graph.set_label(node.id, "Supercalifragilisticexpialidocious" * 2)
        lines = item._name_layout()
        assert len(lines) == 1
        assert lines[0].endswith("…")


class TestCardsAreUntouched:
    def test_a_figure_card_keeps_its_own_size(self, env):
        _node, item = add(env, SHOW_PLOT)
        assert not item._square
        assert (item.width, item.body_height) == (420.0, 320.0)
        assert item._name_rect() is None and item._status_rect() is None

    def test_a_reroute_keeps_its_dot(self, env):
        _node, item = add(env, REROUTE)
        assert item.compact and not item._square
        assert item.width == 28.0

    def test_the_setting_does_not_move_a_card(self, env):
        _graph, scene = env
        _node, item = add(env, SHOW_PLOT)
        before = (item.width, item.body_height)
        scene.set_compact_nodes(False)
        assert (item.width, item.body_height) == before
        scene.set_compact_nodes(True)
        assert (item.width, item.body_height) == before


class TestTheSetting:
    def test_off_restores_the_wide_box(self, env):
        _graph, scene = env
        _node, item = add(env, JOIN)
        scene.set_compact_nodes(False)
        assert not item._square
        assert item.width == NODE_WIDTH
        # the wide box is header + a row per port + padding, as it always was
        assert item.body_height == 26.0 + 2 * ROW_H + 8.0
        assert item._name_rect() is None

    def test_wide_pins_go_back_to_their_rows(self, env):
        _graph, scene = env
        _node, item = add(env, JOIN)
        scene.set_compact_nodes(False)
        ys = [item.input_ports[n].pos().y() for n in ("left", "right")]
        assert ys == [26.0 + ROW_H * 0.5, 26.0 + ROW_H * 1.5]

    def test_toggling_back_and_forth_is_stable(self, env):
        _graph, scene = env
        _node, item = add(env, JOIN)
        start = (item.width, item.body_height,
                 item.input_ports["left"].pos())
        scene.set_compact_nodes(False)
        scene.set_compact_nodes(True)
        assert (item.width, item.body_height,
                item.input_ports["left"].pos()) == start

    def test_wires_follow_the_pins_across_the_toggle(self, env):
        graph, scene = env
        src, src_item = add(env, READ_CSV)
        dst, dst_item = add(env, SORT, pos=(300, 0))
        graph.connect(src.id, "table", dst.id, "table")
        wire = next(iter(scene.connection_items.values()))
        before = wire.path().pointAtPercent(0.0)
        scene.set_compact_nodes(False)
        after = wire.path().pointAtPercent(0.0)
        # the source pin rode the widening node, and the wire came with it
        assert after.x() == pytest.approx(before.x() + NODE_WIDTH - COMPACT_W)

    def test_a_node_can_overrule_the_canvas(self, env):
        """Tri-state, the same shape as port_labels: the node's own choice
        wins, and the global keeps working on everything else."""
        graph, scene = env
        node, item = add(env, SORT)
        _other, other_item = add(env, JOIN, pos=(200, 0))

        scene.push_compact_view(node.id, False)
        assert not item._square and other_item._square

        scene.set_compact_nodes(False)
        assert not item._square and not other_item._square

        scene.push_compact_view(node.id, True)
        assert item._square and not other_item._square

    def test_clearing_the_override_follows_the_canvas_again(self, env):
        graph, scene = env
        node, item = add(env, SORT)
        scene.push_compact_view(node.id, False)
        scene.set_compact_nodes(True)
        assert not item._square      # the override still holds
        scene.push_compact_view(node.id, None)
        assert item._square          # handed back to the canvas setting

    def test_the_override_undoes_and_survives_a_round_trip(self, env,
                                                           registry):
        from flograph.core.serialization import graph_from_dict, graph_to_dict
        graph, scene = env
        node, item = add(env, SORT)
        scene.push_compact_view(node.id, False)
        restored = graph_from_dict(graph_to_dict(graph), registry)
        assert restored.nodes[node.id].compact_view is False
        scene.undo_stack.undo()
        assert node.compact_view is None and item._square

    def test_a_card_ignores_the_override(self, env):
        """compact_on refuses a card whatever it is asked — a Show Plot in a
        60px box would be a chart of nothing."""
        graph, scene = env
        node, item = add(env, SHOW_PLOT)
        scene.push_compact_view(node.id, True)
        assert not item._square
        assert (item.width, item.body_height) == (420.0, 320.0)

    def test_the_window_persists_the_choice(self, qtbot, registry):
        from flograph.ui.mainwindow import MainWindow
        window = MainWindow(registry)
        window.confirm_close = False
        qtbot.addWidget(window)
        assert window.compact_nodes is True
        window.set_compact_nodes(False)
        assert window.scene.compact_nodes is False
        assert window.settings.value("canvas/compact_nodes", True,
                                     type=bool) is False
        window.set_compact_nodes(True)
