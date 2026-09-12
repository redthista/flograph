"""Chunk AB: getting around a dashboard.

AB1 a Note placed on a dashboard page; AB2 an Action Button that goes to a
page; AB3 a Page Links card; AB4 sections in the page tab bar.

Settings kept off the real store (avoid polluting the developer's actual
flograph.conf) -- see test_lod_settings.py's fixture of the same name."""
import pytest
from PySide6.QtCore import QEvent, QPointF, QRectF, QSettings, Qt
from PySide6.QtGui import QImage, QMouseEvent, QPainter
from PySide6.QtTest import QTest

from flograph.core import Graph, Page, ParamSpec, Tile
from flograph.core.page_nav import (
    SHOW_CHOSEN, SHOW_EVERY, SHOW_GROUP, gather_groups, group_names,
    join_page_ids, linked_pages, order_after_regroup, page_for_link,
    split_page_ids,
)
from flograph.ui.page_links import link_rects
from flograph.core.serialization import graph_from_dict, graph_to_dict
from flograph.ui import mainwindow as mw
from flograph.ui.canvas.node_item import NOTE_PAD
from flograph.ui.commands import (
    AddPageCommand, AddTileCommand, RemovePageCommand, SetParamCommand,
)
from flograph.ui.dashboard.tile_item import (
    NOTE_MIN_H, NOTE_MIN_W, default_tile_port, default_tile_size,
    is_tile_able,
)
from flograph.ui.mainwindow import MainWindow

BUTTON = "flograph.util.action_button"
NOTE = "flograph.util.note"


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


def _pages(window, *titles):
    ids = []
    for i, title in enumerate(titles):
        page = Page(id=f"p{i}", title=title)
        window.undo_stack.push(AddPageCommand(window.graph, page))
        ids.append(page.id)
    return ids


def _node(window, type_id, **params):
    node = window.registry.instantiate(type_id, pos=(0.0, 0.0))
    node.params.update(params)
    window.graph.add_node(node)
    return node


def _place(window, page_id, node, tile_id="t1"):
    width, height = default_tile_size(node)
    window.undo_stack.push(AddTileCommand(window.graph, page_id, Tile(
        id=tile_id, node_id=node.id, port=default_tile_port(node),
        rect=(0.0, 0.0, width, height))))
    return window._dashboard_pages[page_id].scene.tile_items[tile_id]


def _row_widget(panel, label):
    for i in range(panel.tree.topLevelItemCount()):
        item = panel.tree.topLevelItem(i)
        if item.text(0) == label:
            return panel.tree.itemWidget(item, 1)
    raise LookupError(f"no {label!r} row")


class _Mouse:
    """Duck-typed stand-in for a QGraphicsSceneMouseEvent — enough for the
    branches of the tile's handlers that return before super()."""

    def __init__(self, pos, button=Qt.LeftButton):
        self._pos = QPointF(pos)
        self._button = button
        self.accepted = False

    def button(self):
        return self._button

    def modifiers(self):
        return Qt.NoModifier

    def pos(self):
        return self._pos

    def scenePos(self):
        return self._pos

    def accept(self):
        self.accepted = True


# ---------------------------------------------------- AB2 a page param

class TestAPageParam:
    def test_one_page_unless_it_says_otherwise(self):
        assert ParamSpec.from_dict({"name": "p", "type": "page_ref"}).multi is False
        assert ParamSpec.from_dict(
            {"name": "p", "type": "page_ref", "multi": True}).multi is True
        # and a columns param is still a list by default
        assert ParamSpec.from_dict({"name": "c", "type": "columns"}).multi is True

    def test_a_set_of_pages_is_a_comma_list(self):
        assert split_page_ids(" a, b ,,c") == ["a", "b", "c"]
        assert split_page_ids("") == split_page_ids(None) == []
        assert join_page_ids(["a", "b"]) == "a,b"


class TestGoToPage:
    def test_the_button_offers_it(self, registry):
        spec = registry.get(BUTTON)
        assert "Go to page" in spec.param("action").options
        page = spec.param("page")
        assert page.type == "page_ref" and page.multi is False
        assert page.visible_for({"action": "Go to page"})
        assert not page.visible_for({"action": "Run nodes"})
        # and the rows for the other actions step aside
        assert not spec.param("targets").visible_for({"action": "Go to page"})
        assert not spec.param("clear_cache").visible_for({"action": "Go to page"})
        assert spec.param("clear_cache").visible_for({"action": "Run frame"})

    def test_a_click_goes_there(self, window):
        ids = _pages(window, "Sales", "Costs")
        window.page_bar.select_page(None)
        node = _node(window, BUTTON, action="Go to page", page=ids[1])
        window._on_button_fired(node.id)
        assert window.page_bar.current_page_id() == ids[1]
        assert window._current_page_id == ids[1]

    def test_it_runs_nothing(self, window, monkeypatch):
        ids = _pages(window, "Sales")
        node = _node(window, BUTTON, action="Go to page", page=ids[0])
        ran = []
        monkeypatch.setattr(window.engine, "run_targets",
                            lambda *a: ran.append(a))
        window._on_button_fired(node.id)
        assert ran == []

    def test_a_deleted_page_says_so(self, window, monkeypatch):
        _pages(window, "Sales")
        window.page_bar.select_page(None)
        node = _node(window, BUTTON, action="Go to page", page="gone")
        said = []
        monkeypatch.setattr(window, "show_status",
                            lambda text, *a: said.append(text))
        window._on_button_fired(node.id)
        assert window.page_bar.current_page_id() is None
        assert said and "deleted" in said[0]

    def test_the_tile_says_where_it_goes(self, window):
        ids = _pages(window, "Sales", "Costs")
        node = _node(window, BUTTON, action="Go to page", page=ids[1])
        item = _place(window, ids[0], node)
        assert item.toolTip().startswith("Click to go to Costs")
        window.undo_stack.push(
            SetParamCommand(window.graph, node.id, "action", "Run nodes"))
        assert item.toolTip().startswith("Click to run")


