"""M7: reroute insertion, frames, alignment, wire-drop palette plumbing."""
import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QUndoStack

from flograph.core import Frame, Graph, NodeRegistry
from flograph.core.serialization import graph_to_dict
from flograph.ui.canvas import FrameItem, NodeGraphScene
from flograph.ui.commands import AddFrameCommand, RemoveFrameCommand, UpdateFrameCommand
from flograph.ui.mainwindow import MainWindow


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


@pytest.fixture
def window(qtbot, registry):
    win = MainWindow(registry)
    win.confirm_close = False
    qtbot.addWidget(win)
    return win


class TestReroute:
    def test_insert_reroute_splits_wire(self, env, registry):
        graph, stack, scene = env
        a = graph.add_node(registry.instantiate("flograph.util.constant"))
        b = graph.add_node(registry.instantiate("flograph.scripting.python_script"))
        conn, _ = graph.connect(a.id, "value", b.id, "in1")
        before = graph_to_dict(graph)

        scene.insert_reroute(conn, QPointF(100, 50))
        reroutes = [n for n in graph.nodes.values()
                    if n.type_id == "flograph.util.reroute"]
        assert len(reroutes) == 1
        assert len(graph.connections) == 2
        assert conn.id not in graph.connections
        # compact item rendering
        item = scene.node_items[reroutes[0].id]
        assert item.compact and item.width < 40

        # single undo step restores the original wire
        stack.undo()
        assert graph_to_dict(graph) == before

    def test_reroute_passes_value_through_engine(self, qtbot, env, registry):
        from flograph.engine import ExecutionEngine
        graph, stack, scene = env
        a = graph.add_node(registry.instantiate("flograph.util.constant"))
        graph.set_param(a.id, "kind", "int")
        graph.set_param(a.id, "value", "7")
        b = graph.add_node(registry.instantiate("flograph.scripting.python_script"))
        conn, _ = graph.connect(a.id, "value", b.id, "in1")
        scene.insert_reroute(conn, QPointF(0, 0))

        engine = ExecutionEngine(graph)
        with qtbot.waitSignal(engine.run_finished, timeout=5000):
            engine.run_all()
        assert engine.cache.outputs_for(b.id)["out1"] == 7


class TestZoomLOD:
    """Nodes flatten and hide ports/embedded widgets below DEFAULT_LOD_THRESHOLD to keep
    large graphs snappy zoomed out — and must restore fully on zoom back in."""

    def test_plain_node_ports_hide_and_restore(self, env, registry):
        from flograph.ui.canvas.node_item import DEFAULT_LOD_THRESHOLD
        graph, stack, scene = env
        node = graph.add_node(registry.instantiate("flograph.util.constant"))
        item = scene.node_items[node.id]
        port = next(iter(item.output_ports.values()))
        assert port.isVisible() and not item._flat

        scene.set_lod(DEFAULT_LOD_THRESHOLD - 0.05)
        assert item._flat
        assert not port.isVisible()

        scene.set_lod(1.0)
        assert not item._flat
        assert port.isVisible()

    def test_table_viewer_proxy_hides_and_restores(self, env, registry):
        from flograph.ui.canvas.node_item import DEFAULT_LOD_THRESHOLD
        graph, stack, scene = env
        node = graph.add_node(registry.instantiate("flograph.viz.show_table"))
        item = scene.node_items[node.id]
        proxy = item._table_viewer_proxy
        assert proxy is not None and proxy.isVisible()

        scene.set_lod(DEFAULT_LOD_THRESHOLD - 0.05)
        assert not proxy.isVisible()

        scene.set_lod(1.0)
        assert proxy.isVisible()

    def test_node_added_while_zoomed_out_starts_flat(self, env, registry):
        from flograph.ui.canvas.node_item import DEFAULT_LOD_THRESHOLD
        graph, stack, scene = env
        scene.set_lod(DEFAULT_LOD_THRESHOLD - 0.05)
        node = graph.add_node(registry.instantiate("flograph.util.constant"))
        item = scene.node_items[node.id]
        assert item._flat
        port = next(iter(item.output_ports.values()))
        assert not port.isVisible()

    def test_lod_disabled_never_flattens_regardless_of_zoom(self, env, registry):
        graph, stack, scene = env
        node = graph.add_node(registry.instantiate("flograph.util.constant"))
        item = scene.node_items[node.id]
        scene.lod_enabled = False

        scene.set_lod(0.01)  # as zoomed out as it gets
        assert not item._flat
        port = next(iter(item.output_ports.values()))
        assert port.isVisible()

    def test_custom_threshold_shifts_where_flattening_kicks_in(self, env, registry):
        graph, stack, scene = env
        node = graph.add_node(registry.instantiate("flograph.util.constant"))
        item = scene.node_items[node.id]
        scene.lod_threshold = 0.9  # much more aggressive than the default

        scene.set_lod(0.8)  # would stay full-detail at the default threshold
        assert item._flat

        scene.set_lod(0.95)
        assert not item._flat

    def test_refresh_lod_settings_applies_immediately_without_a_zoom_change(
            self, env, registry):
        """The whole point of a live Settings toggle: flipping lod_enabled
        or lod_threshold takes effect right away, not just on the next
        zoom — mirrors what MainWindow.set_lod_enabled/set_lod_threshold do
        after a Settings-dialog edit."""
        graph, stack, scene = env
        node = graph.add_node(registry.instantiate("flograph.util.constant"))
        item = scene.node_items[node.id]
        scene.set_lod(0.2)
        assert item._flat

        scene.lod_enabled = False
        scene.refresh_lod_settings()
        assert not item._flat


