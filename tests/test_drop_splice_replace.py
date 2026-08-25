"""G4: dropping a node from the library onto a wire splices it in, and
dropping one onto an existing node replaces it, keeping the connections
that find a home on the new node. The green highlight under a drag is the
promise; these tests hold it to."""
import pytest
from PySide6.QtCore import QMimeData, QPoint, QPointF, Qt
from PySide6.QtGui import QDragLeaveEvent, QDragMoveEvent, QDropEvent, QUndoStack

from flograph.core import Graph, NodeInstance, NodeRegistry, parse_spec
from flograph.core.serialization import graph_to_dict
from flograph.ui.canvas import NodeGraphScene
from flograph.ui.canvas.palette import NODE_TYPE_MIME


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
    return graph, stack, scene


def snap(graph):
    """graph_to_dict with node/wire order canonicalised.

    A replace undoes by re-adding the old node, which lands at the end of
    the insertion-ordered dict — semantically exact but keyed in a new
    order, so a raw dict compare would fail on arrangement alone.
    """
    d = graph_to_dict(graph)
    d["graph"]["nodes"] = sorted(d["graph"]["nodes"], key=lambda n: n["id"])
    d["graph"]["connections"] = sorted(d["graph"]["connections"],
                                       key=lambda c: c["id"])
    return d


def wire(env, registry, src="flograph.util.constant",
         dst="flograph.scripting.python_script"):
    graph, stack, scene = env
    a = graph.add_node(registry.instantiate(src, pos=(0, 0)))
    b = graph.add_node(registry.instantiate(dst, pos=(400, 0)))
    conn, _ = graph.connect(a.id, "value", b.id, "in1")
    return a, b, conn


def wire_mid(scene, conn_id) -> QPointF:
    return scene.connection_items[conn_id].path().pointAtPercent(0.5)


def register_spec(registry: NodeRegistry, source: str, type_id: str):
    spec = parse_spec(source, type_id)
    registry.register(spec)
    return spec


OLD_TWO_OUT = '''
NODE = {"label": "Old Source", "category": "T",
        "inputs": [], "outputs": [("a", "number"), ("b", "number")]}
PARAMS = []
def run(ctx):
    return {}
'''
REORDERED_NEW = '''
NODE = {"label": "New Source", "category": "T",
        "inputs": [], "outputs": [("b", "number"), ("z", "number")]}
PARAMS = []
def run(ctx):
    return {}
'''
OLD_TWO_IN = '''
NODE = {"label": "Old Sink", "category": "T",
        "inputs": [("x", "number"), ("y", "number")], "outputs": []}
PARAMS = []
def run(ctx, x, y):
    return {}
'''
SWAPPED_NEW_SINK = '''
NODE = {"label": "New Sink", "category": "T",
        "inputs": [("y", "number"), ("w", "number")], "outputs": []}
PARAMS = []
def run(ctx, y, w):
    return {}
'''
NUMBER_SINK = '''
NODE = {"label": "Sink", "category": "T",
        "inputs": [("v", "number")], "outputs": []}
PARAMS = []
def run(ctx, v):
    return {}
'''
NUMBER_SOURCE = '''
NODE = {"label": "Source", "category": "T",
        "inputs": [], "outputs": [("out", "number")]}
PARAMS = []
def run(ctx):
    return {}
'''


