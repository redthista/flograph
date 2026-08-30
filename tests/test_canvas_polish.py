"""M7: reroute insertion, frames, alignment, wire-drop palette plumbing."""
import pytest
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QUndoStack
from PySide6.QtWidgets import (QGraphicsItem, QGraphicsProxyWidget,
                               QInputDialog, QMenu, QWidget)

from flograph.core import Frame, Graph, NodeRegistry
from flograph.core.node import NodeStatus
from flograph.core.serialization import graph_from_dict, graph_to_dict
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


def out_x(width: float) -> float:
    """Where an output pin sits for a card of this width. Pins float clear
    of the node's edge rather than being centred on it — see PORT_EDGE_GAP."""
    from flograph.ui.canvas.node_item import PORT_EDGE_GAP, PortItem
    return width + PortItem.RADIUS + PORT_EDGE_GAP


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


class TestRerouteLabel:
    def test_labelless_by_default(self, env, registry):
        graph, stack, scene = env
        node = graph.add_node(registry.instantiate("flograph.util.reroute"))
        item = scene.node_items[node.id]

        assert node.label_override is None
        assert item._reroute_label_rect() is None
        # body plus whatever its pins need — no label extension beyond that
        expected = QRectF(-2, -2, item.width + 4, item.body_height + 4) \
            .united(item.childrenBoundingRect())
        assert item.boundingRect() == expected

    def test_label_expands_bounding_rect(self, env, registry):
        graph, stack, scene = env
        node = graph.add_node(registry.instantiate("flograph.util.reroute"))
        item = scene.node_items[node.id]

        graph.set_label(node.id, "Split point")
        label_rect = item._reroute_label_rect()
        assert label_rect is not None
        assert item.boundingRect().contains(label_rect)
        assert item.boundingRect().top() < -2  # grew upward to fit the pill above the dot

    def test_rename_dialog_unedited_stays_labelless(self, window, monkeypatch):
        node = window.registry.instantiate("flograph.util.reroute")
        window.graph.add_node(node)
        # simulate the user opening Rename and clicking OK without editing --
        # the dialog pre-fills with node.label (the resolved default), so an
        # unguarded commit would silently turn that default into an override
        monkeypatch.setattr(
            QInputDialog, "getText",
            staticmethod(lambda *a, **k: (k.get("text", ""), True)),
        )
        window._rename_node(node.id)
        assert node.label_override is None

    def test_description_tooltip_yields_to_error(self, env, registry):
        graph, stack, scene = env
        node = graph.add_node(registry.instantiate("flograph.util.reroute"))
        item = scene.node_items[node.id]
        assert item.toolTip() == ""

        graph.set_description(node.id, "splits the value stream")
        assert item.toolTip() == "splits the value stream"

        graph.set_status(node.id, NodeStatus.ERROR, "boom")
        assert item.toolTip() == "boom"

        graph.set_status(node.id, NodeStatus.IDLE, "")
        assert item.toolTip() == "splits the value stream"

    def test_an_error_shows_over_the_held_by_frame_note(self, env, registry):
        """A node held by a "run on ask" frame still errors when the frame is
        run — the frame-hold note must not take the slot the error needs."""
        graph, stack, scene = env
        node = graph.add_node(
            registry.instantiate("flograph.util.reroute", pos=(60.0, 60.0)))
        frame = graph.add_frame(
            Frame(id="f1", title="Block", rect=(0.0, 0.0, 400.0, 300.0)))
        graph.set_frame_run_flag(frame.id, "manual", True)
        item = scene.node_items[node.id]
        assert item.held_by_frame() is True
        assert "frame" in item.toolTip()          # held, nothing wrong yet

        graph.set_status(node.id, NodeStatus.ERROR, "Column 'x' not found")
        assert item.toolTip() == "Column 'x' not found"

        graph.set_status(node.id, NodeStatus.IDLE, "")
        assert "frame" in item.toolTip()          # back to the hold note

    def test_label_and_description_round_trip_serialization(self, registry):
        graph = Graph()
        node = graph.add_node(registry.instantiate("flograph.util.reroute"))
        graph.set_label(node.id, "Split point")
        graph.set_description(node.id, "splits the value stream")

        loaded = graph_from_dict(graph_to_dict(graph), registry)
        loaded_node = next(iter(loaded.nodes.values()))
        assert loaded_node.label_override == "Split point"
        assert loaded_node.description == "splits the value stream"

    def test_copy_paste_carries_label_and_description(self, window):
        node = window.registry.instantiate("flograph.util.reroute")
        window.graph.add_node(node)
        window.graph.set_label(node.id, "Split point")
        window.graph.set_description(node.id, "splits the value stream")

        window.scene.node_items[node.id].setSelected(True)
        payload = window._selection_payload()
        assert payload is not None
        entry = payload["nodes"][0]
        assert entry["label"] == "Split point"
        assert entry["description"] == "splits the value stream"

        window._insert_payload(payload)
        pasted = [n for n in window.graph.nodes.values() if n.id != node.id]
        assert len(pasted) == 1
        assert pasted[0].label_override == "Split point"
        assert pasted[0].description == "splits the value stream"


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
    """idea #21: a per-node, persisted toggle. Switching a card's canvas
    preview off *folds* it down to a plain icon (COMPACT_W square, category
    glyph) on the model canvas — Dashboard tiles are a separate rendering
    path and unaffected — without disturbing wireability."""

    def test_fold_hides_proxy_shrinks_to_icon_but_keeps_ports(self, env, registry):
        from flograph.ui.canvas.node_item import COMPACT_MIN_H, COMPACT_W
        from flograph.ui.commands import SetPreviewEnabledCommand
        graph, stack, scene = env
        node = graph.add_node(registry.instantiate("flograph.viz.show_table"))
        item = scene.node_items[node.id]
        proxy = item._table_viewer_proxy
        port = next(iter(item.input_ports.values()))
        open_width = item.width
        assert proxy.isVisible() and node.canvas_preview_enabled
        assert not item._folded and open_width > COMPACT_W

        stack.push(SetPreviewEnabledCommand(graph, node.id, False))
        assert not node.canvas_preview_enabled
        assert not proxy.isVisible()
        assert port.isVisible()  # still wireable, unlike LOD flattening
        assert item._folded and item._square
        assert item.width == COMPACT_W and item.body_height == COMPACT_MIN_H

        stack.undo()
        assert node.canvas_preview_enabled
        assert proxy.isVisible()
        assert not item._folded and item.width == open_width

    def test_header_chevron_folds_and_the_corner_chevron_opens(self, env, registry):
        graph, stack, scene = env
        node = graph.add_node(registry.instantiate("flograph.viz.show_plot"))
        item = scene.node_items[node.id]

        # open: chevron sits in the header bar
        header_rect = item._fold_toggle_rect()
        assert header_rect is not None and header_rect.top() < 20
        item.toggle_folded()
        assert item._folded and not node.canvas_preview_enabled

        # folded: chevron has moved into the icon's corner, still toggles back
        corner_rect = item._fold_toggle_rect()
        assert corner_rect is not None and corner_rect != header_rect
        item.toggle_folded()
        assert not item._folded and node.canvas_preview_enabled

        stack.undo()  # one undo entry per toggle
        assert item._folded

    def test_a_project_saved_folded_opens_folded(self, env, registry):
        from flograph.ui.canvas.node_item import COMPACT_W
        graph, stack, scene = env
        node = graph.add_node(registry.instantiate("flograph.viz.show_table"))
        graph.set_preview_enabled(node.id, False)

        reloaded = graph_from_dict(graph_to_dict(graph), registry)
        scene2 = NodeGraphScene(reloaded, QUndoStack(), registry=registry)
        item = scene2.node_items[next(iter(reloaded.nodes))]
        assert item._folded and item.width == COMPACT_W

    def test_a_plain_node_has_no_fold_chevron(self, env, registry):
        graph, stack, scene = env
        node = graph.add_node(registry.instantiate("flograph.transform.sort"))
        assert scene.node_items[node.id]._fold_toggle_rect() is None

    def test_the_chevron_reads_as_a_click_target_not_a_drag_bar(self, env, registry):
        graph, stack, scene = env
        node = graph.add_node(registry.instantiate("flograph.viz.show_plot"))
        item = scene.node_items[node.id]
        graph.set_preview_enabled(node.id, False)  # fold it

        chevron = item._fold_toggle_rect()
        assert item._hovering_a_chevron(chevron.center())   # → pointer cursor
        assert not item._hovering_a_chevron(QPointF(item.width / 2,
                                                    item.body_height / 2))

    def test_open_preview_is_offered_for_a_run_card(self, qtbot, window, registry, tmp_path):
        from PySide6.QtWidgets import QMenu
        csv = tmp_path / "d.csv"
        csv.write_text("x,y\n1,2\n2,4\n")
        reader = window.registry.instantiate("flograph.io.read_csv")
        table = window.registry.instantiate("flograph.viz.show_table")
        window.graph.add_node(reader)
        window.graph.add_node(table)
        window.graph.set_param(reader.id, "path", str(csv))
        window.graph.connect(reader.id, "table", table.id, "table")
        with qtbot.waitSignal(window.engine.run_finished, timeout=5000):
            window.engine.run_all()

        menu = QMenu()
        entries = window._add_view_actions(menu, table.id)
        assert [a.text() for a, _ in entries] == ["Open Preview"]
        assert entries[0][1] == "table"  # the card's rendered port

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

    def test_kpi_card_does_not_fold(self, env, registry):
        # a painted number already near icon size, nothing heavy to hide
        graph, stack, scene = env
        node = graph.add_node(registry.instantiate("flograph.viz.card"))
        assert not scene.node_items[node.id].foldable()

    def test_table_node_toggle_hides_grid_but_keeps_its_data(self, env, registry):
        """The Table node's spreadsheet is as expensive to paint as a
        chart/table-viewer card, so it gets the same toggle — but its data
        lives in params, not a recomputed cache entry, so disabling must
        never clear it (unlike figure/table_viewer/slicer)."""
        from flograph.ui.commands import SetPreviewEnabledCommand
        graph, stack, scene = env
        node = graph.add_node(registry.instantiate("flograph.io.table"))
        item = scene.node_items[node.id]
        proxy = item._table_proxy
        port = next(iter(item.output_ports.values()))
        assert proxy.isVisible() and node.canvas_preview_enabled

        stack.push(SetPreviewEnabledCommand(graph, node.id, False))
        assert not node.canvas_preview_enabled
        assert not proxy.isVisible()
        assert port.isVisible()  # still wireable
        assert item._table_model is not None  # data is not cleared

        stack.undo()
        assert node.canvas_preview_enabled
        assert proxy.isVisible()


