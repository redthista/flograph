"""DashboardView: the pannable/zoomable viewport over one page's tiles,
accepting drags from the visuals list.

It also renders *fullscreen*, one tile filling the page, by one of two
routes. A tile that scrolls — a spreadsheet, a data table, a report — is
maximized into a **native overlay**: a plain widget laid over the viewport,
outside the graphics scene entirely. A widget inside a QGraphicsProxyWidget
cannot scroll by blitting, so every notch of the wheel re-renders the whole
visible grid, and the cost grows with the window: measured at 1440p, 26 ms
a scroll against 2.4 ms for the same grid as a native widget. On a page
built for typing data in, that is the difference between usable and not.
The overlay binds a *second* view to the tile's own model rather than
moving the tile's widget, so nothing is re-parented and both stay in step
by themselves.

Everything else — a KPI (painted), a figure (its own resolution handling in
the proxy), a Plotly view (a web engine that dislikes re-parenting) — is
still pinned in scene coordinates at 1:1 zoom, where it was already fine.

Either way the stored tile *rect* is never touched; only the page's
`maximized_tile` says what is maximized, and the scene is the sole caller of
enter/exit here — turning fullscreen on or off is a model edit (see
DashboardScene)."""
from __future__ import annotations

import uuid

from typing import Optional

import shiboken6 as shiboken
from PySide6.QtCore import QPointF, Qt, QTimer, Signal
from PySide6.QtGui import QKeyEvent, QPalette
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QMenu, QToolButton,
                               QVBoxLayout, QWidget)

from .. import theme
from ..canvas.base_view import ZoomPanGraphicsView
from ..canvas.stacking import add_layer_menu, layer_action_for
from .dashboard_scene import DashboardScene
from .tile_item import TileItem
from .visuals_list import TILE_NODE_MIME

OVERLAY_TITLE_H = 28

#: Breathing room left around the tiles when a page is scaled to the window.
FIT_MARGIN = 24.0
#: Resizing a window delivers a stream of resize events; refit once the
#: stream stops rather than on every step of it.
FIT_SETTLE_MS = 40
#: Where a pasted tile lands relative to the one it was copied from, so it
#: arrives clear of it instead of exactly on top.
TILE_PASTE_OFFSET = 30.0


class FullscreenOverlay(QWidget):
    """A maximized tile's content as a real widget over the viewport.

    Owns nothing but its chrome: the content comes from the tile and is
    thrown away with the overlay, while the model it reads stays with the
    tile. Escape restores — but only when nothing underneath wanted it
    first, which is what keeps Escape cancelling a half-typed cell.
    """

    def __init__(self, title: str, content: QWidget, on_restore,
                 parent=None) -> None:
        super().__init__(parent)
        self._on_restore = on_restore
        # A plain QWidget subclass paints no background of its own, and
        # setting a stylesheet does *not* change that unless the widget is
        # told to honour it — a stylesheet without WA_StyledBackground is
        # silently ignored for the background and also suppresses the
        # autoFillBackground path, leaving the widget fully transparent.
        # That is what showed the canvas straight through the title bar and
        # the toolbar. Palette first, so the fill stands on its own, and the
        # attribute so the stylesheet is honoured too.
        palette = self.palette()
        palette.setColor(QPalette.Window, theme.NODE_BODY)
        self.setPalette(palette)
        self.setAutoFillBackground(True)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(
            f"FullscreenOverlay {{ background: {theme.NODE_BODY.name()}; }}")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 6)
        layout.setSpacing(4)

        bar = QHBoxLayout()
        bar.setContentsMargins(0, 0, 0, 0)
        label = QLabel(title)
        label.setStyleSheet(
            f"color: {theme.NODE_TEXT.name()}; font-weight: 600;")
        restore = QToolButton(text="✕")
        restore.setAutoRaise(True)
        restore.setToolTip("Restore (Esc)")
        restore.clicked.connect(lambda: self._on_restore())
        bar.addWidget(label)
        bar.addStretch(1)
        bar.addWidget(restore)

        layout.addLayout(bar)
        layout.addWidget(content, 1)
        self.content = content

    def keyPressEvent(self, event: QKeyEvent) -> None:
        # reached only if no child consumed it, so a cell editor still gets
        # its own Escape to cancel with
        if event.key() == Qt.Key_Escape:
            self._on_restore()
            event.accept()
            return
        super().keyPressEvent(event)


