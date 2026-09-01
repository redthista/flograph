"""The interactive viz cards: Slicer (checkbox filter that re-runs the
visuals downstream), Card (big painted KPI value) and Table Spec (spec grid
on the canvas)."""
import json

import pytest
from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QResizeEvent, QUndoStack
from PySide6.QtWidgets import QApplication

from flograph.core import Graph, NodeRegistry, Page, Tile
from flograph.ui.canvas import NodeGraphScene
from flograph.ui.dashboard import default_tile_port, default_tile_size
from flograph.ui.mainwindow import MainWindow

REGIONS = {"columns": ["region", "units"],
           "rows": [["north", "10"], ["south", "20"], ["north", "30"]]}


def _resize_event(w: int, h: int) -> QResizeEvent:
    return QResizeEvent(QSize(w, h), QSize(w, h))


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
    yield win
    # deterministic teardown: dispose dashboard pages (core events hold
    # strong refs to their scenes) and drain deferred deletions now, while
    # the window is intact — leaving them to a later test's event loop is
    # what flips the suite's pre-existing teardown segfault
    for page in list(win._dashboard_pages.values()):
        page.dispose()
    win.close()
    QApplication.processEvents()


def _add_sliced_flow(win):
    """Table -> Slicer(region) -> Show Table, returning the three nodes."""
    source = win.registry.instantiate("flograph.io.table", pos=(0, 0))
    slicer = win.registry.instantiate("flograph.viz.slicer", pos=(400, 0))
    shown = win.registry.instantiate("flograph.viz.show_table", pos=(800, 0))
    for node in (source, slicer, shown):
        win.graph.add_node(node)
    win.graph.set_param(source.id, "data", json.dumps(REGIONS))
    win.graph.set_param(slicer.id, "column", "region")
    win.graph.connect(source.id, "table", slicer.id, "table")
    win.graph.connect(slicer.id, "table", shown.id, "table")
    return source, slicer, shown


