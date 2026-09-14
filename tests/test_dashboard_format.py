"""Formatting a dashboard page: a page's look and a tile's own (the model,
undo and the file), how a tile draws it, the Format pane, tiles with no
title bar, and finding visuals by name and type.

Settings kept off the real store (avoid polluting the developer's actual
flograph.conf) -- see test_lod_settings.py's fixture of the same name."""
import json

import pytest
from PySide6.QtCore import QPointF, QSettings, Qt
from PySide6.QtGui import QColor
from PySide6.QtTest import QTest

from flograph.core import Graph, Page, Tile, serialization
from flograph.core.tile_style import (CARD_LOOK, NOTE_LOOK, TRANSPARENT,
                                      TileStyle, clean, resolve)
from flograph.ui import mainwindow as mod
from flograph.ui.commands import (AddPageCommand, AddTileCommand,
                                  DuplicatePageCommand, SetPageLookCommand,
                                  SetTileStylesCommand)
from flograph.ui.dashboard import DashboardPage, dashboard_view
from flograph.ui.dashboard.tile_item import GRIP_H, SHADOW_PAD, TITLE_H
from flograph.ui.mainwindow import MainWindow


@pytest.fixture(autouse=True)
def _isolated_settings(tmp_path, monkeypatch):
    ini_path = str(tmp_path / "test_settings.ini")
    monkeypatch.setattr(
        mod, "QSettings",
        lambda *a, **k: QSettings(ini_path, QSettings.IniFormat))


@pytest.fixture(autouse=True)
def _clean_tile_clipboard():
    dashboard_view.DashboardView._tile_clipboard = None
    yield
    dashboard_view.DashboardView._tile_clipboard = None


@pytest.fixture
def window(qtbot, registry):
    win = MainWindow(registry)
    win.confirm_close = False
    qtbot.addWidget(win)
    return win


def _page(window, page_id="p1"):
    window.undo_stack.push(
        AddPageCommand(window.graph, Page(id=page_id, title="Board")))
    return window._dashboard_pages[page_id]


def _node(window, type_id="flograph.viz.card", label=None):
    node = window.registry.instantiate(type_id, pos=(0, 0))
    window.graph.add_node(node)
    if label:
        window.graph.set_label(node.id, label)
    return node


def _tile(window, node, tile_id="t1", port="value", page_id="p1",
          rect=(0.0, 0.0, 300.0, 200.0), style=None):
    window.undo_stack.push(AddTileCommand(window.graph, page_id, Tile(
        id=tile_id, node_id=node.id, port=port, rect=rect,
        style=style or TileStyle())))
    return window._dashboard_pages[page_id].scene.tile_items[tile_id]


@pytest.fixture
def shown_page(window, qtbot):
    """A real, mapped DashboardPage — mouse events need one laid out."""
    built = []

    def build(page_id="p1", size=(1100, 640), **kwargs):
        page = DashboardPage(window.graph, window.engine, window.undo_stack,
                             page_id, **kwargs)
        qtbot.addWidget(page)
        page.resize(*size)
        page.show()
        qtbot.waitExposed(page)
        built.append(page)
        return page

    yield build
    for page in built:
        page.dispose()


# ------------------------------------------------------------------ model