class TestFlushPendingEdits:
    """issues.md #4: F5/Run Selected/Reset Caches/the run-node menu actions
    all read node.params synchronously, but Qt only commits a table cell's
    open editor on Tab/click-away/FocusOut — so a value just typed and not
    yet closed off was invisible to the very run meant to pick it up.
    _flush_pending_edits closes that gap by blurring a still-open editor
    (found via _focused_spreadsheet) before any of those actions run."""

    def test_flush_commits_an_open_cell_editor(self, window, qtbot):
        import json

        from flograph.ui.spreadsheet import SheetModel, SpreadsheetView

        grid = SpreadsheetView()
        model = SheetModel(json.dumps({
            "version": 2,
            "columns": [{"name": "A", "type": "auto"}],
            "rows": [[""]],
        }), parent=grid)
        grid.setModel(model)
        grid.show()
        qtbot.addWidget(grid)
        qtbot.waitExposed(grid)

        index = model.index(0, 0)
        grid.setCurrentIndex(index)
        grid.edit(index)
        qtbot.wait(20)
        editor = grid.viewport().focusWidget()
        assert editor is not None

        from PySide6.QtTest import QTest
        QTest.keyClicks(editor, "hello")
        assert model.cell_source(0, 0) == ""  # not committed yet

        window._flush_pending_edits()
        assert model.cell_source(0, 0) == "hello"

    def test_flush_is_a_no_op_without_an_open_editor(self, window):
        window._flush_pending_edits()  # must not raise


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
        assert port.pos().x() == out_x(item.width)
        graph.set_param(item.node.id, "width", 800)
        assert item.width == 800.0
        assert port.pos().x() == out_x(800.0)

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
        assert item.output_ports["figure"].pos().x() == out_x(item.width)
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
        assert item.output_ports["table"].pos().x() == out_x(700.0)
        graph, scene, item = self._card(env, registry, "flograph.io.table")
        graph.set_param(item.node.id, "width", 640)
        assert item.output_ports["table"].pos().x() == out_x(640.0)


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