class TestThePagePicker:
    def test_it_lists_the_pages_by_title_and_stores_the_id(self, window):
        ids = _pages(window, "Sales", "Costs")
        node = _node(window, BUTTON, action="Go to page")
        window.params_panel.set_node(node.id)
        combo = _row_widget(window.params_panel, "Page")
        assert [combo.itemText(i) for i in range(combo.count())] == \
            ["— none —", "Sales", "Costs"]
        combo.setCurrentIndex(2)
        combo.activated.emit(2)   # what a user's pick emits
        assert node.params["page"] == ids[1]

    def test_a_page_added_later_is_offered(self, window):
        _pages(window, "Sales")
        node = _node(window, BUTTON, action="Go to page")
        window.params_panel.set_node(node.id)
        combo = _row_widget(window.params_panel, "Page")
        window.undo_stack.push(
            AddPageCommand(window.graph, Page(id="late", title="Late")))
        combo.showPopup()
        combo.hidePopup()
        assert combo.itemText(combo.count() - 1) == "Late"

    def test_a_deleted_page_stays_visible(self, window):
        node = _node(window, BUTTON, action="Go to page", page="gone")
        window.params_panel.set_node(node.id)
        assert _row_widget(window.params_panel, "Page").currentText() == \
            "⚠ missing"

    def test_only_shown_for_go_to_page(self, window):
        node = _node(window, BUTTON, action="Run nodes")
        window.params_panel.set_node(node.id)
        with pytest.raises(LookupError):
            _row_widget(window.params_panel, "Page")


# ------------------------------------------------------ AB1 notes on pages

class TestANoteOnAPage:
    def test_a_note_can_be_placed(self, window):
        node = _node(window, NOTE)
        assert is_tile_able(node)
        assert default_tile_port(node) is None

    def test_it_lands_as_tall_as_its_text(self, window):
        short = _node(window, NOTE, text="## Heading")
        long = _node(window, NOTE, text="## Heading\n\n"
                     + "\n\n".join(["A line of text."] * 8))
        width, height = default_tile_size(short)
        assert width == 280
        assert NOTE_MIN_H <= height < default_tile_size(long)[1]

    def test_a_height_it_was_given_is_kept(self, window):
        node = _node(window, NOTE, height=300)
        assert default_tile_size(node) == (280, 300)

    def test_it_is_the_text_not_a_card(self, window):
        ids = _pages(window, "Board")
        item = _place(window, ids[0], _node(window, NOTE))
        assert item._kind() == "note"
        assert item._proxy.isVisible() is False   # no widget inside
        assert not item.can_fullscreen()
        assert item._min_size() == (NOTE_MIN_W, NOTE_MIN_H)

    def test_it_paints_its_text(self, window):
        ids = _pages(window, "Board")
        item = _place(window, ids[0], _node(window, NOTE))
        image = QImage(280, 80, QImage.Format_ARGB32)
        image.fill(0)
        painter = QPainter(image)
        item.scene().render(painter, QRectF(image.rect()),
                            item.sceneBoundingRect())
        painter.end()
        colours = {image.pixel(x, y) for x in range(0, 280, 2)
                   for y in range(0, 80, 2)}
        assert len(colours) > 4   # a body, a border and text, at least

    def test_an_edit_reaches_the_tile(self, window):
        ids = _pages(window, "Board")
        node = _node(window, NOTE, text="old words")
        item = _place(window, ids[0], node)
        assert "old words" in item._note_document().toPlainText()
        window.undo_stack.push(
            SetParamCommand(window.graph, node.id, "text", "new words"))
        assert "new words" in item._note_document().toPlainText()

    def test_it_reflows_to_the_tile(self, window):
        ids = _pages(window, "Board")
        item = _place(window, ids[0], _node(window, NOTE))
        item._size = (500.0, item._size[1])
        assert item._note_document().textWidth() == 500 - 2 * NOTE_PAD

    def test_the_body_is_the_handle(self, window):
        ids = _pages(window, "Board")
        item = _place(window, ids[0], _node(window, NOTE, text="## Sales"))
        item._apply_edge_cursor(QPointF(40, 20))
        assert item.cursor().shape() == Qt.SizeAllCursor
        item.set_layout_locked(True)
        item._apply_edge_cursor(QPointF(40, 20))
        assert item.cursor().shape() == Qt.ArrowCursor

    def _link_point(self, item):
        for x in range(0, 200, 2):
            point = QPointF(x, NOTE_PAD + 8)
            if item._note_link_at(point):
                return point
        raise AssertionError("no link found on the first line")

    def test_a_link_opens_on_a_click(self, window, monkeypatch):
        ids = _pages(window, "Board")
        item = _place(window, ids[0], _node(
            window, NOTE, text="[the site](https://example.com) and more"))
        opened = []
        monkeypatch.setattr(item, "_open_note_link", opened.append)
        point = self._link_point(item)
        press = _Mouse(point)
        item.mousePressEvent(press)
        assert press.accepted and not item.isSelected()
        item.mouseReleaseEvent(_Mouse(point))
        assert opened == ["https://example.com"]

    def test_a_link_still_opens_on_a_locked_page(self, window, monkeypatch):
        ids = _pages(window, "Board")
        item = _place(window, ids[0], _node(
            window, NOTE, text="[the site](https://example.com)"))
        item.set_layout_locked(True)
        opened = []
        monkeypatch.setattr(item, "_open_note_link", opened.append)
        point = self._link_point(item)
        item.mousePressEvent(_Mouse(point))
        item.mouseReleaseEvent(_Mouse(point))
        assert opened == ["https://example.com"]

    def test_a_press_that_wanders_off_opens_nothing(self, window, monkeypatch):
        ids = _pages(window, "Board")
        item = _place(window, ids[0], _node(
            window, NOTE, text="[the site](https://example.com)"))
        opened = []
        monkeypatch.setattr(item, "_open_note_link", opened.append)
        point = self._link_point(item)
        item.mousePressEvent(_Mouse(point))
        item.mouseReleaseEvent(_Mouse(point + QPointF(0, 40)))
        assert opened == []

    def test_the_visuals_list_marks_it(self):
        from flograph.ui.dashboard.visuals_list import _KIND_GLYPHS
        assert _KIND_GLYPHS["note"] == "¶"


