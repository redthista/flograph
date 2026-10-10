"""Named ranges, Qt-free: Excel's defined names (Formulas ▸ Name Manager).

A name stands for a cell or a range — ``Sales`` for ``$B$2:$B$40``,
``TaxRate`` for ``$F$1`` — so a formula can say ``=SUM(Sales)`` or
``=[@Price]*TaxRate``. Names are expanded into their references just
before a formula is parsed (`expand_names`), so everything that works
for a typed range — dependencies, recalculation, SUMIF's speed-ups —
works for a name. A name's reference is absolute and moves when rows or
columns are inserted or deleted, as a formula's references do.

A name is letters and ``_``, optionally ending in digits (``Sales``,
``Tax_rate``, ``Q4``-style names are cell addresses, so not those), not
TRUE/FALSE and not a function's name.
"""
from __future__ import annotations

import re
from typing import Optional, Union

from .formula import (FormulaSyntaxError, cell_name, col_letters,
                      shift_for_structure, tokenize)

_SHAPE = re.compile(r"^[A-Za-z_][A-Za-z_]*[0-9]*$")
_LOOKS_LIKE_CELL = re.compile(r"^[A-Za-z]{1,3}[0-9]+$")


def check_name(name: str, taken=(), functions=()) -> Optional[str]:
    """Why `name` can't be a defined name, or None."""
    name = name.strip()
    if not name:
        return "Give the name a name."
    if not _SHAPE.match(name):
        return ("A name is letters and _ — digits only at the end, no "
                "spaces: Sales, Tax_rate, Week52.")
    if _LOOKS_LIKE_CELL.match(name):
        return f"{name} is a cell address, so it can't be a name."
    if name.upper() in ("TRUE", "FALSE"):
        return f"{name} means a true/false value already."
    if name.upper() in {f.upper() for f in functions}:
        return f"{name.upper()} is a function, so it can't be a name."
    if name.casefold() in {t.casefold() for t in taken}:
        return f"There is already a name {name}."
    return None


def parse_target(text: str) -> Union[str, str]:
    """A typed reference (``B2:B40``, ``$F$1``, ``b2``) as the absolute text
    a name keeps (``$B$2:$B$40``); or an error sentence starting "!"."""
    raw = text.strip().lstrip("=")
    try:
        tokens = tokenize(raw)
    except FormulaSyntaxError:
        tokens = []
    kinds = [t.kind for t in tokens]
    if kinds == ["ref"]:
        t = tokens[0]
        return f"${col_letters(t.col)}${t.row + 1}"
    if kinds == ["ref", "colon", "ref"]:
        a, b = tokens[0], tokens[2]
        r0, r1 = sorted((a.row, b.row))
        c0, c1 = sorted((a.col, b.col))
        return (f"${col_letters(c0)}${r0 + 1}:"
                f"${col_letters(c1)}${r1 + 1}")
    return "!A name refers to a cell or a range, such as B2 or B2:B40."


def target_box(target: str) -> Optional[tuple[int, int, int, int]]:
    """(row0, col0, row1, col1) a name's reference covers, or None when it
    is broken (#REF!)."""
    try:
        tokens = tokenize(target)
    except FormulaSyntaxError:
        return None
    refs = [t for t in tokens if t.kind == "ref"]
    if len(refs) == 1:
        return refs[0].row, refs[0].col, refs[0].row, refs[0].col
    if len(refs) == 2:
        a, b = refs
        return (min(a.row, b.row), min(a.col, b.col), max(a.row, b.row),
                max(a.col, b.col))
    return None


def plain(target: str) -> str:
    """``$B$2:$B$40`` read the friendly way: ``B2:B40``."""
    box = target_box(target)
    if box is None:
        return target
    r0, c0, r1, c1 = box
    start = cell_name(r0, c0)
    return start if (r0, c0) == (r1, c1) else f"{start}:{cell_name(r1, c1)}"


_EXPANDED: dict = {}


def expand_names(src: str, names: dict) -> str:
    """`src` with each defined name swapped for its reference, ready to
    parse. A word followed by "(" is a function call, not a name; a word
    that is no name is left for the parser to complain about."""
    if not names or not (isinstance(src, str) and src.startswith("=")):
        return src
    key = (src, tuple(sorted(names.items())))
    cached = _EXPANDED.get(key)
    if cached is not None:
        return cached
    lookup = {k.casefold(): v for k, v in names.items()}
    result = _swap_words(src, lambda w: lookup.get(w.casefold()))
    if len(_EXPANDED) > 50_000:
        _EXPANDED.clear()
    _EXPANDED[key] = result
    return result


_WORD = re.compile(r"[A-Za-z_][A-Za-z_]*[0-9]*")


def _swap_words(src: str, swap) -> str:
    """`src` with each bare word replaced by `swap(word)` (None keeps it),
    in place — spacing kept, "quoted text" and [column] refs left alone, and
    a word followed by "(" (a function call) never offered."""
    out, i, n = [], 0, len(src)
    while i < n:
        ch = src[i]
        if ch == '"':
            j = i + 1
            while j < n:
                if src[j] == '"':
                    if j + 1 < n and src[j + 1] == '"':
                        j += 2
                        continue
                    break
                j += 1
            out.append(src[i:j + 1])
            i = j + 1
            continue
        if ch == "[":
            j = src.find("]", i)
            j = n - 1 if j == -1 else j
            out.append(src[i:j + 1])
            i = j + 1
            continue
        match = _WORD.match(src, i) if (ch.isalpha() or ch == "_") else None
        if match and (i == 0 or not (src[i - 1].isalnum()
                                     or src[i - 1] in "_$")):
            word = match.group(0)
            k = match.end()
            while k < n and src[k] == " ":
                k += 1
            call = k < n and src[k] == "("
            replacement = None if call else swap(word)
            out.append(word if replacement is None else replacement)
            i = match.end()
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def rename_in_formula(src: str, old: str, new: str) -> str:
    """A formula with name `old` now called `new`; others come back
    unchanged, spacing and all."""
    if not (isinstance(src, str) and src.startswith("=")):
        return src
    out = _swap_words(src, lambda w: new if w.casefold() == old.casefold()
                      else None)
    return out


def shift_names(names: dict, axis: str, at: int, count: int) -> dict:
    """Names after rows or columns were inserted or deleted, their
    references moved as a formula's are (#REF! when all of it went)."""
    out = {}
    for name, target in names.items():
        moved = shift_for_structure("=" + target, axis, at, count)
        out[name] = moved[1:] if moved.startswith("=") else moved
    return out


def clean(raw) -> dict:
    """Saved names made safe: good names whose reference reads. A name
    whose cells were deleted keeps its #REF! so it can be seen and fixed."""
    from .functions import FUNCTION_NAMES
    out: dict = {}
    for name, target in (raw.items() if isinstance(raw, dict) else ()):
        if not isinstance(name, str) or not isinstance(target, str):
            continue
        name = name.strip()
        if check_name(name, out, FUNCTION_NAMES):
            continue
        if "#REF!" in target:
            out[name] = "#REF!"
            continue
        parsed = parse_target(target)
        if not parsed.startswith("!"):
            out[name] = parsed
    return out
