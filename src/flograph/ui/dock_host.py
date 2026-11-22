"""The nested QMainWindow that owns the canvas and every dock.

The only thing it adds over a plain QMainWindow is the right-click menu
that pops up over a dock's title bar (Qt's ``createPopupMenu``). Qt's
default build of that menu toggles a dock back to wherever it last lived;
here, turning a closed dock *on* from that menu drops it into the dock you
right-clicked -- if you open Navigator from a right-click on the left-hand
Library, it tabs in next to Library, not back on the right. Turning one
off, and the menu over an empty dock gutter, behave exactly as before.

It also keeps a tab group to one header. A group's tabs sit along its top
(``setTabPosition(North)``), where they already name every panel, so the
title bar Qt draws under them would only repeat the current tab's name.
While a dock shares its spot with another it gets an empty title bar, and
its Float and Close move to the tab's right-click menu; a dock on its own
keeps Qt's title bar, buttons and all (`sync_titles`).
"""
from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import QTimer
from PySide6.QtGui import QContextMenuEvent
from PySide6.QtWidgets import (QDockWidget, QMainWindow, QMenu, QTabBar,
                               QWidget)


class DockHost(QMainWindow):
    def __init__(self, parent: Optional[QWidget] = None,
                 on_reveal: Optional[Callable[[QDockWidget], None]] = None
                 ) -> None:
        super().__init__(parent)
        # called after a dock is shown from the right-click menu, so the
        # window can keep its own "open on this page" bookkeeping in step
        # (a page round-trip otherwise re-closes it)
        self._on_reveal = on_reveal
        # where the last context-menu click landed, in this window's
        # coordinates -- stashed here because createPopupMenu() gets no
        # position of its own
        self._menu_target: Optional[QDockWidget] = None
        # the dock whose tab was right-clicked, for Float/Close on the menu
        self._tab_target: Optional[QDockWidget] = None
        # docks given an empty title bar because a tab group names them
        self._blank_titles: dict[QDockWidget, QWidget] = {}
        self._watched: set[int] = set()
        self._sync_timer = QTimer(self)
        self._sync_timer.setSingleShot(True)
        self._sync_timer.setInterval(0)
        self._sync_timer.timeout.connect(self.sync_titles)
        self.tabifiedDockWidgetActivated.connect(
            lambda _dock: self.schedule_sync())

    # ----------------------------------------------------- tab group titles

    def schedule_sync(self) -> None:
        """Re-check the title bars once the current layout change settles:
        a tab group forms or breaks in several steps (show, tabify, area
        change), and only the end state matters."""
        self._sync_timer.start()

    def watch(self, dock: QDockWidget) -> None:
        """Follow a dock's moves so its title bar tracks its tab group."""
        if id(dock) in self._watched:
            return
        self._watched.add(id(dock))
        dock.dockLocationChanged.connect(lambda _a: self.schedule_sync())
        dock.topLevelChanged.connect(lambda _f: self.schedule_sync())
        dock.visibilityChanged.connect(lambda _v: self.schedule_sync())
        self.schedule_sync()

    def in_group(self, dock: QDockWidget) -> bool:
        """Is `dock` docked in a tab group that has another open panel?"""
        if dock.isFloating() or dock.isHidden():
            return False
        return any(not other.isHidden() and not other.isFloating()
                   for other in self.tabifiedDockWidgets(dock))

    def sync_titles(self) -> None:
        for dock in self.findChildren(QDockWidget):
            grouped = self.in_group(dock)
            blank = self._blank_titles.get(dock)
            if grouped and blank is None:
                blank = QWidget(dock)
                blank.setFixedHeight(0)
                self._blank_titles[dock] = blank
                dock.setTitleBarWidget(blank)
            elif not grouped and blank is not None:
                del self._blank_titles[dock]
                dock.setTitleBarWidget(None)
                blank.deleteLater()

    def _dock_tab_at(self, pos) -> Optional[QDockWidget]:
        """The dock whose tab in a group's tab bar is under `pos`."""
        for bar in self.findChildren(QTabBar):
            if not bar.isVisible() or bar.parent() is not self:
                continue
            index = bar.tabAt(bar.mapFrom(self, pos))
            if index < 0:
                continue
            title = bar.tabText(index)
            for dock in self.findChildren(QDockWidget):
                if dock.windowTitle() == title and self.in_group(dock):
                    return dock
        return None

    def contextMenuEvent(self, event: QContextMenuEvent) -> None:
        from . import menu_guard
        if menu_guard.stray(event):
            # The tail of a menu that has just closed over this window —
            # answering it puts the dock list on screen for a right-click
            # nobody made. Anything a child ignores walks up to here, so
            # this is the last place that leak can come out.
            event.accept()
            return
        if (event.reason() == QContextMenuEvent.Reason.Mouse
                and not self.rect().contains(event.pos())):
            # A right-click here is inside this window, always. One from
            # outside it is a page tab menu's leftover, re-sent on its way
            # up from a page that ignored it — so no longer "spontaneous",
            # which is how it slipped past the guard above: it arrived at
            # y = -8, over the page bar. See ui/menu_guard.
            event.accept()
            return
        self._menu_target = self._dock_at(event.pos())
        self._tab_target = self._dock_tab_at(event.pos())
        super().contextMenuEvent(event)

    def _dock_at(self, pos) -> Optional[QDockWidget]:
        """The docked, on-screen dock whose frame covers `pos` (title bar
        included). Floating panels are their own windows and never a drop
        target; a hidden dock has no frame to hit."""
        for dock in self.findChildren(QDockWidget):
            if (dock.isVisible() and not dock.isFloating()
                    and dock.geometry().contains(pos)):
                return dock
        return None

    def createPopupMenu(self) -> Optional[QMenu]:
        docks = [d for d in self.findChildren(QDockWidget)
                 if d.toggleViewAction().isEnabled()]
        if not docks:
            return None
        target = self._menu_target
        menu = QMenu(self)
        tab = self._tab_target
        self._tab_target = None
        if tab is not None:
            # the buttons a grouped panel's hidden title bar would have had
            float_action = menu.addAction(f"Float {tab.windowTitle()}")
            float_action.setEnabled(bool(
                tab.features() & QDockWidget.DockWidgetFloatable))
            float_action.triggered.connect(lambda: tab.setFloating(True))
            close_action = menu.addAction(f"Close {tab.windowTitle()}")
            close_action.setEnabled(bool(
                tab.features() & QDockWidget.DockWidgetClosable))
            close_action.triggered.connect(tab.close)
            menu.addSeparator()
        for dock in docks:
            action = menu.addAction(dock.windowTitle())
            action.setCheckable(True)
            action.setChecked(not dock.isHidden())
            action.toggled.connect(
                lambda on, d=dock, t=target: self._set_dock_shown(d, on, t))
        return menu

    def _set_dock_shown(self, dock: QDockWidget, shown: bool,
                        target: Optional[QDockWidget]) -> None:
        if not shown:
            dock.close()
            return
        # show() before tabifyDockWidget(): Qt drops the tab relationship
        # for a dock that has never been visible (the same reason
        # _build_docks shows Navigator before tabifying it).
        dock.show()
        if (target is not None and target is not dock
                and not target.isHidden() and not target.isFloating()):
            # tabbing into the right-clicked dock puts the panel on that
            # dock's edge -- the "attach it where I clicked" the menu is
            # there to give
            self.tabifyDockWidget(target, dock)
        # _reveal_dock re-runs show()/raise_() and keeps the window's
        # "open on this page" list in step; fall back to a plain reveal
        # when no owner wired one in.
        if self._on_reveal is not None:
            self._on_reveal(dock)
        else:
            dock.show()
            dock.raise_()
