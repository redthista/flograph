"""A bigger editor for a multi-line text param.

The box in Properties is 90px tall inside a narrow dock: fine for two rename
lines, cramped for a page of Conditional Column rules or Expression lines.
The ⤢ beside it opens the same text in a window that can be made as big as
the work needs, and that is a code editor rather than a bigger box: line
numbers, several carets (ui/editor/multi_cursor), find and replace (Ctrl+F,
Ctrl+H), completion of the box's keywords and the columns coming in, and a
lint that marks the lines the node would refuse (core/text_assist).

It edits a copy — OK writes it back as one undo step, Cancel leaves the
param as it was — the same contract as the Rules… manager. Esc asks before
throwing edits away, because in a window this size it is easy to have
done a lot of work before reaching for it.
"""
from __future__ import annotations

from typing import Iterable, Optional

from PySide6.QtCore import QByteArray, QPointF, QSettings, QSize, Qt, QTimer
from PySide6.QtGui import (
    QColor, QIcon, QKeySequence, QPainter, QPen, QPixmap, QPolygonF, QShortcut,
    QTextCursor,
)
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QMessageBox, QSizeGrip,
    QVBoxLayout, QWidget,
)

from flograph.core.text_assist import TextAssist
from ..editor.code_editor import CodeEditor
from ..editor.find_bar import FindBar
from ..editor.rules_highlighter import RulesHighlighter
from ..editor.word_completion import WordCompleter

LINT_DELAY_MS = 300
_ORG = _APP = "flograph"
#: Where this window was left, so the next one opens the same size. One
#: key for every pop-out rather than one each: they are the same window
#: doing the same job, and somebody who makes it full screen for a script
#: wants it full screen for a box of rules too.
GEOMETRY_KEY = "text_popout/geometry"
MAXIMIZED_KEY = "text_popout/maximized"
ERROR_INK = "#f87171"
WARNING_INK = "#fbbf24"
OK_INK = "#86efac"


def expand_icon(color: QColor, size: int = 16) -> QIcon:
    """Two arrowheads pointing out to opposite corners. Drawn rather than
    typed: ⤢ is missing from plenty of UI fonts and would show as a box."""
    scale = 2
    pixmap = QPixmap(size * scale, size * scale)
    pixmap.setDevicePixelRatio(scale)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    pen = QPen(color, 1.5)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    painter.setPen(pen)
    low, high, arm = 3.5, size - 3.5, 4.5
    painter.drawLine(QPointF(low, high), QPointF(high, low))
    painter.drawPolyline(QPolygonF([QPointF(high - arm, low), QPointF(high, low),
                                    QPointF(high, low + arm)]))
    painter.drawPolyline(QPolygonF([QPointF(low, high - arm), QPointF(low, high),
                                    QPointF(low + arm, high)]))
    painter.end()
    return QIcon(pixmap)


