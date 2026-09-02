"""The Navigator dock: the canvas layout as a tree, its orderings, and the
jump-to-canvas a clicked row triggers."""
import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QUndoStack
from PySide6.QtWidgets import QDockWidget

from flograph.core import Frame, Graph, NodeRegistry
from flograph.engine import ExecutionEngine
from flograph.ui.canvas import NodeGraphScene
from flograph.ui.canvas.view import NodeGraphView
from flograph.ui.mainwindow import MainWindow
from flograph.ui.navigator import NavigatorPanel

REG = NodeRegistry()
REG.load_builtins()


def add_node(graph, label, pos=(0.0, 0.0), type_id="flograph.util.constant"):
    node = REG.instantiate(type_id, pos=pos)
    node.label_override = label
    graph.add_node(node)
    return node


def collapse(scene, frame_id):
    scene.frame_items[frame_id].toggle_collapsed()


def entry(item):
    return item.data(0, Qt.UserRole)  # (kind, id)


def rows(panel, parent=None):
    """The tree as nested [(kind, id, [children])]."""
    parent = parent or panel._tree.invisibleRootItem()
    return [(entry(parent.child(i))[0], entry(parent.child(i))[1],
             rows(panel, parent.child(i)))
            for i in range(parent.childCount())]


def flat(panel):
    def walk(entries):
        for kind, ident, kids in entries:
            yield (kind, ident)
            yield from walk(kids)
    return set(walk(rows(panel)))


def reorder(panel, index):
    panel._combo.setCurrentIndex(index)
    panel._sort = panel._combo.currentData()
    panel._rebuild()


def top_titles(panel):
    return [panel._tree.topLevelItem(i).text(0)
            for i in range(panel._tree.topLevelItemCount())]


def top_item(panel, ident):
    return next(panel._tree.topLevelItem(i)
               for i in range(panel._tree.topLevelItemCount())
               if entry(panel._tree.topLevelItem(i))[1] == ident)


@pytest.fixture
def env(qtbot):
    graph = Graph()
    stack = QUndoStack()
    scene = NodeGraphScene(graph, stack, registry=REG)
    view = NodeGraphView(scene)
    view.resize(800, 600)
    qtbot.addWidget(view)
    engine = ExecutionEngine(graph)
    panel = NavigatorPanel(graph, scene, engine)
    qtbot.addWidget(panel)
    yield graph, scene, view, engine, panel
    stack.clear()


class TestTree:
    def test_bare_canvas_nodes_are_top_level(self, env):
        graph, _, _, _, panel = env
        a = add_node(graph, "A")
        b = add_node(graph, "B")
        panel._rebuild()
        assert flat(panel) == {("node", a.id), ("node", b.id)}

    def test_a_frame_is_a_branch_holding_its_nodes(self, env):
        graph, _, _, _, panel = env
        graph.add_frame(Frame(id="f1", title="Stage", rect=(0, 0, 400, 300)))
        inside = add_node(graph, "Inside", pos=(100, 100))
        outside = add_node(graph, "Outside", pos=(900, 900))
        panel._rebuild()

        frame_row = next(r for r in rows(panel) if r[1] == "f1")
        assert frame_row[0] == "frame"
        assert [(k, i) for k, i, _ in frame_row[2]] == [("node", inside.id)]
        assert ("node", outside.id) in {(r[0], r[1]) for r in rows(panel)}

    def test_nested_frames_nest_in_the_tree(self, env):
        graph, _, _, _, panel = env
        graph.add_frame(Frame(id="outer", title="Outer", rect=(0, 0, 600, 500)))
        graph.add_frame(Frame(id="inner", title="Inner",
                              rect=(50, 50, 200, 200)))
        leaf = add_node(graph, "Leaf", pos=(100, 100))
        panel._rebuild()

        top = rows(panel)
        assert [r[1] for r in top] == ["outer"]
        assert [r[1] for r in top[0][2]] == ["inner"]
        assert [(k, i) for k, i, _ in top[0][2][0][2]] == [("node", leaf.id)]

    def test_a_node_folded_inside_a_collapsed_frame_is_still_listed(self, env):
        graph, scene, _, _, panel = env
        graph.add_frame(Frame(id="f1", title="Stage", rect=(0, 0, 400, 300)))
        inside = add_node(graph, "Inside", pos=(100, 100))
        collapse(scene, "f1")
        panel._rebuild()

        frame_row = next(r for r in rows(panel) if r[1] == "f1")
        assert ("node", inside.id) in {(k, i) for k, i, _ in frame_row[2]}