class TestPreviewToggle:
    """idea #21: a per-node, persisted toggle that hides a card's embedded
    preview widget on the model canvas (Dashboard tiles are unaffected —
    they're a separate rendering path) without disturbing wireability."""

    def test_toggle_hides_proxy_but_keeps_ports_and_geometry(self, env, registry):
        from flograph.ui.commands import SetPreviewEnabledCommand
        graph, stack, scene = env
        node = graph.add_node(registry.instantiate("flograph.viz.show_table"))
        item = scene.node_items[node.id]
        proxy = item._table_viewer_proxy
        port = next(iter(item.input_ports.values()))
        assert proxy.isVisible() and node.canvas_preview_enabled

        stack.push(SetPreviewEnabledCommand(graph, node.id, False))
        assert not node.canvas_preview_enabled
        assert not proxy.isVisible()
        assert port.isVisible()  # still wireable, unlike LOD flattening

        stack.undo()
        assert node.canvas_preview_enabled
        assert proxy.isVisible()

    def test_disabling_clears_held_widget_content(self, env, registry):
        from flograph.ui.commands import SetPreviewEnabledCommand
        graph, stack, scene = env
        node = graph.add_node(registry.instantiate("flograph.viz.show_plot"))
        item = scene.node_items[node.id]
        import matplotlib.figure
        item.set_figure(matplotlib.figure.Figure())
        assert item._figure_view.isVisible()

        stack.push(SetPreviewEnabledCommand(graph, node.id, False))
        assert item._figure_view._canvas is None  # matplotlib canvas released

    def test_serialization_round_trips_preview_flag(self, registry):
        from flograph.core.serialization import graph_from_dict, graph_to_dict
        graph = Graph()
        node = graph.add_node(registry.instantiate("flograph.viz.show_table"))
        graph.set_preview_enabled(node.id, False)

        data = graph_to_dict(graph)
        assert data["graph"]["nodes"][0]["preview"] is False

        reloaded = graph_from_dict(data, registry)
        assert reloaded.node(node.id).canvas_preview_enabled is False

    def test_old_save_files_without_the_key_default_to_enabled(self, registry):
        from flograph.core.serialization import graph_from_dict, graph_to_dict
        graph = Graph()
        node = graph.add_node(registry.instantiate("flograph.viz.show_table"))
        data = graph_to_dict(graph)
        del data["graph"]["nodes"][0]["preview"]  # simulate a pre-idea-21 file

        reloaded = graph_from_dict(data, registry)
        assert reloaded.node(node.id).canvas_preview_enabled is True

    def test_combines_with_lod_flattening_without_fighting_over_visibility(
            self, env, registry):
        from flograph.ui.canvas.node_item import DEFAULT_LOD_THRESHOLD
        graph, stack, scene = env
        node = graph.add_node(registry.instantiate("flograph.viz.show_table"))
        item = scene.node_items[node.id]
        proxy = item._table_viewer_proxy

        graph.set_preview_enabled(node.id, False)
        assert not proxy.isVisible()

        scene.set_lod(DEFAULT_LOD_THRESHOLD - 0.05)  # zoom out too
        assert not proxy.isVisible()
        scene.set_lod(1.0)  # zoom back in — still off, preview is disabled
        assert not proxy.isVisible()

        graph.set_preview_enabled(node.id, True)
        assert proxy.isVisible()  # zoom is full-detail, preview re-enabled

    def test_kpi_card_has_no_toggle_target(self, registry):
        from flograph.ui.canvas.node_item import PREVIEW_TOGGLABLE_KINDS, card_kind
        node = registry.instantiate("flograph.viz.card")
        assert card_kind(node) not in PREVIEW_TOGGLABLE_KINDS


