"""The page tab's context menu must not filter the whole application.

A crash-to-desktop while locking a page and then dragging a Plotly chart
(2026-08-12). The core dump was a hover event inside the chart card's
embedded Chromium — QQuickWidget, QQuickDeliveryAgent::deliverHoverEvent —
routed through QCoreApplicationPrivate::sendThroughApplicationEventFilters
into PySide, which segfaulted building a wrapper for the watched object.

Two faults behind it, both here:

1. The tab menu installed an event filter on the *QApplication* so it could
   swallow the context-menu event that follows its own right-click. Every
   event in the process then went through Python, including the mouse-move
   and hover floods inside WebEngine — which is also why the app felt like
   it was hanging before it died.
2. The filter object was a module-level QObject built at *import* time,
   before any QApplication existed, which is exactly the state PySide's
   wrapper bookkeeping is not safe in.

Both are gone: the event is accepted on the one widget it is delivered to.
These tests pin that, because the fix is a deletion and a deletion is the
easiest thing in the world to reinstate by accident.
"""
import inspect

import pytest
from PySide6.QtCore import QEvent, QObject, QPoint
from PySide6.QtGui import QContextMenuEvent
from PySide6.QtWidgets import QApplication

from flograph.core import Graph, Page
from flograph.ui.dashboard import page_bar as page_bar_module
from flograph.ui.dashboard.page_bar import PageTabBar


@pytest.fixture(autouse=True)
def _app(qapp):
    return qapp


@pytest.fixture
def bar(qtbot):
    widget = PageTabBar()
    qtbot.addWidget(widget)
    graph = Graph()
    for index in range(2):
        page = Page(id=f"p{index}", title=f"Page {index}")
        graph.add_page(page)
        widget.add_page_tab(page)
    return widget


class TestNoApplicationWideFilter:

    def test_no_qobject_is_built_at_import(self):
        """A QObject built at import time has no QApplication behind it,
        which is the state PySide is not safe in."""
        assert not hasattr(page_bar_module, "_guard")
        assert not hasattr(page_bar_module, "_MenuGuard")

    def test_nothing_here_filters_the_application(self):
        """The mechanism itself, pinned by name: an application-wide filter
        sees every event in the process, including the ones belonging to
        WebEngine's internals, and hands each one to Python."""
        source = inspect.getsource(page_bar_module)
        assert "installEventFilter" not in source
        assert "removeEventFilter" not in source

    def test_no_timer_holds_the_cleanup(self):
        """The filter was removed by a QTimer parented to the tab bar, so a
        page bar destroyed first left it installed for the session."""
        assert not hasattr(page_bar_module, "_menu_timer")


class TestTheEventIsStillSwallowed:

    def test_a_context_menu_event_is_accepted(self, bar):
        """What the filter was for: the platform sends this on release after
        the menu was already opened on press, and it would otherwise open a
        second one on top."""
        event = QContextMenuEvent(QContextMenuEvent.Mouse, QPoint(10, 10),
                                  QPoint(110, 110))
        event.ignore()
        bar.contextMenuEvent(event)
        assert event.isAccepted()

    def test_it_is_accepted_when_actually_delivered(self, bar):
        event = QContextMenuEvent(QContextMenuEvent.Mouse, QPoint(5, 5),
                                       QPoint(105, 105))
        QApplication.sendEvent(bar, event)
        assert event.isAccepted()

    def test_the_watcher_sees_it_stop_here(self, bar):
        """Accepting stops it propagating, which is the other half of what
        the application-wide filter was doing by brute force."""
        seen = []

        class Watcher(QObject):
            def eventFilter(self, obj, event):
                if event.type() == QEvent.ContextMenu:
                    seen.append(obj)
                return False

        watcher = Watcher()
        bar.installEventFilter(watcher)
        try:
            QApplication.sendEvent(
                bar, QContextMenuEvent(QContextMenuEvent.Mouse, QPoint(5, 5),
                                       QPoint(105, 105)))
            assert seen == [bar]   # it reached the tab bar and stopped
        finally:
            bar.removeEventFilter(watcher)


class TestTheMenuStillWorks:

    def labels(self, bar, page_id, index=0):
        return [a.text() for a in bar._context_menu(index, page_id).actions()]

    def test_it_still_offers_the_page_actions(self, bar):
        labels = self.labels(bar, "p0")
        assert "Locked" in labels
        assert "Rename" in labels and "Duplicate" in labels
        assert "Delete" in labels

    def test_an_unlocked_page_has_no_export_entries(self, bar):
        assert "Export PDF…" not in self.labels(bar, "p0")

    def test_a_locked_report_offers_setup_and_both_exports(self, bar):
        bar._kinds["p0"] = "report"
        bar.set_page_view_mode("p0", True)
        labels = self.labels(bar, "p0")
        assert "Page Setup…" in labels
        assert "Export PDF…" in labels
        assert "Save HTML…" in labels

    def test_a_locked_dashboard_does_not(self, bar):
        """Those three are a report's, and a dashboard has a visuals panel
        rather than a document to print."""
        bar._kinds["p0"] = "dashboard"
        bar.set_page_view_mode("p0", True)
        assert "Export PDF…" not in self.labels(bar, "p0")

    def test_the_lock_entry_reflects_the_page(self, bar):
        menu = bar._context_menu(0, "p0")
        lock = next(a for a in menu.actions() if a.text() == "Locked")
        assert lock.isCheckable() and not lock.isChecked()
        bar.set_page_view_mode("p0", True)
        menu = bar._context_menu(0, "p0")
        lock = next(a for a in menu.actions() if a.text() == "Locked")
        assert lock.isChecked()
