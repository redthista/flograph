"""Collapsing a whole side of the canvas: the edge strips.

Docks are plain QDockWidgets again -- collapsing an edge closes them, so
Qt's own drag/float/tab machinery is untouched and there is no custom
size arithmetic to test. What needs covering is the strip: which way its
arrow points, what a click takes down and puts back, and that it stays
out of the way on pages the panels don't belong to.

Only TestResizing shows a real MainWindow, and only because dragging a
size handle needs geometry an unshown top-level widget never computes --
see test_gpu_viewport_setting.py's module docstring for why showing them
is otherwise avoided under this offscreen harness. Everything else
asserts on logical state (which docks are hidden, which way the arrow
points). Settings kept off the real store (avoid polluting the
developer's actual flograph.conf).
"""
import pytest
from PySide6.QtCore import QEvent, QPoint, QSettings, Qt
from PySide6.QtGui import QKeySequence, QMouseEvent
from PySide6.QtWidgets import QApplication

from flograph.core import NodeRegistry
from flograph.ui import mainwindow as mod
from flograph.ui.commands import AddNodeCommand


@pytest.fixture(autouse=True)
def _isolated_settings(tmp_path, monkeypatch):
    ini_path = str(tmp_path / "test_settings.ini")
    monkeypatch.setattr(
        mod, "QSettings",
        lambda *a, **k: QSettings(ini_path, QSettings.IniFormat))


@pytest.fixture(scope="module")
def registry():
    reg = NodeRegistry()
    reg.load_builtins()
    return reg


@pytest.fixture
def window(qtbot, registry):
    win = mod.MainWindow(registry)
    win.confirm_close = False
    qtbot.addWidget(win)
    return win


def _right_docks(window):
    return [window.properties_dock, window.editor_dock, window.log_dock]


class TestDockLayout:
    def test_properties_code_and_log_share_the_right_hand_tab_group(
            self, window):
        group = window._dock_host.tabifiedDockWidgets(window.properties_dock)
        assert window.editor_dock in group
        assert window.log_dock in group

    def test_inspector_is_alone_at_the_bottom(self, window):
        assert window._dock_host.tabifiedDockWidgets(
            window.inspector_dock) == []

    def test_every_panel_is_its_own_dock_again(self, window):
        """The point of dropping the rail: five real docks, so Qt's own
        drag/float/tab handling applies to each panel individually."""
        docks = {window.library_dock, window.properties_dock,
                 window.editor_dock, window.log_dock, window.inspector_dock}
        assert len(docks) == 5


class TestEdgeStrips:
    def test_strips_stay_on_screen_while_their_docks_are_open(self, window):
        """The strip is the collapse control, not just a way back -- it has
        to be there while the edge is still up."""
        for strip in window._edge_strips.values():
            assert strip.isVisibleTo(window) is True
            assert strip.is_collapsed() is False

    def test_one_click_collapses_a_whole_tab_group(self, window, qtbot):
        """The complaint that drove this: closing the right-hand side a tab
        at a time is not collapsing it."""
        strip = window._edge_strips["right"]
        qtbot.mouseClick(strip._button, Qt.LeftButton)

        assert all(dock.isHidden() for dock in _right_docks(window))
        assert strip.is_collapsed() is True

    def test_clicking_again_restores_the_whole_edge(self, window, qtbot):
        strip = window._edge_strips["right"]
        qtbot.mouseClick(strip._button, Qt.LeftButton)
        qtbot.mouseClick(strip._button, Qt.LeftButton)

        assert all(not dock.isHidden() for dock in _right_docks(window))
        assert strip.is_collapsed() is False

    def test_the_arrow_turns_around_when_the_edge_collapses(self, window):
        strip = window._edge_strips["right"]
        outward = strip._button.arrowType()
        strip.collapse()
        assert strip._button.arrowType() != outward
        strip.expand()
        assert strip._button.arrowType() == outward

    def test_collapsing_one_edge_leaves_the_others_alone(self, window):
        window._edge_strips["right"].collapse()
        assert window.library_dock.isHidden() is False
        assert window.inspector_dock.isHidden() is False
        assert window._edge_strips["left"].is_collapsed() is False

    def test_restoring_does_not_reopen_a_panel_closed_before_the_collapse(
            self, window):
        """A panel dismissed with its own X stays dismissed -- the edge
        toggle only puts back what it took down."""
        window.log_dock.close()
        strip = window._edge_strips["right"]
        strip.collapse()
        strip.expand()

        assert window.properties_dock.isHidden() is False
        assert window.editor_dock.isHidden() is False
        assert window.log_dock.isHidden() is True

    def test_an_edge_closed_entirely_by_hand_still_reopens(self, window):
        """Nothing was remembered, so the arrow falls back to the whole
        edge rather than doing nothing."""
        for dock in _right_docks(window):
            dock.close()
        strip = window._edge_strips["right"]
        assert strip.is_collapsed() is True

        strip.toggle()

        assert all(not dock.isHidden() for dock in _right_docks(window))

    def test_closing_the_last_panel_by_hand_reads_as_collapsed(self, window):
        """Qt reports a dock behind another tab as visible, so the edge only
        counts as collapsed once no tab is left."""
        strip = window._edge_strips["right"]
        window.editor_dock.close()
        assert strip.is_collapsed() is False
        window.log_dock.close()
        assert strip.is_collapsed() is False
        window.properties_dock.close()
        assert strip.is_collapsed() is True


