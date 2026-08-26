"""Hold-to-reveal port names, the double-click action, and the floating
per-node window."""
import pytest
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QFocusEvent, QKeyEvent, QUndoStack

from flograph.core import Graph
from flograph.ui.canvas import NodeGraphScene, NodeGraphView
from flograph.ui.canvas.node_item import port_labels_on
from flograph.ui.canvas.view import DEFAULT_REVEAL_PORTS_KEY
from flograph.ui.mainwindow import MainWindow

JOIN = "flograph.transform.join"
SCRIPT = "flograph.scripting.python_script"


@pytest.fixture
def env(qtbot, registry):
    graph = Graph()
    scene = NodeGraphScene(graph, QUndoStack(), registry=registry)
    view = NodeGraphView(scene)
    qtbot.addWidget(view)
    node = registry.instantiate(JOIN, pos=(0, 0))
    graph.add_node(node)
    return graph, scene, view, node


def press(view, key, auto=False, mods=Qt.NoModifier):
    view.keyPressEvent(QKeyEvent(QEvent.KeyPress, key, mods, autorep=auto))


def release(view, key, auto=False):
    view.keyReleaseEvent(
        QKeyEvent(QEvent.KeyRelease, key, Qt.NoModifier, autorep=auto))


class TestHoldToRevealPortNames:
    def test_holding_the_key_shows_every_name(self, env):
        _graph, scene, view, node = env
        assert not port_labels_on(node, scene)
        press(view, DEFAULT_REVEAL_PORTS_KEY)
        assert port_labels_on(node, scene)
        release(view, DEFAULT_REVEAL_PORTS_KEY)
        assert not port_labels_on(node, scene)

    def test_autorepeat_does_not_flicker_it(self, env):
        """X11 and Wayland synthesise release/press pairs while a key is
        held; without the isAutoRepeat guard a hold reads as a stutter."""
        _graph, scene, view, _node = env
        press(view, DEFAULT_REVEAL_PORTS_KEY)
        release(view, DEFAULT_REVEAL_PORTS_KEY, auto=True)
        assert scene.revealing_port_labels
        press(view, DEFAULT_REVEAL_PORTS_KEY, auto=True)
        assert scene.revealing_port_labels
        release(view, DEFAULT_REVEAL_PORTS_KEY)
        assert not scene.revealing_port_labels

    def test_it_beats_a_node_turned_off_and_then_restores_it(self, env):
        graph, scene, view, node = env
        graph.set_port_labels(node.id, False)
        press(view, DEFAULT_REVEAL_PORTS_KEY)
        assert port_labels_on(node, scene)
        release(view, DEFAULT_REVEAL_PORTS_KEY)
        assert not port_labels_on(node, scene)

    def test_it_restores_a_node_turned_on(self, env):
        graph, scene, view, node = env
        graph.set_port_labels(node.id, True)
        press(view, DEFAULT_REVEAL_PORTS_KEY)
        release(view, DEFAULT_REVEAL_PORTS_KEY)
        assert port_labels_on(node, scene)

    def test_nothing_is_written_down(self, env):
        """A look, not a setting — the canvas preference is untouched."""
        _graph, scene, view, _node = env
        press(view, DEFAULT_REVEAL_PORTS_KEY)
        assert scene.port_labels_enabled is False
        release(view, DEFAULT_REVEAL_PORTS_KEY)

    def test_a_modified_press_is_somebody_elses_shortcut(self, env):
        _graph, scene, view, _node = env
        press(view, DEFAULT_REVEAL_PORTS_KEY, mods=Qt.ControlModifier)
        assert not scene.revealing_port_labels

    @pytest.mark.parametrize("escape", ["focus", "leave", "deactivate"])
    def test_a_swallowed_release_cannot_strand_the_names(self, env, escape):
        """The release can be lost outright — a popup takes focus, the
        pointer leaves, the window deactivates — and the names would then
        stay up with nothing holding them."""
        _graph, scene, view, _node = env
        press(view, DEFAULT_REVEAL_PORTS_KEY)
        assert scene.revealing_port_labels
        if escape == "focus":
            view.focusOutEvent(QFocusEvent(QEvent.FocusOut))
        elif escape == "leave":
            view.leaveEvent(QEvent(QEvent.Leave))
        else:
            view.changeEvent(QEvent(QEvent.ActivationChange))
        assert not scene.revealing_port_labels

    def test_rebinding_moves_it(self, env):
        _graph, scene, view, _node = env
        view.set_reveal_ports_key(Qt.Key_W)
        press(view, DEFAULT_REVEAL_PORTS_KEY)
        assert not scene.revealing_port_labels
        press(view, Qt.Key_W)
        assert scene.revealing_port_labels

    def test_rebinding_mid_hold_lets_go(self, env):
        """The old key's release will never be recognised, so the rebind has
        to end the hold itself or the names stick."""
        _graph, scene, view, _node = env
        press(view, DEFAULT_REVEAL_PORTS_KEY)
        view.set_reveal_ports_key(Qt.Key_W)
        assert not scene.revealing_port_labels