class TestFrames:
    def test_frame_commands_round_trip(self, env):
        graph, stack, scene = env
        frame = Frame(id="f1", title="Stage", rect=(0, 0, 300, 200))
        stack.push(AddFrameCommand(graph, frame))
        assert "f1" in graph.frames and "f1" in scene.frame_items

        stack.push(UpdateFrameCommand(graph, "f1", title="Renamed",
                                      rect=(10, 10, 400, 250)))
        assert graph.frames["f1"].title == "Renamed"
        stack.undo()
        assert graph.frames["f1"].title == "Stage"
        assert graph.frames["f1"].rect == (0, 0, 300, 200)

        stack.push(RemoveFrameCommand(graph, "f1"))
        assert "f1" not in graph.frames and "f1" not in scene.frame_items
        stack.undo()
        assert "f1" in graph.frames and "f1" in scene.frame_items

    def test_push_frame_color_is_undoable(self, env):
        graph, stack, scene = env
        graph.add_frame(Frame(id="f1", title="Stage", color="#33415c"))
        scene.push_frame_color("f1", "#ff0000")
        assert graph.frames["f1"].color == "#ff0000"
        stack.undo()
        assert graph.frames["f1"].color == "#33415c"
        stack.redo()
        assert graph.frames["f1"].color == "#ff0000"

    def test_frame_serialization_round_trip(self, env, registry):
        from flograph.core.serialization import graph_from_dict
        graph, stack, scene = env
        graph.add_frame(Frame(id="f2", title="T", rect=(5, 5, 100, 80),
                              color="#112233"))
        data = graph_to_dict(graph)
        restored = graph_from_dict(data, registry)
        assert restored.frames["f2"].color == "#112233"

    def test_delete_selection_includes_frames(self, env):
        graph, stack, scene = env
        graph.add_frame(Frame(id="f3"))
        scene.frame_items["f3"].setSelected(True)
        scene.delete_selection()
        assert "f3" not in graph.frames
        stack.undo()
        assert "f3" in graph.frames


class TestAlignment:
    def test_align_left_and_distribute(self, window):
        reg = window.registry
        nodes = [reg.instantiate("flograph.util.constant", pos=(x, y))
                 for x, y in ((0, 0), (50, 100), (120, 260))]
        for n in nodes:
            window.graph.add_node(n)
        for item in window.scene.node_items.values():
            item.setSelected(True)

        window._align("left")
        assert all(n.pos[0] == 0 for n in nodes)

        window._align("dist_v")
        ys = sorted(n.pos[1] for n in nodes)
        assert ys[1] - ys[0] == pytest.approx(ys[2] - ys[1])

        window.undo_stack.undo()  # distribute
        window.undo_stack.undo()  # align
        assert nodes[1].pos == (50.0, 100.0)


class TestCardResize:
    """Ports must ride a card's right edge when it is resized (they used to
    be positioned once at build time and stay behind as the card grew)."""

    def _card(self, env, registry, type_id="flograph.viz.show_plot"):
        graph, stack, scene = env
        node = graph.add_node(registry.instantiate(type_id))
        return graph, scene, scene.node_items[node.id]

    def test_output_port_follows_width_param(self, env, registry):
        graph, scene, item = self._card(env, registry)
        port = item.output_ports["figure"]
        assert port.pos().x() == item.width
        graph.set_param(item.node.id, "width", 800)
        assert item.width == 800.0
        assert port.pos().x() == 800.0

    def test_output_port_follows_live_drag(self, env, registry):
        graph, scene, item = self._card(env, registry)
        scene.snap_enabled = False  # exercise raw drag math, not snapping
        item.setSelected(True)
        item._resizing_card = True
        item._resize_start = (0.0, 0.0, item.width, item.body_height)
        item._live_height = item.body_height

        class DragEvent:
            def scenePos(self):
                return QPointF(150.0, 40.0)  # +150 px wider

            def modifiers(self):
                return Qt.NoModifier

            def accept(self):
                pass

        start_width = item._resize_start[2]
        item.mouseMoveEvent(DragEvent())
        assert item.width == start_width + 150.0
        assert item.output_ports["figure"].pos().x() == item.width
        item._resizing_card = False
        item._live_height = None

    def test_wire_repaths_with_resized_card(self, env, registry):
        graph, scene, item = self._card(env, registry)
        sink = graph.add_node(
            registry.instantiate("flograph.scripting.python_script",
                                 pos=(900, 0)))
        graph.connect(item.node.id, "figure", sink.id, "in1")
        wire = next(iter(scene.connection_items.values()))
        start_x = wire.path().pointAtPercent(0).x()
        graph.set_param(item.node.id, "width", 800)
        assert wire.path().pointAtPercent(0).x() == start_x + (800 - 420)

    def test_show_table_and_table_cards_too(self, env, registry):
        graph, scene, item = self._card(env, registry, "flograph.viz.show_table")
        graph.set_param(item.node.id, "width", 700)
        assert item.output_ports["table"].pos().x() == 700.0
        graph, scene, item = self._card(env, registry, "flograph.io.table")
        graph.set_param(item.node.id, "width", 640)
        assert item.output_ports["table"].pos().x() == 640.0


