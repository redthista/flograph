"""Linting a report page's Markdown and its CSS — Qt-free.

What a report page's two editors underline as they are typed into, with
the same `Diagnostic` (a line, a message, error or warning) and the same
wavy marks the Properties boxes use (ui/editor/diagnostics.py). Errors are
what will go wrong on the page — an embed that names no node, a block
never closed, a brace never matched; warnings are what may not be meant —
an option nothing reads, a stylesheet that would reach the internet.

Both are cheap enough to run on every pause in typing, and neither ever
refuses anything: the page renders whatever is written, and says so.

Each check is careful not to cry wolf. The starter themes and the example
reports lint clean, and a test holds them to it — a lint that marks good
text is one people learn to ignore.
"""
from __future__ import annotations

import re
from typing import Iterable, Optional

from .app_facts import FACTS, PREFIX, fact_name
from .report import EMBED_FLAGS, EMBED_OPTIONS, parse_options
from .text_assist import Diagnostic
from .web_layout import KINDS, _KEYS, _norm


def _line_of(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


# ---------------------------------------------------------------- markdown

_FENCE_RE = re.compile(r"^[ \t]{0,3}(```|~~~)[ \t]*(\w*)")
_OPEN_RE = re.compile(r"^[ \t]{0,3}:{3,}[ \t]*(\w+)")
_CLOSE_RE = re.compile(r"^[ \t]{0,3}:{3,}[ \t]*$")
_TAB_RE = re.compile(r"^[ \t]{0,3}==[ \t]+\S")
_EMBED_RE = re.compile(r"!\[\[\s*([^\]|\n]+?)\s*((?:\|[^\]|\n]*)*)\]\]")
_PAGE_LINK_RE = re.compile(r"\]\((?:<\s*)?page:([^)>\n]*)>?\)", re.IGNORECASE)
_CODE_SPAN_RE = re.compile(r"`+[^`\n]*`+")


def lint_report(text: str, labels: Optional[dict] = None,
                pages: Optional[Iterable[str]] = None) -> list[Diagnostic]:
    """Problems in a report page's Markdown.

    `labels` maps each name an embed may use (a node's label) to the ports
    it has, or to None when they are not known; None skips the names
    altogether — nothing to check them against. `pages` is the project's
    page titles, for `[words](page:Title)` links; None skips those.
    """
    found: list[Diagnostic] = []
    if not text:
        return found
    lines = text.split("\n")
    body_start = _front_matter(lines, found)
    stack: list = []            # (line, kind, parts) of open ::: blocks
    fence = None                # (marks, line, is_columns)
    columns_parts = 0
    for index in range(body_start, len(lines)):
        line = lines[index]
        number = index + 1
        if fence is not None:
            marks, start, is_columns = fence
            if re.match(r"^[ \t]{0,3}" + re.escape(marks) + r"[ \t]*$", line):
                if is_columns and columns_parts < 1:
                    found.append(Diagnostic(
                        start, "a columns block with one column — put --- "
                        "on a line of its own between columns", "warning"))
                fence = None
                continue
            if not is_columns:
                continue
            if re.match(r"^---[ \t]*$", line):
                columns_parts += 1
        else:
            opened = _FENCE_RE.match(line)
            if opened:
                is_columns = opened.group(2).lower() == "columns"
                fence = (opened.group(1), number, is_columns)
                columns_parts = 0
                continue
        if _CLOSE_RE.match(line):
            if stack:
                start, kind, parts = stack.pop()
                if kind == "tabs" and not parts:
                    found.append(Diagnostic(
                        start, "a tabs block with no tabs — start each with "
                        "== and its name", "warning"))
            else:
                found.append(Diagnostic(
                    number, "::: closes nothing — there is no block open "
                    "here", "warning"))
            continue
        opened = _OPEN_RE.match(line)
        if opened:
            kind = opened.group(1).lower()
            if kind in KINDS:
                stack.append([number, kind, 0])
            else:
                found.append(Diagnostic(
                    number, f"::: {opened.group(1)} is not a block — "
                    "details or tabs", "warning"))
            continue
        if _TAB_RE.match(line):
            if stack and stack[-1][1] == "tabs":
                stack[-1][2] += 1
            else:
                found.append(Diagnostic(
                    number, "== starts a tab, but this is not inside a "
                    "::: tabs block", "warning"))
            continue
        _lint_line(line, number, labels, pages, found)
    if fence is not None:
        marks, start, _is_columns = fence
        found.append(Diagnostic(
            start, f"this {marks} block is never closed — everything under "
            "it shows as code", "error"))
    for start, kind, _parts in stack:
        found.append(Diagnostic(
            start, f"this ::: {kind} block is never closed — end it with "
            "::: on a line of its own", "error"))
    return sorted(found, key=lambda d: d.line)


def _lint_line(line: str, number: int, labels, pages, found) -> None:
    # an example in backticks is writing about the syntax, not using it
    plain = _CODE_SPAN_RE.sub(lambda m: " " * len(m.group(0)), line)
    for match in _EMBED_RE.finditer(plain):
        ref = match.group(1).strip()
        port, options, unknown = parse_options(match.group(2))
        fact = fact_name(ref)
        if fact is not None:
            if fact not in FACTS:
                found.append(Diagnostic(
                    number, f"no app fact is called “{ref}” — "
                    + ", ".join(PREFIX + key for key in FACTS), "error"))
            continue
        if labels is not None:
            if ref not in labels:
                found.append(Diagnostic(
                    number, f"no node is called “{ref}” — check the name, "
                    "or pick it from Insert embed", "error"))
                continue
            ports = labels.get(ref)
            if port and ports and port not in ports:
                found.append(Diagnostic(
                    number, f"“{ref}” has no port “{port}” — it has "
                    + ", ".join(ports), "error"))
        for segment in unknown:
            found.append(Diagnostic(
                number, f"“{segment}” is not an embed option — "
                + ", ".join(list(EMBED_OPTIONS) + list(EMBED_FLAGS)),
                "warning"))
    rest = _EMBED_RE.sub(lambda m: " " * len(m.group(0)), plain)
    if "![[" in rest:
        found.append(Diagnostic(
            number, "![[ with no ]] on the same line — an embed is written "
            "![[Name]]", "error"))
    if pages is not None:
        titles = {title.strip().casefold() for title in pages}
        for match in _PAGE_LINK_RE.finditer(plain):
            from urllib.parse import unquote
            target = unquote(match.group(1)).strip()
            if target and target.casefold() not in titles:
                found.append(Diagnostic(
                    number, f"no page is called “{target}”", "warning"))


def _front_matter(lines: list, found: list) -> int:
    """Check the front matter, if the text starts with some; the index of
    the first line after it (0 when there is none)."""
    if not lines or lines[0].strip() != "---":
        return 0
    entries = []
    for index, line in enumerate(lines[1:60], start=1):
        stripped = line.strip()
        if stripped in ("---", "..."):
            if not any(_norm(key) in _KEYS for _n, key, _v in entries):
                return 0            # not front matter — a rule and text
            for number, key, value in entries:
                _lint_setting(number, key, value, found)
            return index + 1
        if not stripped or stripped.startswith("#"):
            continue
        key, colon, value = stripped.partition(":")
        if not colon:
            return 0
        entries.append((index + 1, key.strip(), value.strip()))
    return 0


def _lint_setting(number: int, key: str, value: str, found: list) -> None:
    from .web_layout import WebSettings
    name = _KEYS.get(_norm(key))
    if name is None:
        found.append(Diagnostic(
            number, f"“{key}” is not a setting — title, heading, icon, "
            "sidebar, depth, top bar, menus, split, pages, pager, width, "
            "share", "warning"))
        return
    if name in ("title", "heading", "icon"):
        return
    before = WebSettings()
    # a value that reads differently from a probe of either default was
    # understood; one that changes nothing from both was not
    probe_a, probe_b = before.with_front_matter({key: value}), None
    flipped = WebSettings(sidebar="closed", depth=3, topbar=True, menus=True,
                          split=False, paged="sections", pager=True,
                          width=999, share_state=False)
    probe_b = flipped.with_front_matter({key: value})
    if probe_a == before and probe_b == flipped:
        found.append(Diagnostic(
            number, f"“{value}” is not a value {key} takes", "warning"))


# --------------------------------------------------------------------- css

#: An address a stylesheet would fetch — the saved page fetches nothing, so
#: on a machine with no internet it would simply not be there.
_REMOTE_RE = re.compile(
    r"@import\b|url\(\s*['\"]?\s*(?:https?:)?//", re.IGNORECASE)


def lint_css(text: str) -> list[Diagnostic]:
    """Problems in a report page's CSS. Structural — braces, strings,
    comments, a declaration's `:` and `;` — plus anything that would reach
    the internet; property names and values are the browser's business."""
    found: list[Diagnostic] = []
    if not text:
        return found
    # comments and strings off first, kept to their lines, so a brace or a
    # colon inside one is not read as CSS
    clean = []
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if text.startswith("/*", i):
            end = text.find("*/", i + 2)
            if end == -1:
                found.append(Diagnostic(
                    _line_of(text, i), "this comment is never closed — end "
                    "it with */", "error"))
                clean.append(_blank(text[i:]))
                break
            clean.append(_blank(text[i:end + 2]))
            i = end + 2
            continue
        if ch in "\"'":
            end = i + 1
            while end < n and text[end] != ch and text[end] != "\n":
                end += 2 if text[end] == "\\" else 1
            if end >= n or text[end] != ch:
                found.append(Diagnostic(
                    _line_of(text, i), f"this {ch} string is never closed",
                    "error"))
                # it ends with its line: the line break stays, so every
                # line under it keeps its number
                clean.append("x" * (min(end, n) - i))
                i = end
                continue
            clean.append("x" * (end + 1 - i))
            i = end + 1
            continue
        clean.append(ch)
        i += 1
    css = "".join(clean)

    fetching = set()
    for match in _REMOTE_RE.finditer(text):
        line = _line_of(text, match.start())
        if line in fetching:
            continue                # `@import url(https:…)` is one fetch
        fetching.add(line)
        if css.split("\n")[line - 1].strip():      # not inside a comment
            found.append(Diagnostic(
                line, "this fetches from the internet — a saved report "
                "makes no network calls, so offline it will not load; "
                "put the file's contents in the page instead", "warning"))

    # braces, and each declaration: the text between one {, ; or } and the
    # next. Ended by { it was a selector (a rule inside @media); ended by
    # ; or } it is a declaration, and needs its name: value
    depth = 0
    opened: list = []           # line of each { still open
    paren = 0
    start = 0                   # where the current piece of text began
    for i, ch in enumerate(css):
        if ch == "(":
            paren += 1
        elif ch == ")":
            paren = max(0, paren - 1)
        if paren or ch not in "{};":
            continue
        piece = css[start:i]
        if ch == "{":
            depth += 1
            opened.append(_line_of(css, i))
        elif depth:
            _check_declaration(css, start, piece, found)
        if ch == "}":
            if depth == 0:
                found.append(Diagnostic(
                    _line_of(css, i), "} closes nothing — there is no { "
                    "open here", "error"))
            else:
                depth -= 1
                opened.pop()
        start = i + 1
    for number in opened:
        found.append(Diagnostic(
            number, "this { is never closed — add a } after its rules",
            "error"))
    return sorted(found, key=lambda d: d.line)


#: a line inside a declaration that starts another one: `name:` at its start
_NEXT_DECLARATION_RE = re.compile(r"\n[ \t]*(-{0,2}[A-Za-z][\w-]*)[ \t]*:")


def _check_declaration(css: str, start: int, piece: str, found: list) -> None:
    """One declaration — `piece`, the text before a ; or a } — beginning at
    `start` in `css`."""
    text = piece.strip()
    if not text or text.startswith("@"):
        return
    first = start + (len(piece) - len(piece.lstrip()))
    line = _line_of(css, first)
    if ":" not in text:
        found.append(Diagnostic(
            line, "a declaration is name: value; — this one has no :",
            "error"))
        return
    # another `name:` starting a line after this one's own colon
    following = _NEXT_DECLARATION_RE.search(piece, piece.index(":") + 1)
    if following:
        found.append(Diagnostic(
            _line_of(css, start + following.start() - 1),
            "missing ; at the end of this declaration — the next one is "
            "read as part of it", "error"))


def _blank(chunk: str) -> str:
    """A comment's text as spaces, its line breaks kept."""
    return re.sub(r"[^\n]", " ", chunk)

