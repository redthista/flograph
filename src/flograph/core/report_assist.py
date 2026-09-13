"""What to offer while a report body is being typed.

The report language is small, but every part of it is a name you have to
remember exactly: a node's label, one of its ports, an embed option, a
page's title. This works out, from the text either side of the caret,
which of those is being typed and what could go there:

    ![[Sa            node labels — "Sales Chart", "Sales Table"
    ![[Sales|        its ports, the options (width=, ratio=, …) and fit
    ![[Sales|ratio=  a few shapes: 16:9, 4:3, …
    [costs](page:    page titles
    ```co            columns
    \\pa             pagebreak

Qt-free, and fed a `Vocabulary` rather than a graph, so the report page and
a Report card — whose embeds also name the card's own input ports — can
each say what their names are. `ui/report/completion.py` is the popup.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import quote, unquote

from .report import EMBED_FLAGS, EMBED_OPTIONS


@dataclass(frozen=True)
class Name:
    """Something an embed can name: a node label, or a card's input port."""
    label: str
    hint: str = ""
    ports: tuple = ()


@dataclass
class Vocabulary:
    names: list = field(default_factory=list)    # [Name]
    pages: list = field(default_factory=list)    # page titles


@dataclass(frozen=True)
class Suggestion:
    text: str            # replaces what has been typed of the word
    hint: str = ""       # shown beside it in the list
    close: str = ""      # appended unless the text after the caret has it
    label: str = ""      # shown and matched instead of `text`, when set


@dataclass
class Completion:
    start: int           # where the word being typed starts, in `before`
    prefix: str          # what has been typed of it
    items: list          # [Suggestion], best match first
    #: False for a context that is also ordinary writing — a code fence, a
    #: backslash — where the list waits for a letter before it opens
    eager: bool = True


#: What each embed option does, in the words of the report reference. A
#: test holds this to core.report's closed set, so a new option cannot
#: arrive without its line here.
OPTION_HINTS = {
    "width": "placement width — 50% of the column, or 280 points",
    "ratio": "the shape a chart is drawn at — 16:9, 4x3, 1.5",
    "height": "an exact height in points; a table shows the rows that fit",
    "scale": "a chart's detail (2 = finer); a table's text size",
    "rows": "how many rows of a table to show",
    "radius": "round a picture's corners, in points",
}
FLAG_HINTS = {
    "fit": "shrink a chart, or trim a table, to the room left on the page",
}
#: A few values worth offering once `key=` is typed. Not a closed list —
#: anything the option accepts can still be typed.
OPTION_VALUES = {
    "width": ("50%", "60%", "75%", "100%", "280"),
    "ratio": ("16:9", "4:3", "3:2", "1:1", "21:9"),
    "height": ("180", "240", "320"),
    "scale": ("2", "1.5", "0.8"),
    "rows": ("10", "30", "50"),
    "radius": ("8", "14"),
}
COMMANDS = {
    "pagebreak": "start a new page",
    "newpage": "start a new page",
}
FENCES = {
    "columns": "side-by-side columns, --- between them",
}

_LABEL_RE = re.compile(r"!\[\[\s*([^\]|\n]*)$")
_SEGMENT_RE = re.compile(
    r"!\[\[\s*([^\]|\n]+?)\s*((?:\|[^\]|\n]*)*)\|([^\]|\n]*)$")
_PAGE_RE = re.compile(r"\]\(page:([^)\s]*)$", re.IGNORECASE)
_ANGLE_PAGE_RE = re.compile(r"<page:([^>\n]*)$", re.IGNORECASE)
_FENCE_RE = re.compile(r"^\s*```([A-Za-z]*)$")
_COMMAND_RE = re.compile(r"^\s*\\([A-Za-z]*)$")


def suggest(before: str, after: str, vocabulary: Vocabulary
            ) -> Optional[Completion]:
    """What could be typed at the caret, or None when nothing is being
    named. `before` and `after` are the caret's line either side of it."""
    fence = _FENCE_RE.search(before)
    if fence:
        return _completion(before, fence.group(1), [
            Suggestion(word, hint) for word, hint in FENCES.items()],
            eager=False)
    command = _COMMAND_RE.search(before)
    if command:
        return _completion(before, command.group(1), [
            Suggestion(word, hint) for word, hint in COMMANDS.items()],
            eager=False)
    if _in_code_span(before):
        # `![[Sales]]` in backticks is a page writing about its own syntax,
        # and stays as typed — nothing to name there
        return None

    segment = _SEGMENT_RE.search(before)
    if segment:
        return _segment(before, after, segment, vocabulary)
    label = _LABEL_RE.search(before)
    if label:
        closed = after.lstrip().startswith(("]]", "|"))
        return _completion(before, label.group(1), [
            Suggestion(name.label, name.hint, "" if closed else "]]")
            for name in vocabulary.names
            if "|" not in name.label and "]" not in name.label])

    page = _PAGE_RE.search(before)
    if page:
        close = "" if after.startswith(")") else ")"
        return _completion(before, page.group(1), [
            Suggestion(quote(title, safe=""), "page", close, label=title)
            for title in vocabulary.pages], match=unquote(page.group(1)))
    page = _ANGLE_PAGE_RE.search(before)
    if page:
        close = "" if after.startswith(">") else ">"
        return _completion(before, page.group(1), [
            Suggestion(title, "", close) for title in vocabulary.pages])
    return None


def _segment(before, after, match, vocabulary) -> Optional[Completion]:
    """After a `|`: a port, an option, a flag — or a value, after `key=`."""
    label, rest, typed = match.group(1), match.group(2), match.group(3)
    if "=" in typed:
        key, value = typed.split("=", 1)
        key = key.strip().lower()
        return _completion(before, value, [
            Suggestion(v, OPTION_HINTS.get(key, ""))
            for v in OPTION_VALUES.get(key, ())])

    used = [part.strip() for part in rest.split("|") if part.strip()]
    keys = {part.split("=", 1)[0].strip().lower()
            for part in used if "=" in part}
    flags = {part.lower() for part in used if part.lower() in EMBED_FLAGS}
    has_port = any("=" not in part and part.lower() not in EMBED_FLAGS
                   for part in used)

    items = []
    if not has_port:
        wanted = label.casefold()
        for name in vocabulary.names:
            if name.label.casefold() == wanted:
                items += [Suggestion(port, "output port")
                          for port in name.ports]
                break
    items += [Suggestion(f"{key}=", OPTION_HINTS.get(key, ""))
              for key in EMBED_OPTIONS if key not in keys]
    items += [Suggestion(flag, FLAG_HINTS.get(flag, ""))
              for flag in EMBED_FLAGS if flag not in flags]
    return _completion(before, typed, items)


def _completion(before, typed, items, eager=True, match=None
                ) -> Optional[Completion]:
    """Keep what matches what has been typed: starts-with first, then
    contains — so `chart` still finds "Sales Chart". `match` is the typed
    text as the entries spell it, when that differs (`Sales%20N`)."""
    prefix = typed.lstrip()
    wanted = (prefix if match is None else match.lstrip()).casefold()

    def key(item):
        return (item.label or item.text).casefold()

    starts = [item for item in items if key(item).startswith(wanted)]
    contains = [item for item in items
                if wanted and wanted in key(item) and item not in starts]
    matched = starts + contains
    # the word is already complete: nothing to offer but itself
    if not matched or (len(matched) == 1 and key(matched[0]) == wanted
                       and not matched[0].close):
        return None
    return Completion(start=len(before) - len(prefix), prefix=prefix,
                      items=matched, eager=eager)


def _in_code_span(before: str) -> bool:
    return before.count("`") % 2 == 1
