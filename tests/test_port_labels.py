"""Card ports: spacing when there are several, and floating name pills.

Reported 2026-07-26: "on nodes where i specify more than one input, it starts
to bunch up, so report node as an example has 4 and they are really bunched
up". They were: four 11px pins spaced 6px apart inside a 26px header, so
each overlapped its neighbour by 5px — indistinguishable, and a lottery to
grab the one you wanted.

Two changes here. The spacing is a fix (ports run down the card's edge at
ROW_H, like an ordinary node's rows). The name pills are a feature, off by
default, settable canvas-wide *and* per node.
"""
from __future__ import annotations

import pytest
from PySide6.QtGui import QUndoStack

from flograph.core import Graph, NodeRegistry
from flograph.ui.canvas import NodeGraphScene
from flograph.ui.canvas.node_item import (
    HEADER_H, PORT_EDGE_GAP, PortItem, ROW_H, port_labels_on,
)


@pytest.fixture(scope="module")
def registry():
    reg = NodeRegistry()
    reg.load_builtins()
    return reg


@pytest.fixture
def scene(qtbot, registry):
    graph = Graph()
    return graph, NodeGraphScene(graph, QUndoStack(), registry=registry)


def report_card(scene, registry):
    graph, sc = scene
    node = graph.add_node(registry.instantiate("flograph.viz.report_card"))
    return node, sc.node_items[node.id]


def many_input_card(scene, registry, count: int = 20):
    """A fork of the Report card carrying `count` inputs — the "small node
    with 20 inputs" case, which no built-in has."""
    from flograph.core import NodeInstance
    from flograph.core.script import parse_spec
    graph, sc = scene
    source = registry.get("flograph.viz.report_card").source
    ports = ", ".join(f'("in{i}", "any", {{"optional": True}})'
                      for i in range(count))
    source = source.replace(
        '"inputs": [("a", "any", {"optional": True}),',
        f'"inputs": [{ports}, ("zz", "any", {{"optional": True}}),', 1)
    node = graph.add_node(
        NodeInstance.create(parse_spec(source, "user.many_ports")))
    item = sc.node_items[node.id]
    # keep exactly `count` inputs so the arithmetic in tests is obvious
    for extra in list(item.input_ports):
        if not extra.startswith("in"):
            item.input_ports.pop(extra).setParentItem(None)
    item._layout_ports()
    return node, item


def input_ys(item) -> list[float]:
    return sorted(p.pos().y() for p in item.input_ports.values())


# ---------------------------------------------------------------- spacing