class DashboardView(ZoomPanGraphicsView):
    tile_dropped = Signal(str, QPointF)  # node_id, scene pos
    fullscreen_changed = Signal(bool)    # a tile was maximized / restored

    # Tiles copied from a right-click menu, waiting to be pasted. A *class*
    # attribute on purpose: every page has its own DashboardView, and pasting
    # onto another page must see what was copied here. Each entry is
    # (node_id, port, rel_x, rel_y, w, h), where (rel_x, rel_y) is the tile's
    # position relative to the copied selection's top-left, so a paste on any
    # page rebuilds the arrangement. None until the user copies something.
    _tile_clipboard: Optional[tuple] = None

    def __init__(self, scene: DashboardScene, parent=None) -> None:
        super().__init__(scene, parent)
        self.setAcceptDrops(True)
        self._view_mode = False
        self._fit_to_window = False
        # Coalesces a window drag's worth of resize events into one refit.
        # Also what makes the first fit land after the layout has settled:
        # a view asked to fit itself before it has been given its real size
        # fits to the wrong rectangle.
        self._fit_timer = QTimer(self)
        self._fit_timer.setSingleShot(True)
        self._fit_timer.setInterval(FIT_SETTLE_MS)
        self._fit_timer.timeout.connect(self._fit_page)
        self._fs_tile: Optional[TileItem] = None
        self._fs_restore: Optional[tuple] = None  # (transform, scene centre)
        self._fs_overlay: Optional[FullscreenOverlay] = None

    # ----------------------------------------------------------- view mode

    def set_view_mode(self, view_mode: bool) -> None:
        """In view mode there is no canvas left — only the dashboard.

        A locked page is a finished one, and the thing being handed over is
        the arrangement: these tiles, this size, in this place. So the
        viewport stops being an infinite canvas and becomes a page. No zoom,
        no pan, no wheel, no rubber band, no scroll bars, no context menu,
        and nothing new can be dropped on it.

        What stays is everything *inside* the tiles — slicers, sliders,
        spreadsheets, web views, reports, a PDF's page chevrons, the
        maximize glyph. That is the whole distinction: locked is the
        dashboard, unlocked is the dashboard plus the tools for arranging
        it.
        """
        self._view_mode = bool(view_mode)
        self.setAcceptDrops(not self._view_mode)
        # either mode locks navigation, so unlocking one must not unlock the
        # other's
        self.set_navigation_locked(self._view_mode or self._fit_to_window)
        self.queue_fit()

    # ------------------------------------------------------ scale to window

    def set_fit_to_window(self, fit: bool) -> None:
        """Keep the whole page in view, whatever size the window is.

        The page zooms on every resize so the same tiles stay framed,
        instead of a bigger window revealing empty canvas around them —
        which is what a dashboard handed to somebody else wants, since the
        screen it lands on is not the screen it was built on.

        Zooming and panning by hand go off while it is on: they would fight
        the next resize, and the answer to "why did my zoom snap back?" is
        never satisfying. The same navigation lock a locked page uses, so a
        page that is both stays locked when this is switched off.
        """
        self._fit_to_window = bool(fit)
        self.set_navigation_locked(self._view_mode or self._fit_to_window)
        if self._fit_to_window:
            self.queue_fit()

    def fit_to_window(self) -> bool:
        return self._fit_to_window

    def queue_fit(self) -> None:
        """Ask for a refit once things stop moving."""
        if self._fit_to_window:
            self._fit_timer.start()

    def _fit_page(self) -> None:
        """Put every tile in view, with a margin, centred.

        fitInView rather than the fit_items() the canvas uses: that one
        refuses to magnify past 150% (sensible when you are fitting a
        single node you double-clicked) and stands down while navigation is
        locked (sensible when the user is the one asking). Neither applies
        here — a small dashboard on a big screen *should* fill it, and this
        fit is the mode working, not somebody's stray keystroke.
        """
        if not self._fit_to_window or self._fs_tile is not None:
            return
        scene = self.scene()
        if scene is None:
            return
        # The scrollable span is fitted to the content on a debounce, and a
        # view cannot travel outside it — so a tile just dragged out to the
        # edge would be fitted to and then not reached, leaving it off
        # screen on the page that promises to show everything.
        if hasattr(scene, "flush_rect_fit"):
            scene.flush_rect_fit()
        content = scene.itemsBoundingRect()
        if content.isEmpty():
            return
        self.fitInView(content.adjusted(-FIT_MARGIN, -FIT_MARGIN,
                                        FIT_MARGIN, FIT_MARGIN),
                       Qt.KeepAspectRatio)
        # The transform is the only thing fitInView touches, so the zoom
        # readout and the level-of-detail switch have to be told by hand.
        self._clamp_fit_zoom()
        self._zoom_updated()

    def _clamp_fit_zoom(self) -> None:
        """fitInView answers with whatever ratio the arithmetic gives it,
        including one no other zoom in the app is allowed to reach. Pull it
        back inside the same range, about the same centre."""
        from ..canvas.base_view import ZOOM_MAX, ZOOM_MIN
        zoom = self.zoom
        wanted = max(ZOOM_MIN, min(ZOOM_MAX, zoom))
        if wanted != zoom and zoom > 0:
            centre = self.mapToScene(self.viewport().rect().center())
            self.scale(wanted / zoom, wanted / zoom)
            self.centerOn(centre)

    # --------------------------------------------------------- fullscreen

    @property
    def fullscreen_tile(self) -> Optional[TileItem]:
        return self._fs_tile

    @property
    def fullscreen_overlay(self) -> Optional[FullscreenOverlay]:
        """The native overlay, when this tile's kind uses one and it is
        still alive."""
        return self._live_overlay()

    def _live_overlay(self) -> Optional[FullscreenOverlay]:
        """The overlay, or None once Qt has destroyed it underneath us.

        The overlay is a child of the viewport, so anything that tears the
        page down — deleting the page, closing the project — deletes it
        through C++ without going through exit_fullscreen. The Python
        wrapper survives that and looks perfectly ordinary; touching it
        raises "Internal C++ object already deleted", and since the next
        thing to touch it is resizeEvent, that lands as an unhandled error
        in the middle of removing a page. Ask whether the object is still
        there rather than assuming, and forget it once it is not.
        """
        overlay = self._fs_overlay
        if overlay is not None and not shiboken.isValid(overlay):
            self._fs_overlay = None
            return None
        return overlay

    def enter_fullscreen(self, item: TileItem) -> None:
        if not item.can_fullscreen():
            return
        if self._fs_tile is not None:
            self.exit_fullscreen()
        # 1:1 zoom while maximized: scene units are viewport pixels, so the
        # embedded widgets render at their natural resolution instead of
        # through a magnifying transform
        self._fs_restore = (self.transform(),
                            self.mapToScene(self.viewport().rect().center()))
        self.resetTransform()
        self._fs_tile = item
        for other in self.scene().tile_items.values():
            if other is not item:
                other.setVisible(False)

        content = item.fullscreen_widget()
        if content is not None:
            # out of the scene entirely — see the module docstring for why
            # onto the viewport, not the view: the viewport's rect is exactly
            # the area the scene would have filled
            self._fs_overlay = FullscreenOverlay(
                item.fullscreen_title(), content,
                self._restore_from_overlay, self)
            item.set_fullscreen_overlaid()
            item.setVisible(False)
        self._layout_fullscreen()
        if self._fs_overlay is not None:
            self._fs_overlay.show()
            self._fs_overlay.raise_()
            content.setFocus()
        self._zoom_updated()
        self.fullscreen_changed.emit(True)

    def _restore_from_overlay(self) -> None:
        """Escape or the overlay's close button. Goes through the model like
        every other way out, so the maximized tile saved with the project
        stays the truth."""
        scene = self.scene()
        if scene is not None:
            scene.exit_fullscreen()

    def exit_fullscreen(self) -> None:
        item, self._fs_tile = self._fs_tile, None
        overlay, self._fs_overlay = self._live_overlay(), None
        if overlay is not None:
            # A maximized widget may be running something — an animated
            # report is the case in point — and deleteLater leaves it doing
            # so until the event loop comes round. Ask it to stop first;
            # widgets with nothing to wind down don't define this.
            dispose = getattr(overlay.content, "dispose", None)
            if callable(dispose):
                dispose()
            overlay.hide()
            overlay.setParent(None)
            overlay.deleteLater()
        if item is None:
            return
        scene = self.scene()
        if scene is not None:
            for other in scene.tile_items.values():
                other.setVisible(True)
        item.setVisible(True)
        item.clear_fullscreen()
        if self._fs_restore is not None:
            transform, center = self._fs_restore
            self._fs_restore = None
            self.setTransform(transform)
            self.centerOn(center)
            self._zoom_updated()
        # A fullscreen restored from the saved file was entered before the
        # view had ever been laid out, so the centre captured then points
        # nowhere useful. Whatever the reason, don't leave the user staring
        # at empty canvas with the tile they were just reading off-screen.
        visible = self.mapToScene(self.viewport().rect()).boundingRect()
        if not visible.intersects(item.sceneBoundingRect()):
            self.center_on_scene(item.sceneBoundingRect().center())
        # the transform saved on the way in was the fitted one, but the
        # window may have changed size while a tile filled it
        self.queue_fit()
        self.fullscreen_changed.emit(False)

    def _layout_fullscreen(self) -> None:
        """Re-pin the maximized tile to the viewport — on entry, and on every
        resize after, which is what makes the chart grow with the window."""
        if self._fs_tile is None:
            return
        overlay = self._live_overlay()
        if overlay is not None:
            # the viewport's geometry, in the view's coordinates -- the
            # overlay is the viewport's sibling, not its child (see
            # enter_fullscreen), so this is what lines the two up
            overlay.setGeometry(self.viewport().geometry())
            overlay.raise_()
            return
        # flush to the viewport, with no breathing room: this route has to
        # land in the same place the native overlay does (which takes the
        # viewport's geometry exactly), or maximizing a chart and maximizing
        # a table are visibly two different things
        self._fs_tile.set_fullscreen_rect(
            self.mapToScene(self.viewport().rect()).boundingRect())

    def setViewport(self, widget) -> None:
        """Swapping the viewport (the GPU-viewport setting does this to
        every canvas view, including at startup) installs a brand new widget
        on top of everything else. A maximized tile's overlay is a sibling of
        the viewport, so it survives the swap but ends up *behind* it --
        exactly the problem the minimap solves with a raise_() of its own.

        This is also why the overlay is not a child of the viewport, which is
        the obvious place for it: setViewport deletes the old viewport and
        every child it had, so a project saved with a tile maximized reopened
        onto a blank page -- the tile hidden behind an overlay that had been
        destroyed on the way in.
        """
        super().setViewport(widget)
        self._layout_fullscreen()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._layout_fullscreen()
        self.queue_fit()

    # --------------------------------------------------- navigation gating

    def wheelEvent(self, event) -> None:
        # Zooming or panning while maximized would just slide the tile off
        # the viewport it's pinned to; a wheel over scrollable content (a
        # table, a web view) still belongs to that widget.
        if (self._fs_tile is not None
                and self._scrollable_widget_at(
                    event.position().toPoint()) is None):
            event.accept()
            return
        super().wheelEvent(event)

    def mousePressEvent(self, event) -> None:
        if self._fs_tile is not None and event.button() == Qt.MiddleButton:
            event.accept()
            return
        super().mousePressEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        key = event.key()
        if self._fs_tile is not None:
            if key == Qt.Key_Escape:
                # through the model, like the button: the maximized tile is
                # saved with the project
                self.scene().exit_fullscreen()
                event.accept()
                return
            if key in (Qt.Key_Space, Qt.Key_F):  # no pan, no fit-to-items
                event.accept()
                return
        # While the native overlay is up the page is not being edited, it is
        # being read and typed into. Delete must never reach the tiles: the
        # only reason a Delete arrives here is that a grid below chose not to
        # take it, and "clear the cell" failing must not become "delete the
        # tile".
        if not self._proxy_widget_has_focus() and self._fs_overlay is None:
            if key == Qt.Key_Delete or key == Qt.Key_Backspace:
                self.scene().delete_selected_tiles()
                event.accept()
                return
            if key == Qt.Key_F:
                scene = self.scene()
                self.fit_items(scene.selected_tile_items()
                               or list(scene.tile_items.values()))
                event.accept()
                return
            action = layer_action_for(event)
            if action is not None and self.scene().restack_selection(action):
                event.accept()
                return
        super().keyPressEvent(event)

    # --------------------------------------------------------- context menu

    def contextMenuEvent(self, event) -> None:
        """Right-click on a dashboard page.

        Over a tile: layer actions plus Copy / Paste / Delete. Copy takes
        the *selection* (or the clicked tile if it isn't part of one), so a
        right-click on a multi-selection copies all of it; paste rebuilds
        the copied arrangement, on this page or any other. On empty canvas:
        a Paste menu, so a copied selection can land wherever the cursor
        is. Right-click selects first (adding to the selection when Ctrl or
        Shift is held), so the menu always acts on what the user is looking
        at — and a right-click on an Action Button still can't fire it."""
        if self._view_mode:
            # A locked page has no layout to act on, so there is no menu to
            # show — and accepting is the point: passed up, the event walks
            # the parent chain to the main window, which answers a bare
            # right-click with its own dock-and-toolbar menu. That is the
            # menu "of whatever is underneath" appearing over a finished
            # dashboard.
            event.accept()
            return
        item = self._tile_at(event.pos())
        if self._fs_tile is not None:
            event.accept()
            return
        if item is None:
            self._show_canvas_menu(event)
            return
        if not item.isSelected():
            if not event.modifiers() & (Qt.ControlModifier | Qt.ShiftModifier):
                self.scene().clearSelection()
            item.setSelected(True)
        menu = QMenu(self)
        layer_actions = add_layer_menu(menu)
        browser_action = None
        node = self._browsable_node(item)
        if node is not None:
            menu.addSeparator()
            browser_action = menu.addAction("Open in Browser")
        menu.addSeparator()
        copy_action = menu.addAction("Copy")
        paste_action = menu.addAction("Paste")
        paste_action.setEnabled(bool(DashboardView._tile_clipboard))
        delete_action = menu.addAction("Delete")
        chosen = menu.exec(event.globalPos())
        if chosen is copy_action:
            self._copy_tiles(item)
        elif chosen is paste_action:
            self._paste_tiles(anchor=item)
        elif chosen is delete_action:
            self.scene().delete_selected_tiles()
        elif chosen in layer_actions:
            self.scene().restack_selection(layer_actions[chosen])
        elif browser_action is not None and chosen is browser_action:
            from ..browser import open_node_from
            scene = self.scene()
            scene.engine.cache.outputs_for(node.id)   # load it if it was spilled
            open_node_from(self, node, scene.engine.cache.get(node.id))
        event.accept()

    def _show_canvas_menu(self, event) -> None:
        """Right-click on empty canvas: the paste menu. The one thing an
        empty page has to offer is putting down what was copied, and it must
        not leak up to the main window's own menu the way a bare right-click
        used to."""
        menu = QMenu(self)
        paste_action = menu.addAction("Paste")
        paste_action.setEnabled(bool(DashboardView._tile_clipboard))
        chosen = menu.exec(event.globalPos())
        if chosen is paste_action and DashboardView._tile_clipboard:
            self._paste_tiles(scene_pos=self.mapToScene(event.pos()))
        event.accept()

    def _copy_tiles(self, anchor: TileItem) -> None:
        """Copy the selection — or just the clicked tile when it isn't part
        of one. Positions are stored relative to the selection's top-left so
        a paste on any page restores the arrangement."""
        items = self.scene().selected_tile_items()
        if anchor not in items:
            items = [anchor]
        rects = [item.tile.rect for item in items]
        min_x = min(rect[0] for rect in rects)
        min_y = min(rect[1] for rect in rects)
        DashboardView._tile_clipboard = tuple(
            (item.tile.node_id, item.tile.port,
             item.tile.rect[0] - min_x, item.tile.rect[1] - min_y,
             item.tile.rect[2], item.tile.rect[3])
            for item in items)

    def _paste_tiles(self, scene_pos: Optional[QPointF] = None,
                     anchor: Optional[TileItem] = None) -> None:
        """Stamp the clipboard's tiles onto the current page, one undo step
        for the whole paste.

        `scene_pos` puts the copied arrangement's top-left at the cursor
        (empty-canvas paste); `anchor` offsets it from the tile that was
        right-clicked so it arrives clear of it. Either way the tiles go to
        this view's own page, so a paste lands where the user is looking —
        even when that is another dashboard page."""
        clip = DashboardView._tile_clipboard
        if not clip:
            return
        if anchor is not None:
            base_x, base_y = (anchor.tile.rect[0] + TILE_PASTE_OFFSET,
                              anchor.tile.rect[1] + TILE_PASTE_OFFSET)
        elif scene_pos is not None:
            base_x, base_y = scene_pos.x(), scene_pos.y()
        else:
            base_x = base_y = TILE_PASTE_OFFSET
        from flograph.core import Tile

        from ..commands import AddTileCommand
        scene = self.scene()
        scene.undo_stack.beginMacro("paste tiles")
        for node_id, port, rel_x, rel_y, w, h in clip:
            tile = Tile(
                id=uuid.uuid4().hex,
                node_id=node_id,
                port=port,
                rect=(base_x + rel_x, base_y + rel_y, w, h),
            )
            scene.undo_stack.push(
                AddTileCommand(scene.graph, scene.page_id, tile))
        scene.undo_stack.endMacro()

    def _browsable_node(self, item: TileItem):
        """The node behind a webview tile that has something to open, else
        None. A dashboard is where the tile is *smallest*, so handing the
        page to a full browser window matters more here than on the canvas."""
        from ..browser import can_open
        from ..canvas.node_item import card_kind
        scene = self.scene()
        node = scene.graph.nodes.get(item.tile.node_id)
        if node is None or card_kind(node) != "webview":
            return None
        entry = scene.engine.cache.get(node.id)
        return node if can_open(node, entry) else None

    def _tile_at(self, pos) -> Optional[TileItem]:
        for item in self.items(pos):
            while item is not None and not isinstance(item, TileItem):
                item = item.parentItem()
            if item is not None:
                return item
        return None

    # ---------------------------------------------------------- drag & drop

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasFormat(TILE_NODE_MIME):
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:
        if event.mimeData().hasFormat(TILE_NODE_MIME):
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event) -> None:
        if event.mimeData().hasFormat(TILE_NODE_MIME):
            node_id = bytes(event.mimeData().data(TILE_NODE_MIME)).decode()
            self.tile_dropped.emit(
                node_id, self.mapToScene(event.position().toPoint()))
            event.acceptProposedAction()
        else:
            super().dropEvent(event)
