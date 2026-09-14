"""Properties panel: a resizable property/value table built from a node's
ParamSpecs.

Every ParamSpec type maps to exactly one widget, embedded in the value
column of a two-column QTreeWidget; edits push SetParamCommand (mergeable
while typing), and graph events flow back into the widgets so undo/redo
keeps the table in sync. The property column is user-resizable (drag the
header divider) so a node with long labels doesn't force the whole panel
wider -- unlike a plain form layout, the column split is the user's choice,
not something the widest label dictates. 'columns' params get a picker fed
by the cached output of connected upstream nodes (see
flograph.engine.introspect).
"""
from __future__ import annotations

from typing import Any, Callable, Optional

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QTextCursor, QUndoStack
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QMenu, QPlainTextEdit, QPushButton,
    QSpinBox, QToolButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from flograph.core import Graph, ParamSpec, varlinks
from flograph.core.params import controllers

from . import var_completion
from .colour_row import ColourRow
from ..canvas.node_item import card_kind
from ..controls import UNCAPPED_TEXT
from ..commands import SetDescriptionCommand, SetLabelCommand, SetParamCommand

# How long typing has to pause before a text param reaches the graph. Long
# enough that a normal typing rate never commits mid-word, short enough that
# it feels immediate on release. A run flushes it regardless, so this delays
# nothing the user then asks for.
TYPING_IDLE_MS = 200


class _NodeRefCombo(QComboBox):
    """Combo whose items are rebuilt each time it opens — the set of nodes it
    can point at changes while the panel stays put."""

    def __init__(self, refresh: Callable[[], None], parent=None) -> None:
        super().__init__(parent)
        self._refresh = refresh

    def showPopup(self) -> None:
        self._refresh()
        super().showPopup()


# Marks the actions in a column picker that should leave the menu showing
# when they fire, rather than closing it the way a normal menu entry does.
_STAYS_OPEN = "flograph_stays_open"


def _mapping_key(line: str) -> str:
    """Which column a `column = value` line is about — what a tick in a
    mapping picker stands for.

    Blank lines and comments key to nothing, so they match no column and
    are carried through every edit untouched. A line still being typed
    (`revenue = `, or just `revenue`) keys the same as a finished one, so
    the tick is right the moment it is made rather than once the value
    arrives."""
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return ""
    return stripped.partition("=")[0].strip()


class _ColumnTextEdit(QPlainTextEdit):
    """Multiline editor that knows whether its caret is the user's.

    A freshly built editor has its caret at position 0, and that is a real
    position — indistinguishable from one somebody chose. So "insert at the
    cursor" put the name *in front of everything already written* until the
    box had been clicked into, which reads as the picker being broken. Once
    the box has been focused the caret means something and is honoured.
    """

    def __init__(self, text: str = "", parent=None) -> None:
        super().__init__(text, parent)
        self.caret_placed = False

    def focusInEvent(self, event) -> None:
        self.caret_placed = True
        super().focusInEvent(event)