class TestPortsNoLongerBunch:

    def test_four_inputs_are_a_port_apart(self, scene, registry):
        """The reported bug. Anything less than a diameter apart and two
        pins are one blob."""
        _node, item = report_card(scene, registry)
        gaps = [b - a for a, b in zip(input_ys(item), input_ys(item)[1:])]
        assert gaps == [ROW_H, ROW_H, ROW_H]
        assert min(gaps) > PortItem.RADIUS * 2

    def test_they_start_in_the_header_however_many_there_are(self, scene,
                                                             registry):
        """Reported on the first cut: "when there is one the connector is in
        the node header, when there is more than one its in the node body,
        can we always start from the node header". The first pin now lands
        where a single-port card has always put it, so a second input
        doesn't make the whole row jump."""
        _node, item = report_card(scene, registry)
        assert input_ys(item)[0] == HEADER_H / 2

    def test_a_single_port_still_sits_in_the_header(self, scene, registry):
        """Every card in every existing project has one port a side, and
        must look exactly as it did."""
        graph, sc = scene
        node = graph.add_node(registry.instantiate("flograph.viz.show_plot"))
        item = sc.node_items[node.id]
        assert len(item.input_ports) == 1
        assert list(item.input_ports.values())[0].pos().y() == HEADER_H / 2

    def test_pins_float_clear_of_the_node(self, scene, registry):
        """Reported: "can we move them so they float a few px outside of the
        node and node body? i think this will look cleaner". They used to be
        centred on the edge, so half of every pin was buried under the
        card."""
        _node, item = report_card(scene, registry)
        gap = PortItem.RADIUS + PORT_EDGE_GAP
        assert all(p.pos().x() == -gap for p in item.input_ports.values())
        assert all(p.pos().x() == item.width + gap
                   for p in item.output_ports.values())

    def test_a_reroute_keeps_its_pins_on_its_own_centre(self, scene,
                                                        registry):
        """A reroute *is* a pin — nudging its ports outward would only
        smear the dot."""
        graph, sc = scene
        node = graph.add_node(registry.instantiate("flograph.util.reroute"))
        item = sc.node_items[node.id]
        assert list(item.input_ports.values())[0].pos().x() == 0

    def test_a_short_card_keeps_its_spacing(self, scene, registry):
        node, item = report_card(scene, registry)
        node.params["height"] = 60
        item.on_params_changed()
        ys = input_ys(item)
        assert [b - a for a, b in zip(ys, ys[1:])] == [ROW_H] * 3

    def test_a_node_with_many_inputs_runs_its_pins_onto_the_canvas(
            self, scene, registry):
        """Reported: "if i have a small node with 20inputs i want it to just
        force its way onto the sheet". Compressing to fit is how the pins
        overlapped in the first place — at twenty ports it would be far
        worse. Collapse is the answer to a node that outgrows its card."""
        node, item = many_input_card(scene, registry, count=20)
        node.params["height"] = 140
        item.on_params_changed()
        ys = input_ys(item)
        assert [b - a for a, b in zip(ys, ys[1:])] == [ROW_H] * 19
        assert max(ys) > item.body_height       # runs onto the canvas

    def test_ports_follow_a_resize(self, scene, registry):
        node, item = report_card(scene, registry)
        node.params["width"] = 700
        item.on_params_changed()
        expected = item.width + PortItem.RADIUS + PORT_EDGE_GAP
        assert all(p.pos().x() == expected
                   for p in item.output_ports.values())


# ----------------------------------------------------------------- labels

class TestFloatingPortNames:

    def test_off_by_default(self, scene, registry):
        _node, item = report_card(scene, registry)
        port = item.input_ports["a"]
        assert port._label_rect() is None

    def test_the_canvas_setting_turns_them_on(self, scene, registry):
        _graph, sc = scene
        _node, item = report_card(scene, registry)
        sc.set_port_labels_enabled(True)
        assert item.input_ports["a"]._label_rect() is not None

    def test_an_input_label_sits_outside_the_node(self, scene, registry):
        """Left for inputs, right for outputs — so a name never covers the
        card's content, which on a report card is the text being written."""
        _graph, sc = scene
        _node, item = report_card(scene, registry)
        sc.set_port_labels_enabled(True)
        assert item.input_ports["a"]._label_rect().right() < 0
        assert item.output_ports["text"]._label_rect().left() > 0

    def test_the_pin_grows_its_bounding_rect_to_fit(self, scene, registry):
        """Qt indexes items by bounding rect; a pill painted outside it
        would be clipped and would leave smears when it changed."""
        _graph, sc = scene
        _node, item = report_card(scene, registry)
        port = item.input_ports["a"]
        before = port.boundingRect()
        sc.set_port_labels_enabled(True)
        assert port.boundingRect().width() > before.width()

    def test_hidden_while_the_canvas_is_flattened(self, scene, registry):
        """Zoomed out the pins aren't drawn at all, so their names would be
        labels for nothing."""
        _graph, sc = scene
        _node, item = report_card(scene, registry)
        sc.set_port_labels_enabled(True)
        item.set_lod(True)
        assert item.input_ports["a"]._label_rect() is None

    def test_a_wider_name_gets_a_wider_pill(self, scene, registry):
        _graph, sc = scene
        sc.set_port_labels_enabled(True)
        _node, item = report_card(scene, registry)
        assert (item.output_ports["text"]._label_rect().width()
                > item.input_ports["a"]._label_rect().width())


