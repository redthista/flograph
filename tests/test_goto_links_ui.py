"""Goto/From links on the canvas: the cards' hidden ports and names, the
From's Goto picker, partner highlighting, paste remapping, and the blocking
message the scheduler shows for an unlinked From."""
import pytest
from PySide6.QtGui import QUndoStack
from PySide6.QtWidgets import QMenu

from flograph.core import Graph, NodeRegistry
from flograph.engine.scheduler import ExecutionEngine
from flograph.ui import mainwindow as mw
from flograph.ui.canvas import NodeGraphScene
from flograph.ui.mainwindow import MainWindow
from flograph.ui.properties.params_panel import ParamsPanel

GOTO = "flograph.util.goto"
FROM = "flograph.util.goto_from"
CONST = "flograph.util.constant"


def _pick_menu_action(monkeypatch, text):
    """Drive a context menu without popping a real one — see
    test_project_lifecycle._pick_menu_action for why a genuine QMenu
    subclass is needed rather than patching QMenu.exec directly. Recurses
    into submenus (Go to Connected Node) since only the top-level menu's
    exec() is ever actually called — Qt never runs a submenu's own event
    loop when the parent's exec() already returned a chosen action."""
    def _find(menu, text):
        for action in menu.actions():
            if action.text() == text:
                return action
            if action.menu() is not None:
                found = _find(action.menu(), text)
                if found is not None:
                    return found
        return None

    class _Picker(QMenu):
        def exec(self, *args):
            return _find(self, text)
    monkeypatch.setattr(mw, "QMenu", _Picker)


def _menu_texts(monkeypatch):
    """Every top-level action text the menu would have shown, submenus
    included by their own title rather than their contents."""
    seen: list = []

    class _Recorder(QMenu):
        def exec(self, *args):
            seen.extend(a.text() for a in self.actions())
            return None
    monkeypatch.setattr(mw, "QMenu", _Recorder)
    return seen


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


def add_pair(graph, registry, name="Sales"):
    goto = graph.add_node(registry.instantiate(GOTO))
    node = graph.add_node(registry.instantiate(FROM))
    graph.set_param(goto.id, "name", name)
    graph.set_param(node.id, "source", goto.id)
    return goto, node


class TestCards:
    def test_link_ends_have_no_visible_port(self, env, registry):
        graph, _, scene = env
        goto, node = add_pair(graph, registry)
        goto_item = scene.node_items[goto.id]
        from_item = scene.node_items[node.id]
        # the ports exist in the specs (they carry the link) ...
        assert [p.name for p in goto.spec.outputs] == ["value"]
        assert [p.name for p in node.spec.inputs] == ["value"]
        # ... but the canvas draws only the wireable ends
        assert goto_item.output_ports == {}
        assert list(goto_item.input_ports) == ["value"]
        assert from_item.input_ports == {}
        assert list(from_item.output_ports) == ["value"]

    def test_from_card_shows_the_gotos_name(self, env, registry):
        graph, _, scene = env
        goto, node = add_pair(graph, registry, name="Cleaned sales")
        assert scene.node_items[node.id]._link_card_text() == "Cleaned sales"

    def test_renaming_the_goto_renames_both_cards(self, env, registry):
        graph, _, scene = env
        goto, node = add_pair(graph, registry)
        graph.set_param(goto.id, "name", "Renamed")
        assert scene.node_items[goto.id]._link_card_text() == "Renamed"
        assert scene.node_items[node.id]._link_card_text() == "Renamed"

    def test_unlinked_from_says_so(self, env, registry):
        graph, _, scene = env
        node = graph.add_node(registry.instantiate(FROM))
        assert scene.node_items[node.id]._link_card_text() == "pick a Goto"

    def test_dangling_from_says_so(self, env, registry):
        graph, _, scene = env
        goto, node = add_pair(graph, registry)
        graph.remove_node(goto.id)
        assert scene.node_items[node.id]._link_card_text() == "missing Goto"

    def test_card_width_follows_the_name(self, env, registry):
        graph, _, scene = env
        goto, _ = add_pair(graph, registry, name="x")
        narrow = scene.node_items[goto.id].width
        graph.set_param(goto.id, "name", "a much longer link name")
        assert scene.node_items[goto.id].width > narrow

    def test_selecting_one_end_highlights_the_other(self, env, registry):
        graph, _, scene = env
        goto, node = add_pair(graph, registry)
        scene.node_items[goto.id].setSelected(True)
        assert scene.node_items[node.id]._link_partners
        scene.clearSelection()
        assert not scene.node_items[node.id]._link_partners