# ----------------------------------------------------------- AB4 tab groups

class TestKeepingAGroupTogether:
    def test_a_group_is_gathered_where_it_starts(self):
        groups = {"a": "g", "c": "g"}
        assert gather_groups(["a", "b", "c", "d"], groups) == ["a", "c", "b", "d"]

    def test_no_groups_leaves_the_order_alone(self):
        assert gather_groups(["a", "b"], {}) == ["a", "b"]

    def test_joining_goes_to_the_end_of_the_run(self):
        order, groups = ["a", "b", "c", "d"], {"b": "g", "c": "g"}
        assert order_after_regroup(order, groups, "a", "g") == ["b", "c", "a", "d"]
        assert order_after_regroup(order, groups, "d", "g") == order

    def test_leaving_steps_out_past_the_run(self):
        groups = {"a": "g", "b": "g", "c": "g"}
        assert order_after_regroup(["a", "b", "c"], groups, "b", "") == \
            ["a", "c", "b"]

    def test_a_new_group_stays_where_it_is(self):
        assert order_after_regroup(["a", "b", "c"], {}, "b", "new") == \
            ["a", "b", "c"]

    def test_names_come_in_the_order_of_their_sections(self):
        assert group_names(["a", "b", "c"], {"a": "y", "b": "x", "c": "y"}) \
            == ["y", "x"]


class TestAGroupIsSaved:
    def test_only_a_grouped_page_says_so(self, registry):
        graph = Graph()
        graph.add_page(Page(id="p1", title="A", group="Sales"))
        graph.add_page(Page(id="p2", title="B"))
        data = graph_to_dict(graph)
        pages = (data.get("graph") or data)["pages"]
        assert pages[0]["group"] == "Sales"
        assert "group" not in pages[1]
        back = graph_from_dict(data, registry)
        assert back.pages["p1"].group == "Sales"
        assert back.pages["p2"].group == ""


def _shown(bar):
    return [bar.tabText(i) for i in range(bar.count()) if bar.isTabVisible(i)]


def _mouse(bar, kind, pos, button, buttons):
    handler = {QEvent.MouseButtonPress: bar.mousePressEvent,
               QEvent.MouseMove: bar.mouseMoveEvent,
               QEvent.MouseButtonRelease: bar.mouseReleaseEvent}[kind]
    handler(QMouseEvent(kind, pos, QPointF(bar.mapToGlobal(pos.toPoint())),
                        button, buttons, Qt.NoModifier))


def _press(bar, index, button=Qt.LeftButton):
    """A click on a tab: press and release in place."""
    pos = QPointF(bar.tabRect(index).center())
    _mouse(bar, QEvent.MouseButtonPress, pos, button, button)
    _mouse(bar, QEvent.MouseButtonRelease, pos, button, Qt.NoButton)


def _drag(bar, start, end):
    _mouse(bar, QEvent.MouseButtonPress, start, Qt.LeftButton, Qt.LeftButton)
    _mouse(bar, QEvent.MouseMove, QPointF(start.x() + 20, start.y()),
           Qt.NoButton, Qt.LeftButton)
    _mouse(bar, QEvent.MouseMove, end, Qt.NoButton, Qt.LeftButton)
    _mouse(bar, QEvent.MouseButtonRelease, end, Qt.LeftButton, Qt.NoButton)


def _header(bar):
    return next(i for i in range(bar.count())
                if bar.tabText(i)[:1] in ("▾", "▸"))