# -------------------------------------------------------- the per-node bit

class TestPerNodeOverride:
    """Reported: "as well as settings for all nodes, let me right click a node
    to show input output labels"."""

    def test_a_node_follows_the_canvas_by_default(self, scene, registry):
        _graph, sc = scene
        node, _item = report_card(scene, registry)
        assert node.port_labels is None
        assert not port_labels_on(node, sc)
        sc.set_port_labels_enabled(True)
        assert port_labels_on(node, sc)

    def test_an_override_beats_the_canvas_setting(self, scene, registry):
        graph, sc = scene
        node, item = report_card(scene, registry)
        graph.set_port_labels(node.id, True)
        assert port_labels_on(node, sc)          # canvas-wide is still off
        assert item.input_ports["a"]._label_rect() is not None

        sc.set_port_labels_enabled(True)
        graph.set_port_labels(node.id, False)
        assert not port_labels_on(node, sc)      # ...and hides against it too

    def test_the_canvas_setting_still_moves_untouched_nodes(self, scene,
                                                            registry):
        """The reason the override is tri-state rather than a plain bool:
        singling one node out must not deafen every other node to the
        global switch."""
        graph, sc = scene
        pinned, _ = report_card(scene, registry)
        other, other_item = report_card(scene, registry)
        graph.set_port_labels(pinned.id, False)
        sc.set_port_labels_enabled(True)
        assert other_item.input_ports["a"]._label_rect() is not None
        assert not port_labels_on(pinned, sc)

    def test_it_survives_a_save_and_reload(self, scene, registry):
        from flograph.core.serialization import graph_from_dict, graph_to_dict
        graph, _sc = scene
        node, _item = report_card(scene, registry)
        graph.set_port_labels(node.id, True)
        reloaded = graph_from_dict(graph_to_dict(graph), registry)
        assert reloaded.nodes[node.id].port_labels is True

    def test_a_file_written_before_this_existed_follows_the_canvas(
            self, scene, registry):
        from flograph.core.serialization import graph_from_dict, graph_to_dict
        graph, sc = scene
        node, _item = report_card(scene, registry)
        data = graph_to_dict(graph)
        for entry in data["graph"]["nodes"]:
            entry.pop("port_labels", None)      # as an older flograph wrote it
        reloaded = graph_from_dict(data, registry)
        assert reloaded.nodes[node.id].port_labels is None
        assert not port_labels_on(reloaded.nodes[node.id], sc)


