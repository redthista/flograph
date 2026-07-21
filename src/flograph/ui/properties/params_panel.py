"""Properties panel: an auto-generated form from a node's ParamSpecs.

Every ParamSpec type maps to exactly one widget; edits push SetParamCommand
(mergeable while typing), and graph events flow back into the widgets so
undo/redo keeps the form in sync. 'columns' params get a picker fed by the
cached output of connected upstream nodes (see flograph.engine.introspect).
"""
from __future__ import annotations

from typing import Any, Callable, Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QUndoStack
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout, QHBoxLayout,
    QLabel, QLineEdit, QMenu, QPlainTextEdit, QScrollArea, QSpinBox,
    QToolButton, QVBoxLayout, QWidget,
)

from flograph.core import Graph, ParamSpec

from ..commands import SetLabelCommand, SetParamCommand


class ParamsPanel(QScrollArea):
    def __init__(self, graph: Graph, undo_stack: QUndoStack, parent=None,
                 cache=None) -> None:
        super().__init__(parent)
        self._graph = graph
        self._undo_stack = undo_stack
        self._cache = cache  # engine's OutputCache; enables column pickers
        self._node_id: Optional[str] = None
        self._setters: dict[str, Callable[[Any], None]] = {}
        self._updating = False

        self.setWidgetResizable(True)
        self._body = QWidget()
        self.setWidget(self._body)
        self._layout = QVBoxLayout(self._body)
        self._layout.setAlignment(Qt.AlignTop)
        self._placeholder = QLabel("No node selected")
        self._placeholder.setStyleSheet("color: #6b7280;")
        self._layout.addWidget(self._placeholder)

        graph.events.param_changed.connect(self._on_param_changed)
        graph.events.code_changed.connect(self._on_code_changed)
        graph.events.node_removed.connect(self._on_node_removed)

    # -------------------------------------------------------------- binding

    def set_node(self, node_id: Optional[str]) -> None:
        self._node_id = node_id
        self._rebuild()

    def _clear(self) -> None:
        while self._layout.count():
            item = self._layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                # hide immediately -- taking it out of the layout alone
                # doesn't stop it painting, and two rebuilds can happen back
                # to back (e.g. clearSelection() + setSelected(True)) before
                # deleteLater() actually runs, leaving stale widgets visible
                # on top of the new form
                widget.hide()
                widget.deleteLater()
        self._setters = {}

    def _rebuild(self) -> None:
        self._clear()
        if self._node_id is None or self._node_id not in self._graph.nodes:
            placeholder = QLabel("No node selected")
            placeholder.setStyleSheet("color: #6b7280;")
            self._layout.addWidget(placeholder)
            return
        node = self._graph.node(self._node_id)

        if node.spec.doc:
            doc = QLabel(node.spec.doc.split("\n\n")[0])
            doc.setWordWrap(True)
            doc.setStyleSheet("color: #9ca3af; font-size: 8pt;")
            self._layout.addWidget(doc)

        form_host = QWidget()
        form = QFormLayout(form_host)
        form.setLabelAlignment(Qt.AlignRight)
        self._layout.addWidget(form_host)

        label_edit = QLineEdit(node.label_override or "")
        label_edit.setPlaceholderText(node.spec.label)
        label_edit.editingFinished.connect(
            lambda: self._commit_label(label_edit.text()))
        form.addRow("Name", label_edit)

        for spec in node.spec.params:
            widget, setter = self._make_widget(spec, node.params.get(spec.name))
            self._setters[spec.name] = setter
            form.addRow(spec.label or spec.name, widget)

    # -------------------------------------------------------------- widgets

    def _make_widget(self, spec: ParamSpec, value: Any):
        name = spec.name
        if spec.type == "bool":
            box = QCheckBox()
            box.setChecked(bool(value))
            box.toggled.connect(lambda v: self._commit(name, bool(v)))
            return box, lambda v: self._silently(box.setChecked, bool(v))

        if spec.type == "int":
            spin = QSpinBox()
            spin.setRange(int(spec.minimum) if spec.minimum is not None else -2**31,
                          int(spec.maximum) if spec.maximum is not None else 2**31 - 1)
            spin.setValue(int(value or 0))
            spin.valueChanged.connect(lambda v: self._commit(name, int(v)))
            return spin, lambda v: self._silently(spin.setValue, int(v or 0))

        if spec.type == "float":
            spin = QDoubleSpinBox()
            spin.setDecimals(6)
            spin.setRange(spec.minimum if spec.minimum is not None else -1e18,
                          spec.maximum if spec.maximum is not None else 1e18)
            spin.setValue(float(value or 0.0))
            spin.valueChanged.connect(lambda v: self._commit(name, float(v)))
            return spin, lambda v: self._silently(spin.setValue, float(v or 0.0))

        if spec.type == "choice":
            combo = QComboBox()
            combo.addItems([str(o) for o in spec.options])
            if value is not None and str(value) in spec.options:
                combo.setCurrentText(str(value))
            combo.currentTextChanged.connect(lambda v: self._commit(name, v))
            return combo, lambda v: self._silently(combo.setCurrentText, str(v))

        if spec.type == "text":
            text = QPlainTextEdit(str(value or ""))
            text.setMaximumHeight(90)
            text.textChanged.connect(
                lambda: self._commit(name, text.toPlainText()))

            def set_text(v, text=text):
                # echoing the user's own keystroke back through setPlainText
                # would reset the cursor to the start — only sync real changes
                if text.toPlainText() != str(v or ""):
                    self._silently(text.setPlainText, str(v or ""))
            return text, set_text

        if spec.type in ("file_open", "file_save"):
            host = QWidget()
            row = QHBoxLayout(host)
            row.setContentsMargins(0, 0, 0, 0)
            edit = QLineEdit(str(value or ""))
            browse = QToolButton()
            browse.setText("…")

            def pick() -> None:
                if spec.type == "file_open":
                    path, _ = QFileDialog.getOpenFileName(self, spec.label or name)
                else:
                    path, _ = QFileDialog.getSaveFileName(self, spec.label or name)
                if path:
                    edit.setText(path)
                    self._commit(name, path)

            browse.clicked.connect(pick)
            edit.editingFinished.connect(lambda: self._commit(name, edit.text()))
            row.addWidget(edit, 1)
            row.addWidget(browse)
            return host, self._line_setter(edit)

        if spec.type == "password":
            host = QWidget()
            row = QHBoxLayout(host)
            row.setContentsMargins(0, 0, 0, 0)
            edit = QLineEdit(str(value or ""))
            edit.setObjectName(f"param_{name}")
            edit.setEchoMode(QLineEdit.Password)
            if spec.placeholder:
                edit.setPlaceholderText(spec.placeholder)
            edit.textEdited.connect(lambda v: self._commit(name, v))
            reveal = QToolButton()
            reveal.setObjectName(f"param_{name}_reveal")
            reveal.setText("Show")
            reveal.setCheckable(True)
            reveal.toggled.connect(lambda checked, edit=edit, reveal=reveal:
                                    self._toggle_password_reveal(edit, reveal, checked))
            row.addWidget(edit, 1)
            row.addWidget(reveal)
            return host, self._line_setter(edit)

        if spec.type == "columns":
            return self._make_columns_widget(spec, value)

        # string / anything else -> line edit
        edit = QLineEdit(str(value or ""))
        if spec.placeholder:
            edit.setPlaceholderText(spec.placeholder)
        edit.textEdited.connect(lambda v: self._commit(name, v))
        return edit, self._line_setter(edit)

    def _make_columns_widget(self, spec: ParamSpec, value: Any):
        """Line edit plus a picker button listing the columns of whatever
        cached DataFrames feed this node. Free text still works — the picker
        only fills once upstream has run."""
        name = spec.name
        host = QWidget()
        row = QHBoxLayout(host)
        row.setContentsMargins(0, 0, 0, 0)
        edit = QLineEdit(str(value or ""))
        if spec.placeholder:
            edit.setPlaceholderText(spec.placeholder)
        edit.textEdited.connect(lambda v: self._commit(name, v))

        pick = QToolButton()
        pick.setText("▾")
        pick.setToolTip("Pick from upstream columns (needs an upstream run)")
        pick.setPopupMode(QToolButton.InstantPopup)
        menu = QMenu(pick)
        pick.setMenu(menu)
        # built on demand: always reflects the cache at click time, so no
        # refresh wiring is needed when upstream re-runs
        menu.aboutToShow.connect(
            lambda: self._fill_columns_menu(menu, edit, spec))
        row.addWidget(edit, 1)
        row.addWidget(pick)
        return host, self._line_setter(edit)

    def _fill_columns_menu(self, menu: QMenu, edit: QLineEdit,
                           spec: ParamSpec) -> None:
        from flograph.engine import upstream_columns
        menu.clear()
        columns = (upstream_columns(self._graph, self._cache, self._node_id)
                   if self._cache is not None and self._node_id else [])
        if not columns:
            action = menu.addAction("run upstream nodes to list columns")
            action.setEnabled(False)
            return
        chosen = [c.strip() for c in edit.text().split(",") if c.strip()]
        for column in columns:
            action = menu.addAction(column)
            if spec.multi:
                action.setCheckable(True)
                action.setChecked(column in chosen)
            action.triggered.connect(
                lambda _checked=False, c=column:
                self._pick_column(edit, spec, c))

    def _pick_column(self, edit: QLineEdit, spec: ParamSpec, column: str) -> None:
        if spec.multi:
            chosen = [c.strip() for c in edit.text().split(",") if c.strip()]
            if column in chosen:
                chosen.remove(column)
            else:
                chosen.append(column)
            text = ", ".join(chosen)
        else:
            text = column
        edit.setText(text)
        self._commit(spec.name, text)

    @staticmethod
    def _toggle_password_reveal(edit: QLineEdit, reveal: QToolButton,
                                checked: bool) -> None:
        edit.setEchoMode(QLineEdit.Normal if checked else QLineEdit.Password)
        reveal.setText("Hide" if checked else "Show")

    def _line_setter(self, edit: QLineEdit) -> Callable[[Any], None]:
        def set_line(v):
            # skip no-op echoes so the cursor stays where the user left it
            if edit.text() != str(v or ""):
                self._silently(edit.setText, str(v or ""))
        return set_line

    # --------------------------------------------------------------- commit

    def _commit(self, name: str, value: Any) -> None:
        if self._updating or self._node_id is None:
            return
        node = self._graph.node(self._node_id)
        if node.params.get(name) == value:
            return
        self._undo_stack.push(
            SetParamCommand(self._graph, self._node_id, name, value))

    def _commit_label(self, text: str) -> None:
        if self._node_id is None:
            return
        node = self._graph.node(self._node_id)
        new = text.strip() or None
        if new != node.label_override:
            self._undo_stack.push(SetLabelCommand(self._graph, self._node_id, new))

    def _silently(self, setter: Callable, value: Any) -> None:
        self._updating = True
        try:
            setter(value)
        finally:
            self._updating = False

    # --------------------------------------------------------------- events

    def _on_param_changed(self, node_id: str, name: str, value: Any) -> None:
        if node_id == self._node_id and name in self._setters:
            self._setters[name](value)

    def _on_code_changed(self, node_id: str) -> None:
        if node_id == self._node_id:
            self._rebuild()  # params may have changed shape

    def _on_node_removed(self, node_id: str) -> None:
        if node_id == self._node_id:
            self.set_node(None)