class TestTileStyleModel:
    def test_a_tile_over_its_page_over_the_card(self):
        page = TileStyle(frame=False, radius=12.0, title_color="#ffffff")
        tile = TileStyle(radius=0.0, title_text="Sales")
        look = resolve(page, tile)
        assert look.radius == 0.0          # the tile's own
        assert look.frame is False         # the page's
        assert look.title_color == "#ffffff"
        assert look.title_text == "Sales"
        assert look.background == CARD_LOOK.background   # the card's

    def test_a_page_has_no_title_text_to_hand_down(self):
        assert resolve(TileStyle(title_text="Every tile"), None).title_text \
            is None

    def test_nothing_set_is_the_card_tiles_always_were(self):
        assert resolve(None, None) == CARD_LOOK
        assert resolve(TileStyle(), TileStyle()) == CARD_LOOK

    def test_a_note_starts_from_its_own_look(self):
        look = resolve(TileStyle(shadow=True), None, NOTE_LOOK)
        assert look.shadow is True
        assert look.background is None     # its tinted fill, left to paint
        assert look.radius == NOTE_LOOK.radius

    @pytest.mark.parametrize("name, value, expected", [
        ("radius", "14", 14.0),
        ("radius", 999, 40.0),             # held to its limit
        ("radius", -3, 0.0),
        ("radius", True, None),            # a bool is not a number
        ("radius", float("nan"), None),
        ("frame", "yes", None),
        ("frame", False, False),
        ("background", "#ABCDEF", "#abcdef"),
        ("background", "Transparent", TRANSPARENT),
        ("frame_color", "transparent", None),  # an invisible frame is off
        ("background", "red", None),
        ("title_align", "CENTER", "center"),
        ("title_align", "justify", None),
        ("title_text", "   ", None),
    ])
    def test_clean_keeps_only_what_a_field_can_hold(self, name, value,
                                                    expected):
        assert clean(name, value) == expected

    def test_only_what_was_set_is_written(self):
        style = TileStyle(frame=False, radius=10.0)
        assert style.to_dict() == {"frame": False, "radius": 10.0}
        assert TileStyle.from_dict(style.to_dict()) == style
        assert TileStyle().to_dict() == {}

    def test_a_hand_edit_costs_the_field_not_the_style(self):
        style = TileStyle.from_dict({"radius": "lots", "frame": False,
                                     "colour_of_money": "#00ff00"})
        assert style == TileStyle(frame=False)
        assert TileStyle.from_dict("not a dict") == TileStyle()

    def test_with_value_cleans_and_copies(self):
        style = TileStyle()
        changed = style.with_value("padding", "8")
        assert changed.padding == 8.0 and style.padding is None
        with pytest.raises(KeyError):
            style.with_value("sparkle", 1)


class TestSavedWithThePage:
    def _graph(self):
        graph = Graph()
        graph.add_page(Page(id="p", title="P"))
        graph.add_tile("p", Tile(id="t", node_id="gone",
                                 style=TileStyle(title=False, radius=4.0)))
        graph.add_tile("p", Tile(id="plain", node_id="gone"))
        graph.set_page_look("p", background="#F3F4F6",
                            tile_style=TileStyle(shadow=True))
        return graph

    def test_round_trip(self, registry):
        data = serialization.graph_to_dict(self._graph())
        page = data["graph"]["pages"][0]
        assert page["background"] == "#f3f4f6"
        assert page["tile_style"] == {"shadow": True}
        tiles = {t["id"]: t for t in page["tiles"]}
        assert tiles["t"]["style"] == {"title": False, "radius": 4.0}
        # a tile nobody formatted writes nothing
        assert "style" not in tiles["plain"]

        loaded = serialization.graph_from_dict(
            json.loads(json.dumps(data)), registry)
        page = loaded.pages["p"]
        assert page.background == "#f3f4f6"
        assert page.tile_style == TileStyle(shadow=True)
        assert page.tiles["t"].style == TileStyle(title=False, radius=4.0)
        assert page.tiles["plain"].style == TileStyle()

    def test_an_unformatted_page_writes_nothing_new(self):
        graph = Graph()
        graph.add_page(Page(id="p", title="P"))
        page = serialization.graph_to_dict(graph)["graph"]["pages"][0]
        assert "background" not in page and "tile_style" not in page

    def test_a_file_from_before_formatting_opens_plain(self, registry):
        data = serialization.graph_to_dict(self._graph())
        page = data["graph"]["pages"][0]
        del page["background"], page["tile_style"]
        for tile in page["tiles"]:
            tile.pop("style", None)
        loaded = serialization.graph_from_dict(data, registry).pages["p"]
        assert loaded.background is None
        assert loaded.tile_style == TileStyle()
        assert all(t.style == TileStyle() for t in loaded.tiles.values())

    def test_the_graph_stores_copies(self):
        graph = self._graph()
        style = TileStyle(frame=False)
        graph.set_page_look("p", tile_style=style)
        style.frame = True
        assert graph.pages["p"].tile_style.frame is False