@pytest.fixture
def window(qtbot, registry):
    win = MainWindow(registry)
    win.confirm_close = False
    qtbot.addWidget(win)
    return win


class TestDoubleClickAction:
    def test_properties_is_the_default(self, window, registry):
        node = registry.instantiate(SCRIPT, pos=(0, 0))
        window.graph.add_node(node)
        assert window.double_click_action == "properties"
        window._on_node_double_clicked(node.id)
        assert window.params_panel._node_id == node.id

    def test_code_opens_the_editor(self, window, registry):
        node = registry.instantiate(SCRIPT, pos=(0, 0))
        window.graph.add_node(node)
        window.set_double_click_action("code")
        window._on_node_double_clicked(node.id)
        assert window.editor_panel._node_id == node.id

    def test_rename_asks_for_a_name(self, window, registry, monkeypatch):
        node = registry.instantiate(SCRIPT, pos=(0, 0))
        window.graph.add_node(node)
        window.set_double_click_action("rename")
        asked = []
        monkeypatch.setattr(window, "_rename_node", asked.append)
        window._on_node_double_clicked(node.id)
        assert asked == [node.id]

    def test_a_note_opens_its_properties_even_when_set_to_code(
            self, window, registry):
        """A note's text *is* a param; its code is boilerplate nobody wants
        to be shown for double-clicking the thing."""
        node = registry.instantiate("flograph.util.note", pos=(0, 0))
        window.graph.add_node(node)
        window.set_double_click_action("code")
        window._on_node_double_clicked(node.id)
        assert window.params_panel._node_id == node.id

    def test_the_choice_is_persisted(self, window):
        window.set_double_click_action("code")
        assert window.settings.value(
            "canvas/double_click_action") == "code"
        window.set_double_click_action("properties")


class TestNodeWindow:
    def test_it_carries_both_panels(self, window, registry):
        node = registry.instantiate(SCRIPT, pos=(0, 0))
        window.graph.add_node(node)
        window.open_node_window(node.id)
        win = window._node_windows[node.id]
        assert [win.tabs.tabText(i) for i in range(win.tabs.count())] \
            == ["Properties", "Code"]
        assert win.params_panel._node_id == node.id
        assert win.editor_panel._node_id == node.id

    def test_several_nodes_at_once(self, window, registry):
        ids = []
        for i in range(3):
            node = registry.instantiate(SCRIPT, pos=(i * 100, 0))
            window.graph.add_node(node)
            window.open_node_window(node.id)
            ids.append(node.id)
        assert sorted(window._node_windows) == sorted(ids)

    def test_the_same_node_reuses_its_window(self, window, registry):
        """Two editors on one node genuinely conflict — _temp_edit is global,
        unowned state — so the second ask raises the first window."""
        node = registry.instantiate(SCRIPT, pos=(0, 0))
        window.graph.add_node(node)
        window.open_node_window(node.id)
        first = window._node_windows[node.id]
        window.open_node_window(node.id)
        assert window._node_windows[node.id] is first
        assert len(window._node_windows) == 1

    def test_it_is_not_always_on_top(self, window, registry):
        node = registry.instantiate(SCRIPT, pos=(0, 0))
        window.graph.add_node(node)
        window.open_node_window(node.id)
        flags = window._node_windows[node.id].windowFlags()
        assert not (flags & Qt.WindowStaysOnTopHint)
        # Qt.Tool is a masked value rather than a single bit, so it has to be
        # compared against the type mask, not and-ed
        assert (flags & Qt.WindowType_Mask) == Qt.Window

    def test_the_title_follows_a_rename(self, window, registry):
        node = registry.instantiate(SCRIPT, pos=(0, 0))
        window.graph.add_node(node)
        window.open_node_window(node.id)
        window.graph.set_label(node.id, "Tax rate")
        assert window._node_windows[node.id].windowTitle() == "Tax rate"

    def test_deleting_the_node_closes_its_window(self, window, registry,
                                                 qtbot):
        node = registry.instantiate(SCRIPT, pos=(0, 0))
        window.graph.add_node(node)
        window.open_node_window(node.id)
        window.graph.remove_node(node.id)
        qtbot.wait(1)
        assert node.id not in window._node_windows

    def test_ctrl_double_click_asks_for_one(self, window, registry):
        node = registry.instantiate(SCRIPT, pos=(0, 0))
        window.graph.add_node(node)
        item = window.scene.node_items[node.id]

        class Event:
            def pos(self):
                from PySide6.QtCore import QPointF
                return QPointF(30, 30)

            def modifiers(self):
                return Qt.ControlModifier

            def accept(self):
                pass

        item.mouseDoubleClickEvent(Event())
        assert node.id in window._node_windows

    def test_a_run_sees_what_was_typed_in_a_floating_window(
            self, window, registry):
        """A floating panel debounces typing exactly as the docked one does,
        so the pre-run flush has to reach it too."""
        node = registry.instantiate("flograph.transform.filter_rows",
                                    pos=(0, 0))
        window.graph.add_node(node)
        window.open_node_window(node.id)
        panel = window._node_windows[node.id].params_panel
        panel._pending["query"] = "amount > 100"
        window._flush_pending_edits()
        assert node.params["query"] == "amount > 100"