class TestOutputPreviewFadesWhileRecomputing:
    """A chart or a data table on a card reads as current whatever the
    status LED beside it is doing, which on a slow flow means the previous
    run's numbers get read as this one's."""

    def table_viewer(self, window):
        node = window.registry.instantiate("flograph.viz.show_table")
        window.graph.add_node(node)
        return node, window.scene.node_items[node.id]

    def test_a_queued_rerun_fades_the_preview(self, window):
        node, item = self.table_viewer(window)
        assert item._table_viewer_proxy.opacity() == 1.0

        window.engine.request_run([node.id])
        assert item._table_viewer_proxy.opacity() < 1.0

    def test_the_fade_lifts_when_the_run_lands(self, qtbot, window):
        node, item = self.table_viewer(window)
        window.engine.request_run([node.id])
        with qtbot.waitSignal(window.engine.run_finished, timeout=5000):
            pass
        assert item._table_viewer_proxy.opacity() == 1.0

    def test_a_running_node_fades_the_preview(self, window):
        from flograph.core import NodeStatus
        node, item = self.table_viewer(window)
        window.graph.set_status(node.id, NodeStatus.RUNNING)
        assert item._table_viewer_proxy.opacity() < 1.0

        window.graph.set_status(node.id, NodeStatus.DONE)
        assert item._table_viewer_proxy.opacity() == 1.0

    def test_a_table_cards_grid_is_never_faded(self, window):
        """It is what the user types into, not what a run produces."""
        node = window.registry.instantiate("flograph.io.table")
        window.graph.add_node(node)
        item = window.scene.node_items[node.id]
        window.engine.request_run([node.id])
        assert item._table_proxy.opacity() == 1.0

    def test_only_the_cards_whose_answer_changed_are_touched(self, window):
        """A queued run covers most of a large graph; repainting every card
        for it is the wrong cost to pay for a fade."""
        nodes = []
        for _ in range(3):
            node = window.registry.instantiate("flograph.viz.show_table")
            window.graph.add_node(node)
            nodes.append(node)
        touched = []
        for node in nodes:
            item = window.scene.node_items[node.id]
            item.refresh_updating = (
                lambda nid=node.id: touched.append(nid))

        window.scene.set_requested_nodes({nodes[0].id, nodes[1].id})
        assert set(touched) == {nodes[0].id, nodes[1].id}

        touched.clear()
        window.scene.set_requested_nodes({nodes[1].id})   # only one moved
        assert touched == [nodes[0].id]


