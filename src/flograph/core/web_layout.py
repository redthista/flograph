"""A report page's web shape: sections that fold, tabs, and how it is found
your way around — Qt-free.

Two halves, both here because both are about the Markdown and neither
needs Qt:

**Blocks in the text.** A fenced *container*, the `:::` of VitePress,
markdown-it-container and pandoc's fenced divs, because that is what anyone
who has written docs will try, and because it nests — a folded section can
hold a ```columns block, and a tab a chart grid::

    ::: details Notes on the method|open
    Anything, embeds included.
    :::

    ::: tabs Region
    == North
    ![[North sales|live]]
    == South
    ![[South sales|live]]
    :::

`details` folds; `|open` starts it open. `tabs` shows one of its `== Name`
parts at a time; its own name (optional) is what the page address calls it.

Qt's Markdown reader keeps none of this — it drops every <div>, <details>
and attribute on the way through QTextDocument — so on the web each edge of
a block goes through as a paragraph holding a token, the device page breaks
and embeds already use, and ui/report/web_layout.py swaps the tokens for the
real elements in the finished HTML. On paper there is nothing to fold or
click, so a block is written out whole: its title in bold over its body,
and every tab one after another under its name.

**The page's settings** (`WebSettings`), saved with the page: a sidebar of
its headings, a bar across the top, how wide the text runs, and whether the
address keeps what is open. Only a web page has them; the PDF ignores them.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

#: The token each edge of a block becomes on the web. `{}` is the block's
#: number and, for a tab, `N-K` — its block and its place in it.
BLOCK_TOKEN = "@@flograph-block-{}-{}@@"
#: The same tokens, found again in Qt's HTML: always a paragraph of their
#: own, so the <p> is taken with them — and the <span> Qt sets the page's
#: font on inside it.
BLOCK_P_RE = re.compile(
    r"<p\b[^>]*>\s*(?:<span\b[^>]*>\s*)*"
    r"@@flograph-block-(open|tab|close)-(\d+)(?:-(\d+))?@@"
    r"\s*(?:</span>\s*)*</p>", re.IGNORECASE)

KINDS = ("details", "tabs")

_OPEN_RE = re.compile(r"^[ \t]{0,3}:{3,}[ \t]*(\w+)[ \t]*(.*?)[ \t]*$")
_CLOSE_RE = re.compile(r"^[ \t]{0,3}:{3,}[ \t]*$")
_TAB_RE = re.compile(r"^[ \t]{0,3}==[ \t]+(.+?)[ \t]*$")
_FENCE_RE = re.compile(r"^[ \t]{0,3}(```|~~~)[ \t]*(\w*)")


@dataclass
class Block:
    """One `:::` block, in the order they open."""
    kind: str                 # "details" | "tabs"
    title: str = ""
    open: bool = False        # details: starts open
    tabs: list = field(default_factory=list)   # tabs: each part's name


def _title_and_flags(rest: str) -> "tuple[str, set]":
    parts = [part.strip() for part in rest.split("|")]
    title = parts[0]
    flags = {part.lower() for part in parts[1:] if part}
    return title, flags


def expand_blocks(text: str, web: bool, blocks: "list | None" = None) -> str:
    """Every `:::` block in `text` made into what the target can show.

    `web` writes the block tokens and appends a `Block` to `blocks` for
    each one; otherwise each block is written out flat for paper. Text in
    a code fence is left alone — writing `::: details` in a code block is
    how a report explains the syntax — but a ```columns block is not code,
    and a block may sit inside one of its columns.

    A block nobody closed ends with the text: the reader sees what they
    wrote rather than losing everything under a missing `:::`. A `:::` with
    nothing open, or a kind this does not know, is left as it was.
    """
    if not text or ":::" not in text:
        return text or ""
    if blocks is None:
        blocks = []
    out: list = []
    stack: list = []          # (number, Block)
    fence = None              # the open fence's marks, or None
    fence_is_code = False
    for line in text.split("\n"):
        if fence is not None:
            if re.match(r"^[ \t]{0,3}" + re.escape(fence) + r"[ \t]*$", line):
                fence = None
                out.append(line)
                continue
            if fence_is_code:
                out.append(line)
                continue
        else:
            opened = _FENCE_RE.match(line)
            if opened:
                fence = opened.group(1)
                fence_is_code = opened.group(2).lower() != "columns"
                out.append(line)
                continue
        tab = _TAB_RE.match(line)
        if tab and stack and stack[-1][1].kind == "tabs":
            number, block = stack[-1]
            block.tabs.append(tab.group(1))
            if web:
                out.append(_token_line("tab", f"{number}-{len(block.tabs) - 1}"))
            else:
                out.append(f"\n\n**{_bold_safe(tab.group(1))}**\n\n")
            continue
        if _CLOSE_RE.match(line):
            if not stack:
                out.append(line)
                continue
            number, block = stack.pop()
            if web:
                out.append(_token_line("close", number))
            else:
                out.append("\n")
            continue
        opened = _OPEN_RE.match(line)
        if opened and opened.group(1).lower() in KINDS:
            kind = opened.group(1).lower()
            title, flags = _title_and_flags(opened.group(2))
            block = Block(kind=kind, title=title, open="open" in flags)
            number = len(blocks)
            blocks.append(block)
            stack.append((number, block))
            if web:
                out.append(_token_line("open", number))
            elif kind == "details" and title:
                out.append(f"\n\n**{_bold_safe(title)}**\n\n")
            continue
        out.append(line)
    while stack:
        number, _block = stack.pop()
        if web:
            out.append(_token_line("close", number))
    return "\n".join(out)


def _token_line(edge: str, number) -> str:
    # blank lines either side: written tight against a paragraph, Markdown
    # would fold the token into it and it could no longer be found
    return "\n\n" + BLOCK_TOKEN.format(edge, number) + "\n\n"


def _bold_safe(title: str) -> str:
    return title.replace("*", r"\*")


def slug(text: str, used: set) -> str:
    """An id for `text` that no other one on the page has: lower case,
    words joined by hyphens, and `-2`, `-3`… on a repeat. The same text in
    the same order always gets the same id, so an address copied today
    still opens the same tab after the next run."""
    base = re.sub(r"[^\w]+", "-", text.lower(), flags=re.UNICODE).strip("-_")
    base = base or "section"
    candidate, count = base, 1
    while candidate in used:
        count += 1
        candidate = f"{base}-{count}"
    used.add(candidate)
    return candidate


# ---------------------------------------------------------------- settings

SIDEBAR = ("off", "open", "closed")
#: Content widths offered, in CSS pixels; 0 is the whole window.
WIDTHS = (0, 1400, 1100, 820)


@dataclass
class WebSettings:
    """How a report page's web version is laid out. Defaults are the page as
    it was before any of this existed: no sidebar, no bar, full width.

    Where the way round is, and how the page is cut up, are separate
    choices, so any mix of them works:

    - `sidebar` lists the page's headings down the left and starts `open`
      or `closed` (behind a button); `depth` is how many levels it lists,
      0 for every one there is.
    - `topbar` is a bar across the top naming the page's top-level
      sections. With both, `split` has the bar take the top level and the
      sidebar only what is under the section being read — the shape of a
      documentation site. `menus` gives each section in the bar a
      drop-down of the headings inside it.
    - `paged` shows one top-level section at a time, like the pages of a
      site, from whichever of the two is there.

    `width` holds the text to a column that many pixels wide, 0 for the
    window. `share_state` keeps the open page, tab and sections and the
    place in the page's address, so a copied link opens where it was
    copied from.
    """
    sidebar: str = "off"
    depth: int = 0
    topbar: bool = False
    menus: bool = False
    split: bool = True
    paged: bool = False
    width: int = 0
    share_state: bool = True

    def to_dict(self) -> dict:
        """Only what differs from the defaults, like PageSetup's."""
        default = WebSettings()
        return {name: value for name, value in self.__dict__.items()
                if value != getattr(default, name)}

    @classmethod
    def from_dict(cls, data) -> "WebSettings":
        if not isinstance(data, dict):
            return cls()
        settings = cls()
        if data.get("sidebar") in SIDEBAR:
            settings.sidebar = data["sidebar"]
        for name in ("topbar", "menus", "split", "paged", "share_state"):
            if name in data:
                setattr(settings, name, bool(data[name]))
        try:
            settings.depth = min(6, max(0, int(data.get("depth", 0))))
        except (TypeError, ValueError):
            pass
        try:
            settings.width = max(0, int(data.get("width", 0)))
        except (TypeError, ValueError):
            pass
        return settings

    def copy(self) -> "WebSettings":
        return WebSettings(**self.__dict__)

    def is_default(self) -> bool:
        return not self.to_dict()

    def has_nav(self) -> bool:
        """A sidebar or a top bar — something to go from page to page by,
        which `paged` needs: without one it is ignored."""
        return self.sidebar != "off" or self.topbar