class _ColumnsMenu(QMenu):
    """Column picker menu that stays up while columns are ticked.

    A plain QMenu closes on every pick, so choosing six columns out of a
    multi-select param meant opening the menu six times. Actions carrying
    the `_STAYS_OPEN` property fire in place and leave the menu showing;
    everything else (a disabled placeholder, a single-select column) keeps
    the ordinary close-on-choose behaviour, because there the pick is the
    whole interaction.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        # Was there a press *inside* the menu that this release completes?
        # A tall menu (a wide table has many columns) gets nudged by Qt so it
        # fits on screen, which can drop an item right under the cursor. The
        # button-release that ends the click that opened the menu then lands
        # on that item. Qt's own QMenu guards this by only acting on a release
        # whose press it also saw; our override has to do the same or the
        # first click ticks a column instead of just opening the list.
        self._press_seen = False

    def showEvent(self, event) -> None:
        self._press_seen = False
        super().showEvent(event)

    def mousePressEvent(self, event) -> None:
        self._press_seen = True
        super().mousePressEvent(event)

    @staticmethod
    def _stays_open(action) -> bool:
        return (action is not None and action.isEnabled()
                and bool(action.property(_STAYS_OPEN)))

    def mouseReleaseEvent(self, event) -> None:
        press_seen, self._press_seen = self._press_seen, False
        if press_seen:
            action = self.actionAt(event.position().toPoint())
            if self._stays_open(action):
                action.trigger()
                event.accept()
                return
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event) -> None:
        # keyboard users get the same deal: Space/Enter ticks without
        # dismissing, so a menu walked with the arrow keys behaves like one
        # clicked through
        if event.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
            action = self.activeAction()
            if self._stays_open(action):
                action.trigger()
                event.accept()
                return
        super().keyPressEvent(event)


class ParamsPanel(QWidget):
    def __init__(self, graph: Graph, undo_stack: QUndoStack, parent=None,
                 cache=None) -> None:
        super().__init__(parent)
        self._graph = graph
        self._undo_stack = undo_stack
        self._cache = cache  # engine's OutputCache; enables column pickers
        self._node_id: Optional[str] = None
        self._setters: dict[str, Callable[[Any], None]] = {}
        self._updating = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        self._doc_label = QLabel()
        self._doc_label.setWordWrap(True)
        self._doc_label.setStyleSheet("color: palette(mid); font-size: 8pt;")
        self._doc_label.hide()
        layout.addWidget(self._doc_label)

        # Which *edition* of the node type this is -- see NodeSpec.version.
        # Dimmer than the doc and below it: you only look for it when you are
        # asking "have I got the new one?", and it should not compete the
        # rest of the time.
        self._version_label = QLabel()
        self._version_label.setStyleSheet("color: palette(mid); font-size: 8pt;")
        self._version_label.hide()
        layout.addWidget(self._version_label)

        self._placeholder = QLabel("No node selected")
        self._placeholder.setStyleSheet("color: palette(mid);")
        layout.addWidget(self._placeholder)

        self._locked_label = QLabel(
            "\N{LOCK} Locked — right-click the node and choose Unlock to edit.")
        self._locked_label.setWordWrap(True)
        self._locked_label.setStyleSheet("color: palette(mid); font-size: 8pt;")
        self._locked_label.hide()
        layout.addWidget(self._locked_label)

        self.tree = QTreeWidget()
        self.tree.setColumnCount(2)
        self.tree.setHeaderLabels(["Property", "Value"])
        self.tree.setRootIsDecorated(False)
        self.tree.setAlternatingRowColors(True)
        self.tree.header().setSectionResizeMode(QHeaderView.Interactive)
        self.tree.header().setStretchLastSection(True)
        self.tree.setColumnWidth(0, 140)
        self.tree.hide()
        layout.addWidget(self.tree, 1)

        # Typed params land here first and reach the graph once typing
        # pauses — see _commit_typed. One timer for the panel, not one per
        # widget: only one field can have the keyboard at a time.
        self._pending: dict[str, Any] = {}
        self._typing = QTimer(self)
        self._typing.setSingleShot(True)
        self._typing.setInterval(TYPING_IDLE_MS)
        self._typing.timeout.connect(self.flush_pending)

        graph.events.param_changed.connect(self._on_param_changed)
        graph.events.code_changed.connect(self._on_code_changed)
        graph.events.locked_changed.connect(self._on_locked_changed)
        graph.events.node_removed.connect(self._on_node_removed)

    def minimumSizeHint(self) -> QSize:
        # Rows are only as tall as the embedded widgets demand, and a node
        # with many params just grows the tree's scroll content -- but pin a
        # small floor regardless so the dock is never forced wider/taller
        # than the user left it.
        return QSize(200, 100)

    # -------------------------------------------------------------- binding

    def set_node(self, node_id: Optional[str]) -> None:
        # anything half-typed belongs to the node being left, so it has to
        # land before _node_id moves
        self.flush_pending()
        self._node_id = node_id
        self._rebuild()

    def _on_locked_changed(self, node_id: str, locked: bool) -> None:
        if node_id == self._node_id:
            self._apply_locked(locked)

    def _apply_locked(self, locked: bool) -> None:
        """Grey the whole grid rather than each widget in turn.

        Disabling the tree reaches every embedded editor at once, including
        the ones built by _make_widget for param types added later — a
        per-widget loop would silently miss those."""
        self.tree.setEnabled(not locked)
        self._locked_label.setVisible(locked)

    def _clear(self) -> None:
        self.tree.clear()
        self._setters = {}

    def _rebuild(self) -> None:
        self._clear()
        if self._node_id is None or self._node_id not in self._graph.nodes:
            self._doc_label.hide()
            self._version_label.hide()
            self._locked_label.hide()
            self._placeholder.show()
            self.tree.hide()
            return
        node = self._graph.node(self._node_id)
        self._placeholder.hide()
        self.tree.show()
        self._apply_locked(node.locked)

        if node.spec.doc:
            self._doc_label.setText(node.spec.doc.split("\n\n")[0])
            self._doc_label.show()
        else:
            self._doc_label.hide()

        if node.spec.version:
            self._version_label.setText(f"version {node.spec.version}")
            self._version_label.setToolTip(
                f"{node.spec.type_id} \N{EN DASH} version "
                f"{node.spec.version}. Declared by the node's own code as "
                f"NODE['version'], so it travels with the node.")
            self._version_label.show()
        else:
            self._version_label.hide()

        label_edit = QLineEdit(node.label_override or "")
        label_edit.setPlaceholderText(node.spec.label)
        label_edit.editingFinished.connect(
            lambda: self._commit_label(label_edit.text()))
        self._add_row("Name", label_edit)

        if card_kind(node) == "reroute":
            desc_edit = QPlainTextEdit(node.description)
            desc_edit.setMaximumHeight(60)
            desc_edit.setPlaceholderText("Shown as a tooltip when hovering the reroute")
            desc_edit.textChanged.connect(
                lambda: self._commit_description(desc_edit.toPlainText()))
            self._add_row("Description", desc_edit)

        for spec in node.spec.params:
            # hidden (edited elsewhere, e.g. the Table node's grid) or not
            # applicable to what the sibling params currently say
            if not spec.visible_for(node.params):
                continue
            value = node.params.get(spec.name)
            widget, setter = self._make_widget(spec, value)
            self._setters[spec.name] = setter
            item = self._add_row(spec.label or spec.name, widget)
            self._annotate_variables(item, node, spec, value)
            if varlinks.substitutable(node, spec):
                # Read through a callable, not a snapshot: the panel outlives
                # edits to the Variables node, and a stale list would offer
                # names that no longer exist.
                var_completion.attach(
                    widget, lambda: varlinks.completion_names(self._graph))

    def _annotate_variables(self, item: QTreeWidgetItem, node,
                            spec: ParamSpec, value: Any) -> None:
        """Mark a param that holds a ${name} and say what it resolves to.

        A reference is invisible otherwise — the box shows "${data_dir}/x.csv"
        and nothing says whether that name exists or what is in it. Hovering
        is the cheapest place to answer both.
        """
        if (not varlinks.substitutable(node, spec)
                or not isinstance(value, str) or varlinks.MARKER not in value):
            return
        lines = varlinks.describe(self._graph, node)
        if not lines:
            return
        tip = "Flow variables:\n" + "\n".join(lines)
        font = item.font(0)
        font.setItalic(True)
        item.setFont(0, font)
        item.setToolTip(0, tip)
        widget = self.tree.itemWidget(item, 1)
        if widget is not None:
            widget.setToolTip(tip)

    def _add_row(self, label: str, widget: QWidget) -> QTreeWidgetItem:
        item = QTreeWidgetItem([label, ""])
        item.setToolTip(0, label)
        self.tree.addTopLevelItem(item)
        self.tree.setItemWidget(item, 1, widget)
        # rows default to a single text line's height -- taller widgets
        # (the multiline "text" editor) would get clipped without this, but
        # respect any maximumHeight the widget set on itself (e.g. the "text"
        # editor caps at 90px; its sizeHint() alone would ask for ~190px).
        # QSize requires a non-negative width to count as valid, or the
        # whole hint (including the height we actually care about) is
        # silently discarded -- so pass the widget's own preferred width.
        height = max(24, min(widget.sizeHint().height(), widget.maximumHeight()))
        item.setSizeHint(1, QSize(widget.sizeHint().width(), height))
        return item

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
            # Carry the real value as item data so a sentinel option can be
            # shown under a friendlier label (spec.unset_label) without the
            # stored value changing.
            for option in spec.options:
                option = str(option)
                label = (spec.unset_label
                         if spec.unset_label and option == str(spec.default)
                         else option)
                combo.addItem(label, option)
            if value is not None and combo.findData(str(value)) >= 0:
                combo.setCurrentIndex(combo.findData(str(value)))
            combo.currentIndexChanged.connect(
                lambda _i, c=combo: self._commit(name, c.currentData()))
            return combo, lambda v: self._silently(
                combo.setCurrentIndex, combo.findData(str(v)))

        if spec.type == "text":
            text = _ColumnTextEdit(str(value or ""))
            text.setObjectName(f"param_{name}")
            text.setMaximumHeight(90)
            self._attach_assist(spec, text)
            if spec.placeholder:
                text.setPlaceholderText(spec.placeholder)
            text.textChanged.connect(
                lambda owner=self._node_id: self._commit_typed(
                    name, text.toPlainText(), owner))

            def set_text(v, text=text):
                # echoing the user's own keystroke back through setPlainText
                # would reset the cursor to the start — only sync real changes
                if text.toPlainText() != str(v or ""):
                    self._silently(text.setPlainText, str(v or ""))
            if spec.rule_wizard:
                widget = self._with_rule_wizard(spec, text)
            elif spec.insert_columns:
                widget = self._with_column_inserter(spec, text)
            else:
                widget = text
            return self._with_pop_out(spec, text, widget), set_text

        if spec.type in ("file_open", "file_save", "folder_open"):
            host = QWidget()
            row = QHBoxLayout(host)
            row.setContentsMargins(0, 0, 0, 0)
            edit = QLineEdit(str(value or ""))
            edit.setObjectName(f"param_{name}")
            # An Image node's "file" may be a whole base64-encoded picture,
            # which the default cap would silently cut to 32767 characters.
            edit.setMaxLength(UNCAPPED_TEXT)
            if spec.placeholder:
                edit.setPlaceholderText(spec.placeholder)
            browse = QToolButton()
            browse.setObjectName(f"param_{name}_browse")
            browse.setText("…")

            def pick() -> None:
                if spec.type == "file_open":
                    path, _ = QFileDialog.getOpenFileName(self, spec.label or name)
                elif spec.type == "folder_open":
                    # a folder param wants the directory itself, so the file
                    # dialog must not offer files that would never be valid
                    path = QFileDialog.getExistingDirectory(
                        self, spec.label or name, edit.text().strip())
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
            edit.textEdited.connect(
                lambda v, owner=self._node_id: self._commit_typed(
                    name, v, owner))
            # leaving the field (focus-out or Enter) is a settled
            # value — don't make it wait out the timer
            edit.editingFinished.connect(self.flush_pending)
            reveal = QToolButton()
            reveal.setObjectName(f"param_{name}_reveal")
            reveal.setText("Show")
            reveal.setCheckable(True)
            reveal.toggled.connect(lambda checked, edit=edit, reveal=reveal:
                                    self._toggle_password_reveal(edit, reveal, checked))
            row.addWidget(edit, 1)
            row.addWidget(reveal)
            return host, self._line_setter(edit)

        if spec.type == "color":
            # blank is a real value here, not an empty field: it means "use
            # the theme's own colour", which is what a node should do until
            # someone deliberately overrides it. spec.placeholder names that
            # state on the swatch ("Theme", "None") so the button says what
            # empty *means* rather than just looking unset.
            none_label = spec.placeholder or "Theme"
            row = ColourRow(lambda c: self._commit(name, c),
                            lambda: self._commit(name, ""),
                            clear_tip=f"Back to {none_label.lower()}")
            row.set_colour(str(value or ""), none_label=none_label)
            return row, lambda v: self._silently(
                lambda c: row.set_colour(str(c or ""), none_label=none_label),
                v)

        if spec.type == "date":
            return self._make_date_widget(spec, value)

        if spec.type == "columns":
            return self._make_columns_widget(spec, value)

        if spec.type == "node_ref":
            return self._make_node_ref_widget(spec, value)

        if spec.type == "page_ref":
            if spec.multi:
                return self._make_page_set_widget(spec, value)
            return self._make_page_ref_widget(spec, value)

        # string / anything else -> line edit
        edit = QLineEdit(str(value or ""))
        edit.setMaxLength(UNCAPPED_TEXT)  # never silently truncate a value
        if spec.placeholder:
            edit.setPlaceholderText(spec.placeholder)
        edit.textEdited.connect(
            lambda v, owner=self._node_id: self._commit_typed(name, v, owner))
        # leaving the field (focus-out or Enter) is a settled
        # value — don't make it wait out the timer
        edit.editingFinished.connect(self.flush_pending)
        return edit, self._line_setter(edit)

    def _with_rule_wizard(self, spec: ParamSpec,
                          text: QPlainTextEdit) -> QWidget:
        """A multiline rules box with a 'Rules…' button under it that opens
        the rule manager — a list of the applied rules with add / edit /
        remove — and writes the box back."""
        from flograph.ui.emoji_font import apply_emoji_font

        host = QWidget()
        col = QVBoxLayout(host)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(3)
        # rules carry typed glyphs (`breach=🔥`), and an emoji the UI font
        # cannot draw would leave the line looking like it lost a character
        apply_emoji_font(text)
        col.addWidget(text)
        button = QPushButton("Rules…")
        button.setObjectName(f"param_{spec.name}_wizard")
        button.clicked.connect(lambda: self._open_rule_wizard(spec, text))
        col.addWidget(button, 0, Qt.AlignLeft)
        return host

    def _wizard_columns(self) -> list:
        """Column names to offer the rule wizard: the table feeding this
        node, or — for a Table Style node with no input — the table feeding
        a Show Table it is wired into."""
        from flograph.engine import upstream_columns
        if self._cache is None or self._node_id is None:
            return []
        columns = upstream_columns(self._graph, self._cache, self._node_id)
        if columns:
            return columns
        for conn in self._graph.connections.values():
            if conn.src_node == self._node_id and conn.src_port == "style":
                columns = upstream_columns(
                    self._graph, self._cache, conn.dst_node)
                if columns:
                    return columns
        return []

    def _open_rule_wizard(self, spec: ParamSpec, text: QPlainTextEdit) -> None:
        from PySide6.QtWidgets import QDialog

        from .table_rule_wizard import RuleManager

        dlg = RuleManager(text.toPlainText(), self._wizard_columns(), self)
        if dlg.exec() == QDialog.Accepted:
            new_text = dlg.result_text()
            if new_text != text.toPlainText():
                text.setPlainText(new_text)
                self._commit(spec.name, new_text)

    def _with_column_inserter(self, spec: ParamSpec,
                              text: QPlainTextEdit) -> QWidget:
        """Put an upstream-column picker beside a multiline text box.

        The box holds free text — a rename mapping, a set of expressions —
        so the picker cannot own the value the way a 'columns' param's does.
        All it does is type the name in, which is the part that was sending
        people back to a table view to copy from. Where it lands is the
        param's own choice (spec.insert_columns), because a line means
        different things in the two boxes that want this."""
        host = QWidget()
        row = QHBoxLayout(host)
        row.setContentsMargins(0, 0, 0, 0)
        pick = QToolButton()
        pick.setObjectName(f"param_{spec.name}_columns")
        pick.setText("▾")
        pick.setToolTip(
            "Tick a column to add its line, untick to remove it "
            "(needs an upstream run)"
            if spec.insert_columns == "mapping"
            else "Insert an upstream column name (needs an upstream run)")
        pick.setPopupMode(QToolButton.InstantPopup)
        # a mapping's ticks are toggled several at a time, so it wants the
        # same stay-open menu the 'columns' picker uses; an inline insert is
        # one name at a time and closing after it is right
        menu = (_ColumnsMenu(pick) if spec.insert_columns == "mapping"
                else QMenu(pick))
        pick.setMenu(menu)
        # built on demand, like the 'columns' picker: whatever the cache
        # holds at click time, with no refresh wiring when upstream re-runs
        menu.aboutToShow.connect(
            lambda: self._fill_insert_menu(menu, text, spec,
                                           spec.insert_columns))
        row.addWidget(text, 1)
        # top-aligned: centred, the button floats halfway down a 90px box
        # with nothing to relate it to. A column of its own, so the ⤢ that
        # every multiline box gets stacks under it (_with_pop_out) instead of
        # taking a second button's width out of a narrow dock.
        buttons = QVBoxLayout()
        buttons.setContentsMargins(0, 0, 0, 0)
        buttons.setSpacing(2)
        buttons.addWidget(pick)
        buttons.addStretch(1)
        row.addLayout(buttons)
        host.button_column = buttons
        host.setMaximumHeight(text.maximumHeight())
        return host

    def _fill_insert_menu(self, menu: QMenu, text: QPlainTextEdit,
                          spec: Optional[ParamSpec] = None,
                          mode: str = "inline") -> None:
        from flograph.engine import upstream_columns
        menu.clear()
        columns = (upstream_columns(self._graph, self._cache, self._node_id)
                   if self._cache is not None and self._node_id else [])
        if not columns:
            action = menu.addAction("run upstream nodes to list columns")
            action.setEnabled(False)
            return
        mapped = ({_mapping_key(line) for line in text.toPlainText().split("\n")}
                  if mode == "mapping" else set())
        for column in columns:
            action = menu.addAction(column)
            action.setData(column)
            if mode == "mapping":
                # a tick means "this column has a line"; the box is the
                # value, so the state is read back off the text rather than
                # remembered here
                action.setCheckable(True)
                action.setChecked(column in mapped)
                action.setProperty(_STAYS_OPEN, True)
                action.triggered.connect(
                    lambda _checked=False, c=column:
                    self._toggle_mapping(text, spec, c))
            else:
                action.triggered.connect(
                    lambda _checked=False, c=column:
                    self._insert_column(text, c))

    def _toggle_mapping(self, text: QPlainTextEdit, spec: ParamSpec,
                        column: str) -> None:
        """Tick a column into the mapping, or untick it back out.

        Ticking writes `column = ` and leaves the caret after it, because
        the half you have to supply is the new name. Unticking takes the
        whole line away — the point of a tick is that it undoes itself."""
        body = text.toPlainText()
        lines = body.split("\n")
        kept = [line for line in lines if _mapping_key(line) != column]
        if len(kept) != len(lines):
            new = "\n".join(kept)
        else:
            # a trailing newline is where the user is about to type, not a
            # line to preserve — otherwise the gap grows with every tick
            head = body.rstrip("\n")
            new = f"{head}\n{column} = " if head.strip() else f"{column} = "
        self._silently(text.setPlainText, new)
        self._commit(spec.name, new, merge=False)
        cursor = text.textCursor()
        cursor.movePosition(QTextCursor.End)
        text.setTextCursor(cursor)
        # carry on typing the new name rather than back in the menu
        text.setFocus()

    def _with_pop_out(self, spec: ParamSpec, text: QPlainTextEdit,
                      widget: QWidget) -> QWidget:
        """Put a ⤢ button beside a multiline box that opens it in a big,
        resizable editor (text_popout). The box is 90px tall in a narrow
        dock, and a page of rules or expressions needs more room than that.
        `widget` is the box as already wrapped — picker, Rules… button."""
        from PySide6.QtGui import QPalette

        from .text_popout import expand_icon

        button = QToolButton()
        button.setObjectName(f"param_{spec.name}_popout")
        button.setIcon(expand_icon(self.palette().color(QPalette.ButtonText)))
        button.setToolTip("Open in a bigger editor")
        button.clicked.connect(lambda: self._open_pop_out(spec, text))
        column = getattr(widget, "button_column", None)
        if column is not None:
            # under the column picker, at its width: one button's width out
            # of a narrow dock rather than two side by side
            pick = column.itemAt(0).widget()
            width = max(pick.sizeHint().width(), button.sizeHint().width())
            pick.setFixedWidth(width)
            button.setFixedWidth(width)
            column.insertWidget(1, button)
            return widget
        host = QWidget()
        row = QHBoxLayout(host)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(2)
        row.addWidget(widget, 1)
        row.addWidget(button, 0, Qt.AlignTop)
        # the row sizing in _add_row reads maximumHeight off the widget it is
        # given, so the wrapper carries whatever cap the box inside it has
        host.setMaximumHeight(widget.maximumHeight())
        return host

    def _open_pop_out(self, spec: ParamSpec, text: QPlainTextEdit) -> None:
        from PySide6.QtWidgets import QDialog

        from .text_popout import TextPopOut

        from flograph.core.text_assist import assist_for
        from flograph.engine import upstream_columns

        # anything typed and not yet settled is part of what opens
        self.flush_pending()
        node_id = self._node_id
        if node_id is None:
            return
        node = self._graph.node(node_id)
        picker = menu = None
        if spec.insert_columns:
            picker = QToolButton()
            picker.setObjectName("popout_columns")
            picker.setText("Insert column ▾")
            picker.setPopupMode(QToolButton.InstantPopup)
            menu = QMenu(picker)
            picker.setMenu(menu)
        columns = (upstream_columns(self._graph, self._cache, node_id)
                   if self._cache is not None else [])
        if spec.rule_wizard and not columns:
            columns = self._wizard_columns()
        read_only = text.isReadOnly() or not text.isEnabled()
        dialog = TextPopOut(
            f"{node.label} — {spec.label or spec.name}", text.toPlainText(),
            placeholder=spec.placeholder or "",
            assist=assist_for(node.type_id, spec.name, spec.rule_wizard),
            columns=columns, sample=self._upstream_sample(node_id),
            picker=picker, read_only=read_only, parent=self)
        editor = dialog.editor
        if menu is not None:
            menu.aboutToShow.connect(
                lambda: self._fill_pop_out_menu(menu, editor, spec))
        if spec.rule_wizard:
            from flograph.ui.emoji_font import apply_emoji_font
            apply_emoji_font(editor)
        accepted = dialog.exec() == QDialog.Accepted
        new = editor.toPlainText()
        dialog.deleteLater()
        # through _commit rather than the box: a run finishing while the
        # dialog was up can rebuild the panel, and the box with it — and if
        # the panel has moved to another node, this text isn't that node's
        if accepted and not read_only and self._node_id == node_id:
            self._commit(spec.name, new, merge=False)

    def _attach_assist(self, spec: ParamSpec, text: QPlainTextEdit) -> None:
        """The pop-out's help, in the box itself: completion of the box's
        own words and the columns coming in, and the lint's wavy underlines
        with the problems listed on the box's tooltip.

        Completion only where the box has something to offer — a language
        of its own, or a column picker — so a note or a prompt doesn't pop
        suggestions up at every word typed. The lint runs as the box appears
        and again once typing pauses, against the incoming table only if it
        is already in memory (_resident_sample)."""
        from flograph.core.text_assist import assist_for

        from ..editor.diagnostics import summary, underline_selections
        from ..editor.word_completion import WordCompleter

        node_id = self._node_id
        if node_id is None or node_id not in self._graph.nodes:
            return
        assist = assist_for(self._graph.node(node_id).type_id, spec.name,
                            spec.rule_wizard)
        if assist.keywords or spec.insert_columns or spec.rule_wizard:
            def columns() -> list:
                from flograph.engine import upstream_columns
                if self._node_id != node_id or self._cache is None:
                    return []
                found = upstream_columns(self._graph, self._cache, node_id)
                return found or (self._wizard_columns() if spec.rule_wizard
                                 else [])
            text.completer = WordCompleter(text, assist.keywords, columns,
                                           assist.quote)
        if assist.lint is None:
            return
        from PySide6.QtGui import QBrush, QIcon

        from ..editor.diagnostics import DIAGNOSTIC_COLORS, dot_icon

        own_tip = text.toolTip()
        row_look: dict = {}

        def row() -> Optional[QTreeWidgetItem]:
            for index in range(self.tree.topLevelItemCount()):
                item = self.tree.topLevelItem(index)
                host = self.tree.itemWidget(item, 1)
                if host is not None and (host is text or host.isAncestorOf(text)):
                    return item
            return None

        def mark_row(found: list) -> None:
            """The row's label in the lint's colour, with a dot: the underline
            alone is a thin line in a small box, and easy to miss."""
            item = row()
            if item is None:
                return      # not in its row yet; the run queued below marks it
            if not row_look:
                row_look.update(ink=item.foreground(0), tip=item.toolTip(0))
            if found:
                worst = ("error" if any(d.severity == "error" for d in found)
                         else "warning")
                item.setForeground(0, QBrush(DIAGNOSTIC_COLORS[worst]))
                item.setIcon(0, dot_icon(DIAGNOSTIC_COLORS[worst]))
                item.setToolTip(0, summary(found))
            else:
                item.setForeground(0, row_look["ink"])
                item.setIcon(0, QIcon())
                item.setToolTip(0, row_look["tip"])

        def run_lint() -> None:
            try:
                found = list(assist.lint(text.toPlainText(),
                                         self._resident_sample(node_id)))
            except Exception:   # a lint must never cost the user the box
                found = []
            text.diagnostics = found
            text.setExtraSelections(underline_selections(text.document(), found))
            text.setToolTip("\n\n".join(tip for tip in (own_tip, summary(found))
                                        if tip))
            mark_row(found)

        timer = QTimer(text)
        timer.setSingleShot(True)
        timer.setInterval(400)
        timer.timeout.connect(run_lint)
        text.textChanged.connect(timer.start)
        text.run_lint = run_lint
        run_lint()
        # the box is built before _rebuild puts it in its row: run once more
        # after, to mark the label. Tied to the box, so a panel rebuilt in
        # between drops it rather than reaching for a deleted widget.
        QTimer.singleShot(0, text, run_lint)

    def _resident_sample(self, node_id: str, rows: int = 200):
        """_upstream_sample from memory only. The box lints as the panel is
        built, which happens on every click of a node, and reading a spilled
        table back from disk for that would make selecting slow."""
        import pandas as pd

        if self._cache is None or node_id not in self._graph.nodes:
            return None
        inputs = {p.name for p in self._graph.node(node_id).spec.inputs}
        for conn in self._graph.connections.values():
            if conn.dst_node != node_id or conn.dst_port not in inputs:
                continue
            entry = self._cache.get(conn.src_node)
            if entry is None or not entry.resident:
                continue
            value = entry.outputs.get(conn.src_port)
            if isinstance(value, pd.DataFrame):
                return value.head(rows)
        # Nothing in memory — the usual state just after opening a project.
        # The cache still has the column names on record, and an empty table
        # carrying them is enough for the lint to catch a column that isn't
        # there; with no rows, it checks names rather than evaluating.
        from flograph.engine import upstream_columns
        names = upstream_columns(self._graph, self._cache, node_id)
        if names:
            return pd.DataFrame({name: pd.Series(dtype=object) for name in names})
        return None

    def _upstream_sample(self, node_id: str, rows: int = 200):
        """The first rows of the table feeding this node, for the pop-out's
        lint to try the text against — None when nothing upstream has run.
        A head, not the table: the lint re-runs as you type."""
        import pandas as pd

        if self._cache is None or node_id not in self._graph.nodes:
            return None
        inputs = {p.name for p in self._graph.node(node_id).spec.inputs}
        for conn in self._graph.connections.values():
            if conn.dst_node != node_id or conn.dst_port not in inputs:
                continue
            try:
                outputs = self._cache.outputs_for(conn.src_node) or {}
            except Exception:
                continue
            value = (outputs.get(conn.src_port)
                     if isinstance(outputs, dict) else None)
            if isinstance(value, pd.DataFrame):
                return value.head(rows)
        return None

    def _fill_pop_out_menu(self, menu: QMenu, editor: QPlainTextEdit,
                           spec: ParamSpec) -> None:
        """The column picker, inside the pop-out. It types into the copy and
        commits nothing, so Cancel still means cancel — which is why this
        isn't _fill_insert_menu, whose mapping ticks commit as they go. A
        mapping box gets `column = `, the half you then finish."""
        from flograph.engine import upstream_columns
        menu.clear()
        columns = (upstream_columns(self._graph, self._cache, self._node_id)
                   if self._cache is not None and self._node_id else [])
        if not columns:
            menu.addAction("run upstream nodes to list columns").setEnabled(False)
            return
        mapping = spec.insert_columns == "mapping"
        for column in columns:
            menu.addAction(column).triggered.connect(
                lambda _checked=False, c=column: self._insert_column(
                    editor, f"{c} = " if mapping else c, raw=mapping))

    @staticmethod
    def _insert_column(text: QPlainTextEdit, column: str,
                       raw: bool = False) -> None:
        cursor = text.textCursor()
        if not getattr(text, "caret_placed", False):
            # nobody has put the caret anywhere, so its position 0 is where
            # the widget was built rather than a choice — inserting there
            # would push the name in front of everything already written.
            # Start a fresh line at the end instead, which for both boxes
            # that use this is the next entry.
            cursor.movePosition(QTextCursor.End)
            if cursor.block().text().strip():
                cursor.insertText("\n")
        # bare, the way the name is spelled — an expression puts in the
        # backticks a name with spaces needs — except one like `price($)`,
        # which it can only read in backticks
        from flograph.core.column_refs import as_typed
        cursor.insertText(column if raw else as_typed(column))
        text.setTextCursor(cursor)
        # carry on typing where the name landed rather than back in the menu
        text.setFocus()

    def _make_date_widget(self, spec: ParamSpec, value: Any):
        """Calendar picker storing an ISO "YYYY-MM-DD" string. A blank param
        is a real state (no date chosen), so the editor stays empty until
        something is picked rather than silently committing today."""
        from PySide6.QtWidgets import QDateEdit

        from ..controls import iso_to_qdate, qdate_to_iso

        name = spec.name
        edit = QDateEdit()
        edit.setObjectName(f"param_{name}")
        edit.setCalendarPopup(True)
        edit.setDisplayFormat("yyyy-MM-dd")
        stored = iso_to_qdate(value)
        if stored is not None:
            edit.setDate(stored)
        edit.dateChanged.connect(
            lambda d: self._commit(name, qdate_to_iso(d)))

        def set_date(v, edit=edit):
            parsed = iso_to_qdate(v)
            if parsed is not None and parsed != edit.date():
                blocked = edit.blockSignals(True)
                try:
                    edit.setDate(parsed)
                finally:
                    edit.blockSignals(blocked)
        return edit, set_date

    def _make_columns_widget(self, spec: ParamSpec, value: Any):
        """Line edit plus a picker button listing the columns of whatever
        cached DataFrames feed this node. Free text still works — the picker
        only fills once upstream has run."""
        name = spec.name
        host = QWidget()
        row = QHBoxLayout(host)
        row.setContentsMargins(0, 0, 0, 0)
        edit = QLineEdit(str(value or ""))
        edit.setMaxLength(UNCAPPED_TEXT)  # a wide table's column list is long
        if spec.placeholder:
            edit.setPlaceholderText(spec.placeholder)
        edit.textEdited.connect(
            lambda v, owner=self._node_id: self._commit_typed(name, v, owner))
        # leaving the field (focus-out or Enter) is a settled
        # value — don't make it wait out the timer
        edit.editingFinished.connect(self.flush_pending)

        pick = QToolButton()
        pick.setText("▾")
        pick.setToolTip("Pick from upstream columns (needs an upstream run)")
        pick.setPopupMode(QToolButton.InstantPopup)
        menu = _ColumnsMenu(pick)
        pick.setMenu(menu)
        # built on demand: always reflects the cache at click time, so no
        # refresh wiring is needed when upstream re-runs
        menu.aboutToShow.connect(
            lambda: self._fill_columns_menu(menu, edit, spec))
        row.addWidget(edit, 1)
        row.addWidget(pick)
        return host, self._line_setter(edit)

    def _make_node_ref_widget(self, spec: ParamSpec, value: Any):
        """Combo of the graph's nodes whose card kind matches spec.ref_kind,
        storing the chosen node's *id* while showing its current name (the
        From node's Goto picker). Refilled every time it drops down, so a Goto
        added or renamed while this node stays selected still shows up."""
        combo = _NodeRefCombo(lambda: self._fill_node_refs(combo, spec))
        self._fill_node_refs(combo, spec, str(value or ""))
        # `activated` fires on user choice only — programmatic refills (below,
        # and the setter) must never look like edits
        combo.activated.connect(
            lambda _i: self._commit(spec.name, combo.currentData() or ""))

        def set_ref(v, combo=combo, spec=spec):
            self._fill_node_refs(combo, spec, str(v or ""))
        return combo, set_ref

    def _fill_node_refs(self, combo: QComboBox, spec: ParamSpec,
                        value: Optional[str] = None) -> None:
        from flograph.core.links import link_label

        if value is None:
            value = combo.currentData() or ""
            if self._node_id in self._graph.nodes:
                value = self._graph.node(self._node_id).params.get(spec.name) or value
        self._updating = True
        try:
            combo.clear()
            combo.addItem("— none —", "")
            candidates = [node for node in self._graph.nodes.values()
                          if node.spec.card == spec.ref_kind
                          and node.id != self._node_id]
            # alphabetical, not insertion order: a graph with a dozen Gotos is
            # unusable if the list is ordered by whenever each was dropped
            for node in sorted(candidates, key=lambda n: link_label(n).lower()):
                combo.addItem(link_label(node), node.id)
            index = combo.findData(value)
            if index < 0 and value:
                # the target was deleted: keep the dangling choice visible
                # rather than silently showing (and later committing) another
                combo.addItem("⚠ missing", value)
                index = combo.count() - 1
            combo.setCurrentIndex(max(0, index))
        finally:
            self._updating = False

    def _make_page_ref_widget(self, spec: ParamSpec, value: Any):
        """Combo of the project's pages, storing the chosen page's *id*
        while showing its title — the Action Button's Go to page (AB2). The
        node_ref combo's rules: refilled every time it drops down, and a
        page that has since been deleted stays visible as missing."""
        combo = _NodeRefCombo(lambda: self._fill_page_refs(combo))
        self._fill_page_refs(combo, str(value or ""))
        combo.activated.connect(
            lambda _i: self._commit(spec.name, combo.currentData() or ""))

        def set_ref(v, combo=combo):
            self._fill_page_refs(combo, str(v or ""))
        return combo, set_ref

    def _fill_page_refs(self, combo: QComboBox,
                        value: Optional[str] = None) -> None:
        if value is None:
            value = combo.currentData() or ""
        self._updating = True
        try:
            combo.clear()
            combo.addItem("— none —", "")
            # tab order, the order anyone reading the dashboard knows them by
            from flograph.core.page_nav import reader_pages
            for page in reader_pages(self._graph.pages):
                combo.addItem(page.title, page.id)
            index = combo.findData(value)
            if index < 0 and value:
                combo.addItem("⚠ missing", value)
                index = combo.count() - 1
            combo.setCurrentIndex(max(0, index))
        finally:
            self._updating = False

    def _make_page_set_widget(self, spec: ParamSpec, value: Any):
        """Ticks over the project's pages, for a param that names several
        (Page Links, AB3). Nothing ticked means every page, which is also
        what keeps up by itself when a page is added — so the button says
        so rather than looking empty. Stored as a comma list of ids."""
        from flograph.core.page_nav import join_page_ids, split_page_ids
        name = spec.name
        everything = spec.placeholder or "Every page"
        button = QToolButton()
        button.setPopupMode(QToolButton.InstantPopup)
        button.setToolButtonStyle(Qt.ToolButtonTextOnly)
        menu = _ColumnsMenu(button)
        button.setMenu(menu)
        held = {"ids": split_page_ids(value)}

        def show(v) -> None:
            held["ids"] = split_page_ids(v)
            live = [self._graph.pages[i] for i in held["ids"]
                    if i in self._graph.pages]
            if not held["ids"]:
                button.setText(everything)
            elif len(live) == 1:
                button.setText(live[0].title)
            else:
                button.setText(f"{len(live)} pages")
            button.setToolTip("\n".join(p.title for p in live) or everything)

        def toggle(page_id: str, checked: bool) -> None:
            ids = [i for i in held["ids"] if i != page_id]
            if checked:
                ids.append(page_id)
            # kept in tab order, not in the order they were ticked
            order = list(self._graph.pages)
            ids.sort(key=lambda i: order.index(i) if i in order else len(order))
            new = join_page_ids(ids)
            show(new)
            self._commit(name, new)

        def every() -> None:
            show("")
            self._commit(name, "")

        def fill() -> None:
            from flograph.core.page_nav import reader_pages
            menu.clear()
            pages = reader_pages(self._graph.pages)
            if not pages:
                action = menu.addAction("no pages yet")
                action.setEnabled(False)
                return
            action = menu.addAction(everything)
            action.setCheckable(True)
            action.setChecked(not held["ids"])
            action.triggered.connect(lambda _c=False: every())
            menu.addSeparator()
            for page in pages:
                action = menu.addAction(page.title)
                action.setCheckable(True)
                action.setChecked(page.id in held["ids"])
                action.setProperty(_STAYS_OPEN, True)
                action.toggled.connect(
                    lambda checked, page_id=page.id: toggle(page_id, checked))

        menu.aboutToShow.connect(fill)
        show(value)
        return button, show

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
        if spec.multi:
            # picking six of eight columns is the common case, and doing it
            # one tick at a time is what the stay-open menu is for; these
            # two turn the other common case into a single click
            for label, wanted in (("Select all", columns), ("Select none", [])):
                action = menu.addAction(label)
                action.setProperty(_STAYS_OPEN, True)
                action.triggered.connect(
                    lambda _checked=False, cols=wanted:
                    self._set_columns(menu, edit, spec, cols))
            menu.addSeparator()
        chosen = [c.strip() for c in edit.text().split(",") if c.strip()]
        for column in columns:
            action = menu.addAction(column)
            action.setData(column)
            if spec.multi:
                action.setCheckable(True)
                action.setChecked(column in chosen)
                action.setProperty(_STAYS_OPEN, True)
            action.triggered.connect(
                lambda _checked=False, c=column:
                self._pick_column(edit, spec, c))

    def _set_columns(self, menu: QMenu, edit: QLineEdit, spec: ParamSpec,
                     columns: list[str]) -> None:
        """Select all / select none. The menu is still up, so its ticks have
        to be brought back in line with the value by hand — nothing is going
        to rebuild them until it is next opened."""
        text = ", ".join(columns)
        edit.setText(text)
        self._commit(spec.name, text, merge=False)
        wanted = set(columns)
        for action in menu.actions():
            column = action.data()
            if action.isCheckable() and column is not None:
                action.setChecked(column in wanted)

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
        self._commit(spec.name, text, merge=False)

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

    def _commit_typed(self, name: str, value: Any,
                      owner: Optional[str] = None) -> None:
        """A keystroke. Held back until typing pauses.

        Committing per character is what a QLineEdit invites, and it is far
        from free: every commit pushes an undo command, marks the node and
        its whole downstream cone dirty, evicts that cone from the cache and
        re-renders the report cards. On a large graph that is milliseconds of
        model work per character, before anything repaints.

        Undo behaviour is unchanged — SetParamCommand already merges
        consecutive edits of the same param into one step.
        """
        if self._updating or self._node_id is None:
            return
        # `owner` is the node the box was built for. A box the panel has
        # moved on from can still be typed into — a completion list left
        # open holds the keyboard — and its text is no other node's.
        if owner is not None and owner != self._node_id:
            return
        self._pending[name] = value
        self._typing.start()

    def flush_pending(self) -> None:
        """Commit anything typed but not yet settled.

        Called on the idle timer, when the panel moves to another node, and
        by MainWindow before every run — a run reading a param the user has
        just typed but not paused after is exactly the stale-value bug that
        `_flush_pending_edits` exists to prevent for grid cells.
        """
        self._typing.stop()
        if not self._pending:
            return
        pending, self._pending = self._pending, {}
        for name, value in pending.items():
            self._commit(name, value)

    def _commit(self, name: str, value: Any, *, merge: bool = True) -> None:
        """Settle a param. `merge=False` keeps this edit its own undo step,
        for a discrete click rather than a run of keystrokes — six ticks in
        a picker are six things the user did, and one Ctrl+Z that took them
        all back would be a surprise."""
        if self._updating or self._node_id is None:
            return
        # a settled value supersedes a keystroke still waiting on the timer
        self._pending.pop(name, None)
        node = self._graph.node(self._node_id)
        if node.params.get(name) == value:
            return
        self._undo_stack.push(
            SetParamCommand(self._graph, self._node_id, name, value,
                            merge=merge))

    def _commit_label(self, text: str) -> None:
        if self._node_id is None:
            return
        node = self._graph.node(self._node_id)
        new = text.strip() or None
        if new != node.label_override:
            self._undo_stack.push(SetLabelCommand(self._graph, self._node_id, new))

    def _commit_description(self, text: str) -> None:
        if self._updating or self._node_id is None:
            return
        node = self._graph.node(self._node_id)
        if node.description == text:
            return
        self._undo_stack.push(SetDescriptionCommand(self._graph, self._node_id, text))

    def _silently(self, setter: Callable, value: Any) -> None:
        self._updating = True
        try:
            setter(value)
        finally:
            self._updating = False

    # --------------------------------------------------------------- events

    def _on_param_changed(self, node_id: str, name: str, value: Any) -> None:
        if node_id != self._node_id:
            return
        if name in self._setters:
            self._setters[name](value)
        node = self._graph.node(node_id)
        if name in controllers(node.spec.params):
            # This one decides which other rows exist, so the grid has to be
            # rebuilt — but never from inside the signal of the widget that
            # the rebuild is about to delete. Qt would be left holding a
            # combo it destroyed mid-emit. Next event loop turn is soon
            # enough and the widget has finished by then.
            QTimer.singleShot(0, self._rebuild_if_live)

    def _rebuild_if_live(self) -> None:
        """Deferred rebuild — the node may have been deselected or deleted
        between scheduling and firing."""
        if self._node_id is not None and self._node_id in self._graph.nodes:
            self._rebuild()

    def _on_code_changed(self, node_id: str) -> None:
        if node_id == self._node_id:
            self._rebuild()  # params may have changed shape

    def _on_node_removed(self, node_id: str) -> None:
        if node_id == self._node_id:
            self.set_node(None)
