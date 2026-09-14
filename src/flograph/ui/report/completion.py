"""Autocomplete in a report editor: labels, ports, options and page titles.

`core.report_assist.suggest` decides what fits at the caret; this is the
popup. It opens as you type inside `![[`, after a `|`, after `key=` and in
a `(page:` link, and Ctrl+Space asks for it anywhere. Enter or Tab takes
the highlighted entry, Escape puts the list away.

Built the way `ui.properties.var_completion` is — a QCompleter driven by
hand so it completes mid-text, with the popup's keys handled in a filter
on the popup itself — and used by both the report page's editor and a
Report card's in-place one. `vocabulary` is a function, asked each time the
list opens, because what can be embedded changes with every run.
"""
from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import QEvent, QModelIndex, QObject, Qt, QTimer
from PySide6.QtGui import QStandardItem, QStandardItemModel, QTextCursor
from PySide6.QtWidgets import QCompleter, QPlainTextEdit

from flograph.core.report_assist import Name, Vocabulary, suggest

#: the role an entry's Suggestion rides in; the popup shows DisplayRole
SUGGESTION_ROLE = Qt.UserRole + 1


class ReportCompleter(QObject):
    def __init__(self, editor: QPlainTextEdit,
                 vocabulary: Callable[[], Vocabulary],
                 on_popup: Optional[Callable[[bool], None]] = None) -> None:
        super().__init__(editor)
        self._editor = editor
        self._vocabulary = vocabulary
        #: told True/False as the list opens and closes — a card lifts
        #: itself so the list is not drawn under the card in front
        self._on_popup = on_popup
        self._model = QStandardItemModel(self)
        self._completer = QCompleter(self._model, editor)
        self._completer.setWidget(editor)
        # suggest() has already matched and ordered the entries
        self._completer.setCompletionMode(
            QCompleter.UnfilteredPopupCompletion)
        self._completer.activated[QModelIndex].connect(self._activated)
        self._completer.popup().installEventFilter(self)
        editor.installEventFilter(self)
        #: what the list holds, and where it was opened — see refresh
        self._shown: tuple = ()
        self._anchor: Optional[tuple] = None
        # textChanged also fires on an undo or a load from the model, so
        # the refresh checks focus: nobody typed, nothing should pop up
        editor.textChanged.connect(self._on_text_changed)

    @property
    def popup(self):
        return self._completer.popup()

    # ------------------------------------------------------------- events

    def eventFilter(self, obj, event) -> bool:
        popup = self.popup
        if obj is self._editor and event.type() == QEvent.KeyPress:
            if (event.key() == Qt.Key_Space
                    and event.modifiers() & Qt.ControlModifier):
                self.refresh(force=True)
                return True
        if obj is popup:
            kind = event.type()
            if kind == QEvent.Show and self._on_popup:
                self._on_popup(True)
            elif kind == QEvent.Hide and self._on_popup:
                self._on_popup(False)
            elif kind == QEvent.KeyPress and popup.isVisible():
                if event.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Tab):
                    index = popup.currentIndex()
                    if not index.isValid():
                        index = self._completer.completionModel().index(0, 0)
                    if index.isValid():
                        self._activated(index)
                    popup.hide()
                    return True
                if event.key() == Qt.Key_Escape:
                    popup.hide()
                    return True
        return super().eventFilter(obj, event)

    def _on_text_changed(self) -> None:
        if not self._editor.hasFocus():
            self.popup.hide()
            return
        # after the editor has finished with the key, so the caret has moved
        QTimer.singleShot(0, self.refresh)

    # ------------------------------------------------------------ showing

    def _around_caret(self) -> tuple[str, str]:
        cursor = self._editor.textCursor()
        line = cursor.block().text()
        at = cursor.positionInBlock()
        return line[:at], line[at:]

    def refresh(self, force: bool = False) -> None:
        import shiboken6
        if not shiboken6.isValid(self._editor) or self._editor.isReadOnly():
            return
        carets = getattr(self._editor, "carets", None)
        if carets is not None and carets.active:
            self.popup.hide()
            return
        before, after = self._around_caret()
        try:
            completion = suggest(before, after, self._vocabulary())
        except Exception:   # completion is a nicety; never break typing
            completion = None
        if completion is None or not completion.items or (
                not force and not completion.eager and not completion.prefix):
            self.popup.hide()
            return
        self._fill(completion.items)
        self._place(completion.start)
        self.popup.setCurrentIndex(
            self._completer.completionModel().index(0, 0))

    def _fill(self, suggestions) -> None:
        """Put `suggestions` in the list, row by row in place.

        Not clear() and append: the popup refits itself to every row
        inserted, so a list of seven moved and resized eight times per
        letter typed — and on Wayland each of those is the popup closed
        and opened again. Resizing the model changes the row count once;
        setting an item changes only what the row says."""
        self._model.setRowCount(len(suggestions))
        for row, suggestion in enumerate(suggestions):
            shown = suggestion.label or suggestion.text
            item = QStandardItem(
                f"{shown}    {suggestion.hint}" if suggestion.hint else shown)
            item.setData(suggestion, SUGGESTION_ROLE)
            item.setEditable(False)
            if suggestion.hint:
                item.setToolTip(suggestion.hint)
            self._model.setItem(row, 0, item)
        self._shown = tuple(s.label or s.text for s in suggestions)

    def _place(self, start: int) -> None:
        """Open the list under where the name being typed starts — or, when
        it is open there already, leave it be. Following the caret moved an
        open list on every letter."""
        block = self._editor.textCursor().block()
        at = QTextCursor(block)
        at.setPosition(block.position() + start)
        rect = self._editor.cursorRect(at)
        anchor = (rect.left(), rect.top())
        if self.popup.isVisible() and anchor == self._anchor:
            return
        self._anchor = anchor
        rect.setWidth(min(520, self.popup.sizeHintForColumn(0)
                          + self.popup.verticalScrollBar().sizeHint().width()
                          + 8))
        self._completer.complete(rect)

    def _activated(self, index) -> None:
        suggestion = index.data(SUGGESTION_ROLE)
        if suggestion is not None:
            self.insert(suggestion)

    def insert(self, suggestion) -> None:
        """Put `suggestion` in place of what has been typed of it.

        The context is worked out again here rather than carried from when
        the list opened: an offset held across an edit that moved the text
        would splice the word in at the wrong place.
        """
        before, after = self._around_caret()
        completion = suggest(before, after, self._vocabulary())
        if completion is None:
            self.popup.hide()
            return
        cursor = self._editor.textCursor()
        cursor.movePosition(QTextCursor.Left, QTextCursor.KeepAnchor,
                            len(before) - completion.start)
        close = suggestion.close
        if close and after.startswith(close):
            close = ""
        cursor.insertText(suggestion.text + close)
        self._editor.setTextCursor(cursor)
        self.popup.hide()


