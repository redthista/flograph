"""The per-node code editing panel: explicit Apply (Ctrl+Enter), fork badge,
reset-to-library, and error markers fed by the engine."""
from __future__ import annotations

import re
from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut, QUndoStack
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget,
)

from flograph.core import Graph, NodeRegistry, NodeScriptError, parse_spec
from flograph.engine import NodeError

from ..commands import ResetCodeCommand, SetCodeCommand
from .code_editor import CodeEditor
from .completion import CompletionController

_SYNTAX_LINE = re.compile(r"syntax error on line (\d+)")


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

        self._title = QLabel("No node selected")
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

        header = QHBoxLayout()
        header.addWidget(self._title)
        header.addWidget(self._badge)
        header.addStretch(1)
        header.addWidget(self._save_user_btn)
        header.addWidget(self._reset_btn)

        self.editor = CodeEditor(self)
        self.editor.setEnabled(False)
        self.completion = CompletionController(self.editor)

        self._message = QLabel("")
        self._message.setWordWrap(True)
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
        footer.addWidget(self._apply_btn)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.addLayout(header)
        layout.addWidget(self.editor, 1)
        layout.addLayout(footer)

        QShortcut(QKeySequence("Ctrl+Return"), self.editor, self.apply_code)

        graph.events.code_changed.connect(self._on_code_changed)
        graph.events.label_changed.connect(self._refresh_header)
        graph.events.node_removed.connect(self._on_node_removed)

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
        self._show_message("")
        if node_id is None:
            self.editor.setPlainText("")
            self.editor.setEnabled(False)
            self._apply_btn.setEnabled(False)
            self._unsaved_indicator.hide()
            self._title.setText("No node selected")
            self._badge.hide()
            self._reset_btn.hide()
            self._save_user_btn.hide()
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
        self._title.setText(f"{node.label}  —  {node.type_id}")
        library = self._registry.maybe_get(node.type_id)
        self._badge.setVisible(node.forked)
        self._reset_btn.setVisible(node.forked and library is not None
                                   and library.builtin)
        # any bound node's current code can be promoted to a user library node
        self._save_user_btn.setVisible(not node.spec.broken)

    # --------------------------------------------------------------- apply

    def apply_code(self) -> None:
        if self._node_id is None:
            return
        node = self._graph.node(self._node_id)
        source = self.editor.toPlainText()
        if source == node.source:
            self._show_message("No changes to apply.")
            return
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
        self._show_message(error.message, error=True)
        if error.formatted_tb:
            self._message.setToolTip(error.formatted_tb)

    def on_node_succeeded(self, node_id: str) -> None:
        if node_id == self._node_id:
            self.editor.set_error_line(None)
            self._show_message("")

    def _show_message(self, text: str, error: bool = False) -> None:
        self._message.setText(text)
        self._message.setToolTip("")
        self._message.setStyleSheet(
            "color: #ef4444;" if error else "color: #9ca3af;")