class TestCollapsingPorts:
    """Reported: "we could keep its positioning and add a 'dropdown' toggle
    that collapses all the inputs to a single one in the header. and then i
    can expand and see they spaced out ... by default have everyhting
    expanded"."""

    def test_expanded_by_default(self, scene, registry):
        node, item = report_card(scene, registry)
        assert node.ports_collapsed is False
        assert all(p.isVisible() for p in item.input_ports.values())

    def test_collapsing_leaves_one_pin_in_the_header(self, scene, registry):
        graph, _sc = scene
        node, item = report_card(scene, registry)
        graph.set_ports_collapsed(node.id, True)
        visible = [p for p in item.input_ports.values() if p.isVisible()]
        assert len(visible) == 1
        assert visible[0].pos().y() == HEADER_H / 2

    def test_every_wire_still_reaches_the_node(self, scene, registry):
        """The connections are untouched — collapsing is a drawing change,
        so all four wires converge on the one pin rather than vanishing."""
        graph, sc = scene
        node, item = report_card(scene, registry)
        feed = graph.add_node(registry.instantiate("flograph.util.constant"))
        graph.connect(feed.id, "value", node.id, "c")
        graph.set_ports_collapsed(node.id, True)
        assert len(graph.connections) == 1
        assert item.input_ports["c"].pos().y() == HEADER_H / 2

    def test_expanding_puts_them_back(self, scene, registry):
        graph, _sc = scene
        node, item = report_card(scene, registry)
        before = input_ys(item)
        graph.set_ports_collapsed(node.id, True)
        graph.set_ports_collapsed(node.id, False)
        assert input_ys(item) == before
        assert all(p.isVisible() for p in item.input_ports.values())

    def test_the_collapsed_pin_s_label_counts_rather_than_naming(
            self, scene, registry):
        """Reported: "when collapsing nodes with the labels enabled, it shows
        the first node name still, this could be confusing". It read as
        though that were the only port there is."""
        graph, sc = scene
        node, item = report_card(scene, registry)
        sc.set_port_labels_enabled(True)
        assert item.input_ports["a"].label_text() == "a"
        graph.set_ports_collapsed(node.id, True)
        assert item.input_ports["a"].label_text() == "4 inputs"
        graph.set_ports_collapsed(node.id, False)
        assert item.input_ports["a"].label_text() == "a"

    def test_a_lone_output_keeps_its_name_when_collapsed(self, scene,
                                                          registry):
        """Only a side with something hidden behind it counts — the Report
        card's single output is still just "text"."""
        graph, sc = scene
        node, item = report_card(scene, registry)
        sc.set_port_labels_enabled(True)
        graph.set_ports_collapsed(node.id, True)
        assert item.output_ports["text"].label_text() == "text"

    def test_the_collapsed_pin_says_what_it_is(self, scene, registry):
        """A wire dropped on it lands on that one port, not on a bundle —
        the tooltip has to admit that or it is a trap."""
        graph, _sc = scene
        node, item = report_card(scene, registry)
        graph.set_ports_collapsed(node.id, True)
        tip = item.input_ports["a"].toolTip()
        assert "4 inputs" in tip and "collapsed" in tip
        graph.set_ports_collapsed(node.id, False)
        assert item.input_ports["a"].toolTip() == "a"

    def test_a_single_port_node_is_not_offered_it(self, scene, registry):
        """One pin a side is already as gathered as it gets."""
        graph, sc = scene
        node = graph.add_node(registry.instantiate("flograph.viz.show_plot"))
        assert not sc.node_items[node.id].collapsible()
        assert sc.node_items[node.id]._collapse_toggle_rect() is None

    def test_an_ordinary_node_is_not_offered_it(self, scene, registry):
        """Ordinary nodes size their height from their port count, so their
        pins can never outgrow them — there is nothing to collapse."""
        graph, sc = scene
        node = graph.add_node(registry.instantiate("flograph.transform.join"))
        assert not sc.node_items[node.id].collapsible()

    def test_the_chevron_is_clickable_and_undoable(self, scene, registry):
        graph, sc = scene
        node, item = report_card(scene, registry)
        assert item._collapse_toggle_rect() is not None
        item.toggle_ports_collapsed()
        assert node.ports_collapsed is True
        sc.undo_stack.undo()
        assert node.ports_collapsed is False

    def test_flattening_for_zoom_does_not_un_collapse(self, scene, registry):
        """Two independent reasons to hide a pin; setting one must not
        clear the other on the way back."""
        graph, _sc = scene
        node, item = report_card(scene, registry)
        graph.set_ports_collapsed(node.id, True)
        item.set_lod(True)
        assert not any(p.isVisible() for p in item.input_ports.values())
        item.set_lod(False)
        assert sum(p.isVisible() for p in item.input_ports.values()) == 1

    def test_it_survives_a_save_and_reload(self, scene, registry):
        from flograph.core.serialization import graph_from_dict, graph_to_dict
        graph, _sc = scene
        node, _item = report_card(scene, registry)
        graph.set_ports_collapsed(node.id, True)
        reloaded = graph_from_dict(graph_to_dict(graph), registry)
        assert reloaded.nodes[node.id].ports_collapsed is True

    def test_an_older_project_opens_expanded(self, scene, registry):
        from flograph.core.serialization import graph_from_dict, graph_to_dict
        graph, _sc = scene
        node, _item = report_card(scene, registry)
        data = graph_to_dict(graph)
        for entry in data["graph"]["nodes"]:
            entry.pop("ports_collapsed", None)
        reloaded = graph_from_dict(data, registry)
        assert reloaded.nodes[node.id].ports_collapsed is False


