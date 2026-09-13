"""Highlighting for the small languages in node text boxes — rules,
expressions, checks — as opposed to highlighter.py's Python.

It knows no grammar, only words: the box's keywords, the columns arriving
at the node, quoted text, numbers, the operators and `#` comments. That is
enough to see at a glance that `unit price` was read as a column and that a
typo was not."""
from __future__ import annotations

import re
from typing import Iterable

from PySide6.QtGui import QSyntaxHighlighter, QTextDocument

from .highlighter import COLORS, _fmt

# blue, not One Dark's yellow: on the editor's dark ground that yellow sits
# too close to plain text, and a column read as one is the thing to see
COLUMN = _fmt("#61afef")
OPERATOR = _fmt("#9da5b4")
ARROW = _fmt("#c678dd", bold=True)


def _alternation(words: Iterable[str]) -> str:
    # longest first, so `is not empty` is never read as `is`; a space in a
    # keyword matches any run of spaces
    ordered = sorted({w for w in words if w}, key=len, reverse=True)
    return "|".join(re.escape(w).replace(r"\ ", r"\s+") for w in ordered)


class RulesHighlighter(QSyntaxHighlighter):
    def __init__(self, document: QTextDocument, keywords: Iterable[str] = (),
                 columns: Iterable[str] = ()) -> None:
        super().__init__(document)
        words = _alternation(keywords)
        self._keywords = (re.compile(rf"(?<![\w@])(?:{words})(?!\w)", re.IGNORECASE)
                          if words else None)
        self._columns = None
        self._number = re.compile(r"(?<![\w#.])-?\d+(?:\.\d+)?%?(?![\w.])")
        self._operator = re.compile(r">=|<=|!=|==|[=<>|&+*/-]")
        self._arrow = re.compile(r"=>")
        self._string = re.compile(r'"[^"]*"|\'[^\']*\'|`[^`]*`')
        # a whole-line comment, or a `# ` after a space — never a hex colour
        self._comment = re.compile(r"^\s*#.*$|(?<=\s)#(?=\s|$).*$")
        self.set_columns(columns)

    def set_columns(self, columns: Iterable[str]) -> None:
        names = _alternation(str(c) for c in columns)
        self._columns = (re.compile(rf"(?<!\w)(?:{names})(?!\w)")
                         if names else None)
        self.rehighlight()

    def highlightBlock(self, text: str) -> None:
        def paint(pattern, fmt) -> None:
            if pattern is None:
                return
            for match in pattern.finditer(text):
                self.setFormat(match.start(), match.end() - match.start(), fmt)

        # later wins: a keyword inside quotes is text, and so is a comment
        paint(self._operator, OPERATOR)
        paint(self._arrow, ARROW)
        paint(self._number, COLORS["number"])
        paint(self._keywords, COLORS["keyword"])
        paint(self._columns, COLUMN)
        paint(self._string, COLORS["string"])
        paint(self._comment, COLORS["comment"])
