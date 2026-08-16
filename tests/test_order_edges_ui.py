"""The canvas side of order edges: the two flow pins on every node, dragging
one to another node, and the dashed arc that results."""
import pytest
from PySide6.QtCore import QPointF
from PySide6.QtGui import QUndoStack

from flograph.core import Graph, NodeRegistry
from flograph.ui.canvas import NodeGraphScene
from flograph.ui.canvas.connection_item import order_path
from flograph.ui.canvas.node_item import PortItem

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