class TestTabGroups:
    def test_grouping_draws_a_section(self, window):
        ids = _pages(window, "A", "B", "C")
        window._set_page_group(ids[0], "Sales")
        window._set_page_group(ids[2], "Sales")
        assert list(window.graph.pages) == [ids[0], ids[2], ids[1]]
        assert _shown(window.page_bar) == \
            ["Model", "▾ Sales", "A", "C", "B", "+"]
        assert window.page_bar.page_order() == [ids[0], ids[2], ids[1]]

    def test_a_header_is_not_a_page(self, window):
        ids = _pages(window, "A")
        window._set_page_group(ids[0], "Sales")
        bar = window.page_bar
        header = _header(bar)
        assert not bar.isTabEnabled(header)   # the wheel steps over it
        assert not bar._is_page(header)
        assert bar.page_order() == ids

    def test_one_undo_puts_page_and_place_back(self, window):
        ids = _pages(window, "A", "B", "C")
        window._set_page_group(ids[0], "Sales")
        window._set_page_group(ids[2], "Sales")
        window.undo_stack.undo()
        assert window.graph.pages[ids[2]].group == ""
        assert list(window.graph.pages) == ids
        assert _shown(window.page_bar) == \
            ["Model", "▾ Sales", "A", "B", "C", "+"]

    def test_folding_keeps_the_page_being_looked_at(self, window):
        ids = _pages(window, "A", "B", "C")
        for page_id in ids[:2]:
            window._set_page_group(page_id, "Sales")
        bar = window.page_bar
        bar.select_page(ids[1])
        bar.set_group_folded("Sales", True)
        assert _shown(bar) == ["Model", "▸ Sales  2", "B", "C", "+"]
        bar.select_page(ids[2])
        assert _shown(bar) == ["Model", "▸ Sales  2", "C", "+"]
        # reached some other way — the tab list, a Go to page button
        bar.select_page(ids[0])
        assert bar.current_page_id() == ids[0]
        assert _shown(bar) == ["Model", "▸ Sales  2", "A", "C", "+"]

    def test_unfolding_gives_the_tabs_their_place_back(self, window, qtbot):
        """Dan, testing AB4: fold and unfold Finance and Costs came back
        "visible" with no place on the bar. Re-asserting the visibility of
        the tabs after it cancelled the relayout — see _set_visible."""
        ids = _pages(window, "A", "B", "C")
        window._set_page_group(ids[1], "Finance")
        window.show()
        qtbot.waitExposed(window)
        bar = window.page_bar
        for _ in range(2):
            bar.set_group_folded("Finance", True)
            bar.set_group_folded("Finance", False)
            index = bar._index_of_page(ids[1])
            assert bar.isTabVisible(index)
            assert bar.tabRect(index).width() > 0

    def test_a_click_on_the_header_folds_and_unfolds(self, window, qtbot):
        ids = _pages(window, "A", "B")
        for page_id in ids:
            window._set_page_group(page_id, "Sales")
        # a tab bar never shown has laid nothing out: every tabRect is empty
        window.show()
        qtbot.waitExposed(window)
        bar = window.page_bar
        _press(bar, _header(bar))
        assert bar.is_group_folded("Sales")
        assert _shown(bar) == ["Model", "▸ Sales  2", "+"]
        _press(bar, _header(bar))
        assert not bar.is_group_folded("Sales")
        assert bar.current_page_id() is None   # it switched, not selected

    def _grouped(self, window, qtbot):
        """A, [Sales: B, C], D — on screen, so the tabs have places."""
        ids = _pages(window, "A", "B", "C", "D")
        window._set_page_group(ids[1], "Sales")
        window._set_page_group(ids[2], "Sales")
        window.show()
        qtbot.waitExposed(window)
        return ids, window.page_bar

    def test_a_header_drags_its_whole_group(self, window, qtbot):
        """Dan, testing AB4: move a group the way a page tab moves."""
        ids, bar = self._grouped(window, qtbot)
        start = QPointF(bar.tabRect(_header(bar)).center())
        end = QPointF(bar.tabRect(bar._index_of_page(ids[3])).right() + 4,
                      start.y())
        _drag(bar, start, end)
        assert list(window.graph.pages) == [ids[0], ids[3], ids[1], ids[2]]
        assert _shown(bar) == ["Model", "A", "D", "▾ Sales", "B", "C", "+"]
        assert not bar.is_group_folded("Sales")   # a drag is not a click
        window.undo_stack.undo()
        assert list(window.graph.pages) == ids

    def test_the_bar_moves_while_it_is_dragged(self, window, qtbot):
        """Dan: see it move live, the way a dragged page tab does — and the
        project only changes once, when it is dropped."""
        ids, bar = self._grouped(window, qtbot)
        start = QPointF(bar.tabRect(_header(bar)).center())
        end = QPointF(bar.tabRect(bar._index_of_page(ids[3])).right() + 4,
                      start.y())
        _mouse(bar, QEvent.MouseButtonPress, start, Qt.LeftButton,
               Qt.LeftButton)
        _mouse(bar, QEvent.MouseMove, QPointF(start.x() + 20, start.y()),
               Qt.NoButton, Qt.LeftButton)
        _mouse(bar, QEvent.MouseMove, end, Qt.NoButton, Qt.LeftButton)
        assert bar.page_order() == [ids[0], ids[3], ids[1], ids[2]]
        assert _shown(bar) == ["Model", "A", "D", "▾ Sales", "B", "C", "+"]
        assert list(window.graph.pages) == ids     # not until it's dropped
        _mouse(bar, QEvent.MouseButtonRelease, end, Qt.LeftButton,
               Qt.NoButton)
        assert list(window.graph.pages) == [ids[0], ids[3], ids[1], ids[2]]
        assert window.undo_stack.count() and \
            window.undo_stack.undoText() == "reorder pages"

    def test_dragged_there_and_back_changes_nothing(self, window, qtbot):
        ids, bar = self._grouped(window, qtbot)
        start = QPointF(bar.tabRect(_header(bar)).center())
        far = QPointF(bar.tabRect(bar._index_of_page(ids[3])).right() + 4,
                      start.y())
        before = window.undo_stack.count()
        _mouse(bar, QEvent.MouseButtonPress, start, Qt.LeftButton,
               Qt.LeftButton)
        _mouse(bar, QEvent.MouseMove, far, Qt.NoButton, Qt.LeftButton)
        back = QPointF(bar.tabRect(bar._index_of_page(ids[0])).left() + 2,
                       start.y())
        _mouse(bar, QEvent.MouseMove, back, Qt.NoButton, Qt.LeftButton)
        _mouse(bar, QEvent.MouseMove, start, Qt.NoButton, Qt.LeftButton)
        _mouse(bar, QEvent.MouseButtonRelease, start, Qt.LeftButton,
               Qt.NoButton)
        assert list(window.graph.pages) == bar.page_order()

    def test_dragged_to_the_front(self, window, qtbot):
        ids, bar = self._grouped(window, qtbot)
        start = QPointF(bar.tabRect(_header(bar)).center())
        end = QPointF(bar.tabRect(bar._index_of_page(ids[0])).left() + 2,
                      start.y())
        _drag(bar, start, end)
        assert list(window.graph.pages) == [ids[1], ids[2], ids[0], ids[3]]

    def test_it_never_lands_inside_another_group(self, window, qtbot):
        ids, bar = self._grouped(window, qtbot)
        window._set_page_group(ids[0], "Costs")
        window._set_page_group(ids[3], "Costs")   # joins A: A, D, [B, C]
        assert list(window.graph.pages) == [ids[0], ids[3], ids[1], ids[2]]
        sales = next(i for i in range(bar.count())
                     if bar.tabText(i) == "▾ Sales")
        start = QPointF(bar.tabRect(sales).center())
        # between A and D, which are one group
        end = QPointF(bar.tabRect(bar._index_of_page(ids[0])).right(),
                      start.y())
        _drag(bar, start, end)
        order = list(window.graph.pages)
        assert order in ([ids[1], ids[2], ids[0], ids[3]],
                         [ids[0], ids[3], ids[1], ids[2]])

    def test_a_tab_s_right_click_takes_the_focus(self, window, monkeypatch):
        """Dan, testing AB4: on Wayland a right press's context-menu event
        goes to the focus widget once the menu has closed, so the page
        below opened its own (a lone greyed Paste). The bar holds the focus
        before the menu and again after it — locking a page moves the
        focus to the page, which is how the first version still leaked."""
        ids = _pages(window, "A")
        bar = window.page_bar
        order = []
        monkeypatch.setattr(bar, "setFocus",
                            lambda *a: order.append("focus"))
        monkeypatch.setattr(bar, "_show_context_menu",
                            lambda *a: order.append("menu"))
        _mouse(bar, QEvent.MouseButtonPress,
               QPointF(bar.tabRect(bar._index_of_page(ids[0])).center()),
               Qt.RightButton, Qt.RightButton)
        assert order == ["focus", "menu", "focus"]

    def _stray(self):
        """The event from Dan's log: from the platform, for a point 9px
        above the page — the tab bar, where the right-click really was."""
        from PySide6.QtCore import QPoint
        from PySide6.QtGui import QContextMenuEvent

        class FromThePlatform(QContextMenuEvent):
            def spontaneous(self):
                return True
        return FromThePlatform(QContextMenuEvent.Mouse, QPoint(224, -9),
                               QPoint(245, 54))

    def test_the_page_ignores_a_right_click_that_is_not_on_it(self, window):
        from PySide6.QtCore import QPoint
        from PySide6.QtGui import QContextMenuEvent
        ids = _pages(window, "A")
        view = window._dashboard_pages[ids[0]].view
        shown = []
        view._show_canvas_menu = lambda event: shown.append(1)
        stray = self._stray()
        view.contextMenuEvent(stray)
        assert shown == [] and stray.isAccepted()
        # one sent by code (a test, a script) is taken at its word
        view.contextMenuEvent(QContextMenuEvent(
            QContextMenuEvent.Mouse, QPoint(224, -9), QPoint(245, 54)))
        assert shown == [1]

    def test_so_does_the_canvas(self, window):
        asked = []
        window.view.add_node_requested.connect(lambda *a: asked.append(a))
        window.view.contextMenuEvent(self._stray())
        assert asked == []

    def test_the_header_menu(self, window):
        ids = _pages(window, "A", "B")
        for page_id in ids:
            window._set_page_group(page_id, "Sales")
        menu = window.page_bar._group_menu("Sales")
        # the group's own pages come first (G13): reading what a section
        # holds — and reaching a page from it without unfolding — is what a
        # header's menu is asked for most
        assert [a.text() for a in menu.actions() if not a.isSeparator()] == \
            ["A", "B", "Fold away", "Rename group…", "Change colour…",
             "Ungroup"]
        # a group with a colour of its own can go back to borrowing one
        window._recolor_page_group("Sales", "#123456")
        menu = window.page_bar._group_menu("Sales")
        assert "Reset colour" in [a.text() for a in menu.actions()]

    def test_rename_and_ungroup(self, window):
        ids = _pages(window, "A", "B", "C")
        for page_id in ids[:2]:
            window._set_page_group(page_id, "Sales")
        window._rename_page_group("Sales", "Revenue")
        assert {window.graph.pages[p].group for p in ids[:2]} == {"Revenue"}
        assert "▾ Revenue" in _shown(window.page_bar)
        window._rename_page_group("Revenue", "")
        assert all(p.group == "" for p in window.graph.pages.values())
        assert _shown(window.page_bar) == ["Model", "A", "B", "C", "+"]

    def test_the_tab_menu_offers_the_groups(self, window):
        ids = _pages(window, "A", "B")
        window._set_page_group(ids[0], "Sales")
        bar = window.page_bar
        menu = bar._context_menu(bar._index_of_page(ids[1]), ids[1])
        group_menu = next(a.menu() for a in menu.actions()
                          if a.menu() is not None)
        assert group_menu.title() == "Group"
        assert [a.text() for a in group_menu.actions()
                if not a.isSeparator()] == ["No group", "Sales", "New group…"]
        asked = []
        bar.set_page_group_requested.connect(lambda *a: asked.append(a))
        next(a for a in group_menu.actions() if a.text() == "Sales").trigger()
        assert asked == [(ids[1], "Sales")]

    def test_the_tab_list_heads_each_section(self, window):
        ids = _pages(window, "A", "B", "C")
        window._set_page_group(ids[1], "Sales")
        menu = window.page_bar.tab_list_menu()
        assert [("-" if a.isSeparator() else a.text())
                for a in menu.actions()] == \
            ["Model", "A", "-", "Sales", "B", "-", "C"]

    def test_a_drag_out_of_a_group_goes_back_in(self, window):
        ids = _pages(window, "A", "B", "C")
        for page_id in ids[:2]:
            window._set_page_group(page_id, "Sales")
        # C dropped between the two Sales pages: gathered straight back
        window._reorder_pages([ids[0], ids[2], ids[1]])
        assert list(window.graph.pages) == ids
        assert window.page_bar.page_order() == ids
        # a move that keeps the group whole is taken as it is
        window._reorder_pages([ids[2], ids[0], ids[1]])
        assert list(window.graph.pages) == [ids[2], ids[0], ids[1]]

    def test_a_copy_joins_its_group(self, window):
        ids = _pages(window, "A", "B")
        window._set_page_group(ids[0], "Sales")
        window._duplicate_page(ids[0])
        order = list(window.graph.pages)
        copy = next(p for p in order if p not in ids)
        assert order == [ids[0], copy, ids[1]]
        assert window.graph.pages[copy].group == "Sales"
        assert window.page_bar.current_page_id() == copy
        window.undo_stack.undo()   # one step for the copy and its move
        assert list(window.graph.pages) == ids

    def test_the_last_page_of_a_group_takes_its_header(self, window):
        ids = _pages(window, "A", "B")
        window._set_page_group(ids[0], "Sales")
        window.undo_stack.push(RemovePageCommand(window.graph, ids[0]))
        assert _shown(window.page_bar) == ["Model", "B", "+"]


