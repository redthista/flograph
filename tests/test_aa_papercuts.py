"""Chunk AA: eight small fixes from Dan's 0.1.14 list.

AA1 a plain canvas and AA2 scroll bars, by default; AA3 a column header's
full name on hover; AA4 Properties on a node's right-click menu; AA5 every
tab in one list, from the tab bar's arrows; AA6 Show Table without its row
index; AA7 a slicer's dropdown above the cards in front of it; AA8 the start
screen's "edited" note on the name's line.

Settings kept off the real store (avoid polluting the developer's actual
flograph.conf) -- see test_lod_settings.py's fixture of the same name."""
import importlib

import pandas as pd
import pytest
from PySide6.QtCore import QEvent, QPoint, QSettings, Qt
from PySide6.QtGui import QHelpEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QApplication, QGraphicsProxyWidget, QGraphicsRectItem, QGraphicsScene,
    QGraphicsView, QMenu, QToolButton,
)

from flograph.core import Page, Tile
from flograph.core.table_format import (
    index_shown, merge_styles, rules_from_style, style_payload,
)
from flograph.ui import mainwindow as mw
from flograph.ui.commands import AddPageCommand, AddTileCommand
from flograph.ui.mainwindow import MainWindow

SHOW_TABLE = "flograph.viz.show_table"


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


# ------------------------------------------------------- AA1, AA2 defaults

class TestCanvasDefaults:
    def test_a_plain_canvas_with_snapping_still_on(self, window):
        assert window.grid_visible is False
        assert window.scene.grid_visible is False
        assert window.snap_enabled is True

    def test_scroll_bars_showing(self, window):
        assert window.scrollbars_enabled is True
        assert (window.view.horizontalScrollBarPolicy()
                != Qt.ScrollBarAlwaysOff)

    def test_a_new_page_gets_both(self, window):
        window.undo_stack.push(
            AddPageCommand(window.graph, Page(id="p1", title="Board")))
        page = window._dashboard_pages["p1"]
        assert page.scene.grid_visible is False
        assert page.view.horizontalScrollBarPolicy() != Qt.ScrollBarAlwaysOff

    def test_a_choice_already_made_still_wins(self, qtbot, registry, window):
        """A new default is for people who never chose: someone who turned
        the bars off, or the grid on, keeps what they chose."""
        window.set_scrollbars_enabled(False)
        window.set_grid_visible(True)
        second = MainWindow(registry)
        second.confirm_close = False
        qtbot.addWidget(second)
        assert second.scrollbars_enabled is False
        assert second.grid_visible is True


# ------------------------------------------------------- AA3 header tooltip

def _header_tip(df, format_rules=""):
    from flograph.ui.inspector.pandas_model import PandasModel
    rules = rules_from_style(style_payload({"format_rules": format_rules}))
    model = PandasModel(df, rules=rules)
    return model.headerData(0, Qt.Horizontal, Qt.ToolTipRole)


class TestHeaderTooltip:
    def test_it_names_the_column_in_full(self):
        name = "customer_lifetime_value_after_discounts"
        tip = _header_tip(pd.DataFrame({name: [1, 2]}))
        assert tip.splitlines() == [name, "dtype: int64"]

    def test_a_label_leads_and_the_real_name_follows(self):
        tip = _header_tip(pd.DataFrame({"revenue": [1, 2]}),
                          'revenue label "Revenue (£)"')
        assert tip.splitlines() == ["Revenue (£)", "revenue", "dtype: int64"]

    def test_a_label_the_same_as_the_name_is_not_said_twice(self):
        tip = _header_tip(pd.DataFrame({"revenue": [1]}),
                          "revenue label revenue")
        assert tip.splitlines() == ["revenue", "dtype: int64"]