class TestDoubleClick:
    """Double-clicking the strip is the arrow's gesture with a target the
    width of the whole edge instead of 12px."""

    def _double_click(self, app, strip):
        point = QPoint(5, 60)
        globally = strip.mapToGlobal(point)
        for kind, buttons in ((QEvent.MouseButtonPress, Qt.LeftButton),
                              (QEvent.MouseButtonRelease, Qt.NoButton),
                              (QEvent.MouseButtonDblClick, Qt.LeftButton)):
            app.sendEvent(strip, QMouseEvent(
                kind, point, globally, Qt.LeftButton, buttons, Qt.NoModifier))
        app.processEvents()

    def test_it_collapses_the_edge(self, window):
        app = QApplication.instance()
        strip = window._edge_strips["right"]

        self._double_click(app, strip)

        assert strip.is_collapsed() is True
        assert all(dock.isHidden() for dock in _right_docks(window))

    def test_it_brings_the_edge_back(self, window):
        app = QApplication.instance()
        strip = window._edge_strips["right"]

        self._double_click(app, strip)
        self._double_click(app, strip)

        assert strip.is_collapsed() is False
        assert all(not dock.isHidden() for dock in _right_docks(window))

    def test_a_right_click_is_not_a_collapse(self, window):
        app = QApplication.instance()
        strip = window._edge_strips["right"]
        point = QPoint(5, 60)
        app.sendEvent(strip, QMouseEvent(
            QEvent.MouseButtonDblClick, point, strip.mapToGlobal(point),
            Qt.RightButton, Qt.RightButton, Qt.NoModifier))
        app.processEvents()

        assert strip.is_collapsed() is False

    def test_it_leaves_no_drag_armed_behind_it(self, window):
        """The press that opens a double-click arms a resize; left set, the
        next stray move would drag the edge from a stale origin."""
        app = QApplication.instance()
        strip = window._edge_strips["right"]

        self._double_click(app, strip)

        assert strip._drag is None