class TestWireBoundingRect:
    def test_bounding_rect_covers_the_pen(self, env, registry):
        """The wire paints up to 5px wide (hover/selection/splice hint) plus
        antialiasing; a bounding rect of the bare path leaves those fringe
        pixels outside every damage region, so moving a wire leaves faint
        skids until a zoom or pan forces a full repaint."""
        graph, _stack, scene = env
        a = graph.add_node(registry.instantiate("flograph.util.constant"))
        b = graph.add_node(registry.instantiate(
            "flograph.scripting.python_script"))
        graph.connect(a.id, "value", b.id, "in1")
        ci = next(iter(scene.connection_items.values()))
        padded = ci.boundingRect()
        bare = ci.path().boundingRect()
        assert padded.contains(bare.adjusted(-3.5, -3.5, 3.5, 3.5))


class TestNoStrayPins:
    def test_repeated_growth_leaves_no_pin_the_node_has_lost_track_of(
            self, env, registry):
        """Every PortItem on a node must be one the node still owns.

        A rebuild only removed the pins its dicts pointed at, so a pin the
        dict had dropped stayed parented forever — never laid out, so it
        drew at the node's origin: a connector floating off the top-left
        corner that no wire could reach and no redraw could clear.
        """
        from flograph.ui.canvas.node_item import PortItem

        graph, _stack, scene = env
        cat = graph.add_node(registry.instantiate(
            "flograph.transform.concatenate", pos=(400, 300)))
        src = graph.add_node(registry.instantiate("flograph.util.constant"))
        graph.connect(src.id, "value", cat.id, "top")
        for _ in range(3):
            graph.connect(src.id, "value", cat.id, "more")
        item = scene.node_items[cat.id]
        owned = {id(p) for p in (*item.input_ports.values(),
                                 *item.output_ports.values(),
                                 *item.flow_ports.values())}
        stray = [c for c in item.childItems()
                 if isinstance(c, PortItem) and id(c) not in owned]
        assert stray == []
        # and the pins that are left are the spec's, each once, in order
        assert list(item.input_ports) == [p.name for p in cat.spec.inputs]