class TestUndo:
    def test_a_page_look_undoes_and_a_run_of_one_setting_merges(self, window):
        _page(window)
        graph = window.graph
        for radius in (2.0, 4.0, 6.0):
            window.undo_stack.push(SetPageLookCommand(
                graph, "p1", key="radius",
                tile_style=graph.pages["p1"].tile_style.with_value(
                    "radius", radius)))
        assert graph.pages["p1"].tile_style.radius == 6.0
        window.undo_stack.push(SetPageLookCommand(
            graph, "p1", background="#ffffff", key="background"))
        window.undo_stack.undo()
        assert graph.pages["p1"].background is None
        assert graph.pages["p1"].tile_style.radius == 6.0
        window.undo_stack.undo()   # the three radius steps were one
        assert graph.pages["p1"].tile_style == TileStyle()

    def test_tile_styles_undo_together(self, window):
        _page(window)
        a = _tile(window, _node(window), "a")
        b = _tile(window, _node(window), "b", rect=(320, 0, 300, 200))
        window.undo_stack.push(SetTileStylesCommand(
            window.graph, "p1",
            {"a": TileStyle(frame=False), "b": TileStyle(frame=False)},
            key="frame"))
        assert a.look().frame is False and b.look().frame is False
        window.undo_stack.undo()
        assert a.look().frame is True and b.look().frame is True

    def test_duplicate_page_keeps_the_format(self, window):
        _page(window)
        _tile(window, _node(window), style=TileStyle(title=False))
        window.graph.set_page_look("p1", background="#ffffff",
                                   tile_style=TileStyle(radius=0.0))
        window.undo_stack.push(DuplicatePageCommand(window.graph, "p1"))
        copy = next(p for p in window.graph.pages.values() if p.id != "p1")
        assert copy.background == "#ffffff"
        assert copy.tile_style == TileStyle(radius=0.0)
        (tile,) = copy.tiles.values()
        assert tile.style == TileStyle(title=False)
        # copies, not the original's objects
        tile.style.title = True
        assert window.graph.pages["p1"].tiles["t1"].style.title is False

    def test_copy_and_paste_keep_a_tiles_format(self, window):
        page = _page(window)
        item = _tile(window, _node(window), style=TileStyle(radius=20.0))
        page.view._copy_tiles(item)
        page.view._paste_tiles(anchor=item)
        pasted = [t for t in window.graph.pages["p1"].tiles.values()
                  if t.id != "t1"]
        assert pasted and pasted[0].style == TileStyle(radius=20.0)


# ------------------------------------------------------------- the tile


