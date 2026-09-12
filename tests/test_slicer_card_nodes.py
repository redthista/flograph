"""The interactive viz cards: Slicer (checkbox filter that re-runs the
visuals downstream), Card (big painted KPI value) and Table Spec (spec grid
on the canvas)."""
import json

import pytest
from PySide6.QtCore import QPoint, QSize, Qt
from PySide6.QtGui import QResizeEvent, QUndoStack
from PySide6.QtWidgets import QApplication

from flograph.core import Graph, NodeRegistry, Page, Tile
from flograph.ui.canvas import NodeGraphScene
from flograph.ui.dashboard import default_tile_port, default_tile_size
from flograph.ui.mainwindow import MainWindow

REGIONS = {"columns": ["region", "units"],
           "rows": [["north", "10"], ["south", "20"], ["north", "30"]]}
STORES = {"columns": ["region", "store", "units"],
          "rows": [["north", "alpha", "10"], ["north", "beta", "20"],
                   ["north", "beta", "5"], ["south", "gamma", "30"]]}


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


def _add_sliced_flow(win, column="region"):
    """Table -> Slicer(region) -> Show Table, returning the three nodes."""
    source = win.registry.instantiate("flograph.io.table", pos=(0, 0))
    slicer = win.registry.instantiate("flograph.viz.slicer", pos=(400, 0))
    shown = win.registry.instantiate("flograph.viz.show_table", pos=(800, 0))
    for node in (source, slicer, shown):
        win.graph.add_node(node)
    win.graph.set_param(source.id, "data", json.dumps(REGIONS))
    win.graph.set_param(slicer.id, "column", column)
    win.graph.connect(source.id, "table", slicer.id, "table")
    win.graph.connect(slicer.id, "table", shown.id, "table")
    return source, slicer, shown


def _add_nested_flow(win, column="region, store"):
    """The same flow over a two-level table, for the hierarchy tests."""
    source = win.registry.instantiate("flograph.io.table", pos=(0, 0))
    slicer = win.registry.instantiate("flograph.viz.slicer", pos=(400, 0))
    shown = win.registry.instantiate("flograph.viz.show_table", pos=(800, 0))
    for node in (source, slicer, shown):
        win.graph.add_node(node)
    win.graph.set_param(source.id, "data", json.dumps(STORES))
    win.graph.set_param(slicer.id, "column", column)
    win.graph.connect(source.id, "table", slicer.id, "table")
    win.graph.connect(slicer.id, "table", shown.id, "table")
    return source, slicer, shown


def _panel(qtbot, paths, columns=("region",), params=None, counts=None):
    """A SlicerPanel loaded straight from options, the way a host loads it
    after a run — so a widget test needs no graph, engine or window."""
    from flograph.core.slicer import SlicerOptions
    from flograph.ui.slicer_list import SlicerPanel
    panel = SlicerPanel()
    qtbot.addWidget(panel)
    panel.resize(240, 200)
    panel.set_options(SlicerOptions(columns, paths, counts),
                      dict(DEFAULTS, **(params or {})))
    return panel


DEFAULTS = {"selected": "", "mode": "multi", "layout": "list",
            "show_counts": False}


def _rows(tree):
    """Every built row of a slicer tree, in display order."""
    from PySide6.QtWidgets import QTreeWidgetItemIterator
    out = []
    walker = QTreeWidgetItemIterator(tree)
    while walker.value():
        out.append(walker.value())
        walker += 1
    return out


def _texts(tree):
    return [item.text(0) for item in _rows(tree)]


def _row(tree, text):
    return next(item for item in _rows(tree) if item.text(0) == text)


def _cards(view):
    """The tile buttons a cards layout built, in display order."""
    from PySide6.QtWidgets import QToolButton
    return view.widget().findChildren(QToolButton)