class TestNodeBoundingRectCoversPins:
    def test_pins_live_inside_the_node_damage_rect(self, env, registry):
        """Pins hang outside the body by design, and the node's bounding
        rect is what a move damages. A pin outside it kept its old pixels
        behind on every drag — semi-circle skids until a zoom or pan."""
        graph, _stack, scene = env
        cat = graph.add_node(registry.instantiate(
            "flograph.transform.concatenate", pos=(400, 300)))
        src = graph.add_node(registry.instantiate("flograph.util.constant"))
        graph.connect(src.id, "value", cat.id, "top")
        graph.connect(src.id, "value", cat.id, "more")   # grows in3
        item = scene.node_items[cat.id]
        rect = item.boundingRect()
        for name in ("top", "bottom", "in3", "more"):
            pin = item.input_ports[name]
            assert rect.contains(item.mapRectFromItem(pin, pin.boundingRect()))
        out = item.output_ports["combined"]
        assert rect.contains(item.mapRectFromItem(out, out.boundingRect()))
        # the flow pins ride the corners, above the body — covered too
        flow = item.flow_ports["input"]
        assert rect.contains(item.mapRectFromItem(flow, flow.boundingRect()))


class TestBoundsIgnoreParkedPanels:
    """A card's bounds must describe the card.

    An embedded widget that owns a popup — the overflow menu of the toolbar
    inside a plot card — gets a proxy *panel* from Qt the first time that
    popup is shown, and it stays a child of the card afterwards, parked
    wherever it was last opened. Qt's childrenBoundingRect is recursive, so
    a 440x300 plot card reported bounds of 1450x3276: a giant invisible
    square in the minimap, and — since a card's shape() falls back to its
    bounding rect — half the canvas dragging a plot that looked normal.
    """

    def _card_with_a_popup(self, env, registry, park=QPointF(-1000, -3000)):
        graph, _stack, scene = env
        node = graph.add_node(registry.instantiate(
            "flograph.viz.show_table", pos=(0.0, 0.0)))
        item = scene.node_items[node.id]
        widget = QWidget()
        widget.resize(120, 80)
        menu = QMenu(widget)
        menu.addAction("something")
        proxy = QGraphicsProxyWidget(item)
        proxy.setWidget(widget)
        # Qt builds the panel the first time the popup is shown, and keeps it
        menu.show()
        menu.hide()
        panels = [c for c in proxy.childItems()
                  if c.flags() & QGraphicsItem.ItemIsPanel]
        assert panels, "Qt no longer parks a panel for an embedded popup"
        panels[0].setPos(park)
        return item, proxy, panels[0]

    def test_a_parked_panel_does_not_inflate_the_card(self, env, registry):
        item, _proxy, panel = self._card_with_a_popup(env, registry)
        # the recursive answer is enormous — that part is Qt's, and stands
        assert item.childrenBoundingRect().width() > 900
        rect = item.boundingRect()
        assert rect.width() < item.width + 200
        assert rect.height() < item.body_height + 200
        assert not rect.contains(panel.pos())

    def test_the_shape_is_the_card_too(self, env, registry):
        """The one that bit: a card's shape() is its bounding rect, so
        oversized bounds are oversized *clicks*."""
        item, _proxy, _panel = self._card_with_a_popup(env, registry)
        shape = item.shape().boundingRect()
        assert shape.width() < item.width + 200
        assert not shape.contains(QPointF(-900.0, -2900.0))

    def test_the_cheap_answer_is_still_used_when_it_is_sane(self, env,
                                                            registry):
        """No panel, nothing parked: the bounds are exactly Qt's recursive
        rect united with the body, as they always were."""
        graph, _stack, scene = env
        node = graph.add_node(registry.instantiate(
            "flograph.viz.show_table", pos=(0.0, 0.0)))
        item = scene.node_items[node.id]
        expected = QRectF(-2, -2, item.width + 4, item.body_height + 4) \
            .united(item.childrenBoundingRect())
        assert item.boundingRect() == expected

    def test_the_card_still_covers_its_own_children(self, env, registry):
        """The rule may not shrink the damage rect: a pin left outside it
        smears across the canvas on every drag."""
        item, proxy, _panel = self._card_with_a_popup(env, registry)
        rect = item.boundingRect()
        assert rect.contains(item.mapRectFromItem(proxy, proxy.boundingRect()))
        for port in list(item.input_ports.values()) + list(
                item.output_ports.values()):
            assert rect.contains(
                item.mapRectFromItem(port, port.boundingRect()))