class TestDropTargetAt:
    def test_wire_under_cursor_is_a_splice_target(self, env, registry):
        graph, stack, scene = env
        _a, _b, conn = wire(env, registry)
        kind, item = scene.drop_target_at(
            "flograph.transform.filter_rows", wire_mid(scene, conn.id))
        assert kind == "wire"
        assert item.conn.id == conn.id

    def test_node_under_cursor_is_a_replace_target(self, env, registry):
        graph, stack, scene = env
        _a, b, _conn = wire(env, registry)
        body = scene.node_items[b.id].sceneBoundingRect().center()
        kind, item = scene.drop_target_at(
            "flograph.transform.filter_rows", body)
        assert kind == "node"
        assert item.node.id == b.id

    def test_order_edges_are_never_targets(self, env, registry):
        graph, stack, scene = env
        a = graph.add_node(registry.instantiate("flograph.util.constant"))
        b = graph.add_node(registry.instantiate("flograph.util.constant",
                                                pos=(300, 0)))
        graph.connect(a.id, "flow", b.id, "flow")
        order_item = next(iter(scene.connection_items.values()))
        assert scene.drop_target_at(
            "flograph.scripting.python_script",
            order_item.path().pointAtPercent(0.5)) is None

    def test_type_that_cannot_take_the_upstream_end_gives_none(
            self, env, registry):
        graph, stack, scene = env
        _a, _b, conn = wire(env, registry)
        # read_csv has no inputs, so the upstream end has nowhere to land —
        # and a half-splice would cut the very flow it was joining
        assert scene.drop_target_at("flograph.io.read_csv",
                                    wire_mid(scene, conn.id)) is None

    def test_unknown_type_gives_none(self, env, registry):
        graph, stack, scene = env
        assert scene.drop_target_at("no.such.type", QPointF(10, 10)) is None

    def test_hint_follows_target_and_clears(self, env, registry):
        graph, stack, scene = env
        _a, _b, conn = wire(env, registry)
        item = scene.connection_items[conn.id]
        mid = wire_mid(scene, conn.id)

        scene.set_drop_hint(scene.drop_target_at(
            "flograph.transform.filter_rows", mid))
        assert scene._drop_hint_conn is item

        scene.set_drop_hint(None)
        assert scene._drop_hint_conn is None
        assert not item._drop_hint

    def test_locked_node_is_transparent_to_targeting(self, env, registry):
        """A locked node refuses replacement, so aiming at it must not ring
        it — the highlight would promise something the drop won't do."""
        graph, stack, scene = env
        _a, b, _conn = wire(env, registry)
        graph.set_locked(b.id, True)
        body = scene.node_items[b.id].sceneBoundingRect().center()
        assert scene.drop_target_at(
            "flograph.scripting.python_script", body) is None


class TestSpliceIntoWire:
    def test_splice_splits_wire_and_rewires_both_ends(self, env, registry):
        graph, stack, scene = env
        a, b, conn = wire(env, registry)

        assert scene.splice_into_wire(
            "flograph.transform.filter_rows", conn.id, QPointF(230, 40))

        filters = [n for n in graph.nodes.values()
                   if n.type_id == "flograph.transform.filter_rows"]
        assert len(filters) == 1
        new = filters[0]
        assert len(graph.connections) == 2
        assert conn.id not in graph.connections
        feeds = [c for c in graph.connections.values()
                 if c.dst_node == new.id]
        drains = [c for c in graph.connections.values()
                  if c.src_node == new.id]
        assert [(c.src_node, c.src_port) for c in feeds] == [(a.id, "value")]
        assert feeds[0].dst_port == "table"
        assert [(c.dst_node, c.dst_port) for c in drains] == [(b.id, "in1")]
        assert drains[0].src_port == "filtered"
        assert new.pos == (230.0, 40.0)

    def test_one_undo_step_restores_the_original_wire(self, env, registry):
        graph, stack, scene = env
        _a, _b, conn = wire(env, registry)
        before = snap(graph)
        scene.splice_into_wire("flograph.transform.filter_rows", conn.id,
                               QPointF(200, 30))
        stack.undo()
        assert snap(graph) == before
        stack.redo()
        assert len(graph.connections) == 2
        stack.undo()

    def test_splice_falls_back_when_nothing_fits(self, env, registry):
        graph, stack, scene = env
        _a, _b, conn = wire(env, registry)
        before = snap(graph)
        # read_csv has no inputs, so the upstream end has nowhere to land
        assert scene.splice_into_wire(
            "flograph.io.read_csv", conn.id, QPointF(200, 30)) is False
        assert snap(graph) == before

    def test_unknown_connection_id_is_a_no(self, env, registry):
        graph, stack, scene = env
        assert scene.splice_into_wire(
            "flograph.util.constant", "nope", QPointF(0, 0)) is False

    def test_spliced_flow_runs_through_the_engine(self, qtbot, env, registry):
        from flograph.engine import ExecutionEngine
        graph, stack, scene = env
        a, b, conn = wire(env, registry)
        graph.set_param(a.id, "kind", "int")
        graph.set_param(a.id, "value", "7")
        scene.splice_into_wire("flograph.scripting.python_script", conn.id,
                               QPointF(200, 0))
        engine = ExecutionEngine(graph)
        with qtbot.waitSignal(engine.run_finished, timeout=5000):
            engine.run_all()
        assert engine.cache.outputs_for(b.id)["out1"] == 7