class TestHowATileDraws:
    def test_an_unformatted_tile_is_laid_out_as_before(self, window):
        _page(window)
        item = _tile(window, _node(window))
        assert item._title_h() == TITLE_H
        assert item._content_rect().top() == TITLE_H
        assert item.boundingRect().left() == -1.0
        assert not item.grip_active()

    def test_no_title_puts_the_content_at_the_top(self, window):
        _page(window)
        item = _tile(window, _node(window), style=TileStyle(title=False))
        assert item._title_h() == 0
        assert item._content_rect().top() < 4.0
        assert item.grip_active()

    def test_padding_and_round_corners_inset_the_content(self, window):
        _page(window)
        item = _tile(window, _node(window),
                     style=TileStyle(padding=10.0, radius=20.0))
        rect = item._content_rect()
        # 0.3 of the radius keeps a rectangle's corner off the curve
        assert rect.left() == pytest.approx(6.0 + 10.0)
        assert rect.top() == pytest.approx(TITLE_H + 10.0)

    def test_a_bigger_title_gets_a_taller_bar(self, window):
        _page(window)
        item = _tile(window, _node(window), style=TileStyle(title_size=20.0))
        assert item._title_h() > TITLE_H
        assert item._content_rect().top() == item._title_h()

    def test_title_text_names_the_tile_not_the_node(self, window):
        _page(window)
        node = _node(window, label="Revenue")
        item = _tile(window, node, style=TileStyle(title_text="Q3 revenue"))
        assert item._title() == "Q3 revenue"
        assert item.fullscreen_title() == "Q3 revenue"
        assert window.graph.nodes[node.id].label == "Revenue"

    def test_a_shadow_is_room_outside_the_tile(self, window):
        _page(window)
        item = _tile(window, _node(window), style=TileStyle(shadow=True))
        assert item.boundingRect().left() == -SHADOW_PAD
        see_through = _tile(window, _node(window), "t2",
                            style=TileStyle(shadow=True,
                                            background=TRANSPARENT))
        # nothing to cast one: a shadow under a clear tile is a dark slab
        assert see_through.boundingRect().left() == -1.0

    def test_a_page_format_reaches_every_tile_at_once(self, window):
        _page(window)
        a = _tile(window, _node(window), "a")
        b = _tile(window, _node(window), "b", rect=(320, 0, 300, 200),
                  style=TileStyle(title=True))
        window.undo_stack.push(SetPageLookCommand(
            window.graph, "p1", tile_style=TileStyle(title=False)))
        assert a._title_h() == 0
        assert b._title_h() == TITLE_H     # its own says otherwise
        window.undo_stack.undo()
        assert a._title_h() == TITLE_H

    def test_a_transparent_fill_clears_the_content_host(self, window):
        _page(window)
        item = _tile(window, _node(window),
                     style=TileStyle(background=TRANSPARENT))
        assert "transparent" in item._proxy.widget().styleSheet()
        window.undo_stack.push(SetTileStylesCommand(
            window.graph, "p1", {"t1": TileStyle(background="#ffffff")}))
        assert "#ffffff" in item._proxy.widget().styleSheet()

    def test_buttons_take_no_format(self, window):
        _page(window)
        window.graph.set_page_look("p1", tile_style=TileStyle(title=False,
                                                              radius=30.0))
        item = _tile(window, _node(window, "flograph.util.action_button"),
                     port=None)
        assert not item.styleable()
        assert item.look() == CARD_LOOK
        assert not item.grip_active()

    def test_the_grip_is_gone_on_a_locked_page(self, window):
        _page(window)
        item = _tile(window, _node(window), style=TileStyle(title=False))
        assert item.grip_live()
        strip = QPointF(item._size[0] / 2, GRIP_H / 2)
        assert item.shape().contains(strip)
        window._dashboard_pages["p1"].set_view_mode(True)
        assert not item.grip_live()
        assert not item.shape().contains(strip)
        # the maximize glyph still answers, as it does in a title bar
        assert item.shape().contains(item._fs_button_rect().center())

    def test_a_tile_has_no_python_child_item(self, window):
        """The grip and glyph were once a Python QGraphicsItem of their own
        over the content, and painting it through a wrapper PySide had let
        go of segfaulted the app. The tile paints them now; the stock proxy
        is its only child, and it stacks behind the tile."""
        _page(window)
        for tile_id, style in (("a", TileStyle()),
                               ("b", TileStyle(title=False))):
            item = _tile(window, _node(window), tile_id, style=style,
                         rect=(0, 0, 300, 200) if tile_id == "a"
                         else (320, 0, 300, 200))
            assert item.childItems() == [item._proxy]
            assert item._proxy.flags() & \
                item._proxy.GraphicsItemFlag.ItemStacksBehindParent

    def test_the_content_takes_its_own_clicks(self, window):
        """The proxy is behind the tile, so the tile's shape has to leave
        the content out or a chart would never see a click or a hover."""
        _page(window)
        item = _tile(window, _node(window), style=TileStyle(title=False))
        assert item._proxy.isVisible()   # the run prompt is showing
        content = item._content_rect()
        assert not item.shape().contains(content.center())
        # the edge, the grip strip and the glyph are the tile's
        assert item.shape().contains(QPointF(0.5, content.center().y()))
        assert item.shape().contains(QPointF(content.center().x(), 3.0))

    def test_page_background_and_grid_follow_the_page(self, window):
        page = _page(window)
        from flograph.ui import theme
        assert page.view.background_colour() == theme.CANVAS_BG
        assert page.view.grid_colours() == (theme.GRID_FINE,
                                            theme.GRID_COARSE)
        window.undo_stack.push(SetPageLookCommand(
            window.graph, "p1", background="#ffffff"))
        assert page.view.background_colour() == QColor("#ffffff")
        fine, coarse = page.view.grid_colours()
        assert fine.red() == 0 and coarse.alpha() < 80   # faint dark lines


class TestTheGripMovesATile:
    def test_dragging_the_grip_moves_a_tile_with_no_title(
            self, window, shown_page, qtbot):
        _page(window)
        _tile(window, _node(window), rect=(100.0, 100.0, 300.0, 200.0),
              style=TileStyle(title=False))
        page = shown_page()
        page.scene.snap_enabled = False
        item = page.scene.tile_items["t1"]
        viewport = page.view.viewport()
        start = page.view.mapFromScene(
            item.mapToScene(QPointF(150.0, GRIP_H / 2)))
        end = start + (page.view.mapFromScene(QPointF(160.0, 140.0))
                       - page.view.mapFromScene(QPointF(100.0, 100.0)))
        QTest.mousePress(viewport, Qt.LeftButton, Qt.NoModifier, start)
        QTest.mouseMove(viewport, start + (end - start) / 2)
        QTest.mouseMove(viewport, end)
        QTest.mouseRelease(viewport, Qt.LeftButton, Qt.NoModifier, end)
        x, y, w, h = window.graph.pages["p1"].tiles["t1"].rect
        assert (x, y) == pytest.approx((160.0, 140.0), abs=2.0)
        assert (w, h) == (300.0, 200.0)

    def test_a_press_below_the_grip_does_not_move_it(
            self, window, shown_page):
        _page(window)
        _tile(window, _node(window), rect=(100.0, 100.0, 300.0, 200.0),
              style=TileStyle(title=False))
        page = shown_page()
        item = page.scene.tile_items["t1"]
        viewport = page.view.viewport()
        start = page.view.mapFromScene(item.mapToScene(QPointF(150.0, 90.0)))
        end = start + page.view.mapFromScene(QPointF(160.0, 160.0)) \
            - page.view.mapFromScene(QPointF(100.0, 100.0))
        QTest.mousePress(viewport, Qt.LeftButton, Qt.NoModifier, start)
        QTest.mouseMove(viewport, end)
        QTest.mouseRelease(viewport, Qt.LeftButton, Qt.NoModifier, end)
        assert window.graph.pages["p1"].tiles["t1"].rect[:2] == (100.0, 100.0)


