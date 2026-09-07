"""CodeEditor: QPlainTextEdit with a line-number gutter, current-line
highlight, auto-indent, comment toggling, and an error-line marker."""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QMimeData, QRect, QSize, Qt
from PySide6.QtGui import (
    QColor, QFontDatabase, QKeyEvent, QPainter, QTextCursor, QTextFormat,
)
from PySide6.QtWidgets import QPlainTextEdit, QTextEdit, QWidget

from .highlighter import PythonHighlighter

GUTTER_BG = QColor("#202226")
GUTTER_FG = QColor("#5c6370")
GUTTER_FG_CURRENT = QColor("#9ca3af")
CURRENT_LINE_BG = QColor("#24262d")
ERROR_LINE_BG = QColor("#4b1d24")
MATCH_BG = QColor("#3b4a2a")          # every hit while the find bar is open
CURRENT_MATCH_BG = QColor("#6b5a1a")  # the one Enter/F3 just landed on
ERROR_DOT = QColor("#ef4444")
INDENT = "    "


class _Gutter(QWidget):
    def __init__(self, editor: "CodeEditor") -> None:
        super().__init__(editor)
        self._editor = editor

    def sizeHint(self) -> QSize:
        return QSize(self._editor.gutter_width(), 0)

    def paintEvent(self, event) -> None:
        self._editor.paint_gutter(event)


