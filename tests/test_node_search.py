"""Find Node: the Qt-free ranking, and the canvas bar that flies to a hit."""
import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QUndoStack

from flograph.core import Graph, NodeRegistry, Page, search_nodes
from flograph.ui.canvas import NodeGraphScene
from flograph.ui.canvas.node_search import (
    MAX_ROWS, MIN_REVEAL_ZOOM, REVEAL_ZOOM)
from flograph.ui.canvas.view import NodeGraphView
from flograph.ui.mainwindow import MainWindow


@pytest.fixture(scope="module")
def registry():
    reg = NodeRegistry()
    reg.load_builtins()
    return reg


def add(graph, registry, label, pos=(0.0, 0.0),
        type_id="flograph.util.constant"):
    node = registry.instantiate(type_id, pos=pos)
    node.label_override = label
    graph.add_node(node)
    return node


def centred_on(view, item) -> bool:
    """Is the view looking at this item? Tolerance is in *pixels* converted
    back to scene units, because centring lands on a whole viewport pixel
    and one of those is 3+ scene units when zoomed out."""
    centre = view.mapToScene(view.viewport().rect().center())
    delta = centre - item.sceneBoundingRect().center()
    return delta.manhattanLength() < 4.0 / view.zoom


@pytest.fixture
def env(qtbot, registry):
    graph = Graph()
    scene = NodeGraphScene(graph, QUndoStack(), registry=registry)
    view = NodeGraphView(scene)
    view.resize(800, 600)
    qtbot.addWidget(view)
    view.show()
    return graph, scene, view


@pytest.fixture
def bar(env):
    _, _, view = env
    return view.search_bar


class TestRanking:
    def test_no_query_lists_the_whole_graph_alphabetically(self, registry):
        graph = Graph()
        for label in ("Zebra", "apple", "Mango"):
            add(graph, registry, label)
        assert [n.label for n in search_nodes(graph, "")] == [
            "apple", "Mango", "Zebra"]

    def test_a_name_that_does_not_match_is_left_out(self, registry):
        graph = Graph()
        add(graph, registry, "Cleaned sales")
        add(graph, registry, "Raw costs")
        assert [n.label for n in search_nodes(graph, "clean")] == [
            "Cleaned sales"]

    def test_nothing_matches_is_an_empty_list(self, registry):
        graph = Graph()
        add(graph, registry, "Cleaned sales")
        assert search_nodes(graph, "qqqq") == []

    def test_a_renamed_node_is_still_found_by_its_type(self, registry):
        """The whole reason type matching exists: rename a Constant to
        "Tax rate" and "constant" must still reach it."""
        graph = Graph()
        add(graph, registry, "Tax rate")
        assert [n.label for n in search_nodes(graph, "constant")] == [
            "Tax rate"]

    def test_a_name_hit_outranks_a_type_hit(self, registry):
        graph = Graph()
        add(graph, registry, "Tax rate")      # a Constant, matched by type
        add(graph, registry, "Constant")      # matched by name
        assert [n.label for n in search_nodes(graph, "constant")][0] == \
            "Constant"

    def test_equal_scores_keep_a_stable_order(self, registry):
        graph = Graph()
        for label in ("Sales b", "Sales a", "Sales c"):
            add(graph, registry, label)
        twice = [[n.label for n in search_nodes(graph, "sales")]
                 for _ in range(2)]
        assert twice[0] == twice[1] == ["Sales a", "Sales b", "Sales c"]


