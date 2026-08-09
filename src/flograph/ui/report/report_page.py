"""ReportPage: one report tab — markdown source beside a live preview.

The counterpart to DashboardPage. A dashboard is arranged by dragging; a
report is *written*, so this is an editor and a rendered view of what it
will print as, not a canvas.

Like DashboardPage it owns its Qt objects and must be dispose()d when the
page is removed — core events hold strong references to the callbacks.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QFont, QTextCursor, QUndoStack
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QMenu, QPlainTextEdit, QPushButton, QSplitter,
    QTextBrowser, QToolButton, QVBoxLayout, QWidget,
)

from flograph.core import Graph

from ..commands import SetPageBodyCommand
from .render import render_report

# How long typing has to pause before the preview re-renders. Re-rendering
# is cheap for text but redraws every embedded chart, so it is not something
# to do on each keystroke.
PREVIEW_DELAY_MS = 350

STARTER_BODY = """# New report

Write in markdown. Pull anything the flow produced in by name:

    ![[Node Label]]         a chart, a table, a number, or markdown text
    ![[Node Label|port]]    a particular output port

A node that *returns markdown* is inlined as written — so a whole section
can be built by a Python Script node rather than typed here.

Use **Export PDF…** when it reads the way you want.
"""


class ReportPage(QWidget):
    #: the user asked to export — the window owns the file dialog
    export_requested = Signal(str)   # page_id
    #: the editor-collapse toggle was clicked; the window owns the undo stack
    view_mode_requested = Signal(str, bool)   # page_id, view_mode

    def __init__(self, graph: Graph, engine, undo_stack: QUndoStack,
                 page_id: str, parent=None) -> None:
        super().__init__(parent)
        self.page_id = page_id
        self._graph = graph
        self._engine = engine
        self._undo_stack = undo_stack
        self._loading = False
        self.problems: list[str] = []
        #: drives animated images in the preview; rebuilt on every render
        self._animator = None
        self._view_mode = False

        self.editor = QPlainTextEdit()
        self.editor.setObjectName("report_source")
        font = QFont("monospace")
        font.setStyleHint(QFont.Monospace)
        font.setPointSizeF(10.0)
        self.editor.setFont(font)
        self.editor.setTabChangesFocus(True)
        self.editor.setPlaceholderText(
            "Write the report in markdown, and ![[embed]] what the flow made…")

        self.preview = QTextBrowser()
        self.preview.setObjectName("report_preview")
        self.preview.setOpenExternalLinks(True)

        self._insert_btn = QToolButton()
        self._insert_btn.setText("Insert embed ▾")
        self._insert_btn.setToolTip(
            "Insert an ![[embed]] for a node that has produced something")
        self._insert_btn.clicked.connect(self._show_insert_menu)
        self._export_btn = QPushButton("Export PDF…")
        self._export_btn.clicked.connect(
            lambda: self.export_requested.emit(self.page_id))
        self._status = QLabel("")
        self._status.setStyleSheet("color: #b45309;")

        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(6, 4, 6, 0)
        toolbar.addWidget(self._insert_btn)
        toolbar.addWidget(self._status, 1)
        toolbar.addWidget(self._export_btn)

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self.editor)
        splitter.addWidget(self.preview)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([520, 620])
        self._splitter = splitter

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(toolbar)
        layout.addWidget(splitter, 1)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(PREVIEW_DELAY_MS)
        self._timer.timeout.connect(self.refresh_preview)

        # The editor-collapse toggle *is* the view-mode switch rather than a
        # second, separate setting: two controls that both hide the editor
        # would sooner or later disagree about whether it is hidden.
        self._mode_btn = QToolButton()
        self._mode_btn.setAutoRaise(True)
        self._mode_btn.clicked.connect(
            lambda: self.view_mode_requested.emit(
                self.page_id, not self._view_mode))
        toolbar.insertWidget(0, self._mode_btn)

        self.editor.textChanged.connect(self._on_text_changed)

        self._event_subs = [
            (graph.events.page_body_changed, self._on_body_changed),
            # An embedded node's params can change what the report shows
            # without changing what it *computed* — chart layout being the
            # case in point. Those are declared cosmetic, so no run happens
            # and node_succeeded never fires; without this the page would
            # keep showing the old arrangement.
            (graph.events.param_changed, self._on_param_changed),
        ]
        for event, callback in self._event_subs:
            event.connect(callback)
        engine.node_succeeded.connect(self._on_node_ran)
        engine.node_failed.connect(self._on_node_ran)

        self._load_from_model()
        page = self._page()
        self.set_view_mode(page.view_mode if page is not None else False)

    # ------------------------------------------------------------- the mode

    def set_view_mode(self, view_mode: bool) -> None:
        """View mode is the rendered report on its own: the markdown source
        and the insert-embed button are for *writing* it, and neither is any
        use to someone reading. Export stays — reading is exactly when
        somebody wants the PDF."""
        self._view_mode = bool(view_mode)
        self.editor.setVisible(not self._view_mode)
        self._insert_btn.setVisible(not self._view_mode)
        self._mode_btn.setArrowType(
            Qt.ArrowType.RightArrow if self._view_mode
            else Qt.ArrowType.LeftArrow)
        self._mode_btn.setToolTip(
            "Show the editor (edit mode)" if self._view_mode
            else "Hide the editor (view mode)")

    def view_mode(self) -> bool:
        return self._view_mode

    def dispose(self) -> None:
        """Mandatory on page removal: core events hold strong refs and would
        keep calling into this widget after its Qt side is deleted."""
        for event, callback in self._event_subs:
            event.disconnect(callback)
        self._event_subs = []
        self._engine.node_succeeded.disconnect(self._on_node_ran)
        self._engine.node_failed.disconnect(self._on_node_ran)
        self._timer.stop()
        self._stop_animations()

    # ------------------------------------------------------------- the body

    def _page(self):
        return self._graph.pages.get(self.page_id)

    def _load_from_model(self) -> None:
        page = self._page()
        if page is None:
            return
        self._loading = True
        self.editor.setPlainText(page.body)
        self._loading = False
        self.refresh_preview()

    def _on_text_changed(self) -> None:
        if self._loading:
            return
        page = self._page()
        text = self.editor.toPlainText()
        if page is None or text == page.body:
            return
        # merged, so a burst of typing is one undo step
        self._undo_stack.push(
            SetPageBodyCommand(self._graph, self.page_id, text))
        self._timer.start()

    def _on_body_changed(self, page) -> None:
        """An undo, a redo, or a load changed the body under us. Only touch
        the editor when the text really differs — setPlainText resets the
        cursor to the top, which mid-typing would be unusable."""
        if page.id != self.page_id or self._loading:
            return
        if self.editor.toPlainText() != page.body:
            cursor = self.editor.textCursor().position()
            self._loading = True
            self.editor.setPlainText(page.body)
            self._loading = False
            moved = self.editor.textCursor()
            moved.setPosition(min(cursor, len(page.body)))
            self.editor.setTextCursor(moved)
        self._timer.start()

    def _on_node_ran(self, *_args) -> None:
        """A run finished, so the embeds have new content to show."""
        self._timer.start()

    def _on_param_changed(self, *_args) -> None:
        """Any node's param changed — it may be one this report embeds."""
        self._timer.start()

    # ---------------------------------------------------------- the preview

    def refresh_preview(self) -> None:
        page = self._page()
        if page is None:
            return
        position = self.preview.verticalScrollBar().value()
        rendered = render_report(page.body, self._graph, self._engine.cache)
        self.problems = rendered.problems
        # Before the old document goes: a running QMovie writing frames into
        # a deleted document is a crash, not a stale picture.
        self._stop_animations()
        self.preview.setDocument(rendered.document)
        self._start_animations(rendered)
        # a re-render on every keystroke that jumped to the top would make
        # the preview useless while writing past the first screenful
        self.preview.verticalScrollBar().setValue(position)
        self._status.setText(self._problem_text())

    def _stop_animations(self) -> None:
        if self._animator is not None:
            self._animator.dispose()
            self._animator = None

    def _start_animations(self, rendered) -> None:
        """Play any animated images the render found. Paper can't animate,
        so this only ever runs for the on-screen preview."""
        if not rendered.animations:
            return
        from .animate import ReportAnimator
        self._animator = ReportAnimator(
            rendered.document, rendered.animations, rendered.image_widths,
            on_frame=self.preview.viewport().update, parent=self)
        self._animator.set_playing(self.isVisible())

    def showEvent(self, event) -> None:
        """Switching to this tab resumes its animations, and away pauses
        them — a report nobody is looking at should cost nothing."""
        super().showEvent(event)
        if self._animator is not None:
            self._animator.set_playing(True)

    def hideEvent(self, event) -> None:
        super().hideEvent(event)
        if self._animator is not None:
            self._animator.set_playing(False)

    def _problem_text(self) -> str:
        if not self.problems:
            return ""
        first = self.problems[0]
        more = f" (+{len(self.problems) - 1} more)" if len(self.problems) > 1 else ""
        return f"⚠ {first}{more}"

    # ----------------------------------------------------------- insert menu

    def embeddable_nodes(self) -> list:
        """Nodes worth offering here — shared with the Report card's own
        insert menu, so the two offer the same things."""
        from .render import embeddable_nodes
        return embeddable_nodes(self._graph, self._engine.cache)

    def duplicate_labels(self) -> set:
        from .render import duplicate_labels
        return duplicate_labels(self._graph)

    def _show_insert_menu(self) -> None:
        menu = QMenu(self)
        nodes = self.embeddable_nodes()
        if not nodes:
            menu.addAction("Run the flow first — nothing has output yet"
                           ).setEnabled(False)
        ambiguous = self.duplicate_labels()
        actions = {}
        for node in nodes:
            duplicated = node.label.casefold() in ambiguous
            entry = menu.addAction(
                f"{node.label}  — duplicate name, rename one first"
                if duplicated else node.label)
            entry.setEnabled(not duplicated)
            if not duplicated:
                actions[entry] = node.label
        chosen = menu.exec(self._insert_btn.mapToGlobal(
            self._insert_btn.rect().bottomLeft()))
        if chosen in actions:
            self.insert_embed(actions[chosen])

    def insert_embed(self, label: str) -> None:
        """Drop an embed at the cursor, on its own line — an embed sharing a
        line with a paragraph would render inline, which is almost never
        what someone picking a chart from a menu means."""
        from .render import embed_line
        cursor = self.editor.textCursor()
        cursor.insertText(embed_line(label, cursor.atBlockStart()))
        self.editor.setTextCursor(cursor)
        self.editor.setFocus()

    # ------------------------------------------------------------- exporting

    def rendered(self, for_print: bool = False):
        """The document as it would print, freshly rendered.

        `for_print` rasterises the charts to PRINT_DPI — same layout, same
        text, same page breaks, just enough pixels that a chart doesn't read
        as fuzzy on paper.
        """
        page = self._page()
        return render_report(page.body if page else "", self._graph,
                             self._engine.cache,
                             image_scale=2.0 if for_print else 1.0)