class TestModelTabDoubleClick:
    """Double-clicking the Model tab is Ctrl+Shift+H by mouse. A page tab's
    double-click renames it, but the Model tab has no title to rename, so
    the gesture was going spare."""

    def _double_click_tab(self, app, bar, index):
        point = bar.tabRect(index).center()
        globally = bar.mapToGlobal(point)
        for kind, buttons in ((QEvent.MouseButtonPress, Qt.LeftButton),
                              (QEvent.MouseButtonRelease, Qt.NoButton),
                              (QEvent.MouseButtonDblClick, Qt.LeftButton)):
            app.sendEvent(bar, QMouseEvent(
                kind, point, globally, Qt.LeftButton, buttons, Qt.NoModifier))
        app.processEvents()

    def test_it_hides_and_restores_every_panel(self, window):
        app = QApplication.instance()
        bar = window.page_bar
        model = bar._model_index()

        self._double_click_tab(app, bar, model)
        assert window.all_panels_hidden() is True

        self._double_click_tab(app, bar, model)
        assert window.all_panels_hidden() is False

    def test_the_signal_reaches_the_window(self, window):
        window.page_bar.model_tab_double_clicked.emit()
        assert window.all_panels_hidden() is True

    def test_a_page_tab_still_renames(self, window, monkeypatch):
        """The new Model-tab branch sits in the same handler as rename, so
        pin that a real page tab still gets the rename dialog."""
        from flograph.ui.dashboard import page_bar as bar_mod
        monkeypatch.setattr(bar_mod.QInputDialog, "getText",
                            staticmethod(lambda *a, **k: ("Renamed", True)))
        bar = window.page_bar
        page = mod.Page(id="p1", title="Dash", kind="dashboard")
        window.graph.add_page(page)
        index = bar._index_of_page(page.id)

        renamed = []
        bar.rename_page_requested.connect(
            lambda pid, title: renamed.append((pid, title)))
        # the collapse signal itself, not dock visibility: adding a page
        # switches to it, which hides every model dock legitimately
        toggled = []
        bar.model_tab_double_clicked.connect(lambda: toggled.append(True))
        self._double_click_tab(QApplication.instance(), bar, index)

        assert renamed == [(page.id, "Renamed")]
        assert toggled == []

    def test_a_miss_beside_the_tabs_does_nothing(self, window):
        """tabAt() returns -1 off the end of the strip, and tabData(-1) is
        also None -- so an unguarded 'is it the Model tab?' would fire on
        empty space."""
        assert window.page_bar._is_model(-1) is False
        assert window.page_bar._is_model(window.page_bar.count() + 5) is False


class TestEdgeMembership:
    """Which docks a strip owns is asked of the dock host each time, not
    fixed at build time -- restoreState() and dragging both move panels
    between edges."""

    def test_a_dock_moved_to_another_edge_changes_hands(self, window):
        """The bug this was found by: a layout saved before Log moved to
        the right restores Log to the *bottom*, where the bottom strip
        knew nothing about it -- collapsing that edge closed the Inspector
        and left Log sitting there on its own."""
        window._dock_host.addDockWidget(
            Qt.BottomDockWidgetArea, window.log_dock)

        assert window.log_dock in window._edge_strips["bottom"].docks()
        assert window.log_dock not in window._edge_strips["right"].docks()

    def test_collapsing_an_edge_takes_a_moved_in_dock_with_it(self, window):
        window._dock_host.addDockWidget(
            Qt.BottomDockWidgetArea, window.log_dock)

        window._edge_strips["bottom"].collapse()

        assert window.inspector_dock.isHidden() is True
        assert window.log_dock.isHidden() is True
        assert window._edge_strips["bottom"].is_collapsed() is True

    def test_a_floating_panel_is_nobody_s_business(self, window):
        """dockWidgetArea() still reports the edge a floating dock came
        from, so it has to be excluded by hand -- collapsing an edge must
        not close a panel someone tore off into its own window."""
        window.log_dock.setFloating(True)
        assert window.log_dock not in window._edge_strips["right"].docks()

        window._edge_strips["right"].collapse()
        assert window.log_dock.isHidden() is False

    def test_an_edge_with_nothing_on_it_hides_its_strip(self, window):
        """Otherwise it is a strip of dead chrome with an arrow that does
        nothing."""
        window._dock_host.addDockWidget(
            Qt.RightDockWidgetArea, window.inspector_dock)
        window._edge_strips["bottom"].refresh()

        assert window._edge_strips["bottom"].docks() == []
        assert window._edge_strips["bottom"].isVisibleTo(window) is False