class TestAGroupsColour:
    """Dan, testing AB4: a colour for a group, chosen when it is made and
    changeable after, that leaves the pages' own colours alone."""

    def test_made_with_a_colour_in_one_step(self, window):
        ids = _pages(window, "A", "B")
        before = window.undo_stack.count()
        window._set_page_group(ids[1], "Sales", "#2563eb")
        assert window.graph.pages[ids[1]].group == "Sales"
        assert window.graph.page_group_colors == {"Sales": "#2563eb"}
        assert window.page_bar._group_color("Sales").name() == "#2563eb"
        assert window.undo_stack.count() == before + 1
        window.undo_stack.undo()
        assert window.graph.pages[ids[1]].group == ""
        assert window.graph.page_group_colors == {}

    def test_it_leaves_the_pages_colours_alone(self, window):
        ids = _pages(window, "A")
        window._recolor_page(ids[0], "#b45309")
        window._set_page_group(ids[0], "Sales", "#2563eb")
        assert window.graph.pages[ids[0]].color == "#b45309"
        assert window.page_bar.page_color(ids[0]) == "#b45309"
        assert window.page_bar._group_color("Sales").name() == "#2563eb"

    def test_without_one_it_borrows_its_first_coloured_page_s(self, window):
        ids = _pages(window, "A")
        window._recolor_page(ids[0], "#b45309")
        window._set_page_group(ids[0], "Sales")
        assert window.page_bar._group_color("Sales").name() == "#b45309"
        window._recolor_page_group("Sales", "#2563eb")
        assert window.page_bar._group_color("Sales").name() == "#2563eb"
        window._recolor_page_group("Sales", None)   # Reset colour
        assert window.page_bar._group_color("Sales").name() == "#b45309"

    def test_it_is_muted_like_a_tab(self, window, monkeypatch):
        """Dan: a group's colour mutes the way a tab's and a card's do —
        laid over at the Settings ▸ Canvas strength, not drawn raw."""
        from flograph.ui import theme
        ids = _pages(window, "A")
        window._set_page_group(ids[0], "Sales", "#ff0000")
        bar = window.page_bar
        ground = bar.palette().color(bar.backgroundRole())
        muted = bar._muted_group_color("Sales")
        assert muted.name() != "#ff0000"
        assert muted == theme.tint(ground, "#ff0000", theme.TINT_STRONG)
        # the strength is read when it paints, so the setting reaches it
        monkeypatch.setattr(theme, "TINT_STRONG", 0.2)
        assert bar._muted_group_color("Sales") == \
            theme.tint(ground, "#ff0000", 0.2)

    def test_a_rename_keeps_it_and_ungrouping_drops_it(self, window):
        ids = _pages(window, "A")
        window._set_page_group(ids[0], "Sales", "#2563eb")
        window._rename_page_group("Sales", "Revenue")
        assert window.graph.page_group_colors == {"Revenue": "#2563eb"}
        window._rename_page_group("Revenue", "")
        assert window.graph.page_group_colors == {}

    def test_a_merge_keeps_the_colour_of_the_group_merged_into(self, window):
        ids = _pages(window, "A", "B")
        window._set_page_group(ids[0], "Sales", "#2563eb")
        window._set_page_group(ids[1], "Costs", "#b45309")
        window._rename_page_group("Costs", "Sales")
        assert window.graph.page_group_colors == {"Sales": "#2563eb"}

    def test_it_is_saved_only_while_a_page_is_in_the_group(self, registry):
        graph = Graph()
        graph.add_page(Page(id="p1", title="A", group="Sales"))
        graph.set_page_group_color("Sales", "#2563eb")
        graph.set_page_group_color("Gone", "#000000")
        data = graph_to_dict(graph)
        assert (data.get("graph") or data)["page_group_colors"] == \
            {"Sales": "#2563eb"}
        assert graph_from_dict(data, registry).page_group_colors == \
            {"Sales": "#2563eb"}
        plain = Graph()
        plain.add_page(Page(id="p1", title="A"))
        assert "page_group_colors" not in \
            (graph_to_dict(plain).get("graph") or graph_to_dict(plain))

    def test_opening_a_project_brings_its_colours(self, window, registry):
        loaded = Graph()
        loaded.add_page(Page(id="p1", title="A", group="Sales"))
        loaded.set_page_group_color("Sales", "#2563eb")
        window._replace_graph(loaded)
        assert window.page_bar._group_color("Sales").name() == "#2563eb"

    def test_new_group_asks_for_a_name_and_a_colour(self, window,
                                                    monkeypatch):
        from flograph.ui.dashboard import group_dialog

        class Answered:
            def __init__(self, parent=None):
                pass

            def exec(self):
                return True

            def name(self):
                return "Sales"

            def colour(self):
                return "#2563eb"
        monkeypatch.setattr(group_dialog, "GroupDialog", Answered)
        ids = _pages(window, "A")
        window.page_bar._prompt_new_group(ids[0])
        assert window.graph.pages[ids[0]].group == "Sales"
        assert window.graph.page_group_colors == {"Sales": "#2563eb"}

    def test_the_dialog(self, qtbot):
        from flograph.ui.dashboard.group_dialog import AUTOMATIC, GroupDialog
        dialog = GroupDialog()
        qtbot.addWidget(dialog)
        assert not dialog._ok.isEnabled()          # no name, no group
        dialog.name_edit.setText("  Sales ")
        assert dialog._ok.isEnabled() and dialog.name() == "Sales"
        assert dialog.colour() == ""               # automatic
        assert dialog.colour_row._swatch.text() == AUTOMATIC
        dialog._set_colour("#2563eb")
        assert dialog.colour() == "#2563eb"