class TestSlicerCard:
    def test_item_is_a_resizable_widget_card(self, env, registry):
        graph, stack, scene = env
        node = graph.add_node(registry.instantiate("flograph.viz.slicer"))
        item = scene.node_items[node.id]
        assert item.slicer
        assert item._slicer_list is not None
        assert item._slicer_list.isHidden()  # placeholder until a run

    def test_card_size_params_are_cosmetic(self, registry):
        """Resizing the card must not re-filter the table or re-run the
        visuals downstream — run() never reads width/height."""
        spec = registry.get("flograph.viz.slicer")
        assert spec.param("width").cosmetic
        assert spec.param("height").cosmetic

    def test_the_value_list_is_clipped_to_the_card(self, env, registry):
        """Reported: dragging the card short let the bottom rows paint out
        through its edge — a QListWidget won't shrink past its own minimum,
        so the proxy has to clip it."""
        from PySide6.QtWidgets import QGraphicsItem
        graph, _stack, scene = env
        node = graph.add_node(registry.instantiate("flograph.viz.slicer"))
        item = scene.node_items[node.id]
        assert item._slicer_proxy.flags() & QGraphicsItem.ItemClipsToShape
        graph.set_param(node.id, "height", 10)   # clamped to the floor
        assert item.body_height >= 150

    def test_a_resize_does_not_dirty_the_slicer(self, qtbot, window):
        win = window
        _source, slicer, shown = _add_sliced_flow(win)
        with qtbot.waitSignal(win.engine.run_finished, timeout=20000):
            win.engine.run_all()
        assert not win.graph.nodes[slicer.id].dirty

        win.graph.set_param(slicer.id, "width", 360)
        win.graph.set_param(slicer.id, "height", 500)

        assert not win.graph.nodes[slicer.id].dirty
        assert not win.graph.nodes[shown.id].dirty

    def test_options_populate_after_a_run(self, qtbot, window):
        win = window
        _source, slicer, _shown = _add_sliced_flow(win)
        with qtbot.waitSignal(win.engine.run_finished, timeout=20000):
            win.engine.run_all()
        widget = win.scene.node_items[slicer.id]._slicer_list
        texts = [widget.item(i).text() for i in range(widget.count())]
        assert texts == ["north", "south"]

    def test_tick_commits_param_and_reruns_downstream(self, qtbot, window):
        win = window
        _source, slicer, shown = _add_sliced_flow(win)
        with qtbot.waitSignal(win.engine.run_finished, timeout=20000):
            win.engine.run_all()

        widget = win.scene.node_items[slicer.id]._slicer_list
        # ticking "north" commits the selection and auto-runs downstream
        with qtbot.waitSignal(win.engine.run_finished, timeout=20000):
            widget.item(0).setCheckState(Qt.Checked)

        assert json.loads(win.graph.nodes[slicer.id].params["selected"]) \
            == ["north"]
        filtered = win.engine.cache.get(shown.id).outputs["table"]
        assert list(filtered["region"]) == ["north", "north"]
        # untick via undo: the param rolls back and the checks resync
        win.undo_stack.undo()
        assert win.graph.nodes[slicer.id].params["selected"] == ""
        assert widget.item(0).checkState() == Qt.Unchecked

    def test_single_mode_radio_behaviour(self, qtbot, window):
        win = window
        _source, slicer, shown = _add_sliced_flow(win)
        win.graph.set_param(slicer.id, "mode", "single")
        with qtbot.waitSignal(win.engine.run_finished, timeout=20000):
            win.engine.run_all()

        widget = win.scene.node_items[slicer.id]._slicer_list
        with qtbot.waitSignal(win.engine.run_finished, timeout=20000):
            widget.item(0).setCheckState(Qt.Checked)  # "north"
        assert json.loads(win.graph.nodes[slicer.id].params["selected"]) \
            == ["north"]

        # ticking a second value clears the first — only one at a time
        with qtbot.waitSignal(win.engine.run_finished, timeout=20000):
            widget.item(1).setCheckState(Qt.Checked)  # "south"
        assert widget.item(0).checkState() == Qt.Unchecked
        assert json.loads(win.graph.nodes[slicer.id].params["selected"]) \
            == ["south"]
        filtered = win.engine.cache.get(shown.id).outputs["table"]
        assert list(filtered["region"]) == ["south"]

        # clicking the ticked value again clears the selection entirely
        with qtbot.waitSignal(win.engine.run_finished, timeout=20000):
            widget.item(1).setCheckState(Qt.Unchecked)
        assert win.graph.nodes[slicer.id].params["selected"] == ""

    def test_switching_to_single_mode_trims_a_multi_selection(
            self, qtbot, window):
        """Flipping the "Selection" param from multi to single with two
        values already ticked must trim to one — otherwise the card would
        keep showing both ticked while run() (which only honours the first
        in single mode) filters on just one, a silent card/data mismatch."""
        win = window
        _source, slicer, shown = _add_sliced_flow(win)
        with qtbot.waitSignal(win.engine.run_finished, timeout=20000):
            win.engine.run_all()
        widget = win.scene.node_items[slicer.id]._slicer_list
        with qtbot.waitSignal(win.engine.run_finished, timeout=20000):
            widget.select_all()  # both "north" and "south" ticked
        assert widget.selected_values() == ["north", "south"]

        with qtbot.waitSignal(win.engine.run_finished, timeout=20000):
            win.graph.set_param(slicer.id, "mode", "single")

        assert widget.selected_values() == ["north"]
        assert json.loads(win.graph.nodes[slicer.id].params["selected"]) \
            == ["north"]
        filtered = win.engine.cache.get(shown.id).outputs["table"]
        assert list(filtered["region"]) == ["north", "north"]

    def test_search_filter_keeps_ticks_on_non_matching_values(
            self, qtbot, window):
        win = window
        _source, slicer, _shown = _add_sliced_flow(win)
        with qtbot.waitSignal(win.engine.run_finished, timeout=20000):
            win.engine.run_all()

        item = win.scene.node_items[slicer.id]
        widget = item._slicer_list
        with qtbot.waitSignal(win.engine.run_finished, timeout=20000):
            widget.item(0).setCheckState(Qt.Checked)  # tick "north"

        widget.set_filter("south")
        # "north" doesn't match, but a ticked value always keeps a row so the
        # tick stays visible and un-losable
        rows = {widget.item(i).text(): widget.item(i)
                for i in range(widget.count())}
        assert rows["north"].checkState() == Qt.Checked
        assert widget.selected_values() == ["north"]

        # a search matching neither value still doesn't drop the tick
        widget.set_filter("zzz")
        assert widget.selected_values() == ["north"]

        widget.set_filter("")
        assert widget.selected_values() == ["north"]

    def test_filter_survives_the_rerun_a_tick_triggers(self, qtbot, window):
        """Ticking a value re-runs the slicer, which repopulates the list
        from the freshly-cached upstream table (set_slicer_options ->
        set_options -> rebuild) — an active search must not be silently
        dropped by that rebuild."""
        win = window
        _source, slicer, _shown = _add_sliced_flow(win)
        with qtbot.waitSignal(win.engine.run_finished, timeout=20000):
            win.engine.run_all()

        widget = win.scene.node_items[slicer.id]._slicer_list
        widget.set_filter("north")
        assert [widget.item(i).text() for i in range(widget.count())] == ["north"]

        with qtbot.waitSignal(win.engine.run_finished, timeout=20000):
            widget.item(0).setCheckState(Qt.Checked)  # tick "north" (visible)

        # the rebuild the tick triggered must not have cleared the filter
        assert [widget.item(i).text() for i in range(widget.count())] == ["north"]
        assert widget.item(0).checkState() == Qt.Checked

    def test_select_all_and_clear_all_respect_the_filter(self, qtbot, window):
        win = window
        _source, slicer, _shown = _add_sliced_flow(win)
        with qtbot.waitSignal(win.engine.run_finished, timeout=20000):
            win.engine.run_all()

        widget = win.scene.node_items[slicer.id]._slicer_list
        widget.set_filter("north")
        with qtbot.waitSignal(win.engine.run_finished, timeout=20000):
            widget.select_all()
        assert widget.selected_values() == ["north"]  # "south" stayed hidden

        widget.set_filter("")
        with qtbot.waitSignal(win.engine.run_finished, timeout=20000):
            widget.clear_all()
        assert widget.selected_values() == []

    def test_toolbar_hides_select_all_in_single_mode(self, qtbot):
        from flograph.ui.slicer_list import SlicerListWidget, SlicerToolbar
        target = SlicerListWidget()
        toolbar = SlicerToolbar(target)
        qtbot.addWidget(toolbar)
        assert not toolbar._select_all.isHidden()
        toolbar.set_mode("single")
        assert toolbar._select_all.isHidden()
        toolbar.set_mode("multi")
        assert not toolbar._select_all.isHidden()

    def test_toolbar_wraps_the_buttons_under_the_search_when_narrow(self, qtbot):
        """Reported: the card can be dragged narrower than "Search  All  None"
        fits on one row, clipping the buttons. Below the threshold they drop
        onto a second row instead so the card stays usable at small sizes."""
        from flograph.ui.slicer_list import SlicerListWidget, SlicerToolbar
        toolbar = SlicerToolbar(SlicerListWidget())
        qtbot.addWidget(toolbar)
        row_of = lambda w: toolbar._grid.getItemPosition(
            toolbar._grid.indexOf(w))[0]

        toolbar.setFixedWidth(400)
        toolbar.resizeEvent(_resize_event(400, 30))
        assert toolbar._wrapped is False
        assert row_of(toolbar._search) == row_of(toolbar._clear)  # same row

        toolbar.resizeEvent(_resize_event(150, 60))
        assert toolbar._wrapped is True
        assert row_of(toolbar._search) < row_of(toolbar._clear)  # dropped below

    def test_mode_syncs_to_card_after_a_run(self, qtbot, window):
        win = window
        _source, slicer, _shown = _add_sliced_flow(win)
        win.graph.set_param(slicer.id, "mode", "single")
        with qtbot.waitSignal(win.engine.run_finished, timeout=20000):
            win.engine.run_all()
        item = win.scene.node_items[slicer.id]
        assert item._slicer_list._mode == "single"
        assert item._slicer_toolbar._select_all.isHidden()

    def test_single_mode_draws_radios_not_checkboxes(self, qtbot):
        """ideas.md item 14: a checkbox promises you can tick several, which
        single mode then silently undoes. Painting only — the list still
        stores and reports check state."""
        from flograph.ui.slicer_list import SlicerListWidget
        widget = SlicerListWidget()
        qtbot.addWidget(widget)
        widget.set_options(["north", "south"], {"north"})
        assert not widget._delegate.radio
        widget.set_mode("single")
        assert widget._delegate.radio
        assert widget.selected_values() == ["north"]  # unchanged underneath
        widget.set_mode("multi")
        assert not widget._delegate.radio

    def test_radio_rows_keep_the_checkbox_layout(self, qtbot):
        """The radio is drawn by dropping the check indicator and painting
        one in its place; that also collapses the column it occupied, so
        without compensating the label slides left underneath the radio.
        Rendered and diffed rather than reasoned about: the two modes must
        differ *only* inside the indicator's own rectangle."""
        from PySide6.QtGui import QPixmap
        from PySide6.QtWidgets import QStyle, QStyleOptionViewItem
        from flograph.ui.slicer_list import SlicerListWidget

        widgets = {}

        def render(mode):
            widget = SlicerListWidget()
            qtbot.addWidget(widget)
            widget.resize(220, 80)
            widget.set_mode(mode)
            widget.set_options(["north", "south"], {"north"})
            widgets[mode] = widget
            pixmap = QPixmap(widget.size())
            widget.render(pixmap)
            return pixmap.toImage()

        multi, single = render("multi"), render("single")
        assert multi.size() == single.size()

        widget = widgets["multi"]
        option = QStyleOptionViewItem()
        option.rect = widget.visualItemRect(widget.item(0))
        option.features |= \
            QStyleOptionViewItem.ViewItemFeature.HasCheckIndicator
        indicator = widget.style().subElementRect(
            QStyle.SE_ItemViewItemCheckIndicator, option, widget)

        differing = {x for x in range(multi.width())
                     for y in range(multi.height())
                     if multi.pixelColor(x, y) != single.pixelColor(x, y)}
        assert differing, "single mode drew an identical checkbox"
        assert min(differing) >= indicator.left()
        assert max(differing) <= indicator.right()

    @pytest.mark.parametrize("mode", ["multi", "single"])
    def test_clicking_the_label_ticks_the_row(self, qtbot, mode):
        """The row is one target: hitting the 14px tick box exactly is
        needless precision, and the label looked dead when it only
        selected."""
        from flograph.ui.slicer_list import SlicerListWidget
        widget = SlicerListWidget()
        qtbot.addWidget(widget)
        widget.resize(220, 80)
        widget.set_mode(mode)
        widget.set_options(["north", "south"], set())
        widget.show()
        qtbot.waitExposed(widget)

        item = widget.item(0)
        label = widget.visualItemRect(item).center()
        assert not widget._indicator_rect(item).contains(label)

        with qtbot.waitSignal(widget.selection_committed):
            qtbot.mouseClick(widget.viewport(), Qt.LeftButton, pos=label)
        assert widget.selected_values() == ["north"]

        # and clicking it again clears it, same as clicking the box
        with qtbot.waitSignal(widget.selection_committed):
            qtbot.mouseClick(widget.viewport(), Qt.LeftButton, pos=label)
        assert widget.selected_values() == []

    @pytest.mark.parametrize("mode", ["multi", "single"])
    def test_clicking_the_tick_box_still_toggles_once(self, qtbot, mode):
        """The box is left to the base class; toggling there as well would
        cancel out and leave the row looking unclickable."""
        from flograph.ui.slicer_list import SlicerListWidget
        widget = SlicerListWidget()
        qtbot.addWidget(widget)
        widget.resize(220, 80)
        widget.set_mode(mode)
        widget.set_options(["north", "south"], set())
        widget.show()
        qtbot.waitExposed(widget)

        item = widget.item(0)
        with qtbot.waitSignal(widget.selection_committed):
            qtbot.mouseClick(widget.viewport(), Qt.LeftButton,
                             pos=widget._indicator_rect(item).center())
        assert widget.selected_values() == ["north"]

    def test_clicking_a_label_in_single_mode_replaces_the_selection(
            self, qtbot):
        from flograph.ui.slicer_list import SlicerListWidget
        widget = SlicerListWidget()
        qtbot.addWidget(widget)
        widget.resize(220, 80)
        widget.set_mode("single")
        widget.set_options(["north", "south"], {"north"})
        widget.show()
        qtbot.waitExposed(widget)

        with qtbot.waitSignal(widget.selection_committed):
            qtbot.mouseClick(widget.viewport(), Qt.LeftButton,
                             pos=widget.visualItemRect(widget.item(1)).center())
        assert widget.selected_values() == ["south"]

    def test_clicking_the_more_values_note_does_nothing(self, qtbot):
        from flograph.ui.slicer_list import RENDER_BUDGET, SlicerListWidget
        widget = SlicerListWidget()
        qtbot.addWidget(widget)
        widget.resize(220, 80)
        widget.set_options([str(i) for i in range(RENDER_BUDGET + 5)], set())
        widget.show()
        qtbot.waitExposed(widget)

        # RENDER_BUDGET rows built + one non-interactive "… N more" note
        assert widget.count() == RENDER_BUDGET + 1
        note = widget.item(widget.count() - 1)
        assert not (note.flags() & Qt.ItemIsUserCheckable)
        widget.scrollToItem(note)
        qtbot.mouseClick(widget.viewport(), Qt.LeftButton,
                         pos=widget.visualItemRect(note).center())
        assert widget.selected_values() == []

    def test_values_past_the_render_budget_stay_filterable_and_tickable(
            self, qtbot):
        """The budget bounds how many rows are built, not the column: a
        value with no row is still reachable through the search box, and
        ticking it commits and survives clearing the search."""
        from flograph.ui.slicer_list import RENDER_BUDGET, SlicerListWidget
        widget = SlicerListWidget()
        qtbot.addWidget(widget)
        widget.resize(220, 120)
        values = [f"v{i:05d}" for i in range(RENDER_BUDGET + 200)]
        widget.set_options(values, set())
        widget.show()
        qtbot.waitExposed(widget)

        target = values[-1]  # well past the budget, no row yet
        assert all(widget.item(i).text() != target
                   for i in range(widget.count()))

        widget.set_filter(target)
        row = widget.item(0)
        assert row.text() == target
        with qtbot.waitSignal(widget.selection_committed):
            row.setCheckState(Qt.Checked)
        assert widget.selected_values() == [target]

        widget.set_filter("")  # tick survives the rebuild
        assert widget.selected_values() == [target]
        assert widget.selection_summary() == f"1/{len(values)}"

    def test_mode_syncs_the_delegate_from_the_param(self, qtbot, window):
        win = window
        _source, slicer, _shown = _add_sliced_flow(win)
        win.graph.set_param(slicer.id, "mode", "single")
        with qtbot.waitSignal(win.engine.run_finished, timeout=20000):
            win.engine.run_all()
        assert win.scene.node_items[slicer.id]._slicer_list._delegate.radio

    def test_toolbar_count_label_tracks_ticks(self, qtbot, window):
        win = window
        _source, slicer, _shown = _add_sliced_flow(win)
        with qtbot.waitSignal(win.engine.run_finished, timeout=20000):
            win.engine.run_all()
        item = win.scene.node_items[slicer.id]
        assert item._slicer_toolbar._count.text() == "0/2"

        with qtbot.waitSignal(win.engine.run_finished, timeout=20000):
            item._slicer_list.item(0).setCheckState(Qt.Checked)
        assert item._slicer_toolbar._count.text() == "1/2"