class TestTooltipsOnACard:
    """On a card the table is embedded in the scene and has no window of
    its own, so a tooltip shown against it landed at the top of the page
    (Dan, testing AA3). It is shown against the graphics view instead."""

    def test_off_a_card_it_is_the_widget_itself(self, qtbot):
        from flograph.ui.data_table import DataTableView, tooltip_host
        view = DataTableView()
        qtbot.addWidget(view)
        viewport = view.horizontalHeader().viewport()
        assert tooltip_host(viewport, QPoint(0, 0)) is viewport

    def test_on_a_card_it_is_the_view_drawing_the_card(self, qtbot):
        from flograph.ui.data_table import DataTableView, tooltip_host
        scene = QGraphicsScene()
        canvas = QGraphicsView(scene)
        qtbot.addWidget(canvas)
        canvas.resize(600, 400)
        canvas.show()
        table = DataTableView()
        scene.addWidget(table)
        QApplication.processEvents()
        inside = canvas.viewport().mapToGlobal(QPoint(50, 50))
        header = table.horizontalHeader().viewport()
        assert tooltip_host(header, inside) is canvas.viewport()
        assert tooltip_host(table.viewport(), inside) is canvas.viewport()

    def test_the_header_s_tooltip_goes_that_way(self, qtbot, monkeypatch):
        from flograph.ui import data_table
        from flograph.ui.inspector.pandas_model import PandasModel
        view = data_table.DataTableView()
        qtbot.addWidget(view)
        view.setModel(PandasModel(pd.DataFrame({"long_name": [1]}),
                                  parent=view))
        view.resize(300, 200)
        view.show()
        QApplication.processEvents()
        shown: list = []
        monkeypatch.setattr(data_table, "show_tooltip",
                            lambda pos, text, widget: shown.append(text))
        header = view.horizontalHeader()
        pos = QPoint(header.sectionViewportPosition(0) + 5, 5)
        QApplication.sendEvent(header.viewport(), QHelpEvent(
            QEvent.ToolTip, pos, header.viewport().mapToGlobal(pos)))
        assert shown and shown[0].splitlines()[0] == "long_name"

    def test_the_new_header_still_sorts(self, qtbot):
        from flograph.ui.data_table import DataTableView
        from flograph.ui.inspector.pandas_model import PandasModel
        view = DataTableView()
        qtbot.addWidget(view)
        view.setModel(PandasModel(pd.DataFrame({"n": [2, 1, 3]}),
                                  parent=view))
        view.resize(300, 200)
        view.show()
        QApplication.processEvents()
        header = view.horizontalHeader()
        assert header.sectionsClickable()
        QTest.mouseClick(header.viewport(), Qt.LeftButton,
                         pos=QPoint(header.sectionViewportPosition(0) + 5, 5))

        def column():
            return [view.model().index(r, 0).data() for r in range(3)]
        # the cycler waits out the double-click interval before it sorts
        qtbot.waitUntil(lambda: column() == ["1", "2", "3"], timeout=3000)


def _sheet_view(qtbot):
    """The Table card's grid, holding a long column name and a formula."""
    from flograph.ui.spreadsheet import SheetModel, SpreadsheetView
    view = SpreadsheetView()
    model = SheetModel({
        "version": 2,
        "columns": [{"name": "customer_lifetime_value", "type": "auto"},
                    {"name": "double", "type": "auto"}],
        "rows": [["2", "=A1*2"]],
    })
    model.setParent(view)   # keep C++ destruction ordered at teardown
    view.setModel(model)
    qtbot.addWidget(view)
    view.resize(300, 200)
    view.show()
    QApplication.processEvents()
    return view


class TestTooltipsOnATableCard:
    """Dan, retesting AA3: Show Table was fixed, the Table card was not —
    its grid is a different view with Qt's own header."""

    def test_its_header_is_the_one_that_places_tooltips(self, qtbot):
        from flograph.ui.data_table import TooltipHeader
        view = _sheet_view(qtbot)
        assert isinstance(view.horizontalHeader(), TooltipHeader)

    def test_its_header_tooltip_goes_that_way(self, qtbot, monkeypatch):
        from flograph.ui import data_table
        view = _sheet_view(qtbot)
        shown: list = []
        monkeypatch.setattr(data_table, "show_tooltip",
                            lambda pos, text, widget: shown.append(text))
        header = view.horizontalHeader()
        pos = QPoint(header.sectionViewportPosition(0) + 5, 5)
        QApplication.sendEvent(header.viewport(), QHelpEvent(
            QEvent.ToolTip, pos, header.viewport().mapToGlobal(pos)))
        assert shown and shown[0].startswith("customer_lifetime_value")

    def test_a_cell_s_tooltip_goes_that_way_too(self, qtbot, monkeypatch):
        from flograph.ui import data_table
        view = _sheet_view(qtbot)
        shown: list = []
        monkeypatch.setattr(data_table, "show_tooltip",
                            lambda pos, text, widget: shown.append(text))
        rect = view.visualRect(view.model().index(0, 1))
        pos = rect.center()
        QApplication.sendEvent(view.viewport(), QHelpEvent(
            QEvent.ToolTip, pos, view.viewport().mapToGlobal(pos)))
        assert shown == ["=A1*2"]

    def test_on_a_card_it_is_shown_against_the_canvas(self, qtbot):
        from flograph.ui.data_table import tooltip_host
        from flograph.ui.spreadsheet import SpreadsheetView
        scene = QGraphicsScene()
        canvas = QGraphicsView(scene)
        qtbot.addWidget(canvas)
        canvas.resize(600, 400)
        canvas.show()
        grid = SpreadsheetView()
        scene.addWidget(grid)
        QApplication.processEvents()
        inside = canvas.viewport().mapToGlobal(QPoint(50, 50))
        assert (tooltip_host(grid.horizontalHeader().viewport(), inside)
                is canvas.viewport())