class TestSlicerCard:
    def test_item_is_a_resizable_widget_card(self, env, registry):
        graph, stack, scene = env
        node = graph.add_node(registry.instantiate("flograph.viz.slicer"))
        item = scene.node_items[node.id]
        assert item.slicer
        assert item._slicer_panel is not None
        assert not item._slicer_panel.has_options()  # placeholder until a run

    def test_card_size_params_are_cosmetic(self, registry):
        """Resizing the card must not re-filter the table or re-run the
        visuals downstream — run() never reads width/height."""
        spec = registry.get("flograph.viz.slicer")
        assert spec.param("width").cosmetic
        assert spec.param("height").cosmetic

    def test_layout_and_counts_are_cosmetic_too(self, registry):
        """How the values are *drawn* cannot change which rows come out, so
        switching a slicer to cards must not re-run the flow beneath it."""
        spec = registry.get("flograph.viz.slicer")
        assert spec.param("layout").cosmetic
        assert spec.param("show_counts").cosmetic

    def test_the_value_list_is_clipped_to_the_card(self, env, registry):
        """Reported: dragging the card short let the bottom rows paint out
        through its edge — a tree won't shrink past its own minimum, so the
        proxy has to clip it."""
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
        view = win.scene.node_items[slicer.id]._slicer_panel.view
        assert _texts(view) == ["north", "south"]

    def test_tick_commits_param_and_reruns_downstream(self, qtbot, window):
        win = window
        _source, slicer, shown = _add_sliced_flow(win)
        with qtbot.waitSignal(win.engine.run_finished, timeout=20000):
            win.engine.run_all()

        panel = win.scene.node_items[slicer.id]._slicer_panel
        # ticking "north" commits the selection and auto-runs downstream
        with qtbot.waitSignal(win.engine.run_finished, timeout=20000):
            _row(panel.view, "north").setCheckState(0, Qt.Checked)

        assert json.loads(win.graph.nodes[slicer.id].params["selected"]) \
            == ["north"]
        filtered = win.engine.cache.get(shown.id).outputs["table"]
        assert list(filtered["region"]) == ["north", "north"]
        # untick via undo: the param rolls back and the checks resync
        win.undo_stack.undo()
        assert win.graph.nodes[slicer.id].params["selected"] == ""
        assert _row(panel.view, "north").checkState(0) == Qt.Unchecked

    def test_single_mode_radio_behaviour(self, qtbot, window):
        win = window
        _source, slicer, shown = _add_sliced_flow(win)
        win.graph.set_param(slicer.id, "mode", "single")
        with qtbot.waitSignal(win.engine.run_finished, timeout=20000):
            win.engine.run_all()

        view = win.scene.node_items[slicer.id]._slicer_panel.view
        with qtbot.waitSignal(win.engine.run_finished, timeout=20000):
            _row(view, "north").setCheckState(0, Qt.Checked)
        assert json.loads(win.graph.nodes[slicer.id].params["selected"]) \
            == ["north"]

        # ticking a second value clears the first — only one at a time
        with qtbot.waitSignal(win.engine.run_finished, timeout=20000):
            _row(view, "south").setCheckState(0, Qt.Checked)
        assert _row(view, "north").checkState(0) == Qt.Unchecked
        assert json.loads(win.graph.nodes[slicer.id].params["selected"]) \
            == ["south"]
        filtered = win.engine.cache.get(shown.id).outputs["table"]
        assert list(filtered["region"]) == ["south"]

        # clicking the ticked value again clears the selection entirely
        with qtbot.waitSignal(win.engine.run_finished, timeout=20000):
            _row(view, "south").setCheckState(0, Qt.Unchecked)
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
        panel = win.scene.node_items[slicer.id]._slicer_panel
        with qtbot.waitSignal(win.engine.run_finished, timeout=20000):
            panel.toolbar._select_all.click()  # both "north" and "south"
        assert panel.selected_values() == ["north", "south"]

        with qtbot.waitSignal(win.engine.run_finished, timeout=20000):
            win.graph.set_param(slicer.id, "mode", "single")

        assert panel.selected_values() == ["north"]
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

        panel = win.scene.node_items[slicer.id]._slicer_panel
        with qtbot.waitSignal(win.engine.run_finished, timeout=20000):
            _row(panel.view, "north").setCheckState(0, Qt.Checked)

        panel.toolbar._search.setText("south")
        # "north" doesn't match, but a ticked value always keeps a row so the
        # tick stays visible and un-losable
        assert _row(panel.view, "north").checkState(0) == Qt.Checked
        assert panel.selected_values() == ["north"]

        # a search matching neither value still doesn't drop the tick
        panel.toolbar._search.setText("zzz")
        assert panel.selected_values() == ["north"]

        panel.toolbar._search.setText("")
        assert panel.selected_values() == ["north"]

    def test_filter_survives_the_rerun_a_tick_triggers(self, qtbot, window):
        """Ticking a value re-runs the slicer, which repopulates the list
        from the freshly-cached upstream table (set_slicer_options ->
        set_options -> rebuild) — an active search must not be silently
        dropped by that rebuild."""
        win = window
        _source, slicer, _shown = _add_sliced_flow(win)
        with qtbot.waitSignal(win.engine.run_finished, timeout=20000):
            win.engine.run_all()

        panel = win.scene.node_items[slicer.id]._slicer_panel
        panel.toolbar._search.setText("north")
        assert _texts(panel.view) == ["north"]

        with qtbot.waitSignal(win.engine.run_finished, timeout=20000):
            _row(panel.view, "north").setCheckState(0, Qt.Checked)

        # the rebuild the tick triggered must not have cleared the filter
        assert _texts(panel.view) == ["north"]
        assert _row(panel.view, "north").checkState(0) == Qt.Checked

    def test_select_all_and_clear_all_respect_the_filter(self, qtbot, window):
        win = window
        _source, slicer, _shown = _add_sliced_flow(win)
        with qtbot.waitSignal(win.engine.run_finished, timeout=20000):
            win.engine.run_all()

        panel = win.scene.node_items[slicer.id]._slicer_panel
        panel.toolbar._search.setText("north")
        with qtbot.waitSignal(win.engine.run_finished, timeout=20000):
            panel.toolbar._select_all.click()
        assert panel.selected_values() == ["north"]  # "south" stayed hidden

        panel.toolbar._search.setText("")
        with qtbot.waitSignal(win.engine.run_finished, timeout=20000):
            panel.toolbar._clear.click()
        assert panel.selected_values() == []

    def test_typing_in_the_search_box_does_not_rerun_the_flow(
            self, qtbot, window):
        """A search narrows the list and nothing else — routing it through
        the commit path would ask the engine to re-run everything downstream
        once per keystroke, for a filter the flow cannot see."""
        win = window
        _source, slicer, _shown = _add_sliced_flow(win)
        with qtbot.waitSignal(win.engine.run_finished, timeout=20000):
            win.engine.run_all()

        panel = win.scene.node_items[slicer.id]._slicer_panel
        commits = []
        panel.selection_committed.connect(commits.append)
        runs = []
        win.scene.slicer_changed.connect(runs.append)

        panel.toolbar._search.setText("nor")
        assert _texts(panel.view) == ["north"]
        assert commits == [] and runs == []

    def test_toolbar_hides_select_all_in_single_mode(self, qtbot):
        panel = _panel(qtbot, [("north",), ("south",)])
        assert not panel.toolbar._select_all.isHidden()
        panel.sync_params(dict(DEFAULTS, mode="single"))
        assert panel.toolbar._select_all.isHidden()
        panel.sync_params(dict(DEFAULTS, mode="multi"))
        assert not panel.toolbar._select_all.isHidden()

    def test_toolbar_wraps_the_buttons_under_the_search_when_narrow(self, qtbot):
        """Reported: the card can be dragged narrower than "Search  All  None"
        fits on one row, clipping the buttons. Below the threshold they drop
        onto a second row instead so the card stays usable at small sizes."""
        panel = _panel(qtbot, [("north",)])
        toolbar = panel.toolbar
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
        panel = win.scene.node_items[slicer.id]._slicer_panel
        assert panel.model.mode == "single"
        assert panel.toolbar._select_all.isHidden()

    def test_single_mode_draws_radios_not_checkboxes(self, qtbot):
        """ideas.md item 14: a checkbox promises you can tick several, which
        single mode then silently undoes. Painting only — the list still
        stores and reports check state."""
        panel = _panel(qtbot, [("north",), ("south",)],
                       params={"selected": '["north"]'})
        assert not panel.view._delegate.radio
        panel.sync_params(dict(DEFAULTS, mode="single", selected='["north"]'))
        assert panel.view._delegate.radio
        assert panel.selected_values() == ["north"]  # unchanged underneath
        panel.sync_params(dict(DEFAULTS, mode="multi", selected='["north"]'))
        assert not panel.view._delegate.radio

    def test_radio_rows_keep_the_checkbox_layout(self, qtbot):
        """The radio is drawn by dropping the check indicator and painting
        one in its place; that also collapses the column it occupied, so
        without compensating the label slides left underneath the radio.
        Rendered and diffed rather than reasoned about: the two modes must
        differ *only* inside the indicator's own rectangle."""
        from PySide6.QtGui import QPixmap
        from PySide6.QtWidgets import QStyle, QStyleOptionViewItem

        panels = {}

        def render(mode):
            panel = _panel(qtbot, [("north",), ("south",)],
                           params={"selected": '["north"]', "mode": mode})
            panels[mode] = panel
            # the view is pinned rather than left to the panel's layout: the
            # two modes lay their toolbars out differently (single hides
            # "All"), and a one-pixel difference in the view's height would
            # make the whole image differ instead of just the indicator
            panel.view.setFixedSize(200, 60)
            QApplication.processEvents()
            pixmap = QPixmap(panel.view.size())
            panel.view.render(pixmap)
            return pixmap.toImage()

        multi, single = render("multi"), render("single")
        assert multi.size() == single.size()

        view = panels["multi"].view
        option = QStyleOptionViewItem()
        option.rect = view.visualItemRect(view.topLevelItem(0))
        option.features |= \
            QStyleOptionViewItem.ViewItemFeature.HasCheckIndicator
        indicator = view.style().subElementRect(
            QStyle.SE_ItemViewItemCheckIndicator, option, view)

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
        panel = _panel(qtbot, [("north",), ("south",)],
                       params={"mode": mode})
        view = panel.view
        panel.show()
        qtbot.waitExposed(panel)

        item = view.topLevelItem(0)
        label = view.visualItemRect(item).center()
        assert not view._indicator_rect(item).contains(label)

        with qtbot.waitSignal(panel.selection_committed):
            qtbot.mouseClick(view.viewport(), Qt.LeftButton, pos=label)
        assert panel.selected_values() == ["north"]

        # and clicking it again clears it, same as clicking the box
        with qtbot.waitSignal(panel.selection_committed):
            qtbot.mouseClick(view.viewport(), Qt.LeftButton, pos=label)
        assert panel.selected_values() == []

    @pytest.mark.parametrize("mode", ["multi", "single"])
    def test_clicking_the_tick_box_still_toggles_once(self, qtbot, mode):
        """The box is left to the base class; toggling there as well would
        cancel out and leave the row looking unclickable."""
        panel = _panel(qtbot, [("north",), ("south",)],
                       params={"mode": mode})
        view = panel.view
        panel.show()
        qtbot.waitExposed(panel)

        item = view.topLevelItem(0)
        with qtbot.waitSignal(panel.selection_committed):
            qtbot.mouseClick(view.viewport(), Qt.LeftButton,
                             pos=view._indicator_rect(item).center())
        assert panel.selected_values() == ["north"]

    def test_clicking_a_label_in_single_mode_replaces_the_selection(
            self, qtbot):
        panel = _panel(qtbot, [("north",), ("south",)],
                       params={"mode": "single", "selected": '["north"]'})
        view = panel.view
        panel.show()
        qtbot.waitExposed(panel)

        with qtbot.waitSignal(panel.selection_committed):
            qtbot.mouseClick(
                view.viewport(), Qt.LeftButton,
                pos=view.visualItemRect(view.topLevelItem(1)).center())
        assert panel.selected_values() == ["south"]

    def test_clicking_the_more_values_note_does_nothing(self, qtbot):
        from flograph.ui.slicer_list import RENDER_BUDGET
        panel = _panel(qtbot, [(str(i),) for i in range(RENDER_BUDGET + 5)])
        view = panel.view
        panel.show()
        qtbot.waitExposed(panel)

        # RENDER_BUDGET rows built + one non-interactive "… N more" note
        assert view.topLevelItemCount() == RENDER_BUDGET + 1
        note = view.topLevelItem(view.topLevelItemCount() - 1)
        assert not (note.flags() & Qt.ItemIsUserCheckable)
        view.scrollToItem(note)
        qtbot.mouseClick(view.viewport(), Qt.LeftButton,
                         pos=view.visualItemRect(note).center())
        assert panel.selected_values() == []

    def test_values_past_the_render_budget_stay_filterable_and_tickable(
            self, qtbot):
        """The budget bounds how many rows are built, not the column: a
        value with no row is still reachable through the search box, and
        ticking it commits and survives clearing the search."""
        from flograph.ui.slicer_list import RENDER_BUDGET
        values = [f"v{i:05d}" for i in range(RENDER_BUDGET + 200)]
        panel = _panel(qtbot, [(v,) for v in values])
        view = panel.view
        panel.show()
        qtbot.waitExposed(panel)

        target = values[-1]  # well past the budget, no row yet
        assert target not in _texts(view)

        panel.toolbar._search.setText(target)
        row = view.topLevelItem(0)
        assert row.text(0) == target
        with qtbot.waitSignal(panel.selection_committed):
            row.setCheckState(0, Qt.Checked)
        assert panel.selected_values() == [target]

        panel.toolbar._search.setText("")  # tick survives the rebuild
        assert panel.selected_values() == [target]
        assert panel.selection_summary() == f"1/{len(values)}"

    def test_mode_syncs_the_delegate_from_the_param(self, qtbot, window):
        win = window
        _source, slicer, _shown = _add_sliced_flow(win)
        win.graph.set_param(slicer.id, "mode", "single")
        with qtbot.waitSignal(win.engine.run_finished, timeout=20000):
            win.engine.run_all()
        assert win.scene.node_items[slicer.id]._slicer_panel.view._delegate.radio

    def test_toolbar_count_label_tracks_ticks(self, qtbot, window):
        win = window
        _source, slicer, _shown = _add_sliced_flow(win)
        with qtbot.waitSignal(win.engine.run_finished, timeout=20000):
            win.engine.run_all()
        panel = win.scene.node_items[slicer.id]._slicer_panel
        assert panel.toolbar._count.text() == "0/2"

        with qtbot.waitSignal(win.engine.run_finished, timeout=20000):
            _row(panel.view, "north").setCheckState(0, Qt.Checked)
        assert panel.toolbar._count.text() == "1/2"


