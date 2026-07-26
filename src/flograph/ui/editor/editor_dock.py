"""The per-node code editing panel: explicit Apply (Ctrl+Enter), fork badge,
reset-to-library, and error markers fed by the engine."""
from __future__ import annotations

import re
from typing import Optional

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QFontMetrics, QKeySequence, QShortcut, QUndoStack
from PySide6.QtWidgets import (
    QApplication, QHBoxLayout, QInputDialog, QLabel, QPushButton, QVBoxLayout,
    QWidget,
)

from flograph.core import Graph, NodeRegistry, NodeScriptError, parse_spec
from flograph.engine import NodeError

from ..ai_settings_dialog import load_llm_config
from ..commands import ResetCodeCommand, SetCodeCommand
from .ai_worker import AiAssistantController
from .code_editor import CodeEditor
from .completion import CompletionController
from .find_bar import FindBar

_SYNTAX_LINE = re.compile(r"syntax error on line (\d+)")

# The header title shows "<label> — <type_id>", and type_id can run long
# (e.g. "flograph.scripting.python_script"). It's elided to fit whatever
# width the title label actually has (recomputed on resize, see
# resizeEvent()) rather than a fixed cap, so it uses all the room the header
# gives it; the full text is always available as a tooltip. Used only
# before the label has ever been laid out (width() == 0).
_TITLE_FALLBACK_WIDTH = 220


class _ClickableLabel(QLabel):
    """A QLabel that reports clicks — the error line under the editor, so a
    traceback can be lifted out with one click instead of being retyped."""

    clicked = Signal()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.LeftButton and self.rect().contains(event.pos()):
            self.clicked.emit()
        super().mouseReleaseEvent(event)