# ------------------------------------------------------- AB3 Page Links

LINKS = "flograph.util.page_links"


def _three():
    return {"a": Page(id="a", title="A", group="Sales"),
            "b": Page(id="b", title="B"),
            "c": Page(id="c", title="C", group="Sales")}


class TestWhichPages:
    def test_every_page_by_default(self):
        assert [p.id for p in linked_pages(_three(), {})] == ["a", "b", "c"]

    def test_chosen_pages_come_in_tab_order(self):
        params = {"show": SHOW_CHOSEN, "pages": "c,a"}
        assert [p.id for p in linked_pages(_three(), params)] == ["a", "c"]

    def test_nothing_chosen_is_every_page(self):
        params = {"show": SHOW_CHOSEN, "pages": ""}
        assert len(linked_pages(_three(), params)) == 3

    def test_its_own_group(self):
        params = {"show": SHOW_GROUP}
        assert [p.id for p in linked_pages(_three(), params, "c")] == ["a", "c"]
        # an ungrouped page's group is the other ungrouped pages
        assert [p.id for p in linked_pages(_three(), params, "b")] == ["b"]
        # the canvas is no page, so it gets them all
        assert len(linked_pages(_three(), params, None)) == 3

    def test_the_node_spells_them_the_same(self, registry):
        spec = registry.get(LINKS)
        assert spec.card == "pagelinks"
        assert spec.param("show").options == \
            [SHOW_EVERY, SHOW_GROUP, SHOW_CHOSEN]
        pages = spec.param("pages")
        assert pages.type == "page_ref" and pages.multi is True
        # nothing runs, so no param should mark it as needing to
        assert all(p.cosmetic for p in spec.params)