class TestReplaceNode:
    def test_replace_keeps_wires_that_find_a_home(self, env, registry):
        graph, stack, scene = env
        a = graph.add_node(registry.instantiate("flograph.io.read_csv",
                                                pos=(0, 0)))
        b = graph.add_node(registry.instantiate("flograph.io.read_csv",
                                                pos=(0, 300)))
        cat = graph.add_node(registry.instantiate(
            "flograph.transform.concatenate", pos=(400, 0)))
        out = graph.add_node(registry.instantiate("flograph.viz.show_table",
                                                  pos=(800, 0)))
        g_top, _ = graph.connect(a.id, "table", cat.id, "top")
        g_bottom, _ = graph.connect(b.id, "table", cat.id, "bottom")

        # filter_rows has one dataframe input: the top wire fits, the bottom
        # one has no home, and the outgoing wire follows the node across
        assert scene.replace_node_with("flograph.transform.filter_rows",
                                       cat.id)
        new = [n for n in graph.nodes.values()
               if n.type_id == "flograph.transform.filter_rows"][0]
        assert cat.id not in graph.nodes
        pairs = {(c.src_node, c.src_port, c.dst_node, c.dst_port)
                 for c in graph.connections.values()}
        assert (a.id, "table", new.id, "table") in pairs
        assert all(c.dst_node != cat.id and c.src_node != cat.id
                   for c in graph.connections.values())
        assert g_bottom.id not in graph.connections   # no home, cut cleanly
        assert g_top.id not in graph.connections      # re-made, not reused
        assert len(graph.connections) == 1
        assert new.pos == cat.pos

    def test_one_undo_step_restores_the_original_node(self, env, registry):
        graph, stack, scene = env
        _a, _b, conn = wire(env, registry)
        target_id = conn.dst_node
        graph.set_label(target_id, "My script")
        before = snap(graph)
        scene.replace_node_with("flograph.transform.filter_rows", target_id)
        stack.undo()
        assert snap(graph) == before
        assert graph.node(target_id).label_override == "My script"
        stack.redo()
        assert target_id not in graph.nodes
        stack.undo()

    def test_label_override_carries_over(self, env, registry):
        graph, stack, scene = env
        _a, _b, conn = wire(env, registry)
        target_id = conn.dst_node
        graph.set_label(target_id, "Pass-through")
        scene.replace_node_with("flograph.transform.filter_rows", target_id)
        new = [n for n in graph.nodes.values()
               if n.type_id == "flograph.transform.filter_rows"][0]
        assert new.label_override == "Pass-through"

    def test_output_names_prefer_their_own_port(self, env, registry):
        """Name matches are reserved across every wire first, so whichever
        wire came first in the dict cannot steal the port another wire is
        named for."""
        graph, stack, scene = env
        old = register_spec(registry, OLD_TWO_OUT, "test.old_two_out")
        new = register_spec(registry, REORDERED_NEW, "test.reordered_new")
        sink_a = register_spec(registry, NUMBER_SINK, "test.sink_a")
        sink_b = register_spec(registry, NUMBER_SINK, "test.sink_b")

        o = graph.add_node(NodeInstance.create(old, pos=(0, 0)))
        sa = graph.add_node(NodeInstance.create(sink_a, pos=(400, -100)))
        sb = graph.add_node(NodeInstance.create(sink_b, pos=(400, 100)))
        graph.connect(o.id, "a", sa.id, "v")
        graph.connect(o.id, "b", sb.id, "v")

        assert scene.replace_node_with(new.type_id, o.id)
        by_consumer = {c.dst_node: c.src_port
                       for c in graph.connections.values()}
        # 'a' finds nothing of its own and falls back; 'b' keeps its own
        # name because the fallback went second
        assert by_consumer[sa.id] == "z"
        assert by_consumer[sb.id] == "b"

    def test_input_names_prefer_their_own_port(self, env, registry):
        graph, stack, scene = env
        src = register_spec(registry, NUMBER_SOURCE, "test.num_src")
        old = register_spec(registry, OLD_TWO_IN, "test.old_two_in")
        new = register_spec(registry, SWAPPED_NEW_SINK, "test.swapped_new")

        s1 = graph.add_node(NodeInstance.create(src, pos=(0, -100)))
        s2 = graph.add_node(NodeInstance.create(src, pos=(0, 100)))
        o = graph.add_node(NodeInstance.create(old, pos=(400, 0)))
        graph.connect(s1.id, "out", o.id, "x")
        graph.connect(s2.id, "out", o.id, "y")

        assert scene.replace_node_with(new.type_id, o.id)
        by_source = {c.src_node: c.dst_port
                     for c in graph.connections.values()}
        # s2 asked for 'y' by name and keeps it even though s1's fallback
        # would otherwise have claimed the first free port for itself
        assert by_source[s2.id] == "y"
        assert by_source[s1.id] == "w"

    def test_order_edges_survive_replacement(self, env, registry):
        graph, stack, scene = env
        src = register_spec(registry, NUMBER_SOURCE, "test.ord_src")
        sink = register_spec(registry, NUMBER_SINK, "test.ord_sink")
        o = graph.add_node(NodeInstance.create(src, pos=(0, 0)))
        pre = graph.add_node(registry.instantiate("flograph.util.constant",
                                                  pos=(-400, 0)))
        post = graph.add_node(registry.instantiate("flograph.util.constant",
                                                   pos=(400, 0)))
        graph.connect(pre.id, "flow", o.id, "flow")     # runs before old
        graph.connect(o.id, "flow", post.id, "flow")    # ...and after it

        assert scene.replace_node_with(sink.type_id, o.id)
        new = next(n for n in graph.nodes.values() if n.type_id == sink.type_id)
        flows = [c for c in graph.connections.values()
                 if new.id in (c.src_node, c.dst_node)]
        assert len(flows) == 2
        assert all(c.src_port == "flow" and c.dst_port == "flow"
                   for c in flows)
        assert {(c.src_node, c.dst_node) for c in flows} == \
            {(pre.id, new.id), (new.id, post.id)}
        assert all(c.src_node != o.id and c.dst_node != o.id
                   for c in graph.connections.values())

    def test_locked_refuses(self, env, registry):
        graph, stack, scene = env
        _a, _b, conn = wire(env, registry)
        target_id = conn.dst_node
        graph.set_locked(target_id, True)
        before = snap(graph)
        assert scene.replace_node_with(
            "flograph.transform.filter_rows", target_id) is False
        assert snap(graph) == before

    def test_unknown_or_missing_targets_refuse(self, env, registry):
        graph, stack, scene = env
        _a, _b, conn = wire(env, registry)
        assert scene.replace_node_with("flograph.util.constant",
                                       "no-such-node") is False
        assert scene.replace_node_with("no.such.type",
                                       conn.dst_node) is False