class TestSearchBar:
    def test_it_starts_hidden(self, bar):
        assert not bar.isVisible()

    def test_opening_lists_every_node(self, env, bar, registry):
        graph, _, _ = env
        add(graph, registry, "Alpha")
        add(graph, registry, "Beta")
        bar.open_bar()
        assert bar.isVisible()
        assert len(bar.matches()) == 2

    def test_typing_narrows_the_list(self, env, bar, registry):
        graph, _, _ = env
        alpha = add(graph, registry, "Alpha")
        add(graph, registry, "Beta")
        bar.open_bar()
        bar._edit.setText("alph")
        assert bar.matches() == [alpha.id]

    def test_the_first_hit_is_selected_and_centred(self, env, bar, registry):
        graph, scene, view = env
        add(graph, registry, "Near", pos=(0.0, 0.0))
        far = add(graph, registry, "Faraway", pos=(4000.0, 3000.0))
        bar.open_bar()
        bar._edit.setText("faraway")

        item = scene.node_items[far.id]
        assert item.isSelected()
        assert centred_on(view, item)

    def test_arrowing_down_walks_the_canvas_along(self, env, bar, registry):
        graph, scene, view = env
        first = add(graph, registry, "Sales a", pos=(0.0, 0.0))
        second = add(graph, registry, "Sales b", pos=(2500.0, 0.0))
        bar.open_bar()
        bar._edit.setText("sales")
        assert bar.current_node_id() == first.id

        bar._step(1)
        assert bar.current_node_id() == second.id
        assert scene.node_items[second.id].isSelected()
        assert centred_on(view, scene.node_items[second.id])

    def test_arrowing_wraps_at_the_ends(self, env, bar, registry):
        graph, _, _ = env
        first = add(graph, registry, "Sales a")
        add(graph, registry, "Sales b")
        bar.open_bar()
        bar._edit.setText("sales")
        bar._step(-1)                       # up from the top
        assert bar.current_node_id() != first.id
        bar._step(1)                        # and back round
        assert bar.current_node_id() == first.id

    def test_a_jump_from_far_out_zooms_back_in(self, env, bar, registry):
        """Centring alone would land on a flattened smudge."""
        graph, _, view = env
        add(graph, registry, "Faraway", pos=(3000.0, 0.0))
        view.set_zoom(0.2)
        assert view.zoom < MIN_REVEAL_ZOOM   # setup

        bar.open_bar()
        bar._edit.setText("faraway")
        assert view.zoom == pytest.approx(REVEAL_ZOOM, abs=0.01)

    def test_a_jump_from_close_in_leaves_the_zoom_alone(self, env, bar,
                                                       registry):
        graph, _, view = env
        add(graph, registry, "Faraway", pos=(3000.0, 0.0))
        view.set_zoom(1.8)
        bar.open_bar()
        bar._edit.setText("faraway")
        assert view.zoom == pytest.approx(1.8, abs=0.01)

    def test_enter_keeps_the_node_and_closes(self, env, bar, registry):
        graph, scene, view = env
        far = add(graph, registry, "Faraway", pos=(3000.0, 0.0))
        bar.open_bar()
        bar._edit.setText("faraway")
        bar.accept()

        assert not bar.isVisible()
        assert scene.node_items[far.id].isSelected()
        assert centred_on(view, scene.node_items[far.id])

    def test_escape_puts_the_view_back(self, env, bar, registry):
        graph, _, view = env
        add(graph, registry, "Faraway", pos=(3000.0, 0.0))
        view.set_zoom(0.3)
        home = view.mapToScene(view.viewport().rect().center())

        bar.open_bar()
        bar._edit.setText("faraway")
        bar.cancel()

        assert not bar.isVisible()
        assert view.zoom == pytest.approx(0.3, abs=0.01)
        back = view.mapToScene(view.viewport().rect().center())
        assert (back - home).manhattanLength() < 4.0 / view.zoom

    def test_a_needle_that_matches_nothing_says_so(self, env, bar, registry):
        graph, _, _ = env
        add(graph, registry, "Alpha")
        bar.open_bar()
        bar._edit.setText("qqqq")
        assert bar.matches() == []
        assert bar.current_node_id() is None
        assert bar._count.text() == "none"

    def test_the_box_collapses_when_nothing_matches(self, env, bar, registry):
        """An empty pane hanging over the canvas says less than no pane."""
        graph, _, _ = env
        add(graph, registry, "Alpha")
        bar.open_bar()
        assert not bar._list.isHidden()
        bar._edit.setText("qqqq")
        assert bar._list.isHidden()
        bar._edit.setText("alpha")
        assert not bar._list.isHidden()

    def test_the_box_grows_with_the_hits_but_stops(self, env, bar, registry):
        graph, _, _ = env
        for i in range(MAX_ROWS + 6):
            add(graph, registry, f"Sales {i:02d}")
        bar.open_bar()
        bar._edit.setText("sales 01")
        assert len(bar.matches()) == 1        # setup: one row, not a capped list
        few = bar._list.height()
        bar._edit.setText("sales")
        many = bar._list.height()
        assert few < many
        assert many <= (MAX_ROWS + 1) * bar._list.sizeHintForRow(0)

    def test_the_count_tracks_the_current_row(self, env, bar, registry):
        graph, _, _ = env
        add(graph, registry, "Sales a")
        add(graph, registry, "Sales b")
        bar.open_bar()
        bar._edit.setText("sales")
        assert bar._count.text() == "1 of 2"
        bar._step(1)
        assert bar._count.text() == "2 of 2"

    def test_reopening_searches_the_graph_as_it_now_is(self, env, bar,
                                                       registry):
        graph, _, _ = env
        node = add(graph, registry, "Alpha")
        bar.open_bar()
        bar._edit.setText("beta")
        assert bar.matches() == []
        bar.cancel()

        node.label_override = "Beta"
        bar.open_bar()
        assert bar.matches() == [node.id]

    def test_a_deleted_node_does_not_break_the_jump(self, env, bar, registry):
        graph, _, view = env
        node = add(graph, registry, "Alpha")
        graph.remove_node(node.id)
        assert view.go_to_node(node.id) is False