class CodeEditor(QPlainTextEdit):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        font = QFontDatabase.systemFont(QFontDatabase.FixedFont)
        font.setPointSizeF(10.0)
        self.setFont(font)
        self.setTabStopDistance(self.fontMetrics().horizontalAdvance(" ") * 4)
        self.setLineWrapMode(QPlainTextEdit.NoWrap)

        self.highlighter = PythonHighlighter(self.document())
        self._gutter = _Gutter(self)
        self._error_line: Optional[int] = None
        # (cursor, is_current) pairs owned by the find bar; empty when it's shut
        self._search_hits: list[tuple[QTextCursor, bool]] = []

        self.blockCountChanged.connect(self._update_gutter_width)
        self.updateRequest.connect(self._update_gutter_area)
        self.cursorPositionChanged.connect(self._update_extra_selections)
        self._update_gutter_width()
        self._update_extra_selections()

    # ----------------------------------------------------------- clipboard

    def createMimeDataFromSelection(self) -> QMimeData:
        """The selection, as preformatted HTML as well as plain text.

        A QPlainTextEdit puts only `text/plain` on the clipboard. Every
        rich destination — an email, a Word document, a chat box — then
        converts that to HTML itself, and HTML collapses runs of spaces, so
        the indentation is gone before the recipient sees it and Python
        arrives as one flat unreadable block. "Paste as unformatted" was
        the workaround, and it worked for the wrong reason: it takes the
        same plain flavour and drops it somewhere already monospaced.

        Offering an HTML flavour of our own settles it — `<pre>` says the
        whitespace is load-bearing, which is the one thing the destination
        could not know. The plain flavour is untouched, so pasting into a
        terminal or another editor is exactly as it was.

        Deliberately no syntax colours. The highlighter's palette is built
        to sit on the editor's #202226, and a mail client that keeps
        foreground colours while dropping the background — which is the
        common case — would print pale grey keywords onto white paper.

        Built fresh rather than by amending Qt's: the QMimeData a text
        widget hands back is lazy, regenerating each flavour from the
        document fragment when it is asked for, so `setHtml` on it is
        silently discarded. Building the object also drops the `text/
        markdown` and OpenDocument flavours it offers, which is the point
        — those are what a word processor reaches for first, and both lose
        the indentation exactly as the generated HTML did.
        """
        cursor = self.textCursor()
        if not cursor.hasSelection():
            return super().createMimeDataFromSelection()
        # selectedText() joins blocks with U+2029, not "\n" — pasting that
        # verbatim would put the whole selection on one line
        text = cursor.selectedText().replace(" ", "\n")
        escaped = (text.replace("&", "&amp;")
                       .replace("<", "&lt;")
                       .replace(">", "&gt;"))
        mime = QMimeData()
        mime.setText(text)
        mime.setHtml(
            f'<pre style="font-family:\'{self.font().family()}\',Consolas,'
            f'\'Courier New\',monospace; font-size:10pt; '
            f'white-space:pre">{escaped}</pre>')
        return mime

    # -------------------------------------------------------------- errors

    def set_error_line(self, line: Optional[int]) -> None:
        """1-based line to mark as the failure site, or None to clear."""
        self._error_line = line
        self._update_extra_selections()
        self._gutter.update()

    # -------------------------------------------------------------- search

    def set_search_highlights(
            self, hits: list[tuple[QTextCursor, bool]]) -> None:
        """Paint every find-bar match, the current one more strongly. Routed
        through the editor rather than set directly because extra selections
        are a single list — the current-line and error-line marks would wipe
        each other out otherwise."""
        self._search_hits = list(hits)
        self._update_extra_selections()

    # -------------------------------------------------------------- gutter

    def gutter_width(self) -> int:
        digits = max(2, len(str(max(1, self.blockCount()))))
        return 14 + self.fontMetrics().horizontalAdvance("9") * digits

    def _update_gutter_width(self) -> None:
        self.setViewportMargins(self.gutter_width(), 0, 0, 0)

    def _update_gutter_area(self, rect: QRect, dy: int) -> None:
        if dy:
            self._gutter.scroll(0, dy)
        else:
            self._gutter.update(0, rect.y(), self._gutter.width(), rect.height())
        if rect.contains(self.viewport().rect()):
            self._update_gutter_width()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        rect = self.contentsRect()
        self._gutter.setGeometry(
            QRect(rect.left(), rect.top(), self.gutter_width(), rect.height()))

    def paint_gutter(self, event) -> None:
        painter = QPainter(self._gutter)
        painter.fillRect(event.rect(), GUTTER_BG)
        block = self.firstVisibleBlock()
        block_number = block.blockNumber()
        top = round(self.blockBoundingGeometry(block)
                    .translated(self.contentOffset()).top())
        bottom = top + round(self.blockBoundingRect(block).height())
        current = self.textCursor().blockNumber()

        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                number = block_number + 1
                painter.setPen(GUTTER_FG_CURRENT if block_number == current
                               else GUTTER_FG)
                painter.drawText(0, top, self._gutter.width() - 6,
                                 self.fontMetrics().height(),
                                 Qt.AlignRight, str(number))
                if self._error_line == number:
                    painter.setBrush(ERROR_DOT)
                    painter.setPen(Qt.NoPen)
                    painter.drawEllipse(3, top + self.fontMetrics().height() // 2 - 3,
                                        6, 6)
            block = block.next()
            top = bottom
            bottom = top + round(self.blockBoundingRect(block).height())
            block_number += 1

    # ---------------------------------------------------- extra selections

    def _update_extra_selections(self) -> None:
        selections = []

        current = QTextEdit.ExtraSelection()
        current.format.setBackground(CURRENT_LINE_BG)
        current.format.setProperty(QTextFormat.FullWidthSelection, True)
        current.cursor = self.textCursor()
        current.cursor.clearSelection()
        selections.append(current)

        if self._error_line is not None:
            block = self.document().findBlockByNumber(self._error_line - 1)
            if block.isValid():
                error = QTextEdit.ExtraSelection()
                error.format.setBackground(ERROR_LINE_BG)
                error.format.setProperty(QTextFormat.FullWidthSelection, True)
                error.cursor = QTextCursor(block)
                selections.append(error)

        # last, so a match stays visible on the current and error lines
        for cursor, is_current in self._search_hits:
            hit = QTextEdit.ExtraSelection()
            hit.format.setBackground(CURRENT_MATCH_BG if is_current else MATCH_BG)
            hit.cursor = cursor
            selections.append(hit)

        self.setExtraSelections(selections)
        self._gutter.update()

    # ------------------------------------------------------------ keyboard

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() in (Qt.Key_Return, Qt.Key_Enter) \
                and not event.modifiers() & Qt.ControlModifier:
            self._auto_indent_newline()
            return
        if event.key() == Qt.Key_Tab:
            self._indent_selection()
            return
        if event.key() == Qt.Key_Backtab:
            self._dedent_selection()
            return
        if event.key() == Qt.Key_Slash and event.modifiers() & Qt.ControlModifier:
            self._toggle_comment()
            return
        super().keyPressEvent(event)

    def _auto_indent_newline(self) -> None:
        cursor = self.textCursor()
        line = cursor.block().text()[:cursor.positionInBlock()]
        indent = line[:len(line) - len(line.lstrip())]
        if line.rstrip().endswith(":"):
            indent += INDENT
        cursor.insertText("\n" + indent)

    def _selected_blocks(self) -> tuple[QTextCursor, int, int]:
        cursor = self.textCursor()
        doc = self.document()
        start = doc.findBlock(cursor.selectionStart()).blockNumber()
        end = doc.findBlock(cursor.selectionEnd()).blockNumber()
        return cursor, start, end

    def _for_each_selected_line(self, transform) -> None:
        cursor, start, end = self._selected_blocks()
        cursor.beginEditBlock()
        doc = self.document()
        for line_no in range(start, end + 1):
            block = doc.findBlockByNumber(line_no)
            line_cursor = QTextCursor(block)
            line_cursor.select(QTextCursor.LineUnderCursor)
            line_cursor.insertText(transform(block.text()))
        cursor.endEditBlock()

    def _indent_selection(self) -> None:
        if not self.textCursor().hasSelection():
            self.textCursor().insertText(INDENT)
            return
        self._for_each_selected_line(lambda text: INDENT + text)

    def _dedent_selection(self) -> None:
        def dedent(text: str) -> str:
            if text.startswith(INDENT):
                return text[len(INDENT):]
            return text.lstrip() if text[:1] in (" ", "\t") else text
        self._for_each_selected_line(dedent)

    def _toggle_comment(self) -> None:
        _, start, end = self._selected_blocks()
        doc = self.document()
        lines = [doc.findBlockByNumber(i).text() for i in range(start, end + 1)]
        non_empty = [l for l in lines if l.strip()]
        all_commented = bool(non_empty) and all(
            l.lstrip().startswith("#") for l in non_empty)

        def toggle(text: str) -> str:
            if not text.strip():
                return text
            stripped = text.lstrip()
            indent = text[:len(text) - len(stripped)]
            if all_commented:
                rest = stripped[1:]
                return indent + (rest[1:] if rest.startswith(" ") else rest)
            return indent + "# " + stripped

        self._for_each_selected_line(toggle)