class TestEveryKindPaints:
    @pytest.mark.parametrize("style", [TileStyle(), TileStyle(title=False),
                                       TileStyle(shadow=True, radius=12.0)])
    def test_a_kpi_with_a_value_paints(self, window, style):
        """A KPI showing its number dims by whether its node is updating.
        paint() once lost the name it read that from, and every KPI tile
        with a value raised in paint until Qt segfaulted — on a flow that
        had been run, never on a test page that hadn't. Painted straight
        from Python, so an error fails here instead of printing."""
        from PySide6.QtGui import QImage, QPainter
        _page(window)
        item = _tile(window, _node(window), style=style)
        item._kpi_has_value = True
        item._kpi_value = 1234.5
        image = QImage(400, 300, QImage.Format_ARGB32)
        painter = QPainter(image)
        try:
            item.paint(painter, None)
        finally:
            painter.end()


class TestFramelessEdge:
    def test_no_dashed_edge_until_the_pointer_is_over_it(self, window):
        """A frameless page should look frameless while it is being built:
        the dashed edge that lets a frameless tile be found shows only
        under the pointer."""
        _page(window)
        item = _tile(window, _node(window), style=TileStyle(frame=False))
        assert item.outline_pen() is None
        item._set_hovered(True)
        pen = item.outline_pen()
        assert pen is not None and pen.style() == Qt.DashLine
        window._dashboard_pages["p1"].set_view_mode(True)
        assert item.outline_pen() is None          # never on a locked page
        window._dashboard_pages["p1"].set_view_mode(False)
        item._set_hovered(False)
        item.setSelected(True)
        assert item.outline_pen().style() == Qt.SolidLine   # the selection

    def test_a_framed_tile_keeps_its_frame(self, window):
        _page(window)
        item = _tile(window, _node(window), style=TileStyle(
            frame_color="#dc2626", frame_width=3.0))
        pen = item.outline_pen()
        assert pen.color() == QColor("#dc2626") and pen.widthF() == 3.0


class TestMaximizeButton:
    def test_hidden_it_cannot_be_maximized(self, window):
        _page(window)
        item = _tile(window, _node(window), style=TileStyle(maximize=False))
        assert not item.can_fullscreen()
        item._request_fullscreen()
        assert window.graph.pages["p1"].maximized_tile is None

    def test_a_page_can_hide_every_button(self, window):
        _page(window)
        a = _tile(window, _node(window), "a")
        b = _tile(window, _node(window), "b", rect=(320, 0, 300, 200),
                  style=TileStyle(maximize=True))
        window.undo_stack.push(SetPageLookCommand(
            window.graph, "p1", tile_style=TileStyle(maximize=False)))
        assert not a.can_fullscreen()
        assert b.can_fullscreen()              # its own says otherwise
        window.undo_stack.undo()
        assert a.can_fullscreen()

    def test_no_glyph_to_click_on_a_tile_with_no_title(self, window):
        _page(window)
        item = _tile(window, _node(window),
                     style=TileStyle(title=False, maximize=False))
        glyph = item._fs_button_rect().center()
        assert not item.shape().contains(glyph) or \
            item._grip_rect().contains(glyph)
        window._dashboard_pages["p1"].set_view_mode(True)
        assert not item.shape().contains(glyph)

    def test_a_maximized_tile_can_still_be_restored(self, window):
        page = _page(window)
        item = _tile(window, _node(window))
        page.scene.toggle_fullscreen("t1")
        window.undo_stack.push(SetTileStylesCommand(
            window.graph, "p1", {"t1": TileStyle(maximize=False)}))
        assert item.can_fullscreen()           # a way back out
        page.scene.exit_fullscreen()
        assert not item.can_fullscreen()

    def test_the_pane_has_the_switch(self, window):
        page = _page(window)
        _tile(window, _node(window)).setSelected(True)
        field = page.format.tile_form.field("maximize")
        assert field.itemText(0) == "Page (on)"
        field.setCurrentIndex(2)               # Off
        assert window.graph.pages["p1"].tiles["t1"].style.maximize is False

    def test_saved(self, registry):
        graph = Graph()
        graph.add_page(Page(id="p", title="P"))
        graph.add_tile("p", Tile(id="t", node_id="gone",
                                 style=TileStyle(maximize=False)))
        data = serialization.graph_to_dict(graph)
        assert data["graph"]["pages"][0]["tiles"][0]["style"] == \
            {"maximize": False}
        loaded = serialization.graph_from_dict(data, registry)
        assert loaded.pages["p"].tiles["t"].style.maximize is False