class TestFindNodeAction:
    @pytest.fixture
    def window(self, qtbot, registry):
        win = MainWindow(registry)
        win.confirm_close = False
        qtbot.addWidget(win)
        return win

    def test_the_menu_item_opens_the_bar(self, window):
        window.action_find_node.trigger()
        # isHidden, not isVisible: the window itself is never shown in the
        # test, and a shown child of a hidden parent is not "visible"
        assert not window.view.search_bar.isHidden()

    def test_it_is_scoped_to_the_canvas(self, window):
        """Window-wide it would collide with the code editor's own Ctrl+F
        and Qt would fire neither."""
        assert window.action_find_node.shortcut().toString() == "Ctrl+F"
        assert (window.action_find_node.shortcutContext()
                == Qt.WidgetWithChildrenShortcut)

    def test_it_is_listed_on_the_keyboard_shortcuts_page(self, window):
        entry = next((e for e in window.shortcuts.entries()
                      if e.label == "Find Node…"), None)
        assert entry is not None
        assert entry.group == "Edit"
        assert entry.binding().toString() == "Ctrl+F"

    def test_rebinding_it_leaves_it_scoped_to_the_canvas(self, window):
        """Rebinding must not quietly promote it to a window shortcut, which
        is where it would start fighting the code editor's Ctrl+F."""
        entry = next(e for e in window.shortcuts.entries()
                     if e.label == "Find Node…")
        assert window.shortcuts.set_binding(
            entry.key, QKeySequence("Ctrl+Shift+N")) is None
        assert window.action_find_node.shortcut() == \
            QKeySequence("Ctrl+Shift+N")
        assert (window.action_find_node.shortcutContext()
                == Qt.WidgetWithChildrenShortcut)
        window.shortcuts.reset(entry.key)
        assert window.action_find_node.shortcut() == QKeySequence("Ctrl+F")

    def test_searching_from_a_dashboard_page_comes_back_to_the_canvas(
            self, window):
        page = window.graph.add_page(Page(id="p1", title="Dashboard 1"))
        window.page_bar.select_page(page.id)
        assert window.page_bar.current_page_id() == page.id

        window.action_find_node.trigger()
        assert window.page_bar.current_page_id() is None
        assert not window.view.search_bar.isHidden()