class TestNavigation:
    def test_clicking_a_node_row_asks_to_go_there(self, env, qtbot):
        graph, _, _, _, panel = env
        node = add_node(graph, "Target")
        panel._rebuild()
        with qtbot.waitSignal(panel.navigate_requested) as sig:
            panel._tree.itemClicked.emit(panel._tree.topLevelItem(0), 0)
        assert sig.args == ["node", node.id]

    def test_clicking_a_frame_row_asks_to_go_there(self, env, qtbot):
        graph, _, _, _, panel = env
        graph.add_frame(Frame(id="f1", title="Stage"))
        panel._rebuild()
        with qtbot.waitSignal(panel.navigate_requested) as sig:
            panel._tree.itemClicked.emit(panel._tree.topLevelItem(0), 0)
        assert sig.args == ["frame", "f1"]

    def test_canvas_selection_highlights_the_row(self, env):
        graph, scene, _, _, panel = env
        a = add_node(graph, "A")
        add_node(graph, "B")
        panel._rebuild()
        scene.node_items[a.id].setSelected(True)

        selected = [entry(panel._tree.topLevelItem(i))[1]
                    for i in range(panel._tree.topLevelItemCount())
                    if panel._tree.topLevelItem(i).isSelected()]
        assert selected == [a.id]


class TestOrdering:
    def test_by_name(self, env):
        graph, _, _, _, panel = env
        add_node(graph, "Zebra", pos=(0, 0))
        add_node(graph, "Apple", pos=(500, 0))
        reorder(panel, 1)
        assert top_titles(panel) == ["Apple", "Zebra"]

    def test_by_position_top_to_bottom(self, env):
        graph, _, _, _, panel = env
        add_node(graph, "Low", pos=(0, 900))
        add_node(graph, "High", pos=(300, 10))
        reorder(panel, 0)
        assert top_titles(panel) == ["High", "Low"]

    def test_by_runtime_slowest_first(self, env):
        graph, _, _, engine, panel = env
        fast = add_node(graph, "Fast")
        slow = add_node(graph, "Slow")
        engine.cache.set(fast.id, {}, wall_time=0.1)
        engine.cache.set(slow.id, {}, wall_time=5.0)
        reorder(panel, 2)
        assert top_titles(panel) == ["Slow", "Fast"]

    def test_frame_runtime_is_the_sum_of_its_contents(self, env):
        graph, _, _, engine, panel = env
        graph.add_frame(Frame(id="f1", title="Stage", rect=(0, 0, 400, 300)))
        a = add_node(graph, "A", pos=(50, 50))
        b = add_node(graph, "B", pos=(120, 120))
        engine.cache.set(a.id, {}, wall_time=1.0)
        engine.cache.set(b.id, {}, wall_time=2.0)
        panel._rebuild()
        assert "3.0 s" in top_item(panel, "f1").text(1)


class TestLiveUpdates:
    def test_a_new_node_schedules_a_rebuild(self, env):
        graph, _, _, _, panel = env
        add_node(graph, "First")
        assert panel._pending.isActive()
        panel._rebuild()
        assert panel._tree.topLevelItemCount() == 1

    def test_a_rename_is_reflected(self, env):
        graph, _, _, _, panel = env
        node = add_node(graph, "Before")
        panel._rebuild()
        node.label_override = "After"
        graph.events.label_changed.emit(node.id)
        panel._rebuild()
        assert panel._tree.topLevelItem(0).text(0) == "After"

    def test_tree_collapse_state_survives_a_rebuild(self, env):
        graph, _, _, _, panel = env
        graph.add_frame(Frame(id="f1", title="Stage", rect=(0, 0, 400, 300)))
        add_node(graph, "Inside", pos=(100, 100))
        panel._rebuild()
        panel._tree.topLevelItem(0).setExpanded(False)
        assert "f1" in panel._collapsed

        panel._rebuild()
        assert panel._tree.topLevelItem(0).isExpanded() is False

    def test_empty_canvas_shows_the_placeholder(self, env):
        _, _, _, _, panel = env
        panel._rebuild()
        assert panel._stack.currentIndex() == 1


class TestWindowWiring:
    @pytest.fixture
    def window(self, qtbot):
        win = MainWindow(REG)
        win.confirm_close = False
        qtbot.addWidget(win)
        return win

    def test_the_dock_exists_and_is_titled_navigator(self, window):
        docks = {d.objectName(): d for d in window.findChildren(QDockWidget)}
        assert "dock_navigator" in docks
        assert docks["dock_navigator"].windowTitle() == "Navigator"

    def test_it_has_a_show_hide_toggle_wired_to_the_view_menu(self, window):
        # MainWindow adds every dock's toggleViewAction to the View menu
        toggle = window.navigator_dock.toggleViewAction()
        assert toggle.text() == "Navigator"
        assert toggle.isCheckable()

    def test_a_frame_row_brings_the_canvas_to_the_frame(self, window):
        window.graph.add_frame(
            Frame(id="f1", title="Stage", rect=(2000, 1500, 400, 300)))
        window.navigator_panel._rebuild()
        window._navigate_to("frame", "f1")
        assert window.scene.frame_items["f1"].isSelected()

    def test_a_folded_frames_node_row_lands_on_the_frame(self, window):
        g = window.graph
        g.add_frame(Frame(id="f1", title="Stage", rect=(1200, 800, 400, 300)))
        node = REG.instantiate("flograph.util.constant", pos=(1300, 900))
        g.add_node(node)
        window.scene.frame_items["f1"].toggle_collapsed()
        window.navigator_panel._rebuild()

        window._navigate_to("node", node.id)
        assert window.scene.frame_items["f1"].isSelected()
        assert not window.scene.node_items[node.id].isSelected()