class TestSlicerHierarchy:
    """Several columns turn the slicer into Power BI's multi-field tree: a
    level per column, a parent tick standing for its children."""

    def test_two_columns_nest_into_a_tree(self, qtbot, window):
        win = window
        _source, slicer, _shown = _add_nested_flow(win)
        with qtbot.waitSignal(win.engine.run_finished, timeout=20000):
            win.engine.run_all()
        view = win.scene.node_items[slicer.id]._slicer_panel.view
        assert [item.text(0) for item in
                (view.topLevelItem(i) for i in
                 range(view.topLevelItemCount()))] == ["north", "south"]
        north = view.topLevelItem(0)
        assert [north.child(i).text(0) for i in range(north.childCount())] \
            == ["alpha", "beta"]

    def test_one_column_is_still_a_flat_list(self, qtbot, window):
        """The tree widget draws the ordinary slicer too, and must not grow
        expander arrows or indentation when there is nothing to expand."""
        win = window
        _source, slicer, _shown = _add_sliced_flow(win)
        with qtbot.waitSignal(win.engine.run_finished, timeout=20000):
            win.engine.run_all()
        view = win.scene.node_items[slicer.id]._slicer_panel.view
        assert not view.rootIsDecorated()
        assert all(view.topLevelItem(i).childCount() == 0
                   for i in range(view.topLevelItemCount()))

    def test_ticking_a_parent_keeps_the_whole_branch(self, qtbot, window):
        win = window
        _source, slicer, shown = _add_nested_flow(win)
        with qtbot.waitSignal(win.engine.run_finished, timeout=20000):
            win.engine.run_all()
        panel = win.scene.node_items[slicer.id]._slicer_panel

        with qtbot.waitSignal(win.engine.run_finished, timeout=20000):
            _row(panel.view, "north").setCheckState(0, Qt.Checked)

        # the param carries the *branch*, not every leaf under it
        assert json.loads(win.graph.nodes[slicer.id].params["selected"]) \
            == ["north"]
        filtered = win.engine.cache.get(shown.id).outputs["table"]
        assert sorted(set(filtered["store"])) == ["alpha", "beta"]
        # and the children draw as ticked, because they are
        assert _row(panel.view, "alpha").checkState(0) == Qt.Checked

    def test_ticking_one_child_part_fills_its_parent(self, qtbot, window):
        win = window
        _source, slicer, shown = _add_nested_flow(win)
        with qtbot.waitSignal(win.engine.run_finished, timeout=20000):
            win.engine.run_all()
        panel = win.scene.node_items[slicer.id]._slicer_panel

        with qtbot.waitSignal(win.engine.run_finished, timeout=20000):
            _row(panel.view, "alpha").setCheckState(0, Qt.Checked)

        assert json.loads(win.graph.nodes[slicer.id].params["selected"]) \
            == [["north", "alpha"]]
        assert _row(panel.view, "north").checkState(0) == Qt.PartiallyChecked
        filtered = win.engine.cache.get(shown.id).outputs["table"]
        assert list(filtered["store"]) == ["alpha"]

    def test_unticking_a_child_of_a_ticked_parent_keeps_the_siblings(
            self, qtbot, window):
        """"north" minus "north > alpha" is the rest of north — the parent
        tick has to break up into the branches it stood for, or unticking
        one store would silently clear the whole region."""
        win = window
        _source, slicer, shown = _add_nested_flow(win)
        with qtbot.waitSignal(win.engine.run_finished, timeout=20000):
            win.engine.run_all()
        panel = win.scene.node_items[slicer.id]._slicer_panel

        with qtbot.waitSignal(win.engine.run_finished, timeout=20000):
            _row(panel.view, "north").setCheckState(0, Qt.Checked)
        with qtbot.waitSignal(win.engine.run_finished, timeout=20000):
            _row(panel.view, "alpha").setCheckState(0, Qt.Unchecked)

        assert json.loads(win.graph.nodes[slicer.id].params["selected"]) \
            == [["north", "beta"]]
        filtered = win.engine.cache.get(shown.id).outputs["table"]
        assert list(filtered["store"]) == ["beta", "beta"]

    def test_clicking_the_expander_folds_the_branch_instead_of_ticking(
            self, qtbot):
        """The row is one click target, but the expander arrow sits outside
        it — clicking there must open and shut the branch, not select the
        whole region."""
        panel = _panel(qtbot, [("north", "alpha"), ("north", "beta")],
                       columns=("region", "store"))
        view = panel.view
        panel.show()
        qtbot.waitExposed(panel)
        north = view.topLevelItem(0)
        assert north.isExpanded()

        rect = view.visualItemRect(north)
        arrow = rect.adjusted(-view.indentation() // 2, 0, 0, 0).topLeft()
        qtbot.mouseClick(view.viewport(), Qt.LeftButton,
                         pos=QPoint(arrow.x(), rect.center().y()))
        assert not north.isExpanded()
        assert panel.selected_values() == []

    def test_ticking_every_child_rolls_up_into_the_parent(self, qtbot):
        """Select All over a wide two-level column would otherwise write
        every leaf path into the saved param — thousands of entries meaning
        "everything"."""
        panel = _panel(qtbot, [("north", "alpha"), ("north", "beta")],
                       columns=("region", "store"))
        panel.model.toggle(("north", "alpha"))
        panel.model.toggle(("north", "beta"))
        assert panel.selected_paths() == [("north",)]

    def test_a_deeper_selection_survives_a_round_trip_through_the_param(
            self, qtbot):
        paths = [("north", "alpha"), ("north", "beta"), ("south", "gamma")]
        panel = _panel(qtbot, paths, columns=("region", "store"),
                       params={"selected": '[["north", "alpha"], ["south"]]'})
        assert panel.selected_paths() == [("north", "alpha"), ("south",)]
        assert panel.model.committed_value() == \
            '[["north", "alpha"], ["south"]]'

    def test_a_single_column_still_writes_the_flat_param(self, qtbot):
        """A file saved by an older build reads back unchanged, and one
        saved by this build still opens in an older one."""
        panel = _panel(qtbot, [("north",), ("south",)])
        panel.model.toggle(("north",))
        assert panel.model.committed_value() == '["north"]'

    def test_selected_output_carries_the_deepest_values(self, qtbot, window):
        win = window
        _source, slicer, _shown = _add_nested_flow(win)
        win.graph.set_param(slicer.id, "selected",
                            json.dumps([["north", "alpha"]]))
        with qtbot.waitSignal(win.engine.run_finished, timeout=20000):
            win.engine.run_all()
        assert win.engine.cache.get(slicer.id).outputs["selected"] == ["alpha"]

    def test_search_reaches_a_value_inside_a_branch(self, qtbot):
        panel = _panel(qtbot, [("north", "alpha"), ("north", "beta"),
                               ("south", "gamma")],
                       columns=("region", "store"))
        panel.toolbar._search.setText("gamma")
        # the branch is kept so the match can be reached, but north is gone
        assert _texts(panel.view) == ["south", "gamma"]


class TestSlicerLayouts:
    def test_cards_layout_draws_a_button_per_value(self, qtbot):
        panel = _panel(qtbot, [("north",), ("south",)],
                       params={"layout": "cards"})
        assert [b.text() for b in _cards(panel.view)] == ["north", "south"]

    def test_clicking_a_card_selects_it(self, qtbot):
        panel = _panel(qtbot, [("north",), ("south",)],
                       params={"layout": "cards"})
        with qtbot.waitSignal(panel.selection_committed):
            _cards(panel.view)[1].click()
        assert panel.selected_values() == ["south"]
        assert _cards(panel.view)[1].property("slicerState") == "on"

    def test_a_card_in_single_mode_replaces_the_selection(self, qtbot):
        panel = _panel(qtbot, [("north",), ("south",)],
                       params={"layout": "cards", "mode": "single"})
        _cards(panel.view)[0].click()
        _cards(panel.view)[1].click()
        assert panel.selected_values() == ["south"]

    def test_a_part_filled_branch_card_says_so(self, qtbot):
        panel = _panel(qtbot, [("north", "alpha"), ("north", "beta")],
                       columns=("region", "store"),
                       params={"layout": "cards",
                               "selected": '[["north", "alpha"]]'})
        states = {b.text(): b.property("slicerState")
                  for b in _cards(panel.view)}
        assert states == {"north": "partial", "alpha": "on", "beta": "off"}

    def test_a_dropdown_card_can_be_dragged_down_to_its_button(
            self, env, registry):
        """The list floor leaves room for the search row and a couple of
        values; a dropdown has neither, so that floor would be most of the
        card empty."""
        graph, _stack, scene = env
        node = graph.add_node(registry.instantiate("flograph.viz.slicer"))
        item = scene.node_items[node.id]
        graph.set_param(node.id, "height", 10)      # clamped to the floor
        assert item.body_height >= 150
        graph.set_param(node.id, "layout", "dropdown")
        assert item.body_height < 100

    def test_switching_layout_keeps_the_selection(self, qtbot):
        """The layouts are views over one selection model, so changing the
        picture cannot change what is picked."""
        panel = _panel(qtbot, [("north",), ("south",)],
                       params={"selected": '["south"]'})
        for layout in ("cards", "dropdown", "list"):
            panel.sync_params(dict(DEFAULTS, layout=layout,
                                   selected='["south"]'))
            assert panel.selected_values() == ["south"]

    def test_a_dropdown_slicer_lands_on_a_page_as_one_line(self, registry):
        """Dropped onto a dashboard, a dropdown slicer must not arrive as a
        260px-tall tile of empty card — that is most of the reason to pick
        the layout in the first place."""
        node = registry.instantiate("flograph.viz.slicer")
        assert default_tile_size(node) == (200.0, 260.0)
        node.params["layout"] = "dropdown"
        assert default_tile_size(node) == (240.0, 80.0)

    def test_dropdown_button_says_what_is_picked(self, qtbot):
        panel = _panel(qtbot, [("north",), ("south",), ("west",)],
                       params={"layout": "dropdown"})
        # nothing ticked means the slicer passes everything through
        assert panel.view._button.text() == "All"
        panel.sync_params(dict(DEFAULTS, layout="dropdown",
                               selected='["north"]'))
        assert panel.view._button.text() == "north"
        panel.sync_params(dict(DEFAULTS, layout="dropdown",
                               selected='["north", "south"]'))
        assert panel.view._button.text() == "2 selected"

    def test_ticking_every_value_reads_as_all(self, qtbot):
        """Ticking everything keeps the same rows as ticking nothing, so a
        shut dropdown says the same thing. "3 selected" over three values
        counts the clicking rather than answering what comes through."""
        panel = _panel(qtbot, [("north",), ("south",), ("west",)],
                       params={"layout": "dropdown",
                               "selected": '["north", "south", "west"]'})
        assert panel.view._button.text() == "All"

    def test_select_all_reads_as_all(self, qtbot):
        """The same by the button rather than by the param."""
        panel = _panel(qtbot, [("north",), ("south",), ("west",)],
                       params={"layout": "dropdown"})
        panel.view.toolbar._select_all.click()
        assert panel.selected_values() == ["north", "south", "west"]
        assert panel.view._button.text() == "All"

    def test_a_branch_covering_every_leaf_reads_as_all(self, qtbot):
        """One tick can be all of it: on a one-region tree, ticking the
        region covers every store under it."""
        panel = _panel(qtbot, [("north", "alpha"), ("north", "beta")],
                       columns=("region", "store"),
                       params={"layout": "dropdown",
                               "selected": '[["north"]]'})
        assert panel.view._button.text() == "All"

    def test_all_but_one_still_counts(self, qtbot):
        panel = _panel(qtbot, [("north",), ("south",), ("west",)],
                       params={"layout": "dropdown",
                               "selected": '["north", "south"]'})
        assert panel.view._button.text() == "2 selected"

    def test_dropdown_carries_its_own_search_not_the_panel_toolbar(self, qtbot):
        """A dropdown is one line by definition; a search box above the
        button would be most of the card."""
        panel = _panel(qtbot, [("north",), ("south",)],
                       params={"layout": "dropdown"})
        assert panel.toolbar.isHidden()
        panel.view.toolbar._search.setText("south")
        assert _texts(panel.view.tree) == ["south"]

    def test_ticking_inside_the_dropdown_commits(self, qtbot):
        panel = _panel(qtbot, [("north",), ("south",)],
                       params={"layout": "dropdown"})
        with qtbot.waitSignal(panel.selection_committed):
            _row(panel.view.tree, "north").setCheckState(0, Qt.Checked)
        assert panel.selected_values() == ["north"]
        assert panel.view._button.text() == "north"


class TestSlicerCounts:
    def test_counts_are_off_by_default(self, qtbot, window):
        win = window
        _source, slicer, _shown = _add_sliced_flow(win)
        with qtbot.waitSignal(win.engine.run_finished, timeout=20000):
            win.engine.run_all()
        view = win.scene.node_items[slicer.id]._slicer_panel.view
        assert _texts(view) == ["north", "south"]

    def test_counts_show_the_rows_behind_each_value(self, qtbot, window):
        win = window
        _source, slicer, _shown = _add_sliced_flow(win)
        win.graph.set_param(slicer.id, "show_counts", True)
        with qtbot.waitSignal(win.engine.run_finished, timeout=20000):
            win.engine.run_all()
        view = win.scene.node_items[slicer.id]._slicer_panel.view
        assert _texts(view) == ["north  (2)", "south  (1)"]

    def test_a_parent_counts_every_row_under_it(self, qtbot, window):
        win = window
        _source, slicer, _shown = _add_nested_flow(win)
        win.graph.set_param(slicer.id, "show_counts", True)
        with qtbot.waitSignal(win.engine.run_finished, timeout=20000):
            win.engine.run_all()
        view = win.scene.node_items[slicer.id]._slicer_panel.view
        assert view.topLevelItem(0).text(0) == "north  (3)"

    def test_turning_counts_on_does_not_rerun_the_flow(self, qtbot, window):
        win = window
        _source, slicer, shown = _add_sliced_flow(win)
        with qtbot.waitSignal(win.engine.run_finished, timeout=20000):
            win.engine.run_all()
        win.graph.set_param(slicer.id, "show_counts", True)
        assert not win.graph.nodes[slicer.id].dirty
        assert not win.graph.nodes[shown.id].dirty


class TestSlicerChrome:
    """The search box and the All / None row can each be taken away — on a
    slicer over five regions they are just clutter, and on a dashboard the
    space is the whole point."""

    def test_both_rows_are_there_by_default(self, qtbot):
        panel = _panel(qtbot, [("north",), ("south",)])
        assert panel.toolbar.isVisibleTo(panel)
        assert panel.toolbar._search.isVisibleTo(panel.toolbar)
        assert panel.toolbar._select_all.isVisibleTo(panel.toolbar)
        assert panel.toolbar._clear.isVisibleTo(panel.toolbar)

    def test_hiding_the_search_leaves_the_buttons(self, qtbot):
        panel = _panel(qtbot, [("north",)], params={"show_search": False})
        assert not panel.toolbar._search.isVisibleTo(panel.toolbar)
        assert panel.toolbar._clear.isVisibleTo(panel.toolbar)
        assert panel.toolbar.isVisibleTo(panel)

    def test_hiding_the_buttons_leaves_the_search(self, qtbot):
        panel = _panel(qtbot, [("north",)], params={"show_buttons": False})
        assert panel.toolbar._search.isVisibleTo(panel.toolbar)
        assert not panel.toolbar._select_all.isVisibleTo(panel.toolbar)
        assert not panel.toolbar._clear.isVisibleTo(panel.toolbar)
        assert not panel.toolbar._count.isVisibleTo(panel.toolbar)
        assert panel.toolbar.isVisibleTo(panel)

    def test_hiding_both_hides_the_whole_strip(self, qtbot):
        """Otherwise the card keeps a two-pixel band of nothing above the
        values."""
        panel = _panel(qtbot, [("north",)],
                       params={"show_search": False, "show_buttons": False})
        assert not panel.toolbar.isVisibleTo(panel)

    def test_the_values_are_untouched_by_either_toggle(self, qtbot):
        panel = _panel(qtbot, [("north",), ("south",)],
                       params={"show_search": False, "show_buttons": False})
        assert _texts(panel.view) == ["north", "south"]

    def test_hiding_the_search_clears_a_typed_filter(self, qtbot):
        """A filter with no box to see it in leaves the slicer showing a
        fraction of its values, with nothing on screen saying why."""
        panel = _panel(qtbot, [("north",), ("south",)])
        panel.toolbar._search.setText("nor")
        assert _texts(panel.view) == ["north"]
        panel.sync_params(dict(DEFAULTS, show_search=False))
        assert panel.model.filter_text == ""
        assert _texts(panel.view) == ["north", "south"]

    def test_a_dropdown_popup_answers_to_the_toggles_too(self, qtbot):
        panel = _panel(qtbot, [("north",)],
                       params={"layout": "dropdown",
                               "show_search": False, "show_buttons": False})
        assert not panel.view.toolbar.isVisibleTo(panel.view)

    def test_the_toggles_do_not_rerun_the_flow(self, qtbot, window):
        win = window
        _source, slicer, shown = _add_sliced_flow(win)
        with qtbot.waitSignal(win.engine.run_finished, timeout=20000):
            win.engine.run_all()
        win.graph.set_param(slicer.id, "show_search", False)
        win.graph.set_param(slicer.id, "show_buttons", False)
        assert not win.graph.nodes[slicer.id].dirty
        assert not win.graph.nodes[shown.id].dirty

    def test_a_slicer_saved_before_these_existed_keeps_both(self, qtbot):
        """The params default True, and an older file has neither key —
        loading one must not silently strip its search box."""
        from flograph.core.slicer import SlicerOptions
        from flograph.ui.slicer_list import SlicerPanel
        panel = SlicerPanel()
        qtbot.addWidget(panel)
        panel.set_options(SlicerOptions(["region"], [("north",)]),
                          {"selected": "", "mode": "multi", "layout": "list"})
        assert panel.toolbar._search.isVisibleTo(panel.toolbar)
        assert panel.toolbar._clear.isVisibleTo(panel.toolbar)


class TestSlicerAccent:
    """One colour drives the tick, the chosen tile and the dropdown."""

    def test_no_accent_leaves_the_native_checkbox(self, qtbot):
        """Nothing chosen means the platform draws its own checkbox — not a
        hand-painted look-alike of it in the theme colour."""
        panel = _panel(qtbot, [("north",)])
        assert panel.view._delegate.accent is None

    def test_an_accent_is_painted_by_the_delegate(self, qtbot):
        panel = _panel(qtbot, [("north",)], params={"accent": "#e11d48"})
        assert panel.view._delegate.accent.name() == "#e11d48"

    def test_a_garbled_colour_falls_back_to_the_theme(self, qtbot):
        """A hand-edited param could hold anything; an invalid QColor is
        black, which would paint every tick the colour of the card."""
        from flograph.ui import theme
        panel = _panel(qtbot, [("north",)], params={"accent": "not a colour"})
        assert panel.view._delegate.accent.name() == theme.BUTTON_ACCENT.name()

    def test_a_chosen_tile_is_filled_with_the_accent(self, qtbot):
        panel = _panel(qtbot, [("north",)],
                       params={"layout": "cards", "accent": "#e11d48"})
        assert "#e11d48" in _cards(panel.view)[0].styleSheet()

    def test_changing_the_accent_restyles_the_tiles_in_place(self, qtbot):
        """The rows did not change, so this must not go through a rebuild —
        but the tiles each carry their own copy of the sheet."""
        panel = _panel(qtbot, [("north",)], params={"layout": "cards"})
        before = _cards(panel.view)[0]
        panel.sync_params(dict(DEFAULTS, layout="cards", accent="#16a34a"))
        assert _cards(panel.view)[0] is before      # same button, restyled
        assert "#16a34a" in before.styleSheet()

    def test_the_dropdown_button_takes_the_accent(self, qtbot):
        panel = _panel(qtbot, [("north",)],
                       params={"layout": "dropdown", "accent": "#e11d48"})
        assert "#e11d48" in panel.view._button.styleSheet()

    def test_label_ink_flips_to_stay_readable(self):
        """White on a lime tile is unreadable, and picking lime is exactly
        the sort of thing a filter panel does."""
        from PySide6.QtGui import QColor

        from flograph.ui.slicer_list import ink_on
        assert ink_on(QColor("#1d4ed8")) == "#ffffff"     # deep blue
        assert ink_on(QColor("#facc15")) == "#111827"     # amber
        assert ink_on(QColor("#ffffff")) == "#111827"
        assert ink_on(QColor("#000000")) == "#ffffff"

    def test_the_accent_does_not_rerun_the_flow(self, qtbot, window):
        win = window
        _source, slicer, shown = _add_sliced_flow(win)
        with qtbot.waitSignal(win.engine.run_finished, timeout=20000):
            win.engine.run_all()
        win.graph.set_param(slicer.id, "accent", "#e11d48")
        assert not win.graph.nodes[slicer.id].dirty
        assert not win.graph.nodes[shown.id].dirty

    def test_two_slicers_can_be_different_colours(self, qtbot):
        """The tile stylesheet used to be a module constant, which would
        hand whichever card was built last to both."""
        red = _panel(qtbot, [("north",)],
                     params={"layout": "cards", "accent": "#e11d48"})
        green = _panel(qtbot, [("north",)],
                       params={"layout": "cards", "accent": "#16a34a"})
        assert "#e11d48" in _cards(red.view)[0].styleSheet()
        assert "#16a34a" in _cards(green.view)[0].styleSheet()


class TestStandaloneSlicer:
    def test_a_hierarchy_of_typed_values(self, qtbot, window):
        """With no table wired in, a line is a path: "north > alpha"."""
        win = window
        slicer = win.registry.instantiate("flograph.viz.slicer", pos=(0, 0))
        win.graph.add_node(slicer)
        win.graph.set_param(slicer.id, "column", "region, store")
        win.graph.set_param(slicer.id, "values",
                            "north > alpha\nnorth > beta\nsouth > gamma")
        win.graph.set_param(slicer.id, "selected", json.dumps([["north"]]))
        with qtbot.waitSignal(win.engine.run_finished, timeout=20000):
            win.engine.run_all()
        table = win.engine.cache.get(slicer.id).outputs["table"]
        assert list(table.columns) == ["region", "store"]
        assert list(table["store"]) == ["alpha", "beta"]

    def test_a_value_containing_the_separator_survives_one_column(
            self, qtbot, window):
        """Only a hierarchy has anywhere to put the pieces of a split line,
        so a one-column slicer takes the line whole."""
        win = window
        slicer = win.registry.instantiate("flograph.viz.slicer", pos=(0, 0))
        win.graph.add_node(slicer)
        win.graph.set_param(slicer.id, "column", "label")
        win.graph.set_param(slicer.id, "values", "a > b\nc")
        with qtbot.waitSignal(win.engine.run_finished, timeout=20000):
            win.engine.run_all()
        table = win.engine.cache.get(slicer.id).outputs["table"]
        assert list(table["label"]) == ["a > b", "c"]


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
        panel = item._slicer_panel
        assert _texts(panel.view) == ["north", "south"]

        # ticking on the dashboard commits the param and re-runs downstream
        with qtbot.waitSignal(win.engine.run_finished, timeout=20000):
            _row(panel.view, "south").setCheckState(0, Qt.Checked)
        assert json.loads(win.graph.nodes[slicer.id].params["selected"]) \
            == ["south"]
        filtered = win.engine.cache.get(shown.id).outputs["table"]
        assert list(filtered["region"]) == ["south"]
        # the canvas card's checkboxes follow the same param
        canvas = win.scene.node_items[slicer.id]._slicer_panel
        assert canvas.selected_values() == ["south"]
        # undo unticks the tile without emitting a new commit
        win.undo_stack.undo()
        assert panel.selected_values() == []


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


class TestAReaderThatDoesNotRun:
    def test_a_clean_slicer_fills_in_when_its_input_re_runs(self, qtbot,
                                                            window):
        """Issue 8: a reopen can bring a Slicer back from cache while the
        node feeding it has to run again. The Slicer is clean, so it does
        not run — its card has to fill in when that input arrives."""
        win = window
        source, slicer, _shown = _add_sliced_flow(win)
        with qtbot.waitSignal(win.engine.run_finished, timeout=20000):
            win.engine.run_all()
        item = win.scene.node_items[slicer.id]
        panel = item._slicer_panel

        # what that reopen leaves: the slicer done and waiting on its card,
        # the table feeding it still to run
        item.set_slicer_options(None)
        win.engine.cache.evict(source.id)
        source.dirty = True
        assert not panel.has_options() and not slicer.dirty

        with qtbot.waitSignal(win.engine.run_finished, timeout=20000):
            win.engine.run_targets([source.id])

        assert not slicer.dirty
        assert panel.has_options()

