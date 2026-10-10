"""F4 while typing a formula: pin the reference at the cursor — B2 →
$B$2 → B$2 → $B2 → B2, Excel's cycle.

A ``$`` keeps that part of a reference fixed when the formula is copied
or filled: ``$B$2`` always means B2, ``B$2`` keeps the row, ``$B2`` the
column. F4 cycles the reference the cursor is in or just after; a range
(``B2:B9``) moves as one, and with text selected every reference in it
moves together. Text in quotes and ``[Column]`` references are left
alone.
"""
from __future__ import annotations

import re

# a cell reference: not inside a longer word, not a function call (LOG10()
_REF = re.compile(
    r"(?<![A-Za-z0-9_$.\]])(\$?)([A-Za-z]{1,3})(\$?)(\d+)(?![A-Za-z0-9_(])")


def _protected(text: str) -> list[tuple[int, int]]:
    """Spans of "quoted text" and [column] references."""
    spans, i = [], 0
    while i < len(text):
        ch = text[i]
        if ch in "\"[":
            close = "\"" if ch == "\"" else "]"
            j = text.find(close, i + 1)
            j = len(text) if j < 0 else j + 1
            spans.append((i, j))
            i = j
        else:
            i += 1
    return spans


def references(text: str) -> list[re.Match]:
    """Every cell reference in a formula, left to right."""
    guarded = _protected(text)
    return [m for m in _REF.finditer(text)
            if not any(a <= m.start() < b for a, b in guarded)]


def _state(match: re.Match) -> int:
    """0 B2, 1 $B$2, 2 B$2, 3 $B2 — the place in the cycle."""
    col, row = bool(match.group(1)), bool(match.group(3))
    return {(False, False): 0, (True, True): 1, (False, True): 2,
            (True, False): 3}[(col, row)]


def _write(match: re.Match, state: int) -> str:
    col, row = {0: ("", ""), 1: ("$", "$"), 2: ("", "$"),
                3: ("$", "")}[state]
    return f"{col}{match.group(2)}{row}{match.group(4)}"


def cycle(text: str, start: int, end: int | None = None
          ) -> tuple[str, int, int] | None:
    """F4 on ``text`` with the cursor at ``start`` (or text selected from
    ``start`` to ``end``): the new text and the new selection (start,
    end) — the references changed, selected when a selection was given,
    else the cursor after them. None when there is nothing to cycle."""
    if not text.startswith("="):
        return None
    end = start if end is None else end
    lo, hi = min(start, end), max(start, end)
    refs = references(text)
    if not refs:
        return None
    if lo != hi:
        chosen = [m for m in refs if m.start() < hi and lo < m.end()]
    else:
        # the reference the cursor is in, or the one it just left — and
        # the other end of its range with it
        at = [m for m in refs if m.start() <= lo <= m.end()]
        if not at:
            before = [m for m in refs if m.end() <= lo
                      and not text[m.end():lo].strip()]
            at = before[-1:]
        chosen = list(at)
        for m in at:
            i = refs.index(m)
            if i + 1 < len(refs) and text[m.end():refs[i + 1].start()] == ":":
                chosen.append(refs[i + 1])
            if i > 0 and text[refs[i - 1].end():m.start()] == ":":
                chosen.insert(0, refs[i - 1])
    if not chosen:
        return None
    chosen = sorted(set(chosen), key=lambda m: m.start())
    state = (_state(chosen[0]) + 1) % 4
    out, last, shift = [], 0, 0
    first_start = chosen[0].start()
    for m in chosen:
        out.append(text[last:m.start()])
        new = _write(m, state)
        out.append(new)
        shift += len(new) - (m.end() - m.start())
        last = m.end()
    out.append(text[last:])
    new_text = "".join(out)
    new_end = chosen[-1].end() + shift
    if lo != hi:
        return new_text, first_start, new_end
    return new_text, new_end, new_end
