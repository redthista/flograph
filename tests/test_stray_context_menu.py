"""A second, unasked-for menu after using one of the page bar's (issues 9).

Right-click the Model tab, click *Fold the canvases away*, and a stray menu
appeared — a lone "New group…", which is what the Node Library builds on
empty space. The family is issue 7 and the AB4 Wayland trap: the context
event a right press brings is delivered *after* the handler that opened our
own menu has returned, to whichever widget the platform then picks.

Two guards already existed and neither could close this one. Holding the
focus on the page bar either side of the menu covers the focus half. Asking
whether the position is inside the widget covers leftovers landing outside
it — but the page bar runs along the *top* of the window, so its menus drop
over the Library dock and the canvas, and the position that arrives is
genuinely inside the widget it is handed to. That is why the first fix
(`LibraryTree._context_menu_for` refusing a position off the tree) did not
work: the position was on the tree.

So the guard is timing, in `ui/menu_guard`: the page bar records the moment
one of its menus closed, and every surface that can be underneath one
refuses a context menu for a third of a second afterwards. These tests pin
the decision, the recording, and that the belt is actually fastened on each
surface — the last because it is a handful of one-line calls that are easy
to leave out of the next widget.
"""
import inspect
import time

import pytest
from PySide6.QtCore import QPoint, QSettings

from flograph.core import Graph, Page
from flograph.ui import menu_guard
from flograph.ui.dashboard.page_bar import PageTabBar


@pytest.fixture(autouse=True)
def _no_menu_recently():
    """Each test starts with no menu having closed, and leaves it that way —
    the record is module state, and a leftover would make the next test's
    real menu refuse to open."""
    menu_guard._closed_at = 0.0
    yield
    menu_guard._closed_at = 0.0


@pytest.fixture(scope="module")
def registry():
    from flograph.core import NodeRegistry
    reg = NodeRegistry()
    reg.load_builtins()
    return reg


class FakeContextEvent:
    """A spontaneous context-menu event, which Qt cannot be asked for from
    Python: `spontaneous()` is true only for events the platform itself
    sent, and that is exactly the kind this guard is about."""

    def __init__(self, reason=None, spontaneous=True, pos=QPoint(5, 5)):
        from PySide6.QtGui import QContextMenuEvent
        self._reason = (QContextMenuEvent.Reason.Mouse if reason is None
                        else reason)
        self._spontaneous = spontaneous
        self._pos = pos
        self.accepted = False

    def reason(self):
        return self._reason

    def spontaneous(self):
        return self._spontaneous

    def pos(self):
        return self._pos

    def globalPos(self):
        return self._pos

    def accept(self):
        self.accepted = True

    def ignore(self):
        self.accepted = False


class TestTheRecordItself:

    def test_nothing_is_settling_to_begin_with(self):
        assert not menu_guard.settling()

    def test_a_closed_menu_starts_the_window(self):
        menu_guard.menu_closed()
        assert menu_guard.settling()

    def test_the_window_runs_out(self):
        """A right-click a third of a second after dismissing a menu is a
        gesture; the leftovers arrive in milliseconds."""
        menu_guard._closed_at = time.monotonic() - menu_guard.SETTLE - 0.01
        assert not menu_guard.settling()

    def test_the_window_is_short(self):
        assert menu_guard.SETTLE <= 0.5

    def test_nothing_here_is_a_qobject_or_a_filter(self):
        """The lesson of issue 7, pinned the same way it is pinned on the
        page bar: this module is imported before a QApplication exists, and
        an application-wide event filter cost a segfault and a canvas that
        felt like it was hanging.

        Read as code, not as text — the module's own docstring explains why
        there is no QObject here, and saying so must not look like having
        one."""
        import ast

        tree = ast.parse(inspect.getsource(menu_guard))
        assert not [node for node in ast.walk(tree)
                    if isinstance(node, ast.ClassDef)]
        names = {alias.name for node in ast.walk(tree)
                 if isinstance(node, (ast.Import, ast.ImportFrom))
                 for alias in node.names}
        assert "QObject" not in names
        assert "installEventFilter" not in inspect.getsource(menu_guard)
        assert not [value for value in vars(menu_guard).values()
                    if isinstance(value, type)]


class TestWhichEventsCount:

    def test_a_mouse_event_while_settling_is_stray(self):
        menu_guard.menu_closed()
        assert menu_guard.stray(FakeContextEvent())

    def test_nothing_is_stray_when_no_menu_closed(self):
        assert not menu_guard.stray(FakeContextEvent())

    def test_the_menu_key_is_always_the_user_asking(self):
        """However recently a menu closed: the keyboard cannot be the tail
        of a mouse press."""
        from PySide6.QtGui import QContextMenuEvent
        menu_guard.menu_closed()
        assert not menu_guard.stray(
            FakeContextEvent(reason=QContextMenuEvent.Reason.Keyboard))

    def test_an_event_we_sent_ourselves_is_not_the_platform_s(self):
        menu_guard.menu_closed()
        assert not menu_guard.stray(FakeContextEvent(spontaneous=False))


