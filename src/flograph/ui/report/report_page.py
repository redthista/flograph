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
    QToolButton, QVBoxLayout, QWidget,
)

from flograph.core import Graph

from ..commands import SetPageBodyCommand
from .preview import PagedPreview
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
    #: Page Setup… was clicked; the window owns the dialog and the undo stack
    page_setup_requested = Signal(str)   # page_id
    #: Save as HTML… was clicked — the window owns the file dialog
    export_html_requested = Signal(str)   # page_id

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
        #: a PageSetup the Page Setup dialog is trying out, or None for the
        #: page's own — see preview_setup
        self._setup_override = None

        self.editor = QPlainTextEdit()
        self.editor.setObjectName("report_source")
        font = QFont("monospace")
        font.setStyleHint(QFont.Monospace)
        font.setPointSizeF(10.0)
        self.editor.setFont(font)
        self.editor.setTabChangesFocus(True)
        self.editor.setPlaceholderText(
            "Write the report in markdown, and ![[embed]] what the flow made…")

        # Paper, not a scroll of rich text: everything page setup adds — the
        # cover, the running header and footer, where a page actually ends —
        # is invisible in a continuous view until the PDF comes out.
        self.preview = PagedPreview()

        self._insert_btn = QToolButton()
        self._insert_btn.setText("Insert embed ▾")
        self._insert_btn.setToolTip(
            "Insert an ![[embed]] for a node that has produced something")
        self._insert_btn.clicked.connect(self._show_insert_menu)
        self._setup_btn = QToolButton()
        self._setup_btn.setText("Page Setup…")
        self._setup_btn.setToolTip(
            "Paper size, orientation, margins, a cover page, and running "
            "headers and footers")
        self._setup_btn.clicked.connect(
            lambda: self.page_setup_requested.emit(self.page_id))
        # A view option, not a page setting: it changes how the pages are
        # arranged on screen and nothing about what prints, so it belongs on
        # the toolbar rather than in Page Setup.
        self._flow_btn = QToolButton()
        self._flow_btn.setCheckable(True)
        self._flow_btn.setText("▦")
        self._flow_btn.setToolTip(
            "Lay the pages out left-to-right instead of in one column — "
            "the contact sheet, for seeing where everything falls at once")
        self._flow_btn.toggled.connect(self.preview.set_flow)

        self._help_btn = QToolButton()
        self._help_btn.setText("?")
        self._help_btn.setToolTip("What you can write in a report")
        self._help_btn.clicked.connect(self.show_help)
        self._html_btn = QToolButton()
        self._html_btn.setText("Save HTML…")
        self._html_btn.setToolTip(
            "Save the report as one self-contained HTML file — pictures "
            "included, so it travels as a single file")
        self._html_btn.clicked.connect(
            lambda: self.export_html_requested.emit(self.page_id))
        self._export_btn = QPushButton("Export PDF…")
        self._export_btn.clicked.connect(
            lambda: self.export_requested.emit(self.page_id))
        self._status = QLabel("")
        self._status.setStyleSheet("color: #b45309;")

        # A widget, not a bare layout, so locked mode can hide the strip
        # whole — a layout has no visibility of its own.
        self._toolbar = QWidget()
        toolbar = QHBoxLayout(self._toolbar)
        toolbar.setContentsMargins(6, 4, 6, 0)
        toolbar.addWidget(self._insert_btn)
        toolbar.addWidget(self._flow_btn)
        toolbar.addWidget(self._help_btn)
        toolbar.addWidget(self._status, 1)
        toolbar.addWidget(self._setup_btn)
        toolbar.addWidget(self._html_btn)
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
        layout.addWidget(self._toolbar)
        layout.addWidget(splitter, 1)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(PREVIEW_DELAY_MS)
        self._timer.timeout.connect(self.refresh_preview)

        # Locking lives on the page tab's right-click menu and nowhere else.
        # There used to be a 🔒 here as well, which put the control that
        # *removes the toolbar* on the toolbar: it could only ever be used
        # once, and getting back needed the tab menu anyway. One door in and
        # the same door out.
        self.editor.textChanged.connect(self._on_text_changed)

        self._event_subs = [
            (graph.events.page_body_changed, self._on_body_changed),
            # An embedded node's params can change what the report shows
            # without changing what it *computed* — chart layout being the
            # case in point. Those are declared cosmetic, so no run happens
            # and node_succeeded never fires; without this the page would
            # keep showing the old arrangement.
            (graph.events.param_changed, self._on_param_changed),
            # Page setup arrives on page_changed, and it decides how wide
            # the body is — which is the width every embedded chart is
            # rasterised at. Without this the preview would keep the
            # proportions of the paper size the page used to be.
            (graph.events.page_changed, self._on_page_changed),
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
        """Locked mode is the rendered report and nothing else.

        The whole toolbar goes, not just the editor: every control on it —
        insert an embed, page setup, the unresolved-embed warning — is for
        *writing* the report, and a strip of writing tools above a finished
        document is exactly the chrome locking is meant to remove.

        That leaves no visible way back, which is deliberate rather than an
        oversight: locking and unlocking both live on the page tab's
        right-click menu, and so do Page Setup and the exports while locked,
        so the one surface that is always reachable carries all of it.
        """
        self._view_mode = bool(view_mode)
        self.editor.setVisible(not self._view_mode)
        self._toolbar.setVisible(not self._view_mode)

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

    def _on_page_changed(self, page) -> None:
        """This page's own settings changed — page setup, most of all."""
        if page.id == self.page_id:
            self._timer.start()

    # ---------------------------------------------------------- the preview

    def refresh_preview(self) -> None:
        page = self._page()
        if page is None:
            return
        position = self.preview.verticalScrollBar().value()
        setup = self._setup_override or page.setup
        # No page_break_rule any more: the preview is paginated, so a forced
        # break shows as the page actually ending — which is better feedback
        # than a rule standing in for one, and it is what will print.
        rendered = render_report(page.body, self._graph, self._engine.cache,
                                 setup=setup)
        self.problems = rendered.problems
        # Before the old document goes: a running QMovie writing frames into
        # a deleted document is a crash, not a stale picture.
        self._stop_animations()
        self.preview.set_report(rendered.document, setup, page.title)
        self._start_animations(rendered)
        # a re-render on every keystroke that jumped to the top would make
        # the preview useless while writing past the first screenful
        self.preview.verticalScrollBar().setValue(position)
        self._status.setText(self._problem_text())

    def preview_setup(self, setup) -> None:
        """Show the report on `setup`'s paper without committing it.

        This is what makes Page Setup live: the dialog hands its
        work-in-progress here on every change, so the paper resizes and the
        header appears while the spin box is still being dragged. None puts
        the page's own setup back — which is all Cancel has to do.
        """
        self._setup_override = setup
        self.refresh_preview()

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
        as fuzzy on paper. It also drops the preview's page-break rules: on
        paper the break is the break, and a line drawn at the bottom of the
        previous page would be a leftover from a preview trick.
        """
        page = self._page()
        return render_report(page.body if page else "", self._graph,
                             self._engine.cache,
                             image_scale=2.0 if for_print else 1.0,
                             setup=page.setup if page else None,
                             page_break_rule=not for_print)

    def show_help(self) -> None:
        """The report reference. Kept on the page rather than the window so
        it opens beside the report it is about, and reused rather than
        re-created so clicking "?" twice raises the one that is open."""
        from .help import ReportHelpDialog
        if getattr(self, "_help_dialog", None) is None:
            self._help_dialog = ReportHelpDialog(self)
        self._help_dialog.show()
        self._help_dialog.raise_()
        self._help_dialog.activateWindow()

    def page_setup(self):
        """The page's geometry — what the window hands to export_pdf."""
        page = self._page()
        from flograph.core.page_setup import PageSetup
        return page.setup if page is not None else PageSetup()
