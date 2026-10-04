"""Colour for a report page's two editors: its Markdown and its CSS.

The Markdown is coloured by what it does on the page — a heading, an
embed (its name bold, its options apart), a `:::` block and its `==` tabs,
code, a link, front matter — so the structure of a long report reads at a
glance, and a typo in an embed stands out because it is not coloured like
one. The spell check still runs over it (MarkdownHighlighter *is* the
spell highlighter, with colour first), since a document has room for one
highlighter only.

The CSS is coloured the way any code editor would: selectors, property
names, values, numbers with their units, comments, strings, `@` rules and
`!important`, and every `#hex`, `rgb()` and `hsl()` colour shown on a
swatch of itself (double-click one to pick another: css_colour_pick.py).

Two palettes, for a light editor and a dark one; `set_dark` swaps them
when the app's theme changes.
"""
from __future__ import annotations

import re

from PySide6.QtGui import QColor, QFont, QSyntaxHighlighter, QTextCharFormat

from flograph.core.css_colour import parse as parse_colour
from flograph.core.report import APP_ONLY_RE

from ..editor.spell_check import SpellHighlighter, opens_or_closes_a_fence

LIGHT = {
    "heading": "#5b4bd6", "mark": "#9aa0ad", "embed": "#0e7490",
    "option": "#b45309", "block": "#be185d", "code": "#15803d",
    "code_bg": "#f1f5f1", "link": "#1d4ed8", "page": "#7c3aed",
    "quote": "#6b7280", "list": "#be185d", "key": "#7c3aed",
    "comment": "#8b95a5",
    # css
    "selector": "#0e7490", "class": "#0e7490", "pseudo": "#be185d",
    "property": "#1d4ed8", "custom": "#7c3aed", "number": "#b45309",
    "string": "#15803d", "at": "#7c3aed", "important": "#dc2626",
    "punct": "#9aa0ad",
}
DARK = {
    "heading": "#a99cff", "mark": "#6b7280", "embed": "#22d3ee",
    "option": "#fbbf24", "block": "#f472b6", "code": "#86efac",
    "code_bg": "#1c2a22", "link": "#93c5fd", "page": "#c4b5fd",
    "quote": "#9ca3af", "list": "#f472b6", "key": "#c4b5fd",
    "comment": "#6b7280",
    "selector": "#67e8f9", "class": "#67e8f9", "pseudo": "#f9a8d4",
    "property": "#93c5fd", "custom": "#c4b5fd", "number": "#fb923c",
    "string": "#86efac", "at": "#c4b5fd", "important": "#f87171",
    "punct": "#6b7280",
}


def _format(color: str, bold: bool = False, italic: bool = False,
            background: str = "") -> QTextCharFormat:
    fmt = QTextCharFormat()
    fmt.setForeground(QColor(color))
    if bold:
        fmt.setFontWeight(QFont.Bold)
    if italic:
        fmt.setFontItalic(True)
    if background:
        fmt.setBackground(QColor(background))
    return fmt


# ---------------------------------------------------------------- markdown

_HEADING_RE = re.compile(r"^(#{1,6})(\s+.*)$")
_BLOCK_RE = re.compile(r"^[ \t]{0,3}:{3,}.*$")
_TAB_RE = re.compile(r"^([ \t]{0,3}==)([ \t]+.*)$")
_QUOTE_RE = re.compile(r"^[ \t]*>.*$")
_LIST_RE = re.compile(r"^[ \t]*([-*+]|\d+[.)])[ \t]")
_RULE_RE = re.compile(r"^[ \t]*(---+|\*\*\*+|___+)[ \t]*$")
_BREAK_RE = re.compile(r"^[ \t]*(\\pagebreak|\\newpage|<!--.*-->)[ \t]*$",
                       re.IGNORECASE)
_EMBED_RE = re.compile(r"(!\[\[)(\s*[^\]|\n]+?\s*)((?:\|[^\]|\n]*)*)(\]\])")
_LINK_RE = re.compile(r"(\[[^\]\n]*\])(\((<?)(page:)?[^)\n]*\))",
                      re.IGNORECASE)