class EditorPanel(QWidget):
    # emitted when the user asks to save the bound node as a library user node;
    # MainWindow owns the dialog + filesystem + registry reload
    save_as_user_node_requested = Signal(str)  # node_id

    def __init__(self, graph: Graph, undo_stack: QUndoStack,
                 registry: NodeRegistry, parent=None) -> None:
        super().__init__(parent)
        self._graph = graph
        self._undo_stack = undo_stack
        self._registry = registry
        self._node_id: Optional[str] = None
        self._loading = False
        # Cache unsaved edits keyed by node_id so switching away and back restores them.
        self._temp_edits: dict[str, str] = {}

        self._full_title = "No node selected"
        self._title = QLabel(self._full_title)
        self._title.setStyleSheet("font-weight: bold;")
        self._badge = QLabel("modified from library")
        self._badge.setStyleSheet("color: #eab308;")
        self._badge.hide()
        self._reset_btn = QPushButton("Reset to library")
        self._reset_btn.hide()
        self._reset_btn.clicked.connect(self._reset_to_library)
        self._save_user_btn = QPushButton("Save as user node…")
        self._save_user_btn.setToolTip(
            "Save this node's current code to your library as a reusable node")
        self._save_user_btn.hide()
        self._save_user_btn.clicked.connect(self._save_as_user_node)
        self._ask_ai_btn = QPushButton("Ask AI…")
        self._ask_ai_btn.setToolTip(
            "Describe a change in plain English (e.g. \"format the date "
            "column as YYYY-MM-DD\") and a local LLM will rewrite this "
            "node's code for you to review — nothing is applied "
            "automatically.")
        self._ask_ai_btn.hide()
        self._ask_ai_btn.clicked.connect(self._ask_ai)

        header = QHBoxLayout()
        header.addWidget(self._title, 1)
        header.addWidget(self._badge)

        self.editor = CodeEditor(self)
        self.editor.setEnabled(False)
        self.completion = CompletionController(self.editor)
        self.find_bar = FindBar(self.editor, self)

        self._ai_request_id = 0
        self.ai = AiAssistantController(self.editor)
        self.ai.succeeded.connect(self._on_ai_succeeded)
        self.ai.failed.connect(self._on_ai_failed)

        self._message = _ClickableLabel("")
        self._message.setWordWrap(True)
        self._message.clicked.connect(self._copy_message)
        # what a click puts on the clipboard: the full traceback when the
        # engine gave us one, so the copy is worth more than the one line
        # that fits in the footer. "" = nothing worth copying.
        self._copy_text = ""
        self._restore_message: Optional[tuple[str, bool]] = None
        self._apply_btn = QPushButton("Apply  (Ctrl+Enter)")
        self._apply_btn.setEnabled(False)
        self._apply_btn.clicked.connect(self.apply_code)

        # Unsaved indicator — amber dot shown when temp edits differ from graph.
        self._unsaved_indicator = QLabel("●")
        self._unsaved_indicator.setStyleSheet(
            "color: #eab308; font-size: 14px; font-weight: bold;")
        self._unsaved_indicator.hide()

        footer = QHBoxLayout()
        footer.addWidget(self._message, 1)
        footer.addWidget(self._unsaved_indicator)
        footer.addWidget(self._ask_ai_btn)
        footer.addWidget(self._save_user_btn)
        footer.addWidget(self._reset_btn)
        footer.addWidget(self._apply_btn)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.addLayout(header)
        layout.addWidget(self.editor, 1)
        layout.addWidget(self.find_bar)
        layout.addLayout(footer)

        QShortcut(QKeySequence("Ctrl+Return"), self.editor, self.apply_code)
        # WidgetWithChildren, so Ctrl+F in the canvas or a table doesn't get
        # swallowed by a code panel that merely happens to be open
        for keys, slot in (
                ("Ctrl+F", lambda: self.find_bar.open_bar()),
                ("Ctrl+H", lambda: self.find_bar.open_bar(replace=True)),
                ("F3", lambda: self._find_again()),
                ("Shift+F3", lambda: self._find_again(backwards=True))):
            shortcut = QShortcut(QKeySequence(keys), self, slot)
            shortcut.setContext(Qt.WidgetWithChildrenShortcut)

        graph.events.code_changed.connect(self._on_code_changed)
        graph.events.label_changed.connect(self._refresh_header)
        graph.events.node_removed.connect(self._on_node_removed)

    def _find_again(self, backwards: bool = False) -> None:
        """F3 with the bar shut opens it rather than searching invisibly —
        highlighting matches nobody asked to see, with no ✕ to clear them."""
        if self.find_bar.isHidden():
            self.find_bar.open_bar()
        else:
            self.find_bar.find_next(backwards=backwards)

    def minimumSizeHint(self) -> QSize:
        return QSize(200, 100)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._update_title()

    def _update_title(self) -> None:
        width = self._title.width() or _TITLE_FALLBACK_WIDTH
        metrics = QFontMetrics(self._title.font())
        self._title.setText(
            metrics.elidedText(self._full_title, Qt.ElideRight, width))
        self._title.setToolTip(self._full_title)

    # -------------------------------------------------------------- binding

    def set_node(self, node_id: Optional[str]) -> None:
        # Before switching away from the current node, save any unsaved edits.
        # The node may already be gone (e.g. deletion triggered this switch).
        prev_node = self._graph.nodes.get(self._node_id)
        if prev_node is not None and self.editor.toPlainText():
            current = self.editor.toPlainText()
            graph_source = prev_node.source
            if current != graph_source:
                # Node has temp edits — mark it for canvas indicator.
                prev_node._temp_edit = True
                self._graph.events.temp_edit_changed.emit(
                    self._node_id, True)
            self._temp_edits[self._node_id] = current

        self._node_id = node_id
        self.editor.set_error_line(None)
        # highlights point into the document we're about to replace
        if not self.find_bar.isHidden():
            self.find_bar.close_bar()
        self._show_message("")
        if node_id is None:
            self.editor.setPlainText("")
            self.editor.setEnabled(False)
            self._apply_btn.setEnabled(False)
            self._unsaved_indicator.hide()
            self._full_title = "No node selected"
            self._update_title()
            self._badge.hide()
            self._reset_btn.hide()
            self._save_user_btn.hide()
            self._ask_ai_btn.hide()
            return

        # Check if we have cached temp edits for this node.
        cached = self._temp_edits.get(node_id)
        if cached is not None:
            source_to_load = cached
        else:
            # No cached edits - load from the actual node source.
            node = self._graph.node(node_id)
            source_to_load = node.source

        self._loading = True
        self.editor.setPlainText(source_to_load or "")
        self._loading = False
        self.editor.setEnabled(True)
        self._apply_btn.setEnabled(True)
        # Show unsaved indicator if the cached edit differs from graph.
        if source_to_load != self._graph.node(node_id).source:
            self._unsaved_indicator.show()
            self._graph.node(node_id)._temp_edit = True
            self._graph.events.temp_edit_changed.emit(node_id, True)
        else:
            self._unsaved_indicator.hide()
            if self._graph.node(node_id)._temp_edit:
                self._graph.node(node_id)._temp_edit = False
                self._graph.events.temp_edit_changed.emit(node_id, False)
        self._refresh_header(node_id)

    def _refresh_header(self, node_id: str) -> None:
        if node_id != self._node_id or self._node_id is None:
            return
        node = self._graph.node(node_id)
        self._full_title = f"{node.label}  —  {node.type_id}"
        self._update_title()
        library = self._registry.maybe_get(node.type_id)
        self._badge.setVisible(node.forked)
        self._reset_btn.setVisible(node.forked and library is not None
                                   and library.builtin)
        # any bound node's current code can be promoted to a user library node
        self._save_user_btn.setVisible(not node.spec.broken)
        self._ask_ai_btn.setVisible(True)

    # --------------------------------------------------------------- apply

    def apply_code(self) -> None:
        if self._node_id is None:
            return
        node = self._graph.node(self._node_id)
        source = self.editor.toPlainText()
        if source == node.source and not node.spec.broken:
            self._show_message("No changes to apply.")
            return
        # ...a broken node is the exception: its code never loaded, so
        # re-applying it unchanged is exactly the retry you want after
        # installing the package it was missing
        try:
            parse_spec(source, node.type_id)
        except NodeScriptError as exc:
            self._show_message(str(exc), error=True)
            match = _SYNTAX_LINE.search(str(exc))
            self.editor.set_error_line(int(match.group(1)) if match else None)
            return
        self.editor.set_error_line(None)
        self._undo_stack.push(SetCodeCommand(self._graph, self._node_id, source))
        self._show_message("Applied.")

    def _save_as_user_node(self) -> None:
        if self._node_id is not None:
            self.save_as_user_node_requested.emit(self._node_id)

    def _reset_to_library(self) -> None:
        if self._node_id is None:
            return
        node = self._graph.node(self._node_id)
        library = self._registry.maybe_get(node.type_id)
        if library is not None:
            self._undo_stack.push(
                ResetCodeCommand(self._graph, self._node_id, library))

    # ------------------------------------------------------------------ ai

    def _ask_ai(self) -> None:
        if self._node_id is None:
            return
        instruction, ok = QInputDialog.getMultiLineText(
            self, "Ask AI",
            "Describe the change, e.g. \"format the date column as "
            "YYYY-MM-DD\" or \"filter out rows where price is negative\":")
        if not ok or not instruction.strip():
            return
        node = self._graph.node(self._node_id)
        self._ai_request_id += 1
        self._ask_ai_btn.setEnabled(False)
        self._show_message("Asking the local LLM…")
        self.ai.request_suggestion(
            self._ai_request_id, self.editor.toPlainText(),
            instruction, node.type_id, load_llm_config())

    def _on_ai_succeeded(self, request_id: int, code: str) -> None:
        self._ask_ai_btn.setEnabled(True)
        if request_id != self._ai_request_id or self._node_id is None:
            return  # stale reply, or the user switched nodes meanwhile
        # Populate the editor as if the user had typed it themselves — this
        # is a suggestion for review, never applied automatically. The user
        # still has to read it and press Apply.
        self.editor.setPlainText(code)
        if code != self._graph.node(self._node_id).source:
            self._unsaved_indicator.show()
        self._show_message(
            "AI suggestion loaded — review the code, then Apply.")

    def _on_ai_failed(self, request_id: int, message: str) -> None:
        self._ask_ai_btn.setEnabled(True)
        if request_id != self._ai_request_id:
            return
        self._show_message(message, error=True)

    # -------------------------------------------------------------- events

    def _on_code_changed(self, node_id: str) -> None:
        """Graph-side code change (apply, undo/redo, reset) — reload text."""
        if node_id != self._node_id or self._loading:
            return
        # Clear cached temp edit since the graph now owns this version.
        self._temp_edits.pop(node_id, None)
        self._graph.node(node_id)._temp_edit = False
        self._unsaved_indicator.hide()
        node = self._graph.node(node_id)
        if self.editor.toPlainText() != node.source:
            self._loading = True
            self.editor.setPlainText(node.source)
            self._loading = False
        self.editor.set_error_line(None)
        self._refresh_header(node_id)

    def _on_node_removed(self, node_id: str) -> None:
        if node_id == self._node_id:
            self.set_node(None)

    def on_node_failed(self, node_id: str, error: NodeError) -> None:
        if node_id != self._node_id:
            return
        self.editor.set_error_line(error.script_line)
        self._show_message(error.message, error=True,
                           copy_text=error.formatted_tb or error.message)

    def on_node_succeeded(self, node_id: str) -> None:
        if node_id == self._node_id:
            self.editor.set_error_line(None)
            self._show_message("")

    def _show_message(self, text: str, error: bool = False,
                      copy_text: Optional[str] = None) -> None:
        self._restore_message = None
        self._message.setText(text)
        # errors are the thing worth lifting out; "Applied." is not
        self._copy_text = copy_text if copy_text is not None \
            else (text if error else "")
        # the tooltip carries the full traceback the one-line label elides
        self._message.setToolTip(f"{self._copy_text}\n\n(click to copy)"
                                 if self._copy_text else "")
        self._message.setCursor(Qt.PointingHandCursor if self._copy_text
                                else Qt.ArrowCursor)
        self._message.setStyleSheet(
            "color: #ef4444;" if error else "color: #9ca3af;")

    def _copy_message(self) -> None:
        """Put the current error on the clipboard, confirming in the label
        itself and putting the error back a moment later — a status bar
        message would be nowhere near where the click happened."""
        if not self._copy_text:
            return
        QApplication.clipboard().setText(self._copy_text)
        if self._restore_message is None:
            self._restore_message = (self._message.text(),
                                     "#ef4444" in self._message.styleSheet())
        self._message.setText("Copied to clipboard.")
        QTimer.singleShot(1200, self._restore_after_copy)

    def _restore_after_copy(self) -> None:
        if self._restore_message is None:
            return  # a new message landed meanwhile; leave it alone
        text, error = self._restore_message
        copy_text = self._copy_text
        self._show_message(text, error=error, copy_text=copy_text)