# ------------------------------------------------ AA4 Properties on the menu

def _find(menu, text):
    for action in menu.actions():
        if action.text() == text:
            return action
    return None


def _menu_texts(monkeypatch):
    seen: list = []

    class _Recorder(QMenu):
        def exec(self, *args):
            seen.extend(a.text() for a in self.actions())
            return None
    monkeypatch.setattr(mw, "QMenu", _Recorder)
    return seen


def _pick(monkeypatch, text):
    """A real QMenu subclass rather than a patched exec — see
    test_goto_links_ui for why."""
    class _Picker(QMenu):
        def exec(self, *args):
            return _find(self, text)
    monkeypatch.setattr(mw, "QMenu", _Picker)


def _add_nodes(window, count):
    nodes = []
    for i in range(count):
        node = window.registry.instantiate("flograph.util.constant",
                                           pos=(i * 200.0, 0.0))
        window.graph.add_node(node)
        window.scene.node_items[node.id].setSelected(True)
        nodes.append(node)
    return nodes


class TestPropertiesOnTheNodeMenu:
    def test_one_node_is_offered_it_first_of_its_own_entries(
            self, window, monkeypatch):
        node = _add_nodes(window, 1)[0]
        texts = _menu_texts(monkeypatch)
        window._show_node_menu(node.id, QPoint())
        assert "Properties" in texts
        assert texts.index("Properties") < texts.index("Edit Code")

    def test_a_selection_is_not(self, window, monkeypatch):
        """The panel shows one node; the menu does not pretend otherwise."""
        nodes = _add_nodes(window, 3)
        texts = _menu_texts(monkeypatch)
        window._show_node_menu(nodes[0].id, QPoint())
        assert "Properties" not in texts

    def test_it_opens_the_panel_on_that_node(self, window, monkeypatch):
        node = _add_nodes(window, 1)[0]
        shown: list = []
        monkeypatch.setattr(window.params_panel, "set_node", shown.append)
        window.properties_dock.hide()
        _pick(monkeypatch, "Properties")
        window._show_node_menu(node.id, QPoint())
        assert shown == [node.id]
        assert not window.properties_dock.isHidden()


# ------------------------------------------------------- AA5 the tab list

def _bar(qtbot, pages):
    from flograph.ui.dashboard.page_bar import PageTabBar
    bar = PageTabBar()
    qtbot.addWidget(bar)
    for i in range(pages):
        bar.add_page_tab(Page(id=f"p{i}", title=f"Page {i}"))
    return bar