class TestHideAllPanels:
    def test_the_hotkey_action_carries_the_shortcut(self, window):
        assert (window.action_toggle_panels.shortcut()
                == QKeySequence("Ctrl+Shift+H"))

    def test_it_collapses_every_edge_at_once(self, window):
        window.toggle_all_panels()

        assert window.all_panels_hidden() is True
        for dock in window._model_docks:
            assert dock.isHidden() is True

    def test_it_puts_them_all_back(self, window):
        window.toggle_all_panels()
        window.toggle_all_panels()

        assert window.all_panels_hidden() is False
        for dock in window._model_docks:
            if dock in window._docks_closed_by_default:
                continue  # was closed before the gesture, stays closed after
            assert dock.isHidden() is False

    def test_a_partly_collapsed_layout_hides_the_rest(self, window):
        """Anything still showing means the gesture is 'hide', not 'show' --
        otherwise one collapsed edge would invert what the key does."""
        window._edge_strips["left"].collapse()

        window.toggle_all_panels()

        assert window.all_panels_hidden() is True

    def test_restoring_respects_a_panel_closed_by_hand(self, window):
        window.log_dock.close()
        window.toggle_all_panels()
        window.toggle_all_panels()

        assert window.properties_dock.isHidden() is False
        assert window.log_dock.isHidden() is True

    def test_the_menu_label_says_which_way_the_toggle_goes(self, window):
        window._sync_toggle_panels_action()
        assert window.action_toggle_panels.text() == "Hide All Panels"

        window.toggle_all_panels()
        assert window.action_toggle_panels.text() == "Show All Panels"

    def test_it_does_nothing_on_a_dashboard_page(self, window):
        """Those pages hide the model docks deliberately; the hotkey must
        not haul them onto a page they have no business on."""
        window._dashboard_pages["p1"] = None
        window._on_current_page_changed("p1")

        window.toggle_all_panels()

        for dock in window._model_docks:
            assert dock.isHidden() is True

    def test_hidden_panels_stay_hidden_across_a_dashboard_round_trip(
            self, window):
        """Regression: 'everything hidden' and 'already on a dashboard page'
        look identical by dock visibility, so the snapshot has to key off
        which page we are leaving, not what is currently open."""
        window.toggle_all_panels()
        window._dashboard_pages["p1"] = None

        window._on_current_page_changed("p1")
        window._on_current_page_changed(None)

        assert window.all_panels_hidden() is True


class TestResizing:
    """The strip doubles as the drag handle, so Qt's own dock separators are
    styled away -- one thin column instead of a strip beside a ~5px
    separator. Needs a real shown window: an unshown top-level widget never
    lays out for real, so there are no dock widths to drag."""

    def _drag(self, app, strip, dx, dy):
        origin = strip.mapToGlobal(QPoint(5, 60))
        moved = origin + QPoint(dx, dy)
        for kind, point, buttons in (
                (QEvent.MouseButtonPress, origin, Qt.LeftButton),
                (QEvent.MouseMove, moved, Qt.LeftButton),
                (QEvent.MouseButtonRelease, moved, Qt.NoButton)):
            app.sendEvent(strip, QMouseEvent(
                kind, strip.mapFromGlobal(point), point,
                Qt.LeftButton, buttons, Qt.NoModifier))
        app.processEvents()

    def test_dragging_a_strip_resizes_its_edge(self, qtbot, registry):
        app = QApplication.instance()
        win = mod.MainWindow(registry)
        win.confirm_close = False
        qtbot.addWidget(win)
        win.resize(1400, 900)
        win.show()
        qtbot.wait(10)

        start = win.properties_dock.width()
        # towards the canvas widens a right-hand edge
        self._drag(app, win._edge_strips["right"], -100, 0)
        qtbot.wait(10)
        assert win.properties_dock.width() == start + 100

        self._drag(app, win._edge_strips["right"], 60, 0)
        qtbot.wait(10)
        assert win.properties_dock.width() == start + 40

        bottom_start = win.inspector_dock.height()
        self._drag(app, win._edge_strips["bottom"], 0, -70)
        qtbot.wait(10)
        assert win.inspector_dock.height() == bottom_start + 70

    def test_a_collapsed_edge_has_nothing_to_drag(self, window):
        """_sizing_dock() returns None with every dock closed, so a press
        must fall through rather than starting a drag against nothing."""
        strip = window._edge_strips["right"]
        strip.collapse()
        assert strip._sizing_dock() is None
        assert strip.cursor().shape() == Qt.ArrowCursor

    def test_an_open_edge_offers_a_resize_cursor(self, window):
        strip = window._edge_strips["right"]
        assert strip.cursor().shape() == Qt.SplitHCursor
        assert window._edge_strips["bottom"].cursor().shape() == Qt.SplitVCursor