class TestStrayMenus:
    """On Wayland a page tab's right-click arrives after the tab's menu has
    closed, at whatever is under the pointer then. Locking or unlocking a
    page puts its panels there, and the leftover opened the window's dock
    list over the page. Offscreen sends no platform context events, so these
    pin the two halves of the fix rather than the gesture."""

    def test_a_right_click_on_the_panels_stops_at_the_page(self, window):
        from PySide6.QtCore import QPoint
        from PySide6.QtGui import QContextMenuEvent
        page = _page(window)
        event = QContextMenuEvent(QContextMenuEvent.Reason.Mouse,
                                  QPoint(4, 4), QPoint(4, 4))
        event.setAccepted(False)
        page.contextMenuEvent(event)
        assert event.isAccepted()

    def test_boxes_ignore_a_menus_leftovers(self, window, monkeypatch):
        from PySide6.QtCore import QPoint
        from PySide6.QtGui import QContextMenuEvent
        from flograph.ui import menu_guard
        monkeypatch.setattr(menu_guard, "stray", lambda event: True)
        page = _page(window)
        for box in (page.visuals_search,
                    page.format.tile_form.field("title_text"),
                    page.format.tile_form.field("radius")):
            event = QContextMenuEvent(QContextMenuEvent.Reason.Mouse,
                                      QPoint(2, 2), QPoint(2, 2))
            event.setAccepted(False)
            box.contextMenuEvent(event)   # returns: no menu was opened
            assert event.isAccepted()


class TestShadowStaysOutside:
    def test_a_shadow_never_darkens_the_content(self, window, shown_page):
        """The tile paints over its content, so a shadow drawn across the
        whole tile laid six veils of black over it: a white tile's chart
        came out grey. It is clipped to outside the tile."""
        from PySide6.QtWidgets import QApplication
        _page(window)
        _tile(window, _node(window), rect=(0.0, 0.0, 300.0, 200.0),
              style=TileStyle(shadow=True, frame=False, title=False,
                              background="#ffffff"))
        window.graph.set_page_look("p1", background="#ff00ff")
        page = shown_page()
        page.scene.grid_visible = False
        page.view.centerOn(150.0, 100.0)
        QApplication.processEvents()
        item = page.scene.tile_items["t1"]
        image = page.view.viewport().grab().toImage()
        content = item._content_rect()
        inside = page.view.mapFromScene(item.mapToScene(
            QPointF(content.left() + 3.0, content.top() + 3.0)))
        below = page.view.mapFromScene(item.mapToScene(QPointF(150.0, 204.0)))
        assert image.pixelColor(inside).name() == "#ffffff"
        # and there is still a shadow, on the page under the tile
        assert image.pixelColor(below).name() != "#ff00ff"


# ------------------------------------------------------------- the pane