class TestKpiCard:
    def test_value_lands_on_the_item_after_a_run(self, qtbot, window):
        win = window
        source = win.registry.instantiate("flograph.io.table", pos=(0, 0))
        card = win.registry.instantiate("flograph.viz.card", pos=(400, 0))
        for node in (source, card):
            win.graph.add_node(node)
        win.graph.set_param(source.id, "data", json.dumps(REGIONS))
        win.graph.set_param(card.id, "column", "units")
        win.graph.connect(source.id, "table", card.id, "table")

        item = win.scene.node_items[card.id]
        assert not item._kpi_has_value
        with qtbot.waitSignal(win.engine.run_finished, timeout=20000):
            win.engine.run_all()
        assert item._kpi_has_value
        assert item._kpi_value == 60
        assert item._kpi_text() == "60"

    def test_text_honours_format_and_defaults(self, env, registry):
        graph, stack, scene = env
        node = graph.add_node(registry.instantiate("flograph.viz.card"))
        item = scene.node_items[node.id]
        item.set_card_value(1234567)
        assert item._kpi_text() == "1,234,567"
        graph.set_param(node.id, "format", ",.2f")
        assert item._kpi_text() == "1,234,567.00"
        item.set_card_value("n/a")  # non-numeric value with a numeric format
        assert item._kpi_text() == "n/a"

    def test_caption_falls_back_to_aggregation_of_column(self, env, registry):
        graph, stack, scene = env
        node = graph.add_node(registry.instantiate("flograph.viz.card"))
        graph.set_param(node.id, "column", "units")
        item = scene.node_items[node.id]
        assert item._kpi_label() == "Sum of units"
        graph.set_param(node.id, "label", "Total units")
        assert item._kpi_label() == "Total units"