class TestAPageLinkInMarkdown:
    def test_by_title_ignoring_case(self):
        assert page_for_link(_three(), "page:b") == "b"
        assert page_for_link(_three(), "PAGE: C ") == "c"

    def test_a_title_with_spaces(self):
        pages = {"x": Page(id="x", title="Sales North")}
        assert page_for_link(pages, "page:Sales%20North") == "x"
        assert page_for_link(pages, "page:<Sales North>") == "x"

    def test_by_id(self):
        pages = {"p9": Page(id="p9", title="Costs")}
        assert page_for_link(pages, "page:p9") == "p9"

    def test_anything_else_is_not_a_page(self):
        assert page_for_link(_three(), "https://example.com") is None
        assert page_for_link(_three(), "page:Nowhere") is None
        assert page_for_link(_three(), "page:") is None

    def test_a_note_tile_link_goes_there(self, window):
        ids = _pages(window, "Board", "Costs")
        item = _place(window, ids[0], _node(
            window, NOTE, text="[the costs](page:Costs)"))
        point = TestANoteOnAPage()._link_point(item)
        item.mousePressEvent(_Mouse(point))
        item.mouseReleaseEvent(_Mouse(point))
        assert window.page_bar.current_page_id() == ids[1]

    def test_a_canvas_note_link_goes_there(self, window):
        ids = _pages(window, "Costs")
        node = _node(window, NOTE, text="[the costs](page:Costs)")
        window.scene.node_items[node.id]._open_note_link("page:Costs")
        assert window.page_bar.current_page_id() == ids[0]

    def test_a_report_page_link_goes_there(self, window):
        """N7: the report page's preview hands a clicked `page:` link to the
        window, which resolves it the same way as a Note's."""
        ids = _pages(window, "Costs")
        report = Page(id="r1", title="Notes", kind="report",
                      body="[the costs](page:Costs)")
        window.undo_stack.push(AddPageCommand(window.graph, report))
        window.page_bar.select_page(report.id)
        widget = window._dashboard_pages[report.id]
        widget.preview.link_activated.emit("page:Costs")
        assert window.page_bar.current_page_id() == ids[0]

    def test_a_link_to_no_page_says_so(self, window, monkeypatch):
        _pages(window, "Costs")
        said = []
        monkeypatch.setattr(window, "show_status",
                            lambda text, *a: said.append(text))
        window._follow_page_link("page:Nowhere")
        assert said and "Nowhere" in said[0]