class TestFormatPane:
    def test_nothing_selected_says_how_to_start(self, window):
        page = _page(window)
        _tile(window, _node(window))
        assert page.format.tile_form.isHidden()
        assert "Select a visual" in page.format.selection_note.text()

    def test_selecting_a_tile_shows_its_format(self, window):
        page = _page(window)
        item = _tile(window, _node(window, label="Revenue"),
                     style=TileStyle(frame=False))
        item.setSelected(True)
        pane = page.format
        assert not pane.tile_form.isHidden()
        assert pane.selection_note.text() == "Revenue"
        assert pane.tile_form.field("frame").value() is False
        assert pane.tile_form.field("radius").value_or_none() is None
        assert pane.tile_form.field("title_text").placeholderText() \
            == "Revenue"

    def test_a_change_is_an_undoable_edit_of_the_selection(self, window):
        page = _page(window)
        item = _tile(window, _node(window))
        item.setSelected(True)
        page.format.tile_form.field("title").setCurrentIndex(2)   # Off
        assert window.graph.pages["p1"].tiles["t1"].style.title is False
        assert item._title_h() == 0
        window.undo_stack.undo()
        assert window.graph.pages["p1"].tiles["t1"].style.title is None
        # the pane redraws from the model, so it follows the undo
        assert page.format.tile_form.field("title").value() is None

    def test_a_number_steps_into_one_undo(self, window):
        page = _page(window)
        _tile(window, _node(window)).setSelected(True)
        radius = page.format.tile_form.field("radius")
        for value in (4.0, 8.0, 12.0):
            radius.setValue(value)
        assert window.graph.pages["p1"].tiles["t1"].style.radius == 12.0
        window.undo_stack.undo()
        assert window.graph.pages["p1"].tiles["t1"].style.radius is None

    def test_several_selected_change_together(self, window):
        page = _page(window)
        a = _tile(window, _node(window), "a")
        b = _tile(window, _node(window), "b", rect=(320, 0, 300, 200))
        a.setSelected(True)
        b.setSelected(True)
        pane = page.format
        assert pane.tile_section.toggle.text() == "2 Selected Visuals"
        assert not pane.tile_form.field("title_text").isEnabled()
        pane.tile_form.field("shadow").setCurrentIndex(1)   # On
        tiles = window.graph.pages["p1"].tiles
        assert tiles["a"].style.shadow is True and tiles["b"].style.shadow

    def test_the_page_section_formats_every_tile(self, window):
        page = _page(window)
        item = _tile(window, _node(window))
        page.format.page_form.field("title_background").pick(TRANSPARENT)
        page.format.background.pick("#ffffff")
        graph_page = window.graph.pages["p1"]
        assert graph_page.tile_style.title_background == TRANSPARENT
        assert graph_page.background == "#ffffff"
        assert item.look().title_background == TRANSPARENT
        window.undo_stack.undo()
        assert graph_page.background is None
        assert page.format.background.value() is None

    def test_a_tile_field_says_what_the_page_would_give(self, window):
        page = _page(window)
        window.undo_stack.push(SetPageLookCommand(
            window.graph, "p1", tile_style=TileStyle(radius=14.0)))
        _tile(window, _node(window)).setSelected(True)
        assert page.format.tile_form.field("radius").specialValueText() \
            == "Page (14 px)"
        assert page.format.page_form.field("radius").specialValueText() \
            == "Default (6 px)"

    def test_reset_and_clear_all_take_a_tiles_own_format_away(self, window):
        page = _page(window)
        a = _tile(window, _node(window), "a", style=TileStyle(frame=False))
        _tile(window, _node(window), "b", rect=(320, 0, 300, 200),
              style=TileStyle(radius=0.0))
        a.setSelected(True)
        assert page.format.reset_button.isEnabled()
        page.format.reset_button.click()
        tiles = window.graph.pages["p1"].tiles
        assert tiles["a"].style.is_empty()
        assert not tiles["b"].style.is_empty()
        page.format.clear_all_button.click()
        assert tiles["b"].style.is_empty()
        assert not page.format.clear_all_button.isEnabled()

    def test_a_note_offers_only_its_text_colour_from_the_title(self, window):
        page = _page(window)
        _tile(window, _node(window, "flograph.util.note"),
              port=None).setSelected(True)
        form = page.format.tile_form
        assert form.row_visible("title_color")
        assert not form.row_visible("title")
        assert not form.row_visible("title_size")

    def test_buttons_say_they_take_no_format(self, window):
        page = _page(window)
        _tile(window, _node(window, "flograph.util.action_button"),
              port=None).setSelected(True)
        assert page.format.tile_form.isHidden()
        assert "draw their own face" in page.format.selection_note.text()


class TestFormatPaneChrome:
    def test_locking_hides_the_pane_and_its_strip(self, window, shown_page):
        _page(window)
        page = shown_page(format_visible=True)
        assert page.format.isVisible() and page._format_strip.isVisible()
        page.set_view_mode(True)
        assert not page.format.isVisible()
        assert not page._format_strip.isVisible()
        page.set_view_mode(False)
        # the preference survived the lock
        assert page.format.isVisible()

    def test_the_strip_toggles_the_pane(self, window, shown_page):
        _page(window)
        page = shown_page(format_visible=False)
        assert not page.format.isVisible()
        page._format_btn.click()
        assert page.format.isVisible() and page.format_visible()

    def test_format_from_a_menu_opens_the_pane(self, window, shown_page):
        _page(window)
        page = shown_page(format_visible=False)
        page.view.format_requested.emit()
        assert page.format.isVisible()

    def test_the_window_remembers_the_pane_for_new_pages(self, window):
        page = _page(window)
        assert not page.format_visible()
        page.set_format_visible(True)
        assert window.settings.value("dashboard/format_visible",
                                     type=bool) is True
        assert _page(window, "p2").format_visible()


