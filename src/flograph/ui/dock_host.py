"""The nested QMainWindow that owns the canvas and every dock.

The only thing it adds over a plain QMainWindow is the right-click menu
that pops up over a dock's title bar (Qt's ``createPopupMenu``). Qt's
default build of that menu toggles a dock back to wherever it last lived;
here, turning a closed dock *on* from that menu drops it into the dock you
right-clicked -- if you open Navigator from a right-click on the left-hand
Library, it tabs in next to Library, not back on the right. Turning one
off, and the menu over an empty dock gutter, behave exactly as before.
"""
from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtGui import QContextMenuEvent
from PySide6.QtWidgets import QDockWidget, QMainWindow, QMenu, QWidget


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

    def contextMenuEvent(self, event: QContextMenuEvent) -> None:
        self._menu_target = self._dock_at(event.pos())
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
