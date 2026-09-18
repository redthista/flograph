"""G12: a frame opened in a tab of its own — the model canvas fenced to one
frame, saved with the project like any other page.

Settings kept off the real store (avoid polluting the developer's actual
flograph.conf) -- see test_ab_dashboard_nav.py's fixture of the same name."""
import pytest
from PySide6.QtCore import QEvent, QPointF, QRectF, QSettings, Qt
from PySide6.QtGui import QMouseEvent, QPainterPath
from PySide6.QtWidgets import QComboBox

from flograph.core import Frame, Graph, Page
from flograph.core.page_nav import (CANVAS_KIND, SHOW_EVERY, linked_pages,
                                    reader_pages)
from flograph.core import serialization
from flograph.core.serialization import graph_from_dict, graph_to_dict
from flograph.ui import mainwindow as mw
from flograph.ui.canvas.view import edge_crossing
from flograph.ui.commands import AddPageCommand, SetParamCommand
from flograph.ui.mainwindow import MainWindow

TABLE = "flograph.io.table"
FILTER = "flograph.transform.filter_rows"
FRAME_RECT = QRectF(0, 0, 600, 400)


@pytest.fixture(autouse=True)
def _isolated_settings(tmp_path, monkeypatch):
    ini_path = str(tmp_path / "test_settings.ini")
    monkeypatch.setattr(
        mw, "QSettings",
        lambda *a, **k: QSettings(ini_path, QSettings.IniFormat))


@pytest.fixture
def window(qtbot, registry):
    win = MainWindow(registry)
    win.confirm_close = False
    qtbot.addWidget(win)
    return win


@pytest.fixture
def flow(window, registry):
    """A frame holding one Filter Rows, fed by a Table outside it on the
    left and feeding another Filter Rows outside it on the right."""
    graph = window.graph
    source = registry.instantiate(TABLE, pos=(-600, 100))
    inside = registry.instantiate(FILTER, pos=(200, 150))
    after = registry.instantiate(FILTER, pos=(1400, 150))
    for node in (source, inside, after):
        graph.add_node(node)
    graph.add_frame(Frame(id="f1", title="Cleaning", rect=(0, 0, 600, 400)))
    graph.connect(source.id, "table", inside.id, "table")
    graph.connect(inside.id, "filtered", after.id, "table")
    return source, inside, after


def _open(window) -> str:
    window._open_frame_tab("f1")
    return window._frame_tab_of("f1")