class TestPageLinksOnAPage:
    def test_it_is_a_strip_of_buttons(self, window):
        ids = _pages(window, "Sales")
        node = _node(window, LINKS)
        assert is_tile_able(node)
        assert default_tile_size(node) == (480, 44)
        item = _place(window, ids[0], node)
        assert item._kind() == "pagelinks"
        assert item._proxy.isVisible() is False
        assert not item.can_fullscreen()
        assert item._min_size() == (80, 32)

    def test_a_click_on_a_page_goes_there(self, window):
        ids = _pages(window, "Sales", "Costs", "Staff")
        item = _place(window, ids[0], _node(window, LINKS))
        boxes = link_rects(QRectF(0, 0, 480, 44), 3, False)
        press = _Mouse(boxes[2].center())
        item.mousePressEvent(press)
        assert press.accepted
        assert window.page_bar.current_page_id() == ids[2]

    def _click(self, window, qtbot, page_id, item, local):
        """A real click through the page's view, so Qt's own release
        handling — which selects an item clicked without moving — runs."""
        window.page_bar.select_page(page_id)
        window.show()
        qtbot.waitExposed(window)
        view = window._dashboard_pages[page_id].view
        point = view.mapFromScene(item.mapToScene(local))
        QTest.mouseClick(view.viewport(), Qt.LeftButton, Qt.NoModifier, point)

    def test_a_click_leaves_it_ready_to_click_again(self, window, qtbot):
        """Dan, testing AB3: back on a page a link had left from, the strip
        was selected, so the next click moved it instead of going."""
        ids = _pages(window, "Sales", "Costs")
        item = _place(window, ids[0], _node(window, LINKS))
        boxes = link_rects(QRectF(0, 0, 480, 44), 2, False)
        self._click(window, qtbot, ids[0], item, boxes[1].center())
        assert window.page_bar.current_page_id() == ids[1]
        assert not item.isSelected()

    def test_a_selected_strip_still_goes(self, window, qtbot):
        """Dan: a left-click always goes; selecting it (a drag-select,
        Select All) is not what makes it move."""
        ids = _pages(window, "Sales", "Costs")
        item = _place(window, ids[0], _node(window, LINKS))
        item.setSelected(True)
        boxes = link_rects(QRectF(0, 0, 480, 44), 2, False)
        self._click(window, qtbot, ids[0], item, boxes[1].center())
        assert window.page_bar.current_page_id() == ids[1]

    def test_right_click_is_edit_mode(self, window, qtbot):
        ids = _pages(window, "Sales", "Costs")
        item = _place(window, ids[0], _node(window, LINKS))
        item.mousePressEvent(_Mouse(QPointF(100, 20), Qt.RightButton))
        assert item._edit and item.isSelected()
        # in edit mode a click on a page grabs the strip instead of going
        boxes = link_rects(QRectF(0, 0, 480, 44), 2, False)
        self._click(window, qtbot, ids[0], item, boxes[1].center())
        assert window.page_bar.current_page_id() == ids[0]
        item.setSelected(False)   # a click anywhere else
        assert not item._edit

    def test_so_does_a_go_to_page_button(self, window, qtbot):
        ids = _pages(window, "Sales", "Costs")
        item = _place(window, ids[0], _node(
            window, BUTTON, action="Go to page", page=ids[1]))
        self._click(window, qtbot, ids[0], item, QPointF(40, 20))
        assert window.page_bar.current_page_id() == ids[1]
        assert not item.isSelected()

    def test_between_the_buttons_is_no_page(self, window):
        ids = _pages(window, "Sales", "Costs")
        item = _place(window, ids[0], _node(window, LINKS))
        assert item._page_link_at(QPointF(2, 2)) is None

    def test_right_click_selects_it(self, window):
        ids = _pages(window, "Sales", "Costs")
        item = _place(window, ids[0], _node(window, LINKS))
        item.mousePressEvent(_Mouse(QPointF(100, 20), Qt.RightButton))
        assert item.isSelected()
        assert window.page_bar.current_page_id() != ids[1]

    def test_it_highlights_the_page_it_sits_on(self, window):
        ids = _pages(window, "A", "B")
        item = _place(window, ids[1], _node(window, LINKS))
        assert item._host_page() == ids[1]

    def test_this_page_s_group(self, window):
        ids = _pages(window, "A", "B", "C")
        window._set_page_group(ids[0], "Sales")
        window._set_page_group(ids[2], "Sales")
        item = _place(window, ids[2],
                      _node(window, LINKS, show="This page's group"))
        assert [p.id for p in item._linked_pages()] == [ids[0], ids[2]]

    def test_it_keeps_up_with_the_pages(self, window, monkeypatch):
        ids = _pages(window, "Sales")
        item = _place(window, ids[0], _node(window, LINKS))
        painted = []
        monkeypatch.setattr(item, "update", lambda *a: painted.append(1))
        window.undo_stack.push(
            AddPageCommand(window.graph, Page(id="late", title="Late")))
        assert painted
        assert [p.title for p in item._linked_pages()] == ["Sales", "Late"]
        painted.clear()
        window._rename_page("late", "Later")
        assert painted

    def test_it_paints(self, window):
        ids = _pages(window, "Sales", "Costs")
        item = _place(window, ids[0], _node(window, LINKS))
        image = QImage(480, 44, QImage.Format_ARGB32)
        image.fill(0)
        painter = QPainter(image)
        item.scene().render(painter, QRectF(image.rect()),
                            item.sceneBoundingRect())
        painter.end()
        colours = {image.pixel(x, y) for x in range(0, 480, 2)
                   for y in range(0, 44, 2)}
        assert len(colours) > 4


class TestPageLinksOnTheCanvas:
    def test_a_click_goes_there(self, window):
        ids = _pages(window, "Sales", "Costs")
        node = _node(window, LINKS)
        item = window.scene.node_items[node.id]
        # the Action Button's family: stays put, right-click edits
        assert item.button and item.page_links
        boxes = link_rects(QRectF(0, 0, item.width, item.body_height), 2,
                           False)
        item.mousePressEvent(_Mouse(boxes[1].center()))
        assert window.page_bar.current_page_id() == ids[1]

    def test_it_never_fires_as_a_button(self, window, monkeypatch):
        ids = _pages(window, "Sales")
        node = _node(window, LINKS)
        item = window.scene.node_items[node.id]
        fired = []
        window.scene.button_fired.connect(fired.append)
        boxes = link_rects(QRectF(0, 0, item.width, item.body_height), 1,
                           False)
        item.mousePressEvent(_Mouse(boxes[0].center()))
        assert fired == []
        assert window.page_bar.current_page_id() == ids[0]

    def test_a_column(self, window):
        ids = _pages(window, "Sales", "Costs")
        node = _node(window, LINKS, layout="Column", width=160, height=200)
        item = window.scene.node_items[node.id]
        boxes = link_rects(QRectF(0, 0, 160, 200), 2, True)
        assert item.page_link_at(boxes[1].center()) == ids[1]

    def test_a_width_edit_resizes_it(self, window):
        node = _node(window, LINKS)
        item = window.scene.node_items[node.id]
        window.undo_stack.push(
            SetParamCommand(window.graph, node.id, "width", 600))
        assert item.width == 600


class TestThePageSetPicker:
    def test_ticks_over_the_pages(self, window):
        ids = _pages(window, "Sales", "Costs")
        node = _node(window, LINKS, show="Chosen pages")
        window.params_panel.set_node(node.id)
        button = _row_widget(window.params_panel, "Pages")
        assert button.text() == "Every page"
        menu = button.menu()
        menu.aboutToShow.emit()
        assert [a.text() for a in menu.actions() if not a.isSeparator()] == \
            ["Every page", "Sales", "Costs"]
        next(a for a in menu.actions() if a.text() == "Costs").trigger()
        assert node.params["pages"] == ids[1]
        assert button.text() == "Costs"
        menu.aboutToShow.emit()
        next(a for a in menu.actions() if a.text() == "Sales").trigger()
        assert node.params["pages"] == f"{ids[0]},{ids[1]}"   # tab order
        assert button.text() == "2 pages"
        menu.aboutToShow.emit()
        next(a for a in menu.actions() if a.text() == "Every page").trigger()
        assert node.params["pages"] == ""
        assert button.text() == "Every page"

    def test_only_shown_for_chosen_pages(self, window):
        node = _node(window, LINKS)
        window.params_panel.set_node(node.id)
        with pytest.raises(LookupError):
            _row_widget(window.params_panel, "Pages")