# ------------------------------------------------------------ vocabularies

def page_vocabulary(graph, cache) -> Vocabulary:
    """What a report page can name: every node, the ones that have produced
    something first, and every page a link can go to."""
    from flograph.core.page_nav import reader_pages
    from .render import duplicate_labels
    return Vocabulary(names=_node_names(graph, cache, duplicate_labels(graph)),
                      pages=[p.title for p in reader_pages(graph.pages)])


def card_vocabulary(graph, cache, node) -> Vocabulary:
    """What a Report card can name: its own input ports first — the
    dependency the scheduler can see — then the nodes on the canvas."""
    from flograph.core.page_nav import reader_pages
    from .render import duplicate_labels
    wired = {c.dst_port for c in graph.connections.values()
             if c.dst_node == node.id}
    names = [Name(port.name, "input" if port.name in wired
                  else "input — nothing wired in")
             for port in node.spec.inputs]
    names += _node_names(graph, cache, duplicate_labels(graph),
                         skip=node.id)
    return Vocabulary(names=names,
                      pages=[p.title for p in reader_pages(graph.pages)])


def _node_names(graph, cache, ambiguous, skip=None) -> list:
    ran, waiting = [], []
    for node in graph.nodes.values():
        if node.id == skip or node.label.casefold() in ambiguous:
            # a duplicated label is an embed that cannot resolve
            continue
        result = cache.get(node.id) if cache is not None else None
        has_output = result is not None and bool(result.ports())
        ports = tuple(port.name for port in node.spec.outputs)
        if has_output:
            ran.append(Name(node.label, node.spec.label
                            if node.spec.label != node.label else "", ports))
        else:
            waiting.append(Name(node.label, "not run yet", ports))
    order = lambda name: name.label.casefold()   # noqa: E731
    return sorted(ran, key=order) + sorted(waiting, key=order)
