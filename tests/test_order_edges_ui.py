"""The canvas side of order edges: the two flow pins on every node, when
they are on screen at all, dragging one to another node, and the dashed arc
that results."""
import pytest
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QKeyEvent, QUndoStack

from flograph.core import Graph, NodeRegistry
from flograph.ui.canvas import NodeGraphScene
from flograph.ui.canvas.connection_item import order_path
from flograph.ui.canvas.node_item import PortItem, flow_pins_on
from flograph.ui.canvas.order_help import order_edges_html, reveal_key_name

FLOW = "flow"


@pytest.fixture(scope="module")
def registry():
    reg = NodeRegistry()
    reg.load_builtins()
    return reg


@pytest.fixture
def env(qtbot, registry):
    graph = Graph()
    stack = QUndoStack()
    scene = NodeGraphScene(graph, stack, registry=registry)
    a = graph.add_node(registry.instantiate("flograph.util.constant",
                                            pos=(0, 0)))
    b = graph.add_node(registry.instantiate("flograph.scripting.python_script",
                                            pos=(320, 0)))
    yield graph, stack, scene, a, b
    stack.clear()


def flow_pins(scene, node_id):
    item = scene.node_items[node_id]
    return item.flow_ports["output"], item.flow_ports["input"]


class TestPins:
    def test_every_node_has_a_pair(self, env):
        graph, _stack, scene, a, b = env
        for node in (a, b):
            item = scene.node_items[node.id]
            assert set(item.flow_ports) == {"input", "output"}
            # ...and they are nobody's data port
            assert FLOW not in item.input_ports
            assert FLOW not in item.output_ports

    def test_a_reroute_has_none(self, env, registry):
        graph, _stack, scene, _a, _b = env
        dot = graph.add_node(registry.instantiate("flograph.util.reroute"))
        assert scene.node_items[dot.id].flow_ports == {}

    def test_they_sit_off_the_upper_corners(self, env):
        graph, _stack, scene, a, _b = env
        item = scene.node_items[a.id]
        pin_in = item.flow_ports["input"]
        pin_out = item.flow_ports["output"]
        assert pin_in.pos().x() < 0 < item.width < pin_out.pos().x()
        assert pin_in.pos().y() == pin_out.pos().y() < 0
        # clear of the name a square node draws above itself
        name = item._name_rect()
        if name is not None:
            assert pin_in.pos().y() <= name.top()

    def test_the_pin_is_drawn_smaller_than_a_data_pin(self, env):
        graph, _stack, scene, a, _b = env
        item = scene.node_items[a.id]
        assert item.flow_ports["input"].base_radius < PortItem.RADIUS
        assert item.output_ports["value"].base_radius == PortItem.RADIUS

    def test_the_input_pin_fills_once_something_orders_it(self, env):
        graph, _stack, scene, a, b = env
        pin = scene.node_items[b.id].flow_ports["input"]
        assert not scene.is_port_connected(b.id, pin.spec)
        graph.connect(a.id, FLOW, b.id, FLOW)
        assert scene.is_port_connected(b.id, pin.spec)

    def test_the_pins_ride_the_node(self, env):
        graph, _stack, scene, a, b = env
        graph.connect(a.id, FLOW, b.id, FLOW)
        wire = next(iter(scene.connection_items.values()))
        before = wire.path().boundingRect()
        graph.move_node(a.id, (0.0, 400.0))
        scene.node_item_moved(a.id)
        assert wire.path().boundingRect() != before


