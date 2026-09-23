"""DashboardPage: one dashboard tab — a visuals list on the left of the
page's infinite canvas and the Format pane on its right. Owns the scene/view
pair; dispose() must be called when the page is removed (core events hold
strong refs to the scene, the list and the pane)."""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QUndoStack
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QHBoxLayout, QLabel, QMenu, QSplitter,
    QToolButton, QVBoxLayout, QWidget, QWidgetAction,
)

from flograph.core import Graph

from .dashboard_scene import DashboardScene
from .dashboard_view import DashboardView
from .format_pane import FormatPane, GuardedLineEdit
from .visuals_list import SORT_MODES, VisualsList, kind_glyph, kind_label


class DashboardPage(QWidget):
    # the user opened or closed the visuals panel -- the window remembers it
    # as the starting state for pages made later
    visuals_visibility_changed = Signal(bool)
    # and the same for the Format pane on the other side
    format_visibility_changed = Signal(bool)

    def __init__(self, graph: Graph, engine, undo_stack: QUndoStack,
                 page_id: str, parent=None,
                 visuals_visible: bool = False,
                 format_visible: bool = False) -> None:
        super().__init__(parent)
        self.page_id = page_id
        self.scene = DashboardScene(graph, engine, undo_stack, page_id,
                                    parent=self)
        self.view = DashboardView(self.scene)
        # the engine is what the visuals list builds its hover previews from
        # — a preview is a real tile, and a tile shows cached output
        self.visuals = VisualsList(graph, engine)

        self._side = QWidget()
        side_layout = QVBoxLayout(self._side)
        side_layout.setContentsMargins(6, 6, 4, 6)
        side_layout.setSpacing(4)
        header = QLabel("Visuals")
        header.setStyleSheet("font-weight: bold;")
        side_layout.addWidget(header)

        # finding a visual in a long flow: by name, by type, in an order
        self.visuals_search = GuardedLineEdit()
        self.visuals_search.setPlaceholderText("Search visuals")
        self.visuals_search.setClearButtonEnabled(True)
        self.visuals_search.textChanged.connect(self.visuals.set_search)
        side_layout.addWidget(self.visuals_search)
        tools = QHBoxLayout()
        tools.setContentsMargins(0, 0, 0, 0)
        tools.setSpacing(4)
        self.visuals_types = QToolButton()
        self.visuals_types.setPopupMode(QToolButton.InstantPopup)
        self.visuals_types.setToolTip(
            "Tick types to show only those. Nothing ticked shows them all, "
            "the way a slicer does.")
        types_menu = QMenu(self.visuals_types)
        types_menu.aboutToShow.connect(self._fill_types_menu)
        self.visuals_types.setMenu(types_menu)
        self.visuals_sort = QComboBox()
        self.visuals_sort.setToolTip("Sort the visuals")
        for mode, label in SORT_MODES.items():
            self.visuals_sort.addItem(label, mode)
        self.visuals_sort.currentIndexChanged.connect(
            lambda index: self.visuals.set_sort(
                self.visuals_sort.itemData(index)))
        self.visuals_clear = QToolButton()
        self.visuals_clear.setText("✕")
        self.visuals_clear.setAutoRaise(True)
        self.visuals_clear.setToolTip("Clear the search and the type filter")
        self.visuals_clear.clicked.connect(self.clear_visual_filters)
        tools.addWidget(self.visuals_types, 1)
        tools.addWidget(self.visuals_sort, 1)
        tools.addWidget(self.visuals_clear)
        side_layout.addLayout(tools)

        side_layout.addWidget(self.visuals, 1)
        self.visuals_empty = QLabel()
        self.visuals_empty.setWordWrap(True)
        self.visuals_empty.setStyleSheet("color: palette(mid);")
        self.visuals_empty.hide()
        side_layout.addWidget(self.visuals_empty)
        hint = QLabel("Drag a visual onto the page.")
        hint.setStyleSheet("color: palette(mid); font-size: 8pt;")
        hint.setWordWrap(True)
        side_layout.addWidget(hint)
        self.visuals.filters_changed.connect(self._on_visual_filters_changed)
        self._on_visual_filters_changed()

        self.format = FormatPane(graph, undo_stack, page_id)
        self.scene.selectionChanged.connect(self._on_selection_changed)

        self._splitter = QSplitter(Qt.Horizontal)
        self._splitter.addWidget(self._side)
        self._splitter.addWidget(self.view)
        self._splitter.addWidget(self.format)
        self._splitter.setStretchFactor(0, 0)
        self._splitter.setStretchFactor(1, 1)
        self._splitter.setStretchFactor(2, 0)
        # set before anything is hidden: the splitter keeps the width it was
        # given, so reopening the panel restores it rather than a sliver
        self._splitter.setSizes([180, 1000, 260])
        self._visuals_visible = True
        self._format_visible = True
        self._view_mode = False
        self._fullscreen = False

        # always-visible strip so the panel can be brought back once
        # hidden -- the toggle itself must live outside what it hides
        self._toggle_btn = QToolButton()
        self._toggle_btn.setArrowType(Qt.ArrowType.LeftArrow)
        self._toggle_btn.setToolTip("Hide visuals panel")
        self._toggle_btn.setAutoRaise(True)
        self._toggle_btn.clicked.connect(
            lambda: self.set_visuals_visible(not self._visuals_visible))
        self._toggle_strip = QWidget()
        self._toggle_strip.setFixedWidth(20)
        toggle_layout = QVBoxLayout(self._toggle_strip)
        toggle_layout.setContentsMargins(0, 0, 0, 0)
        toggle_layout.addWidget(self._toggle_btn)
        toggle_layout.addStretch(1)

        # the Format pane's own strip, down the right edge
        self._format_btn = QToolButton()
        self._format_btn.setAutoRaise(True)
        self._format_btn.clicked.connect(
            lambda: self.set_format_visible(not self._format_visible))
        self._format_strip = QWidget()
        self._format_strip.setFixedWidth(20)
        format_layout = QVBoxLayout(self._format_strip)
        format_layout.setContentsMargins(0, 0, 0, 0)
        format_layout.addWidget(self._format_btn)
        format_layout.addStretch(1)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._toggle_strip)
        layout.addWidget(self._splitter, 1)
        layout.addWidget(self._format_strip)

        self.view.fullscreen_changed.connect(self._on_fullscreen_changed)
        self.view.format_requested.connect(
            lambda: self.set_format_visible(True))

        # a dashboard is for looking at, so the page opens as canvas and the
        # visuals panel is asked for -- silently, since nothing has changed yet
        self.set_visuals_visible(visuals_visible, notify=False)
        self.set_format_visible(format_visible, notify=False)
        page = graph.pages.get(page_id)
        self.set_view_mode(page.view_mode if page is not None else False)
        self.set_fit_to_window(
            page.fit_to_window if page is not None else False)
        # last, so a page saved with a tile maximized opens that way and the
        # chrome it hides is not put back by the lines above
        self.scene.sync_fullscreen()

    # ----------------------------------------------------------- fullscreen

    def _on_fullscreen_changed(self, active: bool) -> None:
        """Give a maximized tile the whole page: the visuals panel and its
        toggle strip step aside, and come back on the way out.

        Deliberately not via set_visuals_visible() -- maximizing is not the
        user asking for the panel, so it must leave _visuals_visible alone
        and stay off visuals_visibility_changed, which would otherwise make
        fullscreen rewrite the start state new pages open with."""
        self._fullscreen = bool(active)
        self._apply_chrome()

    def _apply_chrome(self) -> None:
        """One place decides whether the editing chrome shows, because two
        independent things hide it — view mode and a maximized tile — and
        whichever ran last used to win. Reopening a project with a tile
        maximized put the toggle strip back over it.
        """
        hidden = self._view_mode or self._fullscreen
        self._side.setVisible(self._visuals_visible and not hidden)
        self._toggle_strip.setVisible(not hidden)
        # the Format pane is arranging chrome too: a locked page shows
        # neither it nor the strip that would bring it back
        self.format.setVisible(self._format_visible and not hidden)
        self._format_strip.setVisible(not hidden)

    # ----------------------------------------------------------- view mode

    def set_view_mode(self, view_mode: bool) -> None:
        """View mode is the page without the tools for arranging it: the
        visuals panel and its toggle strip go, and tiles stop moving and
        resizing.

        What it deliberately does *not* do is make the page read-only. A
        dashboard exists to be driven — slicers ticked, sliders dragged,
        cells typed into, buttons pressed — so every tile's contents stay
        exactly as live as they were. This locks the furniture, not the
        controls.
        """
        self._view_mode = bool(view_mode)
        self._apply_chrome()
        self.scene.set_view_mode(self._view_mode)
        self.view.set_view_mode(self._view_mode)

    def view_mode(self) -> bool:
        return self._view_mode

    # ------------------------------------------------------ scale to window

    def set_fit_to_window(self, fit: bool) -> None:
        """Scale the page to whatever window it lands in — see
        DashboardView.set_fit_to_window. Independent of view mode: a page
        being built can scale too."""
        self.view.set_fit_to_window(fit)

    def fit_to_window(self) -> bool:
        return self.view.fit_to_window()

    def set_visuals_visible(self, visible: bool, notify: bool = True) -> None:
        """The user's preference for the panel. Kept even while view mode or
        a maximized tile is hiding it, so leaving either puts back what they
        actually had rather than a default."""
        self._visuals_visible = visible
        self._apply_chrome()
        self._toggle_btn.setArrowType(
            Qt.ArrowType.LeftArrow if visible else Qt.ArrowType.RightArrow)
        self._toggle_btn.setToolTip(
            "Hide visuals panel" if visible else "Show visuals panel")
        if notify:
            self.visuals_visibility_changed.emit(visible)

    def contextMenuEvent(self, event) -> None:
        """A right-click that reached the page itself, past every child with
        a menu of its own: the panels, their headings, the strips at the
        edges. Nothing there offers a menu, and passed on the event reaches
        the main window, whose list of docks and toolbars then opens over
        the page. That is what a page tab's menu left behind on Wayland when
        locking or unlocking brought the panels back under the pointer (see
        ui/menu_guard) — so the page takes the event and it stops here."""
        event.accept()

    def set_format_visible(self, visible: bool, notify: bool = True) -> None:
        """The user's preference for the Format pane, kept through view mode
        and a maximized tile exactly like the visuals panel's."""
        self._format_visible = bool(visible)
        self._apply_chrome()
        self._format_btn.setArrowType(
            Qt.ArrowType.RightArrow if visible else Qt.ArrowType.LeftArrow)
        self._format_btn.setToolTip(
            "Hide format pane" if visible else
            "Show format pane: how the page and its visuals look")
        if notify:
            self.format_visibility_changed.emit(self._format_visible)

    def format_visible(self) -> bool:
        return self._format_visible

    def _on_selection_changed(self) -> None:
        self.format.set_selection(
            [item.tile.id for item in self.scene.selected_tile_items()])

    # ----------------------------------------------- visuals search/filter

    def _fill_types_menu(self) -> None:
        """One tick per type, built as the menu opens so the counts are
        today's. A slicer's rules: nothing ticked shows every type, and
        ticking narrows the list to what is ticked. A type still ticked
        after its last visual went is listed at (0), or there would be no
        way left to untick it. Ticks are widgets, not checkable actions, so
        the menu stays open while several are changed."""
        menu = self.visuals_types.menu()
        menu.clear()
        ticked = self.visuals.kinds()
        entries = list(self.visuals.kinds_present())
        present = {kind for kind, _label, _count in entries}
        entries += [(kind, kind_label(kind), 0)
                    for kind in sorted(ticked - present, key=kind_label)]
        if not entries:
            menu.addAction("No visuals in this flow yet").setEnabled(False)
            return
        clear = menu.addAction("Clear Selection")
        clear.setToolTip("Untick every type, so every visual shows")
        clear.setEnabled(bool(ticked))
        clear.triggered.connect(lambda: self.visuals.set_kinds(frozenset()))
        menu.addSeparator()
        for kind, label, count in entries:
            holder = QWidget()
            row = QHBoxLayout(holder)
            row.setContentsMargins(8, 2, 8, 2)
            box = QCheckBox(f"{kind_glyph(kind)} {label} ({count})".strip())
            box.setChecked(kind in ticked)
            box.toggled.connect(
                lambda on, kind=kind: self._tick_kind(kind, on))
            row.addWidget(box)
            action = QWidgetAction(menu)
            action.setDefaultWidget(holder)
            menu.addAction(action)

    def _tick_kind(self, kind: str, ticked: bool) -> None:
        kinds = set(self.visuals.kinds())
        if ticked:
            kinds.add(kind)
        else:
            kinds.discard(kind)
        self.visuals.set_kinds(kinds)

    def clear_visual_filters(self) -> None:
        self.visuals_search.clear()
        self.visuals.clear_filters()

    def _on_visual_filters_changed(self) -> None:
        ticked = self.visuals.kinds()
        if not ticked:
            text = "All types"
        elif len(ticked) == 1:
            text = kind_label(next(iter(ticked)))
        else:
            text = f"{len(ticked)} types"
        self.visuals_types.setText(text)
        self.visuals_clear.setEnabled(self.visuals.is_filtered())
        if self.visuals.total_count() and not self.visuals.count():
            self.visuals_empty.setText(
                "No visuals match. Clear the search or the type filter to "
                "see them all.")
            self.visuals_empty.show()
        else:
            self.visuals_empty.hide()

    def showEvent(self, event) -> None:
        """Switching to this tab resumes its animated tiles, and away pauses
        them — a dashboard nobody is looking at should cost nothing. The
        same bargain the report preview makes."""
        super().showEvent(event)
        self.scene.set_animations_playing(True)
        # tiles skipped while the page was hidden; after this paint, so the
        # page appears at once and its tiles catch up
        # (the page is the timer's context: disposed first, it never fires)
        QTimer.singleShot(0, self, lambda: self.scene.flush_stale())

    def hideEvent(self, event) -> None:
        super().hideEvent(event)
        self.scene.set_animations_playing(False)

    def dispose(self) -> None:
        self.scene.selectionChanged.disconnect(self._on_selection_changed)
        self.scene.dispose()
        self.visuals.dispose()
        self.format.dispose()