class TestViewRouting:
    @pytest.fixture
    def routed(self, qtbot, env):
        from flograph.ui.canvas.view import NodeGraphView
        graph, stack, scene = env
        v = NodeGraphView(scene)
        qtbot.addWidget(v)
        return v, scene, stack

    def _mime_event(self, view, scene_pos, type_id: bytes,
                    modifiers=Qt.NoModifier, move=False):
        point = view.mapFromScene(scene_pos)
        mime = QMimeData()
        mime.setData(NODE_TYPE_MIME, type_id)
        cls = QDragMoveEvent if move else QDropEvent
        # QDragMoveEvent takes a QPoint, not a QPointF
        event = cls(QPoint(point.x(), point.y()), Qt.CopyAction, mime,
                    Qt.LeftButton, modifiers)
        # Qt does not take ownership of the mime data: once this helper's
        # own reference is collected the event would point at freed memory
        # and the next mimeData() call would segfault.
        refs = getattr(self, "_live_mimes", [])
        refs.append(mime)
        self._live_mimes = refs
        return event

    def test_drop_on_wire_splices(self, routed, registry):
        v, scene, stack = routed
        graph = scene.graph
        a = graph.add_node(registry.instantiate("flograph.util.constant"))
        b = graph.add_node(registry.instantiate(
            "flograph.scripting.python_script", pos=(400, 0)))
        conn, _ = graph.connect(a.id, "value", b.id, "in1")

        event = self._mime_event(v, wire_mid(scene, conn.id),
                                 b"flograph.transform.filter_rows")
        v.dropEvent(event)

        assert any(n.type_id == "flograph.transform.filter_rows"
                   for n in graph.nodes.values())
        assert len(graph.connections) == 2
        assert conn.id not in graph.connections
        stack.undo()
        assert len(graph.connections) == 1 and conn.id in graph.connections

    def test_alt_drop_places_past_the_aiming(self, routed, registry):
        v, scene, _stack = routed
        graph = scene.graph
        a = graph.add_node(registry.instantiate("flograph.util.constant"))
        b = graph.add_node(registry.instantiate(
            "flograph.scripting.python_script", pos=(400, 0)))
        conn, _ = graph.connect(a.id, "value", b.id, "in1")
        dropped = []
        v.node_dropped.connect(lambda t, p: dropped.append((t, p)))

        event = self._mime_event(v, wire_mid(scene, conn.id),
                                 b"flograph.transform.filter_rows",
                                 modifiers=Qt.AltModifier)
        v.dropEvent(event)

        # plain add beside the wire: nothing spliced, nothing displaced —
        # the view hands off to the ordinary node_dropped path
        assert conn.id in graph.connections
        assert len(graph.connections) == 1
        assert [t for t, _p in dropped] == \
            ["flograph.transform.filter_rows"]

    def test_drag_move_lights_and_clears_the_hint(self, routed, registry):
        v, scene, _stack = routed
        graph = scene.graph
        a = graph.add_node(registry.instantiate("flograph.util.constant"))
        b = graph.add_node(registry.instantiate(
            "flograph.scripting.python_script", pos=(400, 0)))
        conn, _ = graph.connect(a.id, "value", b.id, "in1")
        item = scene.connection_items[conn.id]
        mid = wire_mid(scene, conn.id)

        v.dragMoveEvent(self._mime_event(v, mid,
                                         b"flograph.transform.filter_rows",
                                         move=True))
        assert scene._drop_hint_conn is item

        v.dragMoveEvent(self._mime_event(v, QPointF(5000, 5000),
                                         b"flograph.transform.filter_rows",
                                         move=True))
        assert scene._drop_hint_conn is None

        v.dragMoveEvent(self._mime_event(v, mid,
                                         b"flograph.transform.filter_rows",
                                         move=True))
        assert scene._drop_hint_conn is item
        v.dragLeaveEvent(QDragLeaveEvent())
        assert scene._drop_hint_conn is None