class TestConnectedNodeLookup:
    """core.links helpers behind the Goto/From 'Go to Connected Node' menu:
    a Goto's glow highlights every From at once, which stops helping once
    they're scattered across a big graph."""

    def test_goto_lists_every_from_reading_it_sorted_by_label(self, env, registry):
        from flograph.core.links import linked_from_nodes

        graph, _, _ = env
        goto, a = add_pair(graph, registry, name="Sales")
        b = graph.add_node(registry.instantiate(FROM))
        graph.set_param(b.id, "source", goto.id)
        graph.set_label(a.id, "Zebra")
        graph.set_label(b.id, "Alpha")
        assert [n.id for n in linked_from_nodes(graph, goto.id)] == [b.id, a.id]

    def test_goto_with_no_froms_lists_nothing(self, env, registry):
        from flograph.core.links import linked_from_nodes

        graph, _, _ = env
        goto = graph.add_node(registry.instantiate(GOTO))
        assert linked_from_nodes(graph, goto.id) == []

    def test_from_finds_its_goto(self, env, registry):
        from flograph.core.links import linked_goto_node

        graph, _, _ = env
        goto, node = add_pair(graph, registry, name="Sales")
        assert linked_goto_node(graph, node.id).id == goto.id

    def test_unlinked_from_finds_no_goto(self, env, registry):
        from flograph.core.links import linked_goto_node

        graph, _, _ = env
        node = graph.add_node(registry.instantiate(FROM))
        assert linked_goto_node(graph, node.id) is None

    def test_dangling_from_finds_no_goto(self, env, registry):
        from flograph.core.links import linked_goto_node

        graph, _, _ = env
        goto, node = add_pair(graph, registry)
        graph.remove_node(goto.id)
        assert linked_goto_node(graph, node.id) is None


class TestGoToConnectedNodeMenu:
    """The MainWindow side: a right-click menu item that selects and
    centres the canvas on a linked node, so a Goto/From pair scattered
    across a big graph can be jumped to rather than hunted for by eye."""

    @pytest.fixture
    def window(self, qtbot, registry):
        win = MainWindow(registry)
        win.confirm_close = False
        qtbot.addWidget(win)
        return win

    def test_goto_with_one_from_offers_a_direct_action(self, window, monkeypatch):
        from PySide6.QtCore import QPoint

        goto, node = add_pair(window.graph, window.registry, name="Sales")
        window.graph.set_label(node.id, "Reader")
        _pick_menu_action(monkeypatch, "Go to Reader")

        window._show_node_menu(goto.id, QPoint(0, 0))

        assert window.scene.node_items[node.id].isSelected()

    def test_goto_with_several_froms_offers_a_submenu(self, window, monkeypatch):
        from PySide6.QtCore import QPoint

        goto, a = add_pair(window.graph, window.registry, name="Sales")
        b = window.graph.add_node(window.registry.instantiate(FROM))
        window.graph.set_param(b.id, "source", goto.id)
        window.graph.set_label(a.id, "Reader A")
        window.graph.set_label(b.id, "Reader B")
        _pick_menu_action(monkeypatch, "Reader B")

        window._show_node_menu(goto.id, QPoint(0, 0))

        assert window.scene.node_items[b.id].isSelected()
        assert not window.scene.node_items[a.id].isSelected()

    def test_from_offers_go_to_its_goto_by_link_name(self, window, monkeypatch):
        from PySide6.QtCore import QPoint

        goto, node = add_pair(window.graph, window.registry, name="Sales")
        _pick_menu_action(monkeypatch, "Go to Sales")

        window._show_node_menu(node.id, QPoint(0, 0))

        assert window.scene.node_items[goto.id].isSelected()

    def test_unlinked_from_offers_no_go_to_action(self, window, monkeypatch):
        from PySide6.QtCore import QPoint

        node = window.graph.add_node(window.registry.instantiate(FROM))
        seen = _menu_texts(monkeypatch)

        window._show_node_menu(node.id, QPoint(0, 0))

        assert not any(text.startswith("Go to") for text in seen)