def _add_tile(win, page_id: str, node, at=(0.0, 0.0)) -> Tile:
    width, height = default_tile_size(node)
    tile = Tile(id=f"tile-{node.id}", node_id=node.id,
                port=default_tile_port(node),
                rect=(at[0], at[1], width, height))
    win.graph.add_tile(page_id, tile)
    return tile


class TestDashboardTiles:
    def _page(self, win) -> str:
        page = Page(id="p1", title="Page 1")
        win.graph.add_page(page)  # mainwindow builds the DashboardPage
        return page.id

    def test_kpi_tile_paints_the_cached_value(self, qtbot, window):
        win = window
        source = win.registry.instantiate("flograph.io.table", pos=(0, 0))
        card = win.registry.instantiate("flograph.viz.card", pos=(400, 0))
        for node in (source, card):
            win.graph.add_node(node)
        win.graph.set_param(source.id, "data", json.dumps(REGIONS))
        win.graph.set_param(card.id, "column", "units")
        win.graph.connect(source.id, "table", card.id, "table")

        page_id = self._page(win)
        tile = _add_tile(win, page_id, card)
        item = win._dashboard_pages[page_id].scene.tile_items[tile.id]
        assert not item._kpi_has_value
        with qtbot.waitSignal(win.engine.run_finished, timeout=20000):
            win.engine.run_all()
        assert item._kpi_has_value
        assert item._kpi_value == 60

    def test_slicer_tile_ticks_filter_and_rerun_downstream(
            self, qtbot, window):
        win = window
        _source, slicer, shown = _add_sliced_flow(win)
        page_id = self._page(win)
        tile = _add_tile(win, page_id, slicer)
        item = win._dashboard_pages[page_id].scene.tile_items[tile.id]

        with qtbot.waitSignal(win.engine.run_finished, timeout=20000):
            win.engine.run_all()
        widget = item._slicer_widget
        texts = [widget.item(i).text() for i in range(widget.count())]
        assert texts == ["north", "south"]

        # ticking on the dashboard commits the param and re-runs downstream
        with qtbot.waitSignal(win.engine.run_finished, timeout=20000):
            widget.item(1).setCheckState(Qt.Checked)
        assert json.loads(win.graph.nodes[slicer.id].params["selected"]) \
            == ["south"]
        filtered = win.engine.cache.get(shown.id).outputs["table"]
        assert list(filtered["region"]) == ["south"]
        # the canvas card's checkboxes follow the same param
        canvas_list = win.scene.node_items[slicer.id]._slicer_list
        assert canvas_list.selected_values() == ["south"]
        # undo unticks the tile without emitting a new commit
        win.undo_stack.undo()
        assert widget.selected_values() == []


class TestTableSpecCard:
    def test_spec_lands_on_the_table_viewer_card(self, qtbot, window):
        win = window
        source = win.registry.instantiate("flograph.io.table", pos=(0, 0))
        spec = win.registry.instantiate("flograph.viz.table_spec", pos=(400, 0))
        for node in (source, spec):
            win.graph.add_node(node)
        win.graph.set_param(source.id, "data", json.dumps(REGIONS))
        win.graph.connect(source.id, "table", spec.id, "table")

        item = win.scene.node_items[spec.id]
        assert item.table_viewer  # reuses the whole Show Table card path
        with qtbot.waitSignal(win.engine.run_finished, timeout=20000):
            win.engine.run_all()
        model = item._table_viewer_view.model()
        assert model is not None
        assert model.rowCount() == 2  # one spec row per source column