_BOLD_RE = re.compile(r"\*\*[^*\n]+\*\*|__[^_\n]+__")
_ITALIC_RE = re.compile(r"(?<![*\w])\*[^*\n]+\*(?![*\w])|(?<![_\w])_[^_\n]+_(?![_\w])")
_CODE_RE = re.compile(r"`+[^`\n]+`+")
_MATTER_RE = re.compile(r"^(\s*[A-Za-z][\w \-]*?)(\s*:)(.*)$")


class MarkdownHighlighter(SpellHighlighter):
    """A report page's Markdown in colour, spell-checked on top."""

    IN_FRONT = 2        # inside front matter (IN_FENCE, 1, is the parent's)
    IN_COLUMNS = 3      # inside a ```columns block: Markdown, not code

    def __init__(self, document, dark: bool = False, extra=None) -> None:
        super().__init__(document, extra)
        self._palette = DARK if dark else LIGHT
        self._formats = {}
        self._build()

    def set_dark(self, dark: bool) -> None:
        palette = DARK if dark else LIGHT
        if palette is not self._palette:
            self._palette = palette
            self._build()
            self.refresh()

    def _build(self) -> None:
        c = self._palette
        self._formats = {
            "heading": _format(c["heading"], bold=True),
            "mark": _format(c["mark"]),
            "embed": _format(c["embed"]),
            "embed_name": _format(c["embed"], bold=True),
            "option": _format(c["option"]),
            "block": _format(c["block"], bold=True),
            "code": _format(c["code"], background=c["code_bg"]),
            "fence": _format(c["code"]),
            "columns": _format(c["block"]),
            "link": _format(c["link"]),
            "page": _format(c["page"]),
            "quote": _format(c["quote"], italic=True),
            "list": _format(c["list"], bold=True),
            "rule": _format(c["mark"]),
            "key": _format(c["key"], bold=True),
            "bold": QTextCharFormat(),
            "italic": QTextCharFormat(),
        }
        self._formats["bold"].setFontWeight(QFont.Bold)
        self._formats["italic"].setFontItalic(True)

    def _paint(self, start: int, length: int, name: str) -> None:
        """Lay a format over what is there (bold inside a heading keeps the
        heading's colour)."""
        extra = self._formats[name]
        for at in range(start, start + length):
            merged = QTextCharFormat(self.format(at))
            merged.merge(extra)
            self.setFormat(at, 1, merged)

    def highlightBlock(self, text: str) -> None:
        f = self._formats
        previous = self.previousBlockState()
        # front matter: first thing in the text, between two --- lines
        if self.currentBlock().blockNumber() == 0 and text.strip() == "---":
            self.setFormat(0, len(text), f["mark"])
            self.setCurrentBlockState(self.IN_FRONT)
            return
        if previous == self.IN_FRONT:
            if text.strip() in ("---", "..."):
                self.setFormat(0, len(text), f["mark"])
                self.setCurrentBlockState(0)
                return
            match = _MATTER_RE.match(text)
            if match:
                self.setFormat(0, match.end(1), f["key"])
                self.setFormat(match.start(2), len(match.group(2)), f["mark"])
            self.setCurrentBlockState(self.IN_FRONT)
            return
        # code fences. The state is kept here, not by the parent: a
        # ```columns block is layout, not code — its lines are Markdown,
        # coloured and spell-checked — so it needs a state of its own, and
        # Qt re-colours one edited line from its neighbour's state alone
        was_code = previous == self.IN_FENCE
        was_columns = previous == self.IN_COLUMNS
        if opens_or_closes_a_fence(text):
            if was_code or was_columns:
                self.setFormat(0, len(text),
                               f["columns"] if was_columns else f["fence"])
                self.setCurrentBlockState(0)
            else:
                info = text.strip().lstrip("`~").strip().lower()
                columns = info.startswith("columns")
                self.setFormat(0, len(text),
                               f["columns"] if columns else f["fence"])
                self.setCurrentBlockState(
                    self.IN_COLUMNS if columns else self.IN_FENCE)
            return
        if was_code:
            self.setFormat(0, len(text), f["fence"])
            self.setCurrentBlockState(self.IN_FENCE)
            return
        tag = APP_ONLY_RE.match(text)
        if tag:
            self.setFormat(0, tag.end(), self._formats["block"])
            self._line(text[tag.end():], at=tag.end())
        else:
            self._line(text)
        super().highlightBlock(text)        # the spelling, over the colour
        if was_columns:
            self.setCurrentBlockState(self.IN_COLUMNS)

    def _line(self, text: str, at: int = 0) -> None:
        """Colour `text`, which starts `at` characters into the line
        (after an `apponly::` tag, the rest is coloured as a line)."""
        f = self._formats

        def set_format(start, length, fmt):
            self.setFormat(at + start, length, fmt)

        def paint(start, length, name):
            self._paint(at + start, length, name)

        heading = _HEADING_RE.match(text)
        if heading:
            set_format(0, len(text), f["heading"])
            paint(0, len(heading.group(1)), "mark")
        elif _BLOCK_RE.match(text):
            set_format(0, len(text), f["block"])
            bar = text.find("|")
            if bar != -1:
                set_format(bar, len(text) - bar, f["option"])
            return
        elif _TAB_RE.match(text):
            match = _TAB_RE.match(text)
            set_format(0, len(match.group(1)), f["block"])
            set_format(len(match.group(1)), len(match.group(2)),
                       f["block"])
            return
        elif _BREAK_RE.match(text) or _RULE_RE.match(text):
            set_format(0, len(text), f["rule"])
            return
        elif _QUOTE_RE.match(text):
            set_format(0, len(text), f["quote"])
        listed = _LIST_RE.match(text)
        if listed:
            set_format(listed.start(1), len(listed.group(1)), f["list"])
        for match in _BOLD_RE.finditer(text):
            paint(match.start(), match.end() - match.start(), "bold")
        for match in _ITALIC_RE.finditer(text):
            paint(match.start(), match.end() - match.start(), "italic")
        for match in _LINK_RE.finditer(text):
            set_format(match.start(1), len(match.group(1)), f["link"])
            set_format(match.start(2), len(match.group(2)),
                       f["page"] if match.group(4) else f["mark"])
        for match in _EMBED_RE.finditer(text):
            set_format(match.start(1), 3, f["embed"])
            set_format(match.start(2), len(match.group(2)),
                       f["embed_name"])
            if match.group(3):
                set_format(match.start(3), len(match.group(3)),
                           f["option"])
            set_format(match.start(4), 2, f["embed"])
        # last: nothing inside backticks is anything but code
        for match in _CODE_RE.finditer(text):
            set_format(match.start(), match.end() - match.start(),
                       f["code"])


