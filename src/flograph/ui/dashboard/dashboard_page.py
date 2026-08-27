"""DashboardPage: one dashboard tab — a visuals list beside the page's
infinite canvas. Owns the scene/view pair; dispose() must be called when the
page is removed (core events hold strong refs to both scene and list)."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QUndoStack
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QSplitter, QToolButton, QVBoxLayout, QWidget,
)

from flograph.core import Graph

from .dashboard_scene import DashboardScene
from .dashboard_view import DashboardView
from .visuals_list import VisualsList


class DashboardPage(QWidget):
    # the user opened or closed the visuals panel -- the window remembers it
    # as the starting state for pages made later
    visuals_visibility_changed = Signal(bool)

    def __init__(self, graph: Graph, engine, undo_stack: QUndoStack,
                 page_id: str, parent=None,
                 visuals_visible: bool = False) -> None:
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
        side_layout.addWidget(self.visuals, 1)
        hint = QLabel("Drag a visual onto the page.")
        hint.setStyleSheet("color: #6b7280; font-size: 8pt;")
        hint.setWordWrap(True)
        side_layout.addWidget(hint)

        self._splitter = QSplitter(Qt.Horizontal)
        self._splitter.addWidget(self._side)
        self._splitter.addWidget(self.view)
        self._splitter.setStretchFactor(0, 0)
        self._splitter.setStretchFactor(1, 1)
        # set before anything is hidden: the splitter keeps the width it was
        # given, so reopening the panel restores it rather than a sliver
        self._splitter.setSizes([180, 1000])
        self._visuals_visible = True
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

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._toggle_strip)
        layout.addWidget(self._splitter, 1)

        self.view.fullscreen_changed.connect(self._on_fullscreen_changed)

        # a dashboard is for looking at, so the page opens as canvas and the
        # visuals panel is asked for -- silently, since nothing has changed yet
        self.set_visuals_visible(visuals_visible, notify=False)
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

    def showEvent(self, event) -> None:
        """Switching to this tab resumes its animated tiles, and away pauses
        them — a dashboard nobody is looking at should cost nothing. The
        same bargain the report preview makes."""
        super().showEvent(event)
        self.scene.set_animations_playing(True)

    def hideEvent(self, event) -> None:
        super().hideEvent(event)
        self.scene.set_animations_playing(False)

    def dispose(self) -> None:
        self.scene.dispose()
        self.visuals.dispose()