class TestGotoPicker:
    def test_lists_gotos_by_name(self, env, qtbot, registry):
        graph, stack, _ = env
        goto = graph.add_node(registry.instantiate(GOTO))
        graph.set_param(goto.id, "name", "Sales")
        node = graph.add_node(registry.instantiate(FROM))
        panel = ParamsPanel(graph, stack)
        qtbot.addWidget(panel)
        panel.set_node(node.id)
        combo = panel.tree.itemWidget(panel.tree.topLevelItem(1), 1)
        assert [combo.itemText(i) for i in range(combo.count())] == \
            ["— none —", "Sales"]
        assert combo.itemData(1) == goto.id

    def test_choosing_a_goto_commits_the_node_id(self, env, qtbot, registry):
        graph, stack, _ = env
        goto = graph.add_node(registry.instantiate(GOTO))
        node = graph.add_node(registry.instantiate(FROM))
        panel = ParamsPanel(graph, stack)
        qtbot.addWidget(panel)
        panel.set_node(node.id)
        combo = panel.tree.itemWidget(panel.tree.topLevelItem(1), 1)
        combo.setCurrentIndex(1)
        combo.activated.emit(1)   # what a user click emits
        assert graph.nodes[node.id].params["source"] == goto.id
        assert graph.links

    def test_a_goto_added_later_shows_up_on_reopen(self, env, qtbot, registry):
        graph, stack, _ = env
        node = graph.add_node(registry.instantiate(FROM))
        panel = ParamsPanel(graph, stack)
        qtbot.addWidget(panel)
        panel.set_node(node.id)
        combo = panel.tree.itemWidget(panel.tree.topLevelItem(1), 1)
        assert combo.count() == 1
        goto = graph.add_node(registry.instantiate(GOTO))
        graph.set_param(goto.id, "name", "Late")
        combo.showPopup()
        combo.hidePopup()
        assert [combo.itemText(i) for i in range(combo.count())] == \
            ["— none —", "Late"]

    def test_gotos_are_listed_alphabetically(self, env, qtbot, registry):
        """ideas.md item 13: insertion order is unusable once a graph has a
        dozen Gotos — you'd have to remember which you dropped first."""
        graph, stack, _ = env
        for name in ("Zulu", "alpha", "Mike"):
            goto = graph.add_node(registry.instantiate(GOTO))
            graph.set_param(goto.id, "name", name)
        node = graph.add_node(registry.instantiate(FROM))
        panel = ParamsPanel(graph, stack)
        qtbot.addWidget(panel)
        panel.set_node(node.id)
        combo = panel.tree.itemWidget(panel.tree.topLevelItem(1), 1)
        names = [combo.itemText(i) for i in range(1, combo.count())]
        # case-insensitive: "alpha" belongs between Mike and Zulu, not after
        assert names == ["alpha", "Mike", "Zulu"]
        assert combo.itemText(0) == "— none —"  # still pinned to the top

    def test_a_deleted_target_stays_visible_as_missing(self, env, qtbot,
                                                       registry):
        graph, stack, _ = env
        goto, node = add_pair(graph, registry)
        graph.remove_node(goto.id)
        panel = ParamsPanel(graph, stack)
        qtbot.addWidget(panel)
        panel.set_node(node.id)
        combo = panel.tree.itemWidget(panel.tree.topLevelItem(1), 1)
        assert combo.currentText() == "⚠ missing"
        assert combo.currentData() == goto.id  # nothing silently rewritten


class TestUndo:
    def test_undoing_a_goto_delete_restores_the_link(self, env, registry):
        from flograph.ui.commands import RemoveSelectionCommand

        graph, stack, scene = env
        goto, node = add_pair(graph, registry)
        scene.node_items[goto.id].setSelected(True)
        stack.push(RemoveSelectionCommand(graph, [goto.id]))
        assert graph.links == {}
        stack.undo()
        assert list(graph.links) == [f"link:{node.id}"]
        assert scene.node_items[node.id]._link_card_text() == "Sales"


class TestPaste:
    def test_copying_the_pair_rewires_the_copies(self, registry):
        goto_spec = registry.get(GOTO)
        from_spec = registry.get(FROM)
        id_map = {"old-goto": "new-goto", "old-from": "new-from"}
        params = MainWindow._remap_node_refs(
            {"source": "old-goto"}, from_spec, id_map)
        assert params["source"] == "new-goto"
        # a Goto has no node_ref params to touch
        assert MainWindow._remap_node_refs({"name": "x"}, goto_spec, id_map) \
            == {"name": "x"}

    def test_copying_a_lone_from_keeps_its_goto(self, registry):
        params = MainWindow._remap_node_refs(
            {"source": "untouched-goto"}, registry.get(FROM),
            {"old-from": "new-from"})
        assert params["source"] == "untouched-goto"


class TestScheduling:
    def test_unlinked_from_blocks_with_a_readable_message(self, env, registry):
        graph, _, _ = env
        node = graph.add_node(registry.instantiate(FROM))
        engine = ExecutionEngine(graph)
        assert engine._blocking_problem(node.id) == \
            "not configured: no Goto selected"

    def test_linked_from_is_blocked_only_by_its_goto(self, env, registry):
        graph, _, _ = env
        goto, node = add_pair(graph, registry)
        const = graph.add_node(registry.instantiate(CONST))
        graph.connect(const.id, "value", goto.id, "value")
        engine = ExecutionEngine(graph)
        # the Goto hasn't run yet, so the From waits on its output like any
        # other downstream node -- not on configuration
        assert engine._blocking_problem(node.id) == \
            "upstream node did not produce output"