class TestResizingNeedsSomewhereToStoreTheSize:
    """Found in a real session log, 2026-07-26 (and present before any of
    this work): dragging the corner of a **Control Template** card raised
    `GraphError: node 'Control Template' has no param 'width'` straight out
    of the mouse-release handler. The card kind offered a resize grip, but
    the node declared no width/height params, so the commit had nowhere to
    put the new size.

    Two halves to the fix. The template now declares them, because it is
    meant to be resizable and its own comments always claimed it was. The
    grip is also gated on the params existing, so the same mistake in a
    node someone forks costs them a missing grip rather than a traceback.
    """

    def forked_without_size(self, scene, registry):
        """A control card whose author left the size params out — which is
        exactly what the shipped template used to be."""
        from flograph.core import NodeInstance
        from flograph.core.script import parse_spec
        graph, sc = scene
        source = registry.get("flograph.scripting.control_template").source
        cut = source[source.index("    # Declare these to make"):
                     source.index("]\n\n\n# run()")]
        node = graph.add_node(NodeInstance.create(
            parse_spec(source.replace(cut, ""), "user.no_size")))
        return node, sc.node_items[node.id]

    def test_a_card_without_size_params_offers_no_grip(self, scene, registry):
        node, item = self.forked_without_size(scene, registry)
        assert node.spec.param("width") is None
        assert not item._resizable()

    def test_the_commit_it_used_to_attempt_is_still_a_hard_error(
            self, scene, registry):
        """Pinning *why* the grip has to go: the graph rightly refuses a
        param the node never declared, so this can't be papered over at the
        commit end."""
        from flograph.core import GraphError
        graph, _sc = scene
        node, _item = self.forked_without_size(scene, registry)
        with pytest.raises(GraphError):
            graph.set_param(node.id, "width", 500)

    @pytest.mark.parametrize("type_id", [
        "flograph.viz.card", "flograph.viz.show_plot",
        "flograph.viz.show_table", "flograph.viz.slicer",
        "flograph.viz.report_card", "flograph.util.note",
        "flograph.io.table", "flograph.input.slider",
        "flograph.scripting.control_template",
    ])
    def test_every_shipped_card_can_be_resized(self, scene, registry,
                                               type_id):
        """Reported: "i cant resize control template at all now?" — the guard
        was right, but the template was the thing that needed fixing."""
        graph, sc = scene
        node = graph.add_node(registry.instantiate(type_id))
        item = sc.node_items[node.id]
        assert item._resizable(), type_id
        graph.set_param(node.id, "width", 300)   # the commit a drag makes
        graph.set_param(node.id, "height", 200)