class TestWhenTheyShow:
    """Hidden by default; four ways to bring them up."""

    def test_hidden_until_asked_for(self, env):
        graph, _stack, scene, a, b = env
        for node in (a, b):
            item = scene.node_items[node.id]
            assert not flow_pins_on(node, scene)
            assert not any(p.isVisible() for p in item.flow_ports.values())
        # the data pins are unaffected — this is not a general LOD switch
        assert scene.node_items[a.id].output_ports["value"].isVisible()

    def test_the_canvas_wide_preference_shows_them(self, env):
        graph, _stack, scene, a, _b = env
        scene.set_flow_pins_enabled(True)
        assert all(p.isVisible() for p in scene.node_items[a.id].flow_ports.values())
        scene.set_flow_pins_enabled(False)
        assert not any(p.isVisible()
                       for p in scene.node_items[a.id].flow_ports.values())

    def test_holding_the_reveal_key_shows_them(self, env):
        graph, _stack, scene, a, _b = env
        scene.set_revealing_port_labels(True)
        assert all(p.isVisible()
                   for p in scene.node_items[a.id].flow_ports.values())
        scene.set_revealing_port_labels(False)
        assert not any(p.isVisible()
                       for p in scene.node_items[a.id].flow_ports.values())

    def test_dragging_one_shows_the_others(self, env):
        """You cannot aim at a pin that is not on screen."""
        graph, _stack, scene, a, b = env
        a_out, _ = flow_pins(scene, a.id)
        scene.begin_wire_drag(a_out)
        assert scene.drawing_order_edge
        assert all(p.isVisible()
                   for p in scene.node_items[b.id].flow_ports.values())
        scene.cancel_wire_drag()
        assert not scene.drawing_order_edge
        assert not any(p.isVisible()
                       for p in scene.node_items[b.id].flow_ports.values())

    def test_dragging_a_data_wire_does_not(self, env):
        graph, _stack, scene, a, b = env
        scene.begin_wire_drag(scene.node_items[a.id].output_ports["value"])
        assert not scene.drawing_order_edge
        assert not any(p.isVisible()
                       for p in scene.node_items[b.id].flow_ports.values())
        scene.cancel_wire_drag()

    def test_a_wired_pin_stays_on_screen(self, env):
        """A hidden pin under a dashed line would leave the wire running
        into the side of a node."""
        graph, _stack, scene, a, b = env
        graph.connect(a.id, FLOW, b.id, FLOW)
        assert scene.node_items[a.id].flow_ports["output"].isVisible()
        assert scene.node_items[b.id].flow_ports["input"].isVisible()
        # ...and only the ends that carry it
        assert not scene.node_items[a.id].flow_ports["input"].isVisible()
        assert not scene.node_items[b.id].flow_ports["output"].isVisible()

    def test_removing_the_edge_puts_them_away_again(self, env):
        graph, _stack, scene, a, b = env
        conn, _ = graph.connect(a.id, FLOW, b.id, FLOW)
        graph.disconnect(conn.id)
        assert not any(p.isVisible()
                       for p in scene.node_items[a.id].flow_ports.values())
        assert not any(p.isVisible()
                       for p in scene.node_items[b.id].flow_ports.values())

    def test_a_node_can_be_set_on_its_own(self, env):
        graph, stack, scene, a, b = env
        from flograph.ui.commands import SetFlowPinsCommand
        stack.push(SetFlowPinsCommand(graph, a.id, True))
        assert scene.node_items[a.id].flow_ports["input"].isVisible()
        assert not scene.node_items[b.id].flow_ports["input"].isVisible()
        # ...and the canvas-wide toggle no longer speaks for it
        scene.set_flow_pins_enabled(False)
        assert scene.node_items[a.id].flow_ports["input"].isVisible()
        stack.undo()
        assert not scene.node_items[a.id].flow_ports["input"].isVisible()

    def test_a_node_can_opt_out_while_the_canvas_shows_them(self, env):
        graph, stack, scene, a, b = env
        from flograph.ui.commands import SetFlowPinsCommand
        scene.set_flow_pins_enabled(True)
        stack.push(SetFlowPinsCommand(graph, a.id, False))
        assert not scene.node_items[a.id].flow_ports["input"].isVisible()
        assert scene.node_items[b.id].flow_ports["input"].isVisible()

    def test_a_node_added_later_answers_the_canvas(self, env, registry):
        graph, _stack, scene, _a, _b = env
        scene.set_flow_pins_enabled(True)
        late = graph.add_node(registry.instantiate("flograph.util.constant",
                                                   pos=(0, 500)))
        assert all(p.isVisible()
                   for p in scene.node_items[late.id].flow_ports.values())


class TestDragging:
    def test_flow_joins_flow_only(self, env):
        graph, _stack, scene, a, b = env
        a_out, _ = flow_pins(scene, a.id)
        _, b_in = flow_pins(scene, b.id)
        assert scene._wire_valid(a_out, b_in)
        # not to a data port, in either direction
        assert not scene._wire_valid(a_out,
                                     scene.node_items[b.id].input_ports["in1"])
        assert not scene._wire_valid(
            scene.node_items[a.id].output_ports["value"], b_in)
        # nor to another output
        assert not scene._wire_valid(a_out, flow_pins(scene, b.id)[0])

    def test_dropping_one_pin_on_the_other_orders_the_nodes(self, env):
        graph, stack, scene, a, b = env
        a_out, _ = flow_pins(scene, a.id)
        _, b_in = flow_pins(scene, b.id)
        scene.begin_wire_drag(a_out)
        scene.finish_wire_drag(b_in.scenePos())
        assert graph.order_sources(b.id) == [a.id]
        stack.undo()
        assert graph.order_sources(b.id) == []

    def test_a_second_prerequisite_does_not_displace_the_first(self, env,
                                                              registry):
        graph, _stack, scene, a, b = env
        c = graph.add_node(registry.instantiate("flograph.util.constant",
                                                pos=(0, 300)))
        graph.connect(a.id, FLOW, b.id, FLOW)
        c_out, _ = flow_pins(scene, c.id)
        _, b_in = flow_pins(scene, b.id)
        scene.begin_wire_drag(c_out)
        scene.finish_wire_drag(b_in.scenePos())
        assert graph.order_sources(b.id) == sorted([a.id, c.id])
        assert len(scene.connection_items) == 2

    def test_dragging_from_a_connected_flow_input_starts_a_new_edge(self, env,
                                                                   registry):
        """A data input hands its wire over to the drag, because it can only
        hold one. A flow input holds any number, so grabbing it would have to
        guess which — it starts a fresh edge instead."""
        graph, _stack, scene, a, b = env
        graph.connect(a.id, FLOW, b.id, FLOW)
        _, b_in = flow_pins(scene, b.id)
        scene.begin_wire_drag(b_in)
        assert scene._drag_detach is None
        scene.cancel_wire_drag()
        assert graph.order_sources(b.id) == [a.id]


