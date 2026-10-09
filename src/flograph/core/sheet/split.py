"""Text to Columns, Qt-free: one column's values split into several.

Two ways, as Excel's wizard has them:

* **delimited** — split at any of the separators (``,`` ``;`` tab, space,
  or your own text such as `` - ``). *Merge* treats a run of separators as
  one, so ``"a  b"`` split at spaces is two parts, not three. With a
  *quote* character, ``"Smith, J", 42`` keeps ``Smith, J`` together;
* **fixed** — split at character positions: breaks at 3 and 8 turn
  ``ABC12345XY`` into ``ABC``, ``12345``, ``XY``.

Parts are trimmed of spaces unless asked not to. `split_values` pads every
row to the most parts any row has.
"""
from __future__ import annotations

import re
from typing import Iterable, Optional, Union

MAX_PARTS = 50
SEPARATORS = (("tab", "Tab", "\t"), ("comma", "Comma", ","),
              ("semicolon", "Semicolon", ";"), ("space", "Space", " "))


def split_delimited(text: str, separators: Iterable[str], *,
                    merge: bool = False, quote: str = '"',
                    trim: bool = True) -> list[str]:
    seps = sorted({s for s in separators if s}, key=len, reverse=True)
    if not seps:
        return [text.strip() if trim else text]
    parts: list[str] = []
    field: list[str] = []
    i, n = 0, len(text)
    at_start = True          # at the start of a field (a quote may open)
    after_sep = False
    while i < n:
        if quote and at_start and text[i] == quote:
            # a quoted field: up to the closing quote, "" is a quote
            i += 1
            while i < n:
                if text[i] == quote:
                    if i + 1 < n and text[i + 1] == quote:
                        field.append(quote)
                        i += 2
                        continue
                    i += 1
                    break
                field.append(text[i])
                i += 1
            at_start = False
            after_sep = False
            continue
        sep = next((s for s in seps if text.startswith(s, i)), None)
        if sep is not None:
            if not (merge and after_sep):
                parts.append("".join(field))
                field = []
            i += len(sep)
            at_start = True
            after_sep = True
            continue
        if not (text[i] == " " and at_start and quote
                and i + 1 < n and text[i + 1] == quote):
            field.append(text[i])
            at_start = False
        after_sep = False
        i += 1
    parts.append("".join(field))
    return [p.strip() for p in parts] if trim else parts


def split_fixed(text: str, breaks: Iterable[int], *,
                trim: bool = True) -> list[str]:
    cuts = [0] + sorted({b for b in breaks if b > 0}) + [None]
    parts = [text[a:b] for a, b in zip(cuts, cuts[1:])]
    return [p.strip() for p in parts] if trim else parts


def parse_breaks(text: str) -> Union[list[int], str]:
    """``"3, 8"`` → [3, 8], or a sentence saying what is wrong."""
    raw = [t for t in re.split(r"[\s,;]+", text.strip()) if t]
    if not raw:
        return "Type where to break, e.g. 3, 8 — after the 3rd and 8th " \
               "characters."
    try:
        breaks = sorted({int(t) for t in raw})
    except ValueError:
        return "Breaks are whole numbers, e.g. 3, 8."
    if breaks[0] < 1:
        return "Breaks start after the 1st character."
    return breaks


def split_values(values: list[str], *, mode: str = "delimited",
                 separators: Iterable[str] = (",",), merge: bool = False,
                 quote: str = '"', breaks: Iterable[int] = (),
                 trim: bool = True) -> list[list[str]]:
    """Every value split, padded to the widest row (at most MAX_PARTS)."""
    separators, breaks = list(separators), list(breaks)
    rows = []
    for text in values:
        if mode == "fixed":
            parts = split_fixed(text, breaks, trim=trim)
        else:
            parts = split_delimited(text, separators, merge=merge,
                                    quote=quote, trim=trim)
        if not any(p for p in parts):
            parts = [""]
        rows.append(parts[:MAX_PARTS])
    width = max((len(r) for r in rows), default=1)
    return [r + [""] * (width - len(r)) for r in rows]


def guess_separator(values: Iterable[str]) -> Optional[str]:
    """The separator most of the values contain — tab, ;, comma, | or
    space, in that order of preference — or None."""
    sample = [v for v in values if v.strip()][:200]
    if not sample:
        return None
    best, best_count = None, 0
    for sep in ("\t", ";", ",", "|", " "):
        count = sum(1 for v in sample if sep in v.strip())
        if count > best_count and count * 2 >= len(sample):
            best, best_count = sep, count
    return best


def new_names(base: str, count: int, existing: Iterable[str],
              keep: bool) -> list[str]:
    """Names for the columns a split makes: the original's name stays on
    the first part unless the original is kept; the rest are numbered and
    never clash with another column."""
    taken = {n.casefold() for n in existing}
    if not keep:
        taken.discard(base.casefold())
    names = []
    for i in range(count):
        if i == 0 and not keep:
            names.append(base)
            continue
        n = i + 1
        name = f"{base} {n}"
        while name.casefold() in taken or name in names:
            n += 1
            name = f"{base} {n}"
        names.append(name)
        taken.add(name.casefold())
    return names