class TestRenamingAReroute:
    """Reported: "can we rename routes on double click? similar to how we do
    with other nodes". A reroute is all dot and no header, so it fell
    through to the header-double-click test and opened its code instead —
    which is of no use to anyone."""

    def reroute(self, scene, registry):
        graph, sc = scene
        node = graph.add_node(registry.instantiate("flograph.util.reroute"))
        return node, sc.node_items[node.id]

    def test_double_click_asks_to_rename(self, scene, registry, qtbot):
        from PySide6.QtCore import QPointF, Qt
        from PySide6.QtWidgets import QGraphicsSceneMouseEvent
        _graph, sc = scene
        node, item = self.reroute(scene, registry)
        assert item.compact

        renamed, coded = [], []
        sc.node_rename_requested.connect(renamed.append)
        sc.node_double_clicked.connect(coded.append)

        event = QGraphicsSceneMouseEvent(
            QGraphicsSceneMouseEvent.GraphicsSceneMouseDoubleClick)
        event.setPos(QPointF(item.width / 2, item.body_height / 2))
        event.setButton(Qt.LeftButton)
        item.mouseDoubleClickEvent(event)

        assert renamed == [node.id]
        assert coded == []

    def test_the_new_name_shows_as_the_floating_pill(self, scene, registry):
        """Which is the whole point — an unnamed reroute is deliberately
        labelless, and naming it is what makes the pill appear."""
        graph, sc = scene
        node, item = self.reroute(scene, registry)
        assert item._reroute_label_rect() is None
        graph.set_label(node.id, "to totals")
        assert item._reroute_label_rect() is not None


class TestTheMenuEntry:

    @pytest.fixture
    def window(self, qtbot, registry, tmp_path, monkeypatch):
        from PySide6.QtCore import QSettings
        from flograph.ui import mainwindow as mod
        monkeypatch.setattr(mod, "QSettings", lambda *a, **k: QSettings(
            str(tmp_path / "s.ini"), QSettings.IniFormat))
        win = mod.MainWindow(registry)
        win.confirm_close = False
        qtbot.addWidget(win)
        return win

    def add_card(self, window):
        node = window.registry.instantiate("flograph.viz.report_card")
        window.graph.add_node(node)
        return node

    def _dialog(self, window, node):
        from flograph.ui.canvas.appearance_dialog import AppearanceDialog
        return AppearanceDialog(window.scene, node.id, window)

    def test_the_menu_points_at_the_appearance_dialog(self, window,
                                                      monkeypatch):
        """Six appearance entries became one; port names is now a tri-state
        inside it rather than a toggle whose label had to say which way it
        would go."""
        from PySide6.QtWidgets import QMenu
        from flograph.ui import mainwindow as mod
        node = self.add_card(window)
        seen = []

        class _Recorder(QMenu):
            def exec(self, *args):
                seen.extend(a.text() for a in self.actions())
                return None

        monkeypatch.setattr(mod, "QMenu", _Recorder)
        window._show_node_menu(node.id, window.pos())
        assert "Appearance…" in seen
        assert not any(text in seen for text in
                       ("Show Port Names", "Hide Port Names"))

    def test_the_dialog_opens_on_what_the_node_is_doing(self, window, qtbot):
        node = self.add_card(window)
        dialog = self._dialog(window, node)
        qtbot.addWidget(dialog)
        assert dialog._labels_combo.currentData() is None   # canvas default
        window.graph.set_port_labels(node.id, True)
        dialog = self._dialog(window, node)
        qtbot.addWidget(dialog)
        assert dialog._labels_combo.currentData() is True

    def test_choosing_is_one_undo_step(self, window, qtbot):
        node = self.add_card(window)
        dialog = self._dialog(window, node)
        qtbot.addWidget(dialog)
        depth = window.undo_stack.count()
        dialog._labels_combo.setCurrentIndex(
            dialog._labels_combo.findData(True))
        assert window.undo_stack.count() == depth + 1
        assert node.port_labels is True
        window.undo_stack.undo()
        assert node.port_labels is None

    def test_canvas_default_is_offered_outright(self, window, qtbot):
        """Rather than having to toggle a node on and off again to get back
        to following the global setting."""
        node = self.add_card(window)
        window.graph.set_port_labels(node.id, False)
        dialog = self._dialog(window, node)
        qtbot.addWidget(dialog)
        dialog._labels_combo.setCurrentIndex(
            dialog._labels_combo.findData(None))
        assert node.port_labels is None

    def test_the_canvas_setting_persists(self, window):
        window.set_port_labels_enabled(True)
        assert window.settings.value("canvas/port_labels", type=bool) is True
        assert window.scene.port_labels_enabled