class TestTheWire:
    def test_it_is_drawn_as_an_upward_arc(self, env):
        graph, _stack, scene, a, b = env
        graph.connect(a.id, FLOW, b.id, FLOW)
        wire = next(iter(scene.connection_items.values()))
        assert wire.is_order
        a_out, _ = flow_pins(scene, a.id)
        _, b_in = flow_pins(scene, b.id)
        # it leaves through the top: the path rises above both of its ends
        assert wire.path().boundingRect().top() < min(a_out.scenePos().y(),
                                                      b_in.scenePos().y())

    def test_a_data_wire_is_not_one(self, env):
        graph, _stack, scene, a, b = env
        graph.connect(a.id, "value", b.id, "in1")
        wire = next(iter(scene.connection_items.values()))
        assert not wire.is_order

    def test_double_clicking_it_inserts_no_reroute(self, env):
        graph, _stack, scene, a, b = env
        graph.connect(a.id, FLOW, b.id, FLOW)
        wire = next(iter(scene.connection_items.values()))

        class _Event:
            def scenePos(self):
                return QPointF(160, -40)

            def accept(self):
                pass

        wire.mouseDoubleClickEvent(_Event())
        assert len(graph.nodes) == 2   # nothing was spliced in

    def test_selecting_it_and_deleting_removes_the_order(self, env):
        graph, _stack, scene, a, b = env
        graph.connect(a.id, FLOW, b.id, FLOW)
        next(iter(scene.connection_items.values())).setSelected(True)
        scene.delete_selection()
        assert graph.order_sources(b.id) == []
        assert graph.connections == {}

    def test_the_arc_rises_between_its_ends(self):
        path = order_path(QPointF(0, 0), QPointF(200, 0))
        assert path.boundingRect().top() < 0


class TestRightClick:
    """Right-clicking an order edge is the only way in to what it is: it
    shows nothing and carries nothing, so there is nothing else to poke."""

    def test_right_clicking_one_asks_for_its_menu(self, qtbot, env):
        from flograph.ui.canvas import NodeGraphView
        graph, _stack, scene, a, b = env
        conn, _ = graph.connect(a.id, FLOW, b.id, FLOW)
        view = NodeGraphView(scene)
        qtbot.addWidget(view)
        wire = scene.connection_items[conn.id]
        asked: list = []
        view.order_context_requested.connect(
            lambda conn_id, _pos: asked.append(conn_id))
        _right_click(view, wire.path().pointAtPercent(0.5))
        assert asked == [conn.id]

    def test_right_clicking_a_data_wire_does_not(self, qtbot, env):
        from flograph.ui.canvas import NodeGraphView
        graph, _stack, scene, a, b = env
        conn, _ = graph.connect(a.id, "value", b.id, "in1")
        view = NodeGraphView(scene)
        qtbot.addWidget(view)
        wire = scene.connection_items[conn.id]
        asked: list = []
        view.order_context_requested.connect(
            lambda conn_id, _pos: asked.append(conn_id))
        _right_click(view, wire.path().pointAtPercent(0.5))
        assert asked == []


class TestHelp:
    def test_it_explains_the_things_that_are_not_obvious(self):
        html = order_edges_html("Q")
        for phrase in ("no data", "run that node first", "several",
                       "Delete", "Appearance"):
            assert phrase in html

    def test_it_names_the_key_that_is_actually_bound(self):
        assert "hold Q" in order_edges_html("Q")
        assert "hold F4" in order_edges_html("F4")

    def test_the_reveal_key_reads_as_the_user_would_say_it(self):
        assert reveal_key_name(Qt.Key_Q) == "Q"
        assert reveal_key_name(Qt.Key_F4) == "F4"

    def test_the_dialog_rewrites_itself_for_a_rebound_key(self, qtbot):
        from flograph.ui.canvas.order_help import OrderEdgeHelpDialog
        dialog = OrderEdgeHelpDialog(reveal_key="Q")
        qtbot.addWidget(dialog)
        assert "hold Q" in dialog._browser.toHtml()
        dialog.set_reveal_key("F4")
        assert "hold F4" in dialog._browser.toHtml()


def _right_click(view, scene_pos: QPointF) -> None:
    from PySide6.QtGui import QContextMenuEvent
    view.contextMenuEvent(QContextMenuEvent(
        QContextMenuEvent.Mouse, view.mapFromScene(scene_pos),
        view.viewport().mapToGlobal(view.mapFromScene(scene_pos))))
