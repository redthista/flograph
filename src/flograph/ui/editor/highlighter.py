"""Python syntax highlighting for the node code editor."""
from __future__ import annotations

import builtins
import keyword
import re

from PySide6.QtCore import Qt
from PySide6.QtGui import (
    QColor, QFont, QSyntaxHighlighter, QTextCharFormat, QTextDocument,
)


def _fmt(color: str, bold: bool = False, italic: bool = False) -> QTextCharFormat:
    fmt = QTextCharFormat()
    fmt.setForeground(QColor(color))
    if bold:
        fmt.setFontWeight(QFont.Bold)
    if italic:
        fmt.setFontItalic(True)
    return fmt


COLORS = {
    "keyword": _fmt("#c678dd", bold=True),
    "builtin": _fmt("#56b6c2"),
    "self": _fmt("#e06c75", italic=True),
    "def_name": _fmt("#61afef", bold=True),
    "decorator": _fmt("#e5c07b"),
    "string": _fmt("#98c379"),
    "number": _fmt("#d19a66"),
    "comment": _fmt("#5c6370", italic=True),
}

_STATE_NONE = -1
_STATE_TRIPLE_SINGLE = 1
_STATE_TRIPLE_DOUBLE = 2


class PythonHighlighter(QSyntaxHighlighter):
    def __init__(self, document: QTextDocument) -> None:
        super().__init__(document)
        kw = "|".join(keyword.kwlist)
        bi = "|".join(n for n in dir(builtins) if not n.startswith("_"))
        self._rules: list[tuple[re.Pattern, QTextCharFormat]] = [
            (re.compile(rf"\b(?:{kw})\b"), COLORS["keyword"]),
            (re.compile(rf"\b(?:{bi})\b"), COLORS["builtin"]),
            (re.compile(r"\b(?:self|cls|ctx)\b"), COLORS["self"]),
            (re.compile(r"\bdef\s+(\w+)|\bclass\s+(\w+)"), COLORS["def_name"]),
            (re.compile(r"@\w+(?:\.\w+)*"), COLORS["decorator"]),
            (re.compile(r"\b\d+(?:\.\d*)?(?:[eE][+-]?\d+)?\b|\b0[xXbBoO][0-9a-fA-F]+\b"),
             COLORS["number"]),
            (re.compile(r"(?:[rbfu]{0,2})'[^'\\\n]*(?:\\.[^'\\\n]*)*'|"
                        r'(?:[rbfu]{0,2})"[^"\\\n]*(?:\\.[^"\\\n]*)*"'),
             COLORS["string"]),
        ]
        self._comment = re.compile(r"#[^\n]*")
        self._triple_single = re.compile(r"'''")
        self._triple_double = re.compile(r'"""')

    def highlightBlock(self, text: str) -> None:
        for pattern, fmt in self._rules:
            for match in pattern.finditer(text):
                if match.lastindex:  # def/class: highlight the name group
                    for gi in range(1, (match.lastindex or 0) + 1):
                        if match.group(gi):
                            self.setFormat(match.start(gi),
                                           match.end(gi) - match.start(gi), fmt)
                else:
                    self.setFormat(match.start(), match.end() - match.start(), fmt)

        for match in self._comment.finditer(text):
            self.setFormat(match.start(), match.end() - match.start(),
                           COLORS["comment"])

        self._highlight_multiline(text)

    def _highlight_multiline(self, text: str) -> None:
        """Triple-quoted strings across blocks using block state."""
        self.setCurrentBlockState(_STATE_NONE)
        start = 0
        state = self.previousBlockState()

        while start < len(text) or (start == 0 and text == ""):
            if state in (_STATE_TRIPLE_SINGLE, _STATE_TRIPLE_DOUBLE):
                delim = self._triple_single if state == _STATE_TRIPLE_SINGLE \
                    else self._triple_double
                match = delim.search(text, start)
                if match is None:
                    self.setFormat(start, len(text) - start, COLORS["string"])
                    self.setCurrentBlockState(state)
                    return
                self.setFormat(start, match.end() - start, COLORS["string"])
                start = match.end()
                state = _STATE_NONE
            else:
                single = self._triple_single.search(text, start)
                double = self._triple_double.search(text, start)
                candidates = [(m, s) for m, s in
                              ((single, _STATE_TRIPLE_SINGLE),
                               (double, _STATE_TRIPLE_DOUBLE)) if m]
                if not candidates:
                    return
                match, new_state = min(candidates, key=lambda pair: pair[0].start())
                start = match.start()
                # skip if inside a comment
                comment_pos = text.find("#")
                if 0 <= comment_pos < start:
                    return
                inner = match.end()
                state = new_state
                # highlight opening delimiter onwards; loop handles closing
                closing = (self._triple_single if new_state == _STATE_TRIPLE_SINGLE
                           else self._triple_double).search(text, inner)
                if closing is None:
                    self.setFormat(start, len(text) - start, COLORS["string"])
                    self.setCurrentBlockState(new_state)
                    return
                self.setFormat(start, closing.end() - start, COLORS["string"])
                start = closing.end()
                state = _STATE_NONE
            if text == "":
                break