# ----------------------------------------------------- finding a visual


class TestFindingAVisual:
    def _visuals(self, window):
        _node(window, label="Revenue")
        _node(window, label="Orders")
        _node(window, "flograph.viz.show_table", label="Accounts")
        _node(window, "flograph.util.note", label="Heading")
        return _page(window)

    def _rows(self, page):
        return [page.visuals.item(i).text().split(" ", 1)[1]
                for i in range(page.visuals.count())]

    def test_search_by_name(self, window):
        page = self._visuals(window)
        page.visuals_search.setText("rev")
        assert self._rows(page) == ["Revenue"]
        assert page.visuals_clear.isEnabled()

    def test_search_by_type_and_every_word_must_match(self, window):
        page = self._visuals(window)
        page.visuals_search.setText("table")
        assert self._rows(page) == ["Accounts"]
        page.visuals_search.setText("table orders")
        assert self._rows(page) == []
        assert not page.visuals_empty.isHidden()

    def test_ticking_types_works_like_a_slicer(self, window):
        """Nothing ticked shows every type; ticking narrows the list to
        what is ticked."""
        page = self._visuals(window)
        kinds = {kind for kind, _label, _count
                 in page.visuals.kinds_present()}
        assert {"kpi", "table_viewer", "note"} <= kinds
        assert page.visuals.kinds() == frozenset()
        assert page.visuals.count() == 4
        assert page.visuals_types.text() == "All types"
        page._tick_kind("kpi", True)
        assert self._rows(page) == ["Orders", "Revenue"]
        assert page.visuals_types.text() == "KPI"
        page._tick_kind("note", True)
        assert self._rows(page) == ["Heading", "Orders", "Revenue"]
        assert page.visuals_types.text() == "2 types"
        page._tick_kind("kpi", False)
        page._tick_kind("note", False)
        assert page.visuals.count() == 4
        assert page.visuals_types.text() == "All types"

    def test_nothing_ticked_shows_a_type_new_to_the_flow(self, window):
        page = self._visuals(window)
        _node(window, "flograph.viz.show_table", label="Stock")
        assert "Stock" in self._rows(page)

    def test_sorts(self, window):
        page = self._visuals(window)
        assert self._rows(page) == ["Accounts", "Heading", "Orders",
                                    "Revenue"]
        page.visuals_sort.setCurrentIndex(
            page.visuals_sort.findData("name_desc"))
        assert self._rows(page) == ["Revenue", "Orders", "Heading",
                                    "Accounts"]
        page.visuals_sort.setCurrentIndex(page.visuals_sort.findData("kind"))
        # by type label (KPI, Note, Table), names A–Z within one
        assert self._rows(page) == ["Orders", "Revenue", "Heading",
                                    "Accounts"]

    def test_clear_puts_every_visual_back_but_keeps_the_sort(self, window):
        page = self._visuals(window)
        page.visuals_sort.setCurrentIndex(
            page.visuals_sort.findData("name_desc"))
        page.visuals_search.setText("rev")
        page._tick_kind("note", True)
        page.clear_visual_filters()
        assert page.visuals_search.text() == ""
        assert page.visuals.count() == 4
        assert page.visuals.sort_mode() == "name_desc"
        assert not page.visuals_clear.isEnabled()

    def test_the_types_menu_opens_with_nothing_ticked(self, window):
        from PySide6.QtWidgets import QCheckBox
        page = self._visuals(window)
        page._fill_types_menu()
        boxes = page.visuals_types.menu().findChildren(QCheckBox)
        assert boxes and not any(box.isChecked() for box in boxes)
        page._tick_kind("note", True)
        page._fill_types_menu()
        ticked = {box.text(): box.isChecked() for box in
                  page.visuals_types.menu().findChildren(QCheckBox)}
        assert any(text.endswith("Note (1)") and on
                   for text, on in ticked.items())
        assert any(text.endswith("KPI (2)") and not on
                   for text, on in ticked.items())

    def test_a_ticked_type_with_no_visuals_left_can_be_unticked(self, window):
        from PySide6.QtWidgets import QCheckBox
        page = self._visuals(window)
        page._tick_kind("slicer", True)       # the flow has none
        assert page.visuals.count() == 0
        page._fill_types_menu()
        boxes = [box for box in
                 page.visuals_types.menu().findChildren(QCheckBox)
                 if box.text().endswith("Slicer (0)")]
        assert boxes and boxes[0].isChecked()
        boxes[0].setChecked(False)
        assert page.visuals.count() == 4