class TestPageSwitching:
    def test_dashboard_pages_hide_the_strips_too(self, window):
        """A dashboard page hides the model-only docks on purpose, so there
        is nothing on those edges left to collapse -- an arrow there would
        just be noise on a page the panels don't belong to."""
        window.library_dock.close()
        page = mod.Page(id="p1", title="Dash", kind="dashboard")
        window._dashboard_pages[page.id] = None
        window._on_current_page_changed(page.id)

        for strip in window._edge_strips.values():
            assert strip.isVisibleTo(window) is False

    def test_a_page_round_trip_does_not_reopen_a_closed_dock(self, window):
        """Regression: switching pages hides every model dock and shows
        them all again, which would quietly undo a deliberate close."""
        window.log_dock.close()
        page = mod.Page(id="p1", title="Dash", kind="dashboard")
        window._dashboard_pages[page.id] = None

        window._on_current_page_changed(page.id)
        window._on_current_page_changed(None)

        assert window.log_dock.isHidden() is True
        assert window.properties_dock.isHidden() is False

    def test_switching_between_two_dashboard_pages_keeps_the_open_set(
            self, window):
        """The all-hidden state between two dashboard pages must not be
        recorded as 'the user closed everything'."""
        window.log_dock.close()
        for page_id in ("p1", "p2"):
            window._dashboard_pages[page_id] = None
        window._on_current_page_changed("p1")
        window._on_current_page_changed("p2")
        window._on_current_page_changed(None)

        assert window.properties_dock.isHidden() is False
        assert window.library_dock.isHidden() is False
        assert window.log_dock.isHidden() is True


class TestPanelReveal:
    def test_double_clicking_a_node_reopens_a_closed_code_dock(
            self, window, registry):
        node = registry.instantiate(
            "flograph.scripting.python_script", pos=(0, 0))
        window.undo_stack.push(AddNodeCommand(window.graph, node))
        # which dock a double-click opens is the user's setting; this is
        # about the reveal, so ask for the one being revealed
        window.double_click_action = "code"
        window.editor_dock.close()

        window._on_node_double_clicked(node.id)

        assert window.editor_dock.isHidden() is False

    def test_double_clicking_a_node_reopens_a_closed_properties_dock(
            self, window, registry):
        """The default action, and the same reveal path."""
        node = registry.instantiate(
            "flograph.scripting.python_script", pos=(0, 0))
        window.undo_stack.push(AddNodeCommand(window.graph, node))
        assert window.double_click_action == "properties"
        window.properties_dock.close()

        window._on_node_double_clicked(node.id)

        assert window.properties_dock.isHidden() is False

    def test_a_revealed_dock_survives_a_dashboard_round_trip(
            self, window, registry):
        """_reveal_dock has to put the dock back in the restore set, or the
        next page switch closes what it just opened."""
        node = registry.instantiate(
            "flograph.scripting.python_script", pos=(0, 0))
        window.undo_stack.push(AddNodeCommand(window.graph, node))
        window.double_click_action = "code"
        window.editor_dock.close()
        window._on_node_double_clicked(node.id)

        window._dashboard_pages["p1"] = None
        window._on_current_page_changed("p1")
        window._on_current_page_changed(None)

        assert window.editor_dock.isHidden() is False


class TestResetAndPersistence:
    def test_reset_window_layout_reopens_every_closed_dock(self, window):
        for dock in window._model_docks:
            dock.close()

        window.reset_window_layout()

        assert all(dock.isHidden() is (dock in window._docks_closed_by_default)
                   for dock in window._model_docks)
        for strip in window._edge_strips.values():
            assert strip.is_collapsed() is False

    def test_a_closed_dock_stays_closed_across_a_restart(
            self, window, qtbot, registry):
        """Qt's own saveState() carries dock visibility, which is why there
        is no custom collapse-state setting any more."""
        window.log_dock.close()
        window._save_window_state()

        win2 = mod.MainWindow(registry)
        win2.confirm_close = False
        qtbot.addWidget(win2)

        assert win2.log_dock.isHidden() is True
        assert win2.properties_dock.isHidden() is False

    def test_a_dock_closed_at_save_time_is_not_in_the_restore_set(
            self, window, qtbot, registry):
        """Otherwise the first dashboard round trip after a restart would
        reopen it."""
        window.library_dock.close()
        window._save_window_state()

        win2 = mod.MainWindow(registry)
        win2.confirm_close = False
        qtbot.addWidget(win2)
        assert win2.library_dock not in win2._docks_open_on_model_page
