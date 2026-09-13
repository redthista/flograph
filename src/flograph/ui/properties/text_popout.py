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

from PySide6.QtCore import QPointF, Qt, QTimer
from PySide6.QtGui import (
    QColor, QIcon, QKeySequence, QPainter, QPen, QPixmap, QPolygonF, QShortcut,
    QTextCursor,
)
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QMessageBox, QVBoxLayout,
    QWidget,
)

from flograph.core.text_assist import TextAssist
from ..editor.code_editor import CodeEditor
from ..editor.find_bar import FindBar
from ..editor.rules_highlighter import RulesHighlighter
from ..editor.word_completion import WordCompleter

LINT_DELAY_MS = 300
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

    HINT = ("Ctrl+Space completes · Ctrl+F finds · "
            "Alt+Click adds a caret · Ctrl+Enter applies")
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
                ("Shift+F3", lambda: self._find_again(backwards=True))):
            QShortcut(QKeySequence(keys), self, slot).setContext(
                Qt.WidgetWithChildrenShortcut)

        self._lint_timer = QTimer(self)
        self._lint_timer.setSingleShot(True)
        self._lint_timer.setInterval(LINT_DELAY_MS)
        self._lint_timer.timeout.connect(self.run_lint)
        editor.textChanged.connect(self._lint_timer.start)
        self.run_lint()

        self.resize(820, 560)
        cursor = editor.textCursor()
        cursor.movePosition(QTextCursor.End)
        editor.setTextCursor(cursor)
        editor.setFocus()

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