class TextPopOut(QDialog):
    """`editor` holds the copy being edited; read it back after exec().

    sample: the first rows of the table coming in, for the lint to try the
    text against, or None when nothing upstream has run."""

    #: How big a pop-out opens when nothing has been remembered yet. A
    #: subclass says its own — a script wants more room than a box of
    #: rules does — and a geometry saved from either wins over both.
    DEFAULT_SIZE = QSize(820, 560)

    HINT = ("Ctrl+Space completes · Ctrl+F finds · "
            "Alt+Click adds a caret · F11 full screen · Ctrl+Enter applies")
    # said after "No problems found" when there is no table to check against
    UNCHECKED = (" — columns not checked until the nodes feeding this one "
                 "have run")

    def __init__(self, title: str, text: str, *, placeholder: str = "",
                 assist: Optional[TextAssist] = None,
                 columns: Iterable[str] = (), sample=None,
                 picker: Optional[QWidget] = None, read_only: bool = False,
                 parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("text_popout")
        self.setWindowTitle(title)
        # A QDialog gets no maximize button from Qt, so a window meant to
        # be "as big as the work needs" could be dragged bigger and never
        # simply filled out. The hint has to be asked for by name, and it
        # is added to the flags the platform already gave this dialog
        # rather than replacing them — a bare setWindowFlags here loses the
        # dialog's own type and reparents the native window.
        self.setWindowFlags(self.windowFlags()
                            | Qt.WindowMaximizeButtonHint)
        self.setSizeGripEnabled(True)
        self.assist = assist or TextAssist()
        self._sample = sample
        self._original = text
        columns = list(columns)

        editor = CodeEditor(self)
        editor.setObjectName("text_popout_editor")
        editor.setPlainText(text)
        # the caret is placed (at the end, below): a column picked from the
        # menu goes where it is rather than on a fresh line
        editor.caret_placed = True
        if placeholder:
            editor.setPlaceholderText(placeholder)
        editor.setReadOnly(read_only)
        self.editor = editor
        self._assist_editor(editor, columns)
        self.find_bar = FindBar(editor, self)

        self.status = QLabel()
        self.status.setObjectName("text_popout_status")
        self.status.setTextInteractionFlags(Qt.TextSelectableByMouse)

        layout = QVBoxLayout(self)
        layout.addWidget(editor, 1)
        layout.addWidget(self.find_bar)
        layout.addWidget(self.status)
        row = QHBoxLayout()
        if picker is not None:
            row.addWidget(picker)
        row.addStretch(1)
        if read_only:
            buttons = QDialogButtonBox(QDialogButtonBox.Close)
        else:
            hint = QLabel(self.HINT)
            hint.setObjectName("text_popout_hint")
            hint.setEnabled(False)
            row.addWidget(hint)
            buttons = QDialogButtonBox(QDialogButtonBox.Ok
                                       | QDialogButtonBox.Cancel)
            for keys in ("Ctrl+Return", "Ctrl+Enter"):
                QShortcut(QKeySequence(keys), self, activated=self.accept)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self._discard)
        row.addWidget(buttons)
        layout.addLayout(row)

        for keys, slot in (
                ("Ctrl+F", lambda: self.find_bar.open_bar()),
                ("Ctrl+H", lambda: self.find_bar.open_bar(replace=True)),
                ("F3", lambda: self._find_again()),
                ("Shift+F3", lambda: self._find_again(backwards=True)),
                ("F11", lambda: self.toggle_maximized())):
            QShortcut(QKeySequence(keys), self, slot).setContext(
                Qt.WidgetWithChildrenShortcut)

        self._lint_timer = QTimer(self)
        self._lint_timer.setSingleShot(True)
        self._lint_timer.setInterval(LINT_DELAY_MS)
        self._lint_timer.timeout.connect(self.run_lint)
        editor.textChanged.connect(self._lint_timer.start)
        self.run_lint()

        self.resize(self.DEFAULT_SIZE)
        self._restore_geometry()
        cursor = editor.textCursor()
        cursor.movePosition(QTextCursor.End)
        editor.setTextCursor(cursor)
        editor.setFocus()

    # ------------------------------------------------------- the window

    def toggle_maximized(self) -> None:
        """F11, and the title bar's button by another route. Not full
        screen proper: a maximized window keeps its title bar, and losing
        that in a modal dialog leaves no obvious way back."""
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()

    def _restore_geometry(self) -> None:
        """Open where the last one was left. Size and place, not contents:
        every pop-out shares the key, because they are one window doing one
        job (see GEOMETRY_KEY)."""
        settings = QSettings(_ORG, _APP)
        stored = settings.value(GEOMETRY_KEY)
        if isinstance(stored, QByteArray) and not stored.isEmpty():
            self.restoreGeometry(stored)
        if settings.value(MAXIMIZED_KEY, False, type=bool):
            self.showMaximized()

    def done(self, result: int) -> None:
        settings = QSettings(_ORG, _APP)
        settings.setValue(MAXIMIZED_KEY, self.isMaximized())
        # the *normal* geometry, so un-maximizing lands back on a sensible
        # window rather than on whatever size it was before it was grown
        settings.setValue(GEOMETRY_KEY, self.saveGeometry())
        super().done(result)

    def _assist_editor(self, editor: CodeEditor, columns: list) -> None:
        """Highlighting and completion for what is being edited: the box's
        own words and the columns coming in. The code pop-out swaps in the
        Python ones (editor/code_popout)."""
        editor.set_highlighter(RulesHighlighter(
            editor.document(), self.assist.keywords, columns))
        self.completer = WordCompleter(editor, self.assist.keywords, columns,
                                       self.assist.quote)

    # ---------------------------------------------------------------- lint

    def run_lint(self) -> None:
        lint = self.assist.lint
        if lint is None:
            self.editor.set_diagnostics([])
            self.status.setText("")
            return
        try:
            found = list(lint(self.editor.toPlainText(), self._sample))
        except Exception as exc:  # a lint must never cost the user the editor
            self.editor.set_diagnostics([])
            self._say(f"Couldn't check this text ({exc})", WARNING_INK)
            return
        self.editor.set_diagnostics(found)
        if not found:
            unchecked = "" if self._sample is not None else self.UNCHECKED
            self._say(f"✓ No problems found{unchecked}", OK_INK)
            return
        errors = sum(1 for d in found if d.severity == "error")
        warnings = len(found) - errors
        counts = ", ".join(part for part in (
            f"{errors} error{'s' * (errors != 1)}" if errors else "",
            f"{warnings} warning{'s' * (warnings != 1)}" if warnings else "")
            if part)
        first = found[0]
        self._say(f"{counts} — line {first.line}: {first.message}",
                  ERROR_INK if errors else WARNING_INK)

    def _say(self, text: str, ink: str) -> None:
        self.status.setText(text)
        self.status.setStyleSheet(f"color: {ink};")

    # ------------------------------------------------------------- closing

    def _find_again(self, backwards: bool = False) -> None:
        if self.find_bar.isHidden():
            self.find_bar.open_bar()
        else:
            self.find_bar.find_next(backwards=backwards)

    def reject(self) -> None:
        """Esc: shut the find bar first if it's open, then ask before losing
        edits."""
        if not self.find_bar.isHidden():
            self.find_bar.close_bar()
            self.editor.setFocus()
            return
        self._discard()

    def _discard(self) -> None:
        if (not self.editor.isReadOnly()
                and self.editor.toPlainText() != self._original):
            answer = QMessageBox.question(
                self, "Discard changes?",
                "Close without keeping the changes you made here?",
                QMessageBox.Discard | QMessageBox.Cancel, QMessageBox.Cancel)
            if answer != QMessageBox.Discard:
                return
        super().reject()