def _press(view, scene_pos: QPointF) -> QMouseEvent:
    pos = QPointF(view.mapFromScene(scene_pos))
    event = QMouseEvent(QEvent.MouseButtonPress, pos,
                        QPointF(view.viewport().mapToGlobal(pos.toPoint())),
                        Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
    view.mousePressEvent(event)
    return event


# ------------------------------------------------------------------ the model

class TestThePage:
    def test_a_frame_tab_round_trips_through_the_file(self, registry):
        graph = Graph()
        graph.add_frame(Frame(id="f1"))
        graph.add_page(Page(id="p1", title="Cleaning", kind=CANVAS_KIND,
                            frame="f1"))
        graph.add_page(Page(id="p2", title="Board"))
        data = graph_to_dict(graph)
        entries = {e["id"]: e for e in data["graph"]["pages"]}
        assert entries["p1"]["frame"] == "f1"
        assert "frame" not in entries["p2"]    # only a frame tab names one
        back = graph_from_dict(data, registry)
        assert back.pages["p1"].kind == CANVAS_KIND
        assert back.pages["p1"].frame == "f1"
        assert back.pages["p2"].frame == ""

    def test_pages_for_readers_leave_frame_tabs_out(self):
        pages = {"a": Page(id="a", title="Board"),
                 "b": Page(id="b", title="Cleaning", kind=CANVAS_KIND,
                           frame="f1"),
                 "c": Page(id="c", title="Notes", kind="report")}
        assert [p.id for p in reader_pages(pages)] == ["a", "c"]
        assert [p.id for p in linked_pages(pages, {"show": SHOW_EVERY})] \
            == ["a", "c"]

    def test_edge_crossing_finds_where_a_path_leaves_a_rect(self):
        path = QPainterPath(QPointF(0, 0))
        path.lineTo(200, 0)
        t = edge_crossing(path, QRectF(-10, -10, 110, 20))
        assert t == pytest.approx(0.5, abs=0.01)
        assert edge_crossing(path, QRectF(-10, -10, 300, 20)) is None
        assert edge_crossing(QPainterPath(), QRectF(0, 0, 1, 1)) is None


# ------------------------------------------------------------------ the tab

class TestOpeningOne:
    def test_open_in_new_tab_makes_one_tab_and_goes_there(self, window, flow):
        page_id = _open(window)
        page = window.graph.pages[page_id]
        assert (page.kind, page.frame, page.title) == (CANVAS_KIND, "f1",
                                                      "Cleaning")
        assert window.page_bar.current_page_id() == page_id
        window.page_bar.select_page(None)
        _open(window)                       # asked again: the same tab
        assert len(window.graph.pages) == 1
        assert window.page_bar.current_page_id() == page_id

    def test_it_is_undoable(self, window, flow):
        _open(window)
        window.undo_stack.undo()
        assert not window.graph.pages
        assert window.view.fence_frame is None

    def test_the_tab_is_the_canvas_fenced_to_the_frame(self, window, flow):
        window.set_minimap_enabled(True)
        _open(window)
        view = window.view
        assert window._canvas_stack.currentWidget() is view
        assert view.fence_frame == "f1"
        assert view.fence_rect() == FRAME_RECT
        assert not window._docks_away()     # Properties & co stay up
        assert view.minimap.isHidden()
        window.page_bar.select_page(None)
        assert view.fence_frame is None
        assert not view.minimap.isHidden()

    def test_a_dashboard_still_puts_the_docks_away(self, window, flow):
        _open(window)
        window.undo_stack.push(AddPageCommand(window.graph,
                                              Page(id="board", title="B")))
        window.page_bar.select_page("board")
        assert window._docks_away()
        window.page_bar.select_page(window._frame_tab_of("f1"))
        assert not window._docks_away()
        assert window.view.fence_frame == "f1"

    def test_each_canvas_tab_keeps_its_own_place(self, window, flow):
        view = window.view
        view.set_zoom(0.5)
        model_center = view.view_state()[1]
        page_id = _open(window)
        view.set_zoom(1.2)
        window.page_bar.select_page(None)
        assert view.zoom == pytest.approx(0.5)
        assert view.view_state()[1].x() == pytest.approx(model_center.x(),
                                                         abs=2)
        window.page_bar.select_page(page_id)
        assert view.zoom == pytest.approx(1.2)


class TestInsideTheFence:
    def test_a_wire_leaving_the_frame_gets_a_label_at_the_edge(self, window,
                                                                flow):
        source, inside, after = flow
        _open(window)
        stubs = {s.node_id: s for s in window.view.fence_stubs()}
        assert set(stubs) == {source.id, after.id}
        out = stubs[after.id]
        assert out.outgoing and out.text == f"→ {after.label}"
        assert out.point.x() == pytest.approx(600, abs=1)   # the right edge
        into = stubs[source.id]
        assert not into.outgoing and into.text == f"← {source.label}"
        assert into.point.x() == pytest.approx(0, abs=1)

    def test_select_all_selects_only_what_the_tab_shows(self, window, flow):
        source, inside, after = flow
        _open(window)
        window._select_all_nodes()
        assert window.page_bar.current_page_id() is not None   # stayed
        items = window.scene.node_items
        assert items[inside.id].isSelected()
        assert not items[source.id].isSelected()
        assert not items[after.id].isSelected()
        assert window.scene.frame_items["f1"].isSelected()

    def test_a_frame_around_it_is_not_part_of_the_tab(self, window, flow):
        window.graph.add_frame(Frame(id="outer", title="All",
                                     rect=(-800, -200, 2600, 900)))
        _open(window)
        window._select_all_nodes()
        assert not window.scene.frame_items["outer"].isSelected()

    def test_a_click_outside_the_frame_picks_nothing(self, window, flow):
        _source, inside, after = flow
        _open(window)
        view = window.view
        event = _press(view, window.scene.node_items[after.id]
                       .sceneBoundingRect().center())
        assert event.isAccepted()
        assert not window.scene.selectedItems()
        assert not view._fence_blocks(QMouseEvent(
            QEvent.MouseButtonPress,
            QPointF(view.mapFromScene(QPointF(300, 300))), QPointF(),
            Qt.LeftButton, Qt.LeftButton, Qt.NoModifier))

    def test_clicking_a_label_goes_to_its_node_on_the_whole_canvas(
            self, window, flow):
        _source, _inside, after = flow
        _open(window)
        view = window.view
        view.resize(900, 600)
        view.viewport().grab()           # a paint lays the labels out
        hit = next(h for h in view._stub_hits if h[1] == after.id)
        pos = hit[0].center()
        view.mousePressEvent(QMouseEvent(
            QEvent.MouseButtonPress, pos,
            QPointF(view.viewport().mapToGlobal(pos.toPoint())),
            Qt.LeftButton, Qt.LeftButton, Qt.NoModifier))
        assert window.page_bar.current_page_id() is None
        assert view.fence_frame is None
        assert window.scene.node_items[after.id].isSelected()

    def test_a_jump_to_a_node_outside_leaves_the_tab(self, window, flow):
        source, inside, _after = flow
        page_id = _open(window)
        window._go_to_node(inside.id)
        assert window.page_bar.current_page_id() == page_id
        window._go_to_node(source.id)
        assert window.page_bar.current_page_id() is None
        assert window.view.fence_frame is None

    def test_f_fits_the_frame(self, window, flow):
        _open(window)
        view = window.view
        view.set_zoom(0.1)
        window.scene.clearSelection()
        view.frame_content()
        shown = view.mapToScene(view.viewport().rect()).boundingRect()
        assert shown.contains(FRAME_RECT.center())
        assert view.zoom > 0.1


class TestClosingAndLosing:
    def test_close_tab_keeps_the_frame(self, window, flow):
        page_id = _open(window)
        index = window.page_bar._index_of_page(page_id)
        texts = [a.text() for a in
                 window.page_bar._context_menu(index, page_id).actions()]
        assert "Close Tab" in texts
        assert "Locked" not in texts and "Duplicate" not in texts
        window._delete_page(page_id)
        assert page_id not in window.graph.pages
        assert "f1" in window.graph.frames
        assert window.page_bar.current_page_id() is None
        assert window.view.fence_frame is None
        assert not window._docks_away()

    def test_a_deleted_frame_leaves_the_tab_saying_so(self, window, flow):
        _open(window)
        view = window.view
        window.scene.delete_items([], [], ["f1"])
        assert view.fence_rect() is not None and view.fence_rect().isNull()
        assert view.fence_stubs() == []
        view.viewport().grab()           # paints the notice, doesn't crash
        window.undo_stack.undo()
        assert view.fence_rect() == FRAME_RECT

    def test_the_page_pickers_leave_frame_tabs_out(self, window, flow):
        _open(window)
        window.undo_stack.push(AddPageCommand(window.graph,
                                              Page(id="board", title="B")))
        combo = QComboBox()
        window.params_panel._fill_page_refs(combo)
        assert [combo.itemData(i) for i in range(combo.count())] \
            == ["", "board"]


class TestACanvasOfItsOwn:
    """A Model canvas tab holds its own nodes: the same flow, drawn on
    another surface."""

    def test_a_node_added_there_belongs_to_that_canvas(self, window, flow):
        _source, inside, _after = flow
        window._add_page(CANVAS_KIND)
        page_id = window.page_bar.current_page_id()
        window._add_node_at(TABLE, QPointF(40, 40))
        added = next(n for n in window.graph.nodes.values()
                     if n.canvas == page_id)
        items = window.scene.node_items
        assert items[added.id].isVisible()
        assert not items[inside.id].isVisible()     # the model canvas's own
        window.page_bar.select_page(None)
        assert not items[added.id].isVisible()
        assert items[inside.id].isVisible()

    def test_canvases_round_trip_through_the_file(self, window, registry,
                                                   flow):
        window._add_page(CANVAS_KIND)
        page_id = window.page_bar.current_page_id()
        window._add_node_at(TABLE, QPointF(40, 40))
        window._push_new_shape("rect", QRectF(0, 0, 80, 60))
        data = graph_to_dict(window.graph)
        back = graph_from_dict(data, registry)
        assert sorted(n.canvas for n in back.nodes.values()) == \
            sorted(n.canvas for n in window.graph.nodes.values())
        assert [s.canvas for s in back.shapes.values()] == [page_id]
        assert [f.canvas for f in back.frames.values()] == [""]

    def test_a_frame_never_holds_another_canvas_s_nodes(self, window, flow):
        """Canvases share one coordinate space, so a frame on the model
        canvas sits over the same (100, 100) as a node on another one."""
        window._add_page(CANVAS_KIND)
        window._add_node_at(TABLE, QPointF(100, 100))
        held = window._frame_node_ids_by_id("f1")
        assert [window.graph.nodes[nid].canvas for nid in held] == [""]

    def test_goto_and_from_reach_across_canvases(self, window, registry):
        goto = registry.instantiate("flograph.util.goto", pos=(0, 0))
        window.graph.add_node(goto)
        window._add_page(CANVAS_KIND)
        page_id = window.page_bar.current_page_id()
        window._add_node_at("flograph.util.goto_from", QPointF(0, 0))
        taker = next(n for n in window.graph.nodes.values()
                     if n.canvas == page_id)
        window.undo_stack.push(SetParamCommand(window.graph, taker.id,
                                               "source", goto.id))
        links = list(window.graph.links.values())
        assert [(l.src_node, l.dst_node) for l in links] == \
            [(goto.id, taker.id)]

    def test_the_navigator_tree_is_the_canvas_being_shown(self, window, flow):
        _source, inside, _after = flow
        window._add_page(CANVAS_KIND)
        page_id = window.page_bar.current_page_id()
        window._add_node_at(TABLE, QPointF(40, 40))
        added = next(n.id for n in window.graph.nodes.values()
                     if n.canvas == page_id)
        top_nodes, _frames, _tree = window.scene.canvas_outline()
        assert added in top_nodes and inside.id not in top_nodes


class TestAModelCanvasTab:
    """+ ▸ Model canvas: another tab onto the whole canvas, at a zoom and
    place of its own."""

    def test_plus_offers_one(self, window):
        _menu, choices = window.page_bar._add_menu()
        by_text = {action.text(): kind for action, kind in choices.items()}
        assert by_text["Model canvas"] == CANVAS_KIND
        assert list(by_text)[0] == "Dashboard page"    # still the default

    def test_it_is_the_whole_canvas_with_a_place_of_its_own(self, window,
                                                             flow):
        source, _inside, _after = flow
        window.set_minimap_enabled(True)
        view = window.view
        view.set_zoom(0.5)
        window._add_page(CANVAS_KIND)
        page_id = window.page_bar.current_page_id()
        page = window.graph.pages[page_id]
        assert (page.kind, page.frame, page.title) == (CANVAS_KIND, "",
                                                      "Model 2")
        assert window._canvas_stack.currentWidget() is view
        assert view.fence_frame is None and view.fence_stubs() == []
        assert not view.minimap.isHidden()
        assert not window._docks_away()
        assert view.zoom == pytest.approx(0.5)     # opens where it was made
        view.set_zoom(1.3)
        window.page_bar.select_page(None)
        assert view.zoom == pytest.approx(0.5)
        window.page_bar.select_page(page_id)
        assert view.zoom == pytest.approx(1.3)
        window._go_to_node(source.id)              # nothing to escape from
        assert window.page_bar.current_page_id() == page_id

    def test_the_model_tab_is_their_header(self, window, flow):
        """Canvas tabs fold away under the **Model** tab itself, rather than
        under a header tab repeating a name the bar already carries."""
        bar = window.page_bar
        model_index = bar._model_index()
        assert bar.tabText(model_index) == "Model"   # nothing to head yet
        window._add_page(CANVAS_KIND)
        page_id = bar.current_page_id()
        assert bar.tabText(model_index).startswith("▾")
        bar.select_page(None)                        # off the folding tab
        bar.toggle_model_fold()
        assert bar.tabText(model_index).startswith("▸")
        assert "1" in bar.tabText(model_index)       # how many are away
        assert not bar.isTabVisible(bar._index_of_page(page_id))
        bar.toggle_model_fold()
        assert bar.isTabVisible(bar._index_of_page(page_id))
        assert bar.tabText(model_index).startswith("▾")

    def test_dragging_a_page_leaves_the_canvases_folded(self, window):
        """0.1.15 #11: "dragging around pages to reorder them causes the
        model to expand and makes the dragging annoying."

        A drag changes which tab is current, which runs `_apply_folds` —
        and that knew about a *section's* fold but not the Model tab's, so
        every canvas tab came back onto the bar mid-drag and the tabs
        shuffled under the pointer. Both folds are one decision now
        (`_folded_away`).
        """
        bar = window.page_bar
        for i in range(3):
            window.undo_stack.push(AddPageCommand(
                window.graph, Page(id=f"pp{i}", title=f"Page {i}")))
        window._add_page(CANVAS_KIND)
        canvas_id = bar.current_page_id()
        bar.select_page("pp0")
        bar.toggle_model_fold()
        assert not bar.isTabVisible(bar._index_of_page(canvas_id))

        # drive the drag the way Qt does: move the tab, and let the bar
        # react to each step through the signal it connects
        bar._dragged = "pp0"
        for target in (bar._index_of_page("pp0") + 1,
                       bar._index_of_page("pp0") + 2):
            bar.moveTab(bar._index_of_page("pp0"), target)
            bar._on_tab_moved(target - 1, target)
            assert not bar.isTabVisible(bar._index_of_page(canvas_id)), \
                "the canvases unfolded mid-drag"
        bar._dragged = None
        bar._rebuild_groups()
        assert bar.model_folded() is True
        assert not bar.isTabVisible(bar._index_of_page(canvas_id))

    def test_applying_the_folds_alone_does_not_unfold_them(self, window):
        """The narrowest statement of the same bug, so a future caller of
        `_apply_folds` cannot bring it back."""
        bar = window.page_bar
        window.undo_stack.push(AddPageCommand(
            window.graph, Page(id="pp0", title="Page 0")))
        window._add_page(CANVAS_KIND)
        canvas_id = bar.current_page_id()
        bar.select_page("pp0")
        bar.toggle_model_fold()
        bar._apply_folds()
        assert not bar.isTabVisible(bar._index_of_page(canvas_id))

    def test_the_canvas_tab_being_looked_at_still_shows_through(self, window):
        """The fold hides the others, never the one you are on — that is
        what `_apply_folds` is *for*, and it still does it."""
        bar = window.page_bar
        window._add_page(CANVAS_KIND)
        canvas_id = bar.current_page_id()
        bar.toggle_model_fold()
        assert bar.isTabVisible(bar._index_of_page(canvas_id))

    def test_a_folded_section_is_unaffected_by_the_shared_rule(self, window):
        """The other half of `_folded_away`, still working."""
        bar = window.page_bar
        for i in range(2):
            window.undo_stack.push(AddPageCommand(
                window.graph, Page(id=f"pp{i}", title=f"P{i}",
                                   group="Sales")))
        bar.select_page("pp0")
        bar.set_group_folded("Sales", True)
        assert bar.isTabVisible(bar._index_of_page("pp0"))     # the current
        assert not bar.isTabVisible(bar._index_of_page("pp1"))

    def test_a_canvas_tab_is_the_model_tab_s_and_nothing_else_s(self, window):
        """One header per tab (Dan): a canvas tab is never offered a group
        of its own, and folding the Model tab is what puts it away."""
        bar = window.page_bar
        window._add_page(CANVAS_KIND)
        page_id = bar.current_page_id()
        index = bar._index_of_page(page_id)
        texts = [a.text() for a in bar._context_menu(index, page_id).actions()]
        assert "Group" not in texts
        bar.select_page(None)
        assert bar._canvas_tabs() == [index]
        bar.toggle_model_fold()
        assert not bar.isTabVisible(bar._index_of_page(page_id))
        bar.toggle_model_fold()
        assert bar.isTabVisible(bar._index_of_page(page_id))

    def test_canvas_tabs_reorder_only_among_themselves(self, window):
        """They sit next to the Model tab that heads them: a drag moves one
        within the run rather than out of it (Dan)."""
        bar = window.page_bar
        window._add_page(CANVAS_KIND)
        first = bar.current_page_id()
        window._add_page(CANVAS_KIND)
        second = bar.current_page_id()
        window.undo_stack.push(AddPageCommand(
            window.graph, Page(id="board", title="Board")))
        assert bar.page_order() == [first, second, "board"]

        # dragged out past the dashboard — and put straight back in the run
        bar.moveTab(bar._index_of_page(first), bar._index_of_page("board"))
        assert bar.page_order() == [second, first, "board"]

    def test_the_model_menu_heading_nothing_offers_only_a_new_page(self, window):
        """With no canvas tabs there is nothing to list and nothing to
        fold, so neither is offered — it used to offer the fold regardless
        (Dan). What is left is New ▸, because the Model tab is the one tab
        every project has and so the one place a right-click can always be
        relied on to make a page (0.1.15 #10)."""
        bar = window.page_bar
        assert bar._canvas_tabs() == []
        menu = bar._model_menu()
        assert [a.text() for a in menu.actions() if not a.isSeparator()] \
            == ["New"]

    def test_right_clicking_the_model_tab_lists_its_canvases(self, window):
        """Read what a group holds and go straight to a page, without
        unfolding it first."""
        bar = window.page_bar
        window._add_page(CANVAS_KIND)
        page_id = bar.current_page_id()
        title = bar.tabText(bar._index_of_page(page_id))
        bar.select_page(None)
        bar.toggle_model_fold()                       # folded away
        menu = bar._model_menu()
        texts = [action.text() for action in menu.actions()]
        assert title in texts
        assert "Show the canvases" in texts
        next(a for a in menu.actions() if a.text() == title).trigger()
        assert bar.current_page_id() == page_id       # reached while folded

    def test_a_group_header_lists_its_pages_too(self, window):
        bar = window.page_bar
        window.undo_stack.push(AddPageCommand(
            window.graph, Page(id="p_sales", title="Sales")))
        window._set_page_group("p_sales", "Reports", None)
        bar.set_group_folded("Reports", True)
        bar.select_page(None)
        menu = bar._group_menu("Reports")
        texts = [action.text() for action in menu.actions()]
        assert "Sales" in texts and "Unfold" in texts
        next(a for a in menu.actions() if a.text() == "Sales").trigger()
        assert bar.current_page_id() == "p_sales"

    def test_its_menu_closes_it_and_can_copy_it(self, window):
        """A canvas of its own can be duplicated — contents and all — unlike
        a tab that only looks at a frame. Neither is locked or scaled."""
        window._add_page(CANVAS_KIND)
        page_id = window.page_bar.current_page_id()
        index = window.page_bar._index_of_page(page_id)
        texts = [a.text() for a in
                 window.page_bar._context_menu(index, page_id).actions()]
        assert "Close Tab" in texts and "Duplicate" in texts
        assert "Locked" not in texts
        assert "Scale to fit the window" not in texts

    def test_it_can_be_duplicated_with_what_is_on_it(self, window, registry,
                                                      monkeypatch):
        window._add_page(CANVAS_KIND)
        page_id = window.page_bar.current_page_id()
        window._add_node_at(TABLE, QPointF(0, 0))
        window._add_node_at(FILTER, QPointF(300, 0))
        a, b = [n for n in window.graph.nodes.values() if n.canvas == page_id]
        window.graph.connect(a.id, "table", b.id, "table")
        window._duplicate_page(page_id)
        copy_id = window.page_bar.current_page_id()
        assert copy_id != page_id
        copied = [n for n in window.graph.nodes.values()
                  if n.canvas == copy_id]
        assert len(copied) == 2
        assert len(window.graph.connections) == 2   # the wire came across
        assert window.graph.pages[copy_id].kind == CANVAS_KIND

    def test_closing_it_takes_its_nodes(self, window, monkeypatch):
        monkeypatch.setattr(mw.QMessageBox, "question",
                            lambda *a, **k: mw.QMessageBox.Yes)
        window._add_page(CANVAS_KIND)
        page_id = window.page_bar.current_page_id()
        window._add_node_at(TABLE, QPointF(0, 0))
        node_id = next(n.id for n in window.graph.nodes.values()
                       if n.canvas == page_id)
        window._delete_page(page_id)
        assert page_id not in window.graph.pages
        assert node_id not in window.graph.nodes
        window.undo_stack.undo()                    # one step brings it back
        assert page_id in window.graph.pages
        assert node_id in window.graph.nodes

    def test_a_frame_tab_and_a_model_tab_are_told_apart(self, window, flow):
        window._add_page(CANVAS_KIND)
        whole = window.page_bar.current_page_id()
        fenced = _open(window)
        assert fenced != whole                      # its own tab, not this one
        assert window._frame_tab_of("f1") == fenced
        window.page_bar.select_page(whole)
        assert window.view.fence_frame is None
        window.page_bar.select_page(fenced)
        assert window.view.fence_frame == "f1"


# ------------------------------------------------- 0.1.15 #3 and #4
#
# "Can we save open and collapse status of the report/dashboard/model
# groups?" and "model canvas pages don't seem to save and restore your
# viewport position on .flograph file reopen?"
#
# Both are how the bar and its canvases were *left*, and both were runtime
# only — the fold said so in its own comment ("Bar state, not saved"), and
# the viewport was kept in a dict the window cleared on open. They travel
# in the file now, for the same reason `view_mode` and `fit_to_window` do:
# a project should open the way it was left, for whoever opens it.
#
# Deliberately *not* on the undo stack. Folding a section or panning a
# canvas is not a change to the project, and marking it modified would ask
# you to save for having looked at something. So the window writes them as
# it saves and reads them as it opens, and a fold you never save is one you
# keep for the session only.

class TestHowTheBarWasLeftIsSaved:

    def _project(self, window, tmp_path):
        """(path to save to, the frame tab's page id) for a project with a
        canvas tab and a grouped pair of dashboard pages."""
        window.undo_stack.push(AddPageCommand(
            window.graph, Page(id="board", title="Board", group="Sales")))
        window.undo_stack.push(AddPageCommand(
            window.graph, Page(id="board2", title="Board 2", group="Sales")))
        return str(tmp_path / "p.flograph"), _open(window)

    def test_a_folded_section_comes_back_folded(self, window, flow, tmp_path):
        _path, _tab = self._project(window, tmp_path)
        window.page_bar.set_group_folded("Sales", True)
        window._capture_view_state()
        assert window.graph.folded_page_groups == {"Sales"}
        reloaded = graph_from_dict(graph_to_dict(window.graph),
                                   window.registry)
        assert reloaded.folded_page_groups == {"Sales"}

    def test_an_unfolded_one_says_nothing_at_all(self, window, flow,
                                                 tmp_path):
        """A project nobody has folded is written as it always was."""
        _path, _tab = self._project(window, tmp_path)
        window._capture_view_state()
        data = graph_to_dict(window.graph)["graph"]
        assert "folded_page_groups" not in data
        assert "canvases_folded" not in data

    def test_the_model_tabs_own_fold_is_saved_too(self, window, flow,
                                                  tmp_path):
        _path, _tab = self._project(window, tmp_path)
        window.page_bar.toggle_model_fold()
        assert window.page_bar.model_folded() is True
        window._capture_view_state()
        reloaded = graph_from_dict(graph_to_dict(window.graph),
                                   window.registry)
        assert reloaded.canvases_folded is True

    def test_a_fold_on_a_group_with_no_pages_left_is_dropped(self, window,
                                                             flow, tmp_path):
        """The same rule its colour follows — it would otherwise come back,
        unasked, on the next group given that name."""
        _path, _tab = self._project(window, tmp_path)
        window.page_bar.set_group_folded("Sales", True)
        window._set_page_group("board", "")
        window._set_page_group("board2", "")
        window._capture_view_state()
        data = graph_to_dict(window.graph)["graph"]
        assert "folded_page_groups" not in data

    def test_where_each_canvas_tab_was_looking_is_saved(self, window, flow,
                                                       tmp_path):
        _path, page_id = self._project(window, tmp_path)
        window.page_bar.select_page(None)
        window.view.set_zoom(0.5)
        window.view.centerOn(120.0, -40.0)
        window._capture_view_state()
        views = window.graph.canvas_views
        assert "" in views, "the model canvas has no Page, so it keys on ''"
        zoom, x, y = views[""]
        assert zoom == pytest.approx(0.5)
        assert x == pytest.approx(120.0, abs=2)
        assert y == pytest.approx(-40.0, abs=2)

    def test_each_tab_keeps_its_own(self, window, flow, tmp_path):
        _path, page_id = self._project(window, tmp_path)
        window.page_bar.select_page(None)
        window.view.set_zoom(0.5)
        window.page_bar.select_page(page_id)
        window.view.set_zoom(1.5)
        window._capture_view_state()
        assert window.graph.canvas_views[""][0] == pytest.approx(0.5)
        assert window.graph.canvas_views[page_id][0] == pytest.approx(1.5)

    def test_a_view_for_a_page_that_has_gone_is_not_written(self, window,
                                                            flow, tmp_path):
        _path, _tab = self._project(window, tmp_path)
        window.graph.canvas_views["ghost"] = (1.0, 5.0, 5.0)
        data = graph_to_dict(window.graph)["graph"]
        assert "ghost" not in data.get("canvas_views", {})

    def test_reopening_puts_the_view_back(self, window, flow, tmp_path):
        """End to end, through a real save and a real open."""
        path, _tab = self._project(window, tmp_path)
        window.page_bar.select_page(None)
        window.view.set_zoom(0.4)
        window.view.centerOn(300.0, 200.0)
        window.page_bar.set_group_folded("Sales", True)
        window._capture_view_state()
        serialization.save(window.graph, path)

        window.open_path(path, confirm=False)
        assert window.page_bar.folded_groups() == {"Sales"}
        assert window.view.zoom == pytest.approx(0.4)
        centre = window.view.view_state()[1]
        assert centre.x() == pytest.approx(300.0, abs=1)
        assert centre.y() == pytest.approx(200.0, abs=1)

    def test_saving_and_reopening_over_and_over_does_not_walk(
            self, window, flow, tmp_path):
        """It used to lose one scroll step per cycle — 2.5 scene units at
        this zoom, every time the project was opened. `QRect::center()`
        truncates, so the centre read back out of the view was half a pixel
        off the one `centerOn` had been given, and saving that back asked
        for a point that landed a step further along. See
        `ZoomPanGraphicsView.viewport_centre`."""
        path, _tab = self._project(window, tmp_path)
        window.page_bar.select_page(None)
        window.view.set_zoom(0.4)
        window.view.centerOn(300.0, 200.0)
        first = None
        for _ in range(5):
            window._capture_view_state()
            serialization.save(window.graph, path)
            window.open_path(path, confirm=False)
            centre = window.view.view_state()[1]
            if first is None:
                first = centre
            assert centre.x() == pytest.approx(first.x(), abs=1)
            assert centre.y() == pytest.approx(first.y(), abs=1)
            assert window.view.zoom == pytest.approx(0.4)

    def test_a_project_saved_before_this_opens_at_the_old_defaults(
            self, window, flow, tmp_path):
        path, _tab = self._project(window, tmp_path)
        serialization.save(window.graph, path)
        # strip the keys, the way a file written by 0.1.14 has none
        import json
        with open(path) as fh:
            data = json.load(fh)
        for key in ("folded_page_groups", "canvases_folded", "canvas_views"):
            data["graph"].pop(key, None)
        with open(path, "w") as fh:
            json.dump(data, fh)
        window.open_path(path, confirm=False)
        assert window.page_bar.folded_groups() == set()
        assert window.page_bar.model_folded() is False

    def test_folding_a_section_does_not_mark_the_project_modified(
            self, window, flow, tmp_path):
        """The whole reason this is not a command: tidying the bar must not
        ask you to save."""
        _path, _tab = self._project(window, tmp_path)
        clean = window.undo_stack.index()
        window.page_bar.set_group_folded("Sales", True)
        window.page_bar.toggle_model_fold()
        assert window.undo_stack.index() == clean

    def test_nor_does_panning_a_canvas(self, window, flow, tmp_path):
        _path, _tab = self._project(window, tmp_path)
        clean = window.undo_stack.index()
        window.view.set_zoom(0.3)
        window.view.centerOn(999.0, 999.0)
        assert window.undo_stack.index() == clean
