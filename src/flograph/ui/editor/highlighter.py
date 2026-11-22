"""Python syntax highlighting for the node code editor."""
from __future__ import annotations

import builtins
import keyword
import re

from PySide6.QtCore import Qt
from PySide6.QtGui import (
    QColor, QFont, QSyntaxHighlighter, QTextCharFormat, QTextDocument,
)

from flograph.ui import theme


def _fmt(color: str, bold: bool = False, italic: bool = False) -> QTextCharFormat:
    fmt = QTextCharFormat()
    fmt.setForeground(QColor(color))
    if bold:
        fmt.setFontWeight(QFont.Bold)
    if italic:
        fmt.setFontItalic(True)
    return fmt


# name: (bold, italic). The colours are the theme's `[syntax]` section.
_SYNTAX = {
    "keyword": (True, False),
    "builtin": (False, False),
    "self": (False, True),
    "def_name": (True, False),
    "decorator": (False, False),
    "string": (False, False),
    "number": (False, False),
    "comment": (False, True),
}

# Formats for the current theme. Rebuilt in place by `apply_mode`, and read
# from here at highlight time (never kept in a rule), so a theme switch only
# has to re-run the highlighters.
COLORS: dict[str, QTextCharFormat] = {}


def apply_mode() -> None:
    for name, (bold, italic) in _SYNTAX.items():
        COLORS[name] = _fmt(theme.ACTIVE.get("syntax", name), bold, italic)


apply_mode()
theme.on_change(apply_mode)

_STATE_NONE = -1
_STATE_TRIPLE_SINGLE = 1
_STATE_TRIPLE_DOUBLE = 2


class PythonHighlighter(QSyntaxHighlighter):
    def __init__(self, document: QTextDocument) -> None:
        super().__init__(document)
        kw = "|".join(keyword.kwlist)
        bi = "|".join(n for n in dir(builtins) if not n.startswith("_"))
        self._rules: list[tuple[re.Pattern, str]] = [
            (re.compile(rf"\b(?:{kw})\b"), "keyword"),
            (re.compile(rf"\b(?:{bi})\b"), "builtin"),
            (re.compile(r"\b(?:self|cls|ctx)\b"), "self"),
            (re.compile(r"\bdef\s+(\w+)|\bclass\s+(\w+)"), "def_name"),
            (re.compile(r"@\w+(?:\.\w+)*"), "decorator"),
            (re.compile(r"\b\d+(?:\.\d*)?(?:[eE][+-]?\d+)?\b|\b0[xXbBoO][0-9a-fA-F]+\b"),
             "number"),
            (re.compile(r"(?:[rbfu]{0,2})'[^'\\\n]*(?:\\.[^'\\\n]*)*'|"
                        r'(?:[rbfu]{0,2})"[^"\\\n]*(?:\\.[^"\\\n]*)*"'),
             "string"),
        ]
        self._comment = re.compile(r"#[^\n]*")
        self._triple_single = re.compile(r"'''")
        self._triple_double = re.compile(r'"""')

    def highlightBlock(self, text: str) -> None:
        for pattern, key in self._rules:
            fmt = COLORS[key]
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