class TestTheTabList:
    def test_it_lists_every_tab_but_the_plus(self, qtbot):
        bar = _bar(qtbot, 3)
        texts = [a.text() for a in bar.tab_list_menu().actions()]
        assert texts == ["Model", "Page 0", "Page 1", "Page 2"]

    def test_the_current_tab_is_ticked(self, qtbot):
        bar = _bar(qtbot, 3)
        bar.select_page("p1")
        ticked = [a.text() for a in bar.tab_list_menu().actions()
                  if a.isChecked()]
        assert ticked == ["Page 1"]

    def test_picking_one_goes_there(self, qtbot):
        bar = _bar(qtbot, 3)
        menu = bar.tab_list_menu()
        with qtbot.waitSignal(bar.current_page_changed) as blocker:
            _find(menu, "Page 2").trigger()
        assert blocker.args == ["p2"]
        _find(bar.tab_list_menu(), "Model").trigger()
        assert bar.current_page_id() is None

    def test_it_follows_a_reorder(self, qtbot):
        """Held by page id, not by index — the list is built on open, but a
        menu that jumped to whatever now sits at index 2 would be wrong."""
        bar = _bar(qtbot, 3)
        menu = bar.tab_list_menu()
        bar.set_page_order(["p2", "p0", "p1"])
        _find(menu, "Page 2").trigger()
        assert bar.current_page_id() == "p2"

    def test_right_clicking_the_arrows_opens_it(self, qtbot, monkeypatch):
        bar = _bar(qtbot, 30)
        bar.resize(300, 30)
        bar.show()
        QApplication.processEvents()
        arrow = bar.findChild(QToolButton, "ScrollRightButton")
        assert arrow is not None and arrow.isVisible()
        opened: list = []

        class _Recorder(QMenu):
            def exec(self, *args):
                opened.append([a.text() for a in self.actions()])
                return None
        monkeypatch.setattr(bar, "tab_list_menu",
                            lambda: _Recorder(bar))
        QTest.mouseClick(arrow, Qt.RightButton, pos=QPoint(4, 4))
        assert len(opened) == 1

    def test_right_clicking_the_greyed_out_arrow_opens_it(self, qtbot,
                                                          monkeypatch):
        """Dan, testing AA5: the left arrow is disabled until you scroll,
        and a disabled button takes the click and drops it — so the list
        only opened from the right one."""
        bar = _bar(qtbot, 30)
        bar.resize(300, 30)
        bar.show()
        QApplication.processEvents()
        arrow = bar.findChild(QToolButton, "ScrollLeftButton")
        assert arrow is not None and arrow.isVisible()
        assert not arrow.isEnabled()
        opened: list = []

        class _Recorder(QMenu):
            def exec(self, *args):
                opened.append(1)
                return None
        monkeypatch.setattr(bar, "tab_list_menu", lambda: _Recorder(bar))
        QTest.mouseClick(arrow, Qt.RightButton, pos=QPoint(4, 4))
        assert opened == [1]

    def test_a_left_click_on_the_arrows_still_scrolls(self, qtbot,
                                                      monkeypatch):
        bar = _bar(qtbot, 30)
        bar.resize(300, 30)
        bar.show()
        QApplication.processEvents()
        called: list = []
        monkeypatch.setattr(bar, "tab_list_menu",
                            lambda: called.append(1) or QMenu(bar))
        arrow = bar.findChild(QToolButton, "ScrollRightButton")
        QTest.mouseClick(arrow, Qt.LeftButton, pos=QPoint(4, 4))
        assert called == []


# ----------------------------------------------------- AA6 the row index

class _Ctx:
    def __init__(self, params):
        self.params = params
        self.logs: list = []

    def log(self, message):
        self.logs.append(message)


class TestTheRowIndex:
    def test_a_style_says_nothing_about_it_by_default(self):
        payload = style_payload({})
        assert "index" not in payload
        assert index_shown(payload)
        assert index_shown(None)

    def test_unticking_puts_it_away(self):
        payload = style_payload({"row_index": False})
        assert payload["index"] is False
        assert not index_shown(payload)

    def test_either_side_of_a_merge_can_put_it_away(self):
        off, on = style_payload({"row_index": False}), style_payload({})
        assert not index_shown(merge_styles(off, on))
        assert not index_shown(merge_styles(on, off))
        assert index_shown(merge_styles(on, on))
        assert index_shown(merge_styles(None, None))

    def test_the_node_ticks_it_by_default(self, registry):
        node = registry.instantiate(SHOW_TABLE)
        assert node.params["row_index"] is True

    def test_the_node_carries_it_on_its_style_and_keeps_the_table(self):
        show_table = importlib.import_module("flograph.nodes.viz.show_table")
        df = pd.DataFrame({"a": [1, 2]}, index=[10, 20])
        out = show_table.run(_Ctx({"row_index": False}), df)
        assert out["table"] is df                  # the index is left alone
        assert not index_shown(out["style"])

    def test_the_canvas_card_drops_it(self, qtbot, window):
        node = window.registry.instantiate(SHOW_TABLE)
        window.graph.add_node(node)
        item = window.scene.node_items[node.id]
        df = pd.DataFrame({"a": [1, 2]})
        item.set_table_data(df, style_payload({"row_index": False}))
        assert item._table_viewer_view.verticalHeader().isHidden()
        item.set_table_data(df, None)
        assert not item._table_viewer_view.verticalHeader().isHidden()

    def test_the_dashboard_tile_drops_it(self, window):
        window.undo_stack.push(
            AddPageCommand(window.graph, Page(id="p1", title="Board")))
        node = window.registry.instantiate(SHOW_TABLE)
        window.graph.add_node(node)
        window.undo_stack.push(AddTileCommand(
            window.graph, "p1", Tile(id="t1", node_id=node.id, port="table")))
        tile = window._dashboard_pages["p1"].scene.tile_items["t1"]
        df = pd.DataFrame({"a": [1, 2]})
        window.engine.cache.set(
            node.id, {"table": df,
                      "style": style_payload({"row_index": False})}, 0.01)
        window.graph.mark_clean(node.id)
        window.engine.node_succeeded.emit(node.id)
        assert tile._table_view.model() is not None
        assert tile._table_view.verticalHeader().isHidden()


# ------------------------------------------- AA7 the slicer dropdown on top