class TestWireDropPalette:
    def test_wire_drop_offers_compatible_and_connects(self, window):
        reg = window.registry
        src = reg.instantiate("flograph.io.read_csv", pos=(0, 0))
        window.graph.add_node(src)
        port_item = window.scene.node_items[src.id].output_ports["table"]

        window._on_wire_dropped(port_item, QPointF(300, 0))
        # popup should be filtered to nodes with a dataframe-compatible input
        labels = [window._palette_popup._list.item(i).text()
                  for i in range(window._palette_popup._list.count())]
        assert any("Filter Rows" in l for l in labels)
        assert not any("Read CSV" in l for l in labels)  # no inputs
        window._palette_popup.hide()

        window._add_node_from_palette("flograph.transform.filter_rows")
        assert len(window.graph.nodes) == 2
        assert len(window.graph.connections) == 1
        conn = next(iter(window.graph.connections.values()))
        assert conn.src_node == src.id and conn.dst_port == "table"
        # one undo step for add+connect
        window.undo_stack.undo()
        assert len(window.graph.nodes) == 1 and not window.graph.connections


class TestFrameRunButton:
    def test_click_runs_and_sloppy_drag_does_not_move_the_frame(
            self, qtbot, env):
        """The run glyph acts like a button: emit on release inside it, and
        never let the press double as a frame drag — before this, a slightly
        sloppy click ran the frame AND dragged it, pushing a bogus undo
        entry built from stale press coordinates."""
        from PySide6.QtCore import QEvent, QPoint, Qt
        from PySide6.QtGui import QMouseEvent
        from PySide6.QtTest import QTest
        from PySide6.QtWidgets import QApplication

        from flograph.ui.canvas.view import NodeGraphView

        graph, stack, scene = env
        view = NodeGraphView(scene)
        qtbot.addWidget(view)
        view.resize(800, 600)
        view.show()

        graph.add_frame(Frame(id="fr", title="Stage", rect=(0, 0, 300, 200)))
        item = scene.frame_items["fr"]
        fired = []
        scene.frame_run_requested.connect(fired.append)

        btn = view.mapFromScene(
            item.mapToScene(item._run_button_rect().center()))
        QTest.mouseClick(view.viewport(), Qt.LeftButton, Qt.NoModifier, btn)
        assert fired == ["fr"]

        # press the button, drag off it, release: no run, no frame move
        away = btn + QPoint(80, 80)
        QTest.mousePress(view.viewport(), Qt.LeftButton, Qt.NoModifier, btn)
        QApplication.sendEvent(view.viewport(), QMouseEvent(
            QEvent.MouseMove, QPointF(away),
            view.viewport().mapToGlobal(QPointF(away)),
            Qt.NoButton, Qt.LeftButton, Qt.NoModifier))
        QTest.mouseRelease(view.viewport(), Qt.LeftButton, Qt.NoModifier, away)
        assert fired == ["fr"]
        assert item.pos() == QPointF(0, 0)
        assert stack.count() == 0


class TestCardMultiPortLayout:
    """A card-type node (figure/table/kpi/slicer) with more than one port on
    a side used to pin every one of them to the exact same header point —
    the wires still connected correctly, but the pins visually merged into
    what looked like a single port, with no way to tell which wire fed
    which parameter. See node_item.py's _space_header_ports."""

    TWO_INPUT_FIGURE_CARD = '''
NODE = {
    "label": "Two Input Figure",
    "category": "Viz",
    "card": "figure",
    "inputs": [("a", "dataframe"), ("b", "dataframe")],
    "outputs": [("figure", "figure")],
}
PARAMS = []
def run(ctx, a, b):
    return None
'''

    def test_two_input_figure_card_spaces_ports_apart(self, env):
        from flograph.core import NodeInstance, parse_spec

        graph, stack, scene = env
        spec = parse_spec(self.TWO_INPUT_FIGURE_CARD, "test.two_input_figure")
        node = graph.add_node(NodeInstance.create(spec))
        item = scene.node_items[node.id]
        assert item.figure_card
        assert len(item.input_ports) == 2

        positions = {name: port.pos().y()
                     for name, port in item.input_ports.items()}
        assert positions["a"] != positions["b"]
        assert abs(positions["a"] - positions["b"]) >= 11.0  # port diameter

    def test_single_input_card_port_position_is_unchanged(self, env, registry):
        graph, stack, scene = env
        node = graph.add_node(registry.instantiate("flograph.viz.show_table"))
        item = scene.node_items[node.id]
        assert item.table_viewer
        assert len(item.input_ports) == 1
        port = next(iter(item.input_ports.values()))
        from flograph.ui.canvas.node_item import HEADER_H
        assert port.pos().y() == HEADER_H / 2