class TestThePageBarRecordsIt:

    @pytest.fixture
    def bar(self, qtbot):
        widget = PageTabBar()
        qtbot.addWidget(widget)
        graph = Graph()
        for index in range(2):
            page = Page(id=f"p{index}", title=f"Page {index}")
            graph.add_page(page)
            widget.add_page_tab(page)
        return widget

    def test_every_menu_of_the_bar_s_records_its_close(self, bar):
        """One place: each of the bar's menus — a tab's, a group header's,
        the Model tab's, the tab list — is shown through this."""
        shown = []
        bar._menu_with_the_focus(lambda: shown.append(True))
        assert shown == [True]
        assert menu_guard.settling()

    def test_the_plus_menu_goes_through_it_too(self, bar, monkeypatch):
        """"+" opens on press like the rest, so it leaves the same tail. It
        used to exec() its menu directly and record nothing."""

        class FakeMenu:
            def exec(self, _where):
                return None

        monkeypatch.setattr(bar, "_add_menu", lambda: (FakeMenu(), {}))
        bar._show_add_menu(QPoint(0, 0))
        assert menu_guard.settling()

    def test_the_plus_menu_still_asks_for_the_page(self, bar, monkeypatch):
        """The guard is wrapped round it, not in the way of it."""
        asked = []

        class FakeMenu:
            def __init__(self, action):
                self._action = action

            def exec(self, _where):
                return self._action

        action = object()
        monkeypatch.setattr(bar, "_add_menu",
                            lambda: (FakeMenu(action), {action: "canvas"}))
        bar.add_page_requested.connect(asked.append)
        bar._show_add_menu(QPoint(0, 0))
        assert asked == ["canvas"]


class TestTheSurfacesRefuse:
    """The widgets a page-bar menu drops over. Each is asked directly,
    because the platform behaviour itself cannot be reproduced offscreen."""

    @pytest.fixture
    def tree(self, qtbot, registry, tmp_path):
        from flograph.ui.canvas.palette import LibraryTree
        from flograph.ui.favorites import Favorites
        settings = QSettings(str(tmp_path / "settings.ini"),
                             QSettings.IniFormat)
        widget = LibraryTree(registry, Favorites(settings))
        qtbot.addWidget(widget)
        return widget

    def test_the_library_opens_no_menu_while_settling(self, tree, monkeypatch):
        """The one Dan saw: a lone "New group…" over the dock the Model
        tab's menu had just been covering, at a position on the tree."""
        built = []
        monkeypatch.setattr(tree, "_context_menu_for",
                            lambda pos: built.append(pos))
        menu_guard.menu_closed()
        tree._on_context_menu(QPoint(5, 5))
        assert built == []

    def test_the_library_still_answers_a_real_right_click(self, tree,
                                                         monkeypatch):
        built = []
        monkeypatch.setattr(tree, "_context_menu_for",
                            lambda pos: built.append(pos) or None)
        tree._on_context_menu(QPoint(5, 5))
        assert built == [QPoint(5, 5)]

    def test_a_table_view_opens_no_menu_while_settling(self, qtbot,
                                                       monkeypatch):
        from flograph.ui.data_table import DataTableView
        view = DataTableView()
        qtbot.addWidget(view)
        built = []
        monkeypatch.setattr(view, "build_menu", lambda: built.append(True))
        menu_guard.menu_closed()
        view._show_menu(QPoint(5, 5))
        assert built == []

    def test_the_dock_host_swallows_a_stray_event(self, qtbot):
        """Whatever a child ignores walks up to the window, whose bare
        right-click menu is the dock list — the last place this can come
        out, and the "menu of whatever is underneath" from issue 7."""
        from flograph.ui.dock_host import DockHost
        host = DockHost()
        qtbot.addWidget(host)
        menu_guard.menu_closed()
        event = FakeContextEvent()
        host.contextMenuEvent(event)
        assert event.accepted

    def test_the_dock_host_still_answers_its_own_right_click(self, qtbot):
        """A real event this time, so it can be passed on to Qt the way the
        unguarded path does — which is also why it is not spontaneous, and
        so never stray."""
        from PySide6.QtGui import QContextMenuEvent
        from flograph.ui.dock_host import DockHost
        host = DockHost()
        qtbot.addWidget(host)
        host._menu_target = "not looked for yet"
        menu_guard.menu_closed()          # and even so, because it is ours
        host.contextMenuEvent(QContextMenuEvent(
            QContextMenuEvent.Mouse, QPoint(5, 5), QPoint(5, 5)))
        # it got as far as looking for the dock under the pointer, which is
        # the work the guard above skips
        assert host._menu_target is None


class TestTheBeltIsFastened:
    """Every menu that can open underneath one of the page bar's consults
    the guard. A source check, deliberately: the calls are one-liners in
    seven places, and the failure mode is the next widget not having one."""

    def surfaces(self):
        from flograph.ui.canvas.palette import LibraryTree
        from flograph.ui.canvas.view import NodeGraphView
        from flograph.ui.dashboard.dashboard_view import DashboardView
        from flograph.ui.data_table import DataTableView
        from flograph.ui.dock_host import DockHost
        from flograph.ui.spreadsheet.view import SpreadsheetView
        return [
            LibraryTree._on_context_menu,
            NodeGraphView.contextMenuEvent,
            DashboardView.contextMenuEvent,
            DockHost.contextMenuEvent,
            DataTableView._show_menu,
            SpreadsheetView._column_menu,
            SpreadsheetView._row_menu,
        ]

    @pytest.mark.parametrize("index", range(7))
    def test_the_surface_consults_the_guard(self, index):
        function = self.surfaces()[index]
        source = inspect.getsource(function)
        assert "menu_guard" in source, f"{function.__qualname__} does not ask"