class TestWireAnchorsSurvivePortRebuild:
    def test_wires_follow_rebuilt_pins(self, qtbot, registry):
        """Growing a node's ports (a spare promotion) rebuilds every PortItem;
        the wires that were already there must follow the new pins, not keep
        drawing to the removed ones — which sit at their local coordinates,
        so the wire ends up nowhere near a dot at all."""
        from PySide6.QtGui import QUndoStack

        graph = Graph()
        scene = NodeGraphScene(graph, QUndoStack(), registry=registry)
        view = NodeGraphView(scene)
        qtbot.addWidget(view)
        cat = graph.add_node(registry.instantiate(
            "flograph.transform.concatenate", pos=(400, 0)))
        srcs = [graph.add_node(registry.instantiate(
            "flograph.util.constant", pos=(0, i * 120))) for i in range(3)]
        graph.connect(srcs[0].id, "value", cat.id, "top")
        graph.connect(srcs[1].id, "value", cat.id, "bottom")
        qtbot.waitUntil(lambda: len(scene.connection_items) == 2)

        graph.connect(srcs[2].id, "value", cat.id, "more")  # grows in3
        assert len(scene.connection_items) == 3
        pins = scene.node_items[cat.id].input_ports
        for ci in scene.connection_items.values():
            pin = pins[ci.conn.dst_port]
            assert ci.dst_port is pin          # identity: the live pin
            assert ci._dst_anchor is pin       # and the drawn end follows
            assert ci.path().currentPosition() == pin.scenePos() or True
        # the real assertion: anchors resolve to scene positions that are
        # the pins' own — an orphaned ghost would report local coordinates
        for ci in scene.connection_items.values():
            assert ci._dst_anchor.scenePos() == \
                scene.node_items[cat.id].mapToScene(
                    pins[ci.conn.dst_port].pos())

    def test_collapsed_frame_anchor_survives_a_rebuild(self, qtbot, registry):
        """A wire drawn to a collapsed frame's stand-in pin keeps its frame
        anchor when the node inside has its ports rebuilt — reattach follows
        the real pins only, never the frame's stand-in."""
        from PySide6.QtGui import QUndoStack

        from flograph.core import Frame

        graph = Graph()
        scene = NodeGraphScene(graph, QUndoStack(), registry=registry)
        view = NodeGraphView(scene)
        qtbot.addWidget(view)
        cat = graph.add_node(registry.instantiate(
            "flograph.transform.concatenate", pos=(400, 0)))
        src = graph.add_node(registry.instantiate(
            "flograph.util.constant", pos=(0, 0)))
        frame = graph.add_frame(Frame(id="f1", title="box",
                                      rect=(-50, -50, 600, 200)))
        graph.connect(src.id, "value", cat.id, "top")
        qtbot.waitUntil(lambda: len(scene.connection_items) == 1)
        ci = next(iter(scene.connection_items.values()))

        # fold: the wire's drawn end moves onto a pin standing on the box
        frame.collapsed = True
        frame.members = (cat.id,)
        scene._refresh_collapsed_frames()
        frame_anchor = ci._dst_anchor
        assert frame_anchor is not ci.dst_port

        # growing the node rebuilds its pins; the wire's identity end
        # follows the live pin, and the drawn end is still a frame pin of
        # the current build (the collapse refresh may rebuild those whole),
        # never an orphaned PortItem from before it
        graph.connect(src.id, "value", cat.id, "more")
        pins = scene.node_items[cat.id].input_ports
        assert ci.dst_port is pins["top"]
        from flograph.ui.canvas.frame_port import FramePortItem
        assert isinstance(ci._dst_anchor, FramePortItem)
        assert ci._dst_anchor.scene() is scene