def _dropdown_in_a_card(z=3.0):
    """A dropdown slicer embedded the way a card embeds one: a widget in a
    proxy, the proxy a child of the card item."""
    from flograph.core.slicer import SlicerOptions
    from flograph.ui.slicer_list import SlicerPanel
    scene = QGraphicsScene()
    card = QGraphicsRectItem(0, 0, 240, 200)
    card.setZValue(z)
    scene.addItem(card)
    panel = SlicerPanel()
    panel.set_options(SlicerOptions(["region"], [("north",), ("south",)]),
                      {"selected": "", "mode": "multi", "layout": "dropdown",
                       "show_counts": False})
    proxy = QGraphicsProxyWidget(card)
    proxy.setWidget(panel)
    return scene, card, panel.view


class TestTheSlicerDropdown:
    def test_its_card_is_lifted_while_it_is_open(self, qtbot):
        from flograph.ui.canvas.stacking import POPUP_HOST_Z
        scene, card, dropdown = _dropdown_in_a_card()
        dropdown._popup.popup(QPoint(0, 0))
        assert dropdown._popup.isVisible()
        assert card.zValue() == POPUP_HOST_Z
        dropdown._popup.close()
        assert card.zValue() == 3.0

    def test_a_maximized_tile_is_not_lowered(self, qtbot):
        from flograph.ui.canvas.stacking import FULLSCREEN_TILE_Z
        scene, card, dropdown = _dropdown_in_a_card(FULLSCREEN_TILE_Z)
        dropdown._popup.popup(QPoint(0, 0))
        assert card.zValue() == FULLSCREEN_TILE_Z
        dropdown._popup.close()
        assert card.zValue() == FULLSCREEN_TILE_Z

    def test_outside_a_scene_it_simply_opens(self, qtbot):
        from flograph.core.slicer import SlicerOptions
        from flograph.ui.slicer_list import SlicerPanel
        panel = SlicerPanel()
        qtbot.addWidget(panel)
        panel.set_options(SlicerOptions(["region"], [("north",)]),
                          {"selected": "", "mode": "multi",
                           "layout": "dropdown", "show_counts": False})
        panel.view._popup.popup(QPoint(0, 0))
        assert panel.view._popup.isVisible()
        panel.view._popup.close()


# ------------------------------------------- AA8 the start screen's rows

class TestTheStartScreenRow:
    def test_the_note_is_on_the_name_s_line(self, qtbot, tmp_path):
        from flograph.ui.window_frame import _RecentRow
        path = str(tmp_path / "alpha.flograph")
        row = _RecentRow(path, lambda p: None, on_toggle_fav=lambda p: False,
                         detail="edited 3 days ago")
        qtbot.addWidget(row)
        row.resize(700, 50)
        row.show()
        QApplication.processEvents()
        name = next(label for label in row.findChildren(type(row.detail_label))
                    if label.objectName() == "recent_name")
        detail, folder = row.detail_label, row.path_label
        # same line as the name, and at the end of it
        assert abs(detail.geometry().center().y()
                   - name.geometry().center().y()) <= 3
        assert detail.geometry().left() > name.geometry().left()
        # the folder has the line below to itself, from under the name to
        # past where the note begins
        assert folder.geometry().top() >= name.geometry().bottom()
        assert folder.geometry().left() == name.geometry().left()
        assert folder.geometry().right() >= detail.geometry().right()

    def test_the_folder_elides_to_the_width_it_is_given(self, qtbot):
        from flograph.ui.window_frame import _ElidedLabel
        folder = "~/" + "/".join(f"folder_number_{i}" for i in range(12))
        label = _ElidedLabel(folder, 340)
        qtbot.addWidget(label)
        label.show()
        label.resize(120, 20)
        QApplication.processEvents()
        assert "…" in label.text()
        label.resize(3000, 20)
        QApplication.processEvents()
        assert label.text() == folder
        assert label.full_text() == folder

    def test_it_asks_for_no_more_than_its_cap(self, qtbot):
        """So a row in the title bar's switcher menu still sets a sensible
        menu width, as the fixed 340px elide used to."""
        from flograph.ui.window_frame import _ElidedLabel
        label = _ElidedLabel("~/" + "x" * 400, 340)
        qtbot.addWidget(label)
        margins = label.contentsMargins()
        assert label.sizeHint().width() <= 340 + margins.left() + margins.right()

    def test_the_switcher_s_row_has_no_note(self, qtbot, tmp_path):
        from flograph.ui.window_frame import _RecentRow
        row = _RecentRow(str(tmp_path / "alpha.flograph"), lambda p: None)
        qtbot.addWidget(row)
        assert not hasattr(row, "detail_label")