# --------------------------------------------------------------------- css

_CSS_TOKEN_RE = re.compile(
    r"(?P<important>!important)"
    r"|(?P<at>@[\w-]+)"
    r"|(?P<hex>#[0-9a-fA-F]{3,8}\b)"
    r"|(?P<func>\b(?:rgba?|hsla?)\([^()]*\))"
    r"|(?P<var>var\(\s*--[\w-]+\s*\))"
    r"|(?P<number>-?\b\d+(?:\.\d+)?(?:px|em|rem|%|pt|vh|vw|vmin|vmax|ch|ex|s|ms|deg|fr|dpi)?\b|-?\.\d+)"
    r"|(?P<punct>[{}();:,>+~])")
_CSS_PROPERTY_RE = re.compile(r"(?:^|(?<=[;{\s]))(--[\w-]+|-?[A-Za-z][\w-]*)(\s*:)")
_CSS_SELECTOR_BITS_RE = re.compile(r"(?P<class>[.#][\w-]+)|(?P<pseudo>::?[\w-]+(?:\([^)]*\))?)|(?P<attr>\[[^\]]*\])")


class CssHighlighter(QSyntaxHighlighter):
    """A report page's CSS in colour. The block state carries what a line
    needs from the ones before it: how deep in braces it is, and whether a
    comment is still open (`depth * 2 + in_comment`)."""

    def __init__(self, document, dark: bool = False) -> None:
        super().__init__(document)
        self._palette = DARK if dark else LIGHT

    def set_dark(self, dark: bool) -> None:
        palette = DARK if dark else LIGHT
        if palette is not self._palette:
            self._palette = palette
            self.rehighlight()

    def _fmt(self, name: str, **kw) -> QTextCharFormat:
        return _format(self._palette[name], **kw)

    def highlightBlock(self, text: str) -> None:
        state = max(0, self.previousBlockState())
        depth, in_comment = state >> 1, bool(state & 1)
        n = len(text)
        # comments and strings first: nothing inside either is CSS
        masked = list(text)
        i = 0
        while i < n:
            if in_comment:
                end = text.find("*/", i)
                stop = n if end == -1 else end + 2
                self.setFormat(i, stop - i, self._fmt("comment", italic=True))
                for k in range(i, stop):
                    masked[k] = " "
                in_comment = end == -1
                i = stop
                continue
            if text.startswith("/*", i):
                in_comment = True
                continue
            if text[i] in "\"'":
                quote, end = text[i], i + 1
                while end < n and text[end] != quote:
                    end += 2 if text[end] == "\\" else 1
                stop = min(n, end + 1)
                self.setFormat(i, stop - i, self._fmt("string"))
                for k in range(i, stop):
                    masked[k] = " "
                i = stop
                continue
            i += 1
        code = "".join(masked)

        # the selector part of the line: before its first {, at the top
        # level or inside @media — and a line of a selector list (ends ,)
        selector_end = -1
        brace = code.find("{")
        if brace != -1:
            selector_end = brace
        elif depth == 0 or (code.rstrip().endswith(",") and ":" not in code):
            selector_end = len(code)
        if selector_end > 0 and not code[:selector_end].lstrip().startswith("@"):
            start = len(code) - len(code.lstrip())
            self.setFormat(start, selector_end - start, self._fmt("selector"))
            for bit in _CSS_SELECTOR_BITS_RE.finditer(code[:selector_end]):
                kind = bit.lastgroup
                self.setFormat(bit.start(), bit.end() - bit.start(),
                               self._fmt("pseudo" if kind == "pseudo"
                                         else "class", bold=kind == "class"))
        # declarations: property names, then values
        body_from = selector_end + 1 if brace != -1 else (
            0 if selector_end == -1 else len(code))
        for match in _CSS_PROPERTY_RE.finditer(code, max(0, body_from)):
            name = match.group(1)
            self.setFormat(match.start(1), len(name),
                           self._fmt("custom" if name.startswith("--")
                                     else "property"))
        for match in _CSS_TOKEN_RE.finditer(code):
            kind = match.lastgroup
            start, length = match.start(), match.end() - match.start()
            if kind in ("hex", "func"):
                if start < selector_end:
                    continue            # an #id, not a colour
                # read as CSS reads it: Qt takes 8 hex digits as #AARRGGBB,
                # CSS as #RRGGBBAA — the same parser the colour picker uses
                rgba = parse_colour(match.group(0))
                fmt = QTextCharFormat()
                if rgba is not None:
                    swatch = QColor(*rgba)
                    fmt.setBackground(swatch)
                    if rgba[3] >= 128:   # see-through: the editor's own ink
                        fmt.setForeground(QColor(
                            "#000000" if swatch.lightness() > 140
                            else "#ffffff"))
                self.setFormat(start, length, fmt)
            elif kind == "var":
                self.setFormat(start, length, self._fmt("custom"))
            elif kind == "number":
                if start < selector_end:
                    continue
                self.setFormat(start, length, self._fmt("number"))
            elif kind == "important":
                self.setFormat(start, length, self._fmt("important", bold=True))
            elif kind == "at":
                self.setFormat(start, length, self._fmt("at", bold=True))
            elif kind == "punct":
                if start < selector_end and match.group(0) != "{":
                    continue            # a selector's : is its :hover's
                self.setFormat(start, length, self._fmt("punct"))
        for ch in code:
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth = max(0, depth - 1)
        self.setCurrentBlockState(depth * 2 + (1 if in_comment else 0))
