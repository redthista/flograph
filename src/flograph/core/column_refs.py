"""Column names in the free text a Transform node reads.

pandas `eval` and `query` read a column called `unit price` only inside
backticks, and even then get one case wrong: the target of an assignment,
`` `line total` = `unit price` * qty ``, comes back as a column called
`BACKTICK_QUOTED_STRING_line_total`. The nodes that take typed expressions
or rules share these helpers so a name with a space in it can be written
the way it is spelled, with or without the backticks.
"""
from __future__ import annotations

import keyword
import re
from typing import Iterable, Iterator, Optional

_QUOTES = "'\"`"


def needs_backticks(name) -> bool:
    """Whether pandas can read `name` bare: an identifier that isn't a
    Python keyword."""
    text = str(name)
    return not text.isidentifier() or keyword.iskeyword(text)


def backticked(name) -> str:
    """`name` as an expression should spell it: bare when it can be,
    in backticks when it can't."""
    text = str(name)
    return f"`{text}`" if needs_backticks(text) else text


def as_typed(name) -> str:
    """`name` as a column picker should type it into node text: bare when
    the node can read it bare — an identifier, or a name with spaces that
    `quote_bare_columns` will put the backticks round — and in backticks
    only when it can't, like `price($)`."""
    text = str(name)
    if re.search(r"\s", text) and text.strip() == text:
        return text
    return backticked(text)


def unquote(text) -> str:
    """Strip surrounding whitespace and one pair of matching backticks or
    quotes: the column or value a user wrote, as the table spells it."""
    stripped = str(text).strip()
    if len(stripped) >= 2 and stripped[0] == stripped[-1] \
            and stripped[0] in _QUOTES:
        return stripped[1:-1]
    return stripped


def is_quoted(text) -> bool:
    stripped = str(text).strip()
    return len(stripped) >= 2 and stripped[0] == stripped[-1] \
        and stripped[0] in _QUOTES


def segments(text: str) -> Iterator[tuple[str, bool]]:
    """Split `text` into (chunk, quoted) pieces, in order. A quoted chunk is
    a string literal or a backticked name, delimiters included; it is to be
    passed through untouched. An unclosed quote runs to the end."""
    start = i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch not in _QUOTES:
            i += 1
            continue
        if i > start:
            yield text[start:i], False
        j = i + 1
        while j < n and text[j] != ch:
            # a backslash escapes the next character inside a string, the
            # way Python reads it; a backticked name has no escapes
            j += 2 if text[j] == "\\" and ch != "`" else 1
        end = min(j + 1, n)
        yield text[i:end], True
        start = i = end
    if start < n:
        yield text[start:], False


def find_outside_quotes(text: str, token: str) -> int:
    """Index of the first `token` not inside quotes or backticks, else -1."""
    offset = 0
    for chunk, quoted in segments(text):
        if not quoted:
            index = chunk.find(token)
            if index != -1:
                return offset + index
        offset += len(chunk)
    return -1


def split_keyword(text: str, word: str) -> list[str]:
    """Split on a whole word (`and`, `or`) with space either side, in any
    case, wherever it isn't inside quotes or backticks."""
    pattern = re.compile(rf"\s+{re.escape(word)}\s+", re.IGNORECASE)
    parts, current = [], ""
    for chunk, quoted in segments(text):
        if quoted:
            current += chunk
            continue
        pieces = pattern.split(chunk)
        current += pieces[0]
        for piece in pieces[1:]:
            parts.append(current)
            current = piece
    parts.append(current)
    return parts


def quote_bare_columns(text: str, columns: Iterable) -> str:
    """Put backticks round every column name in `text` that has a space in
    it and is written bare — outside quotes and backticks, and not part of
    a longer word. Longest names first, so `unit price usd` is never read
    as `unit price` followed by `usd`.

    Only names with whitespace: `a-b` could as well be `a` minus `b`, so a
    name like that still needs its backticks written."""
    spaced = sorted({str(c) for c in columns if re.search(r"\s", str(c))
                     and str(c).strip() == str(c)}, key=len, reverse=True)
    if not spaced:
        return text
    pattern = re.compile(
        r"(?<![\w`])(" + "|".join(re.escape(c) for c in spaced) + r")(?![\w`])")
    return "".join(
        chunk if quoted else pattern.sub(lambda m: f"`{m.group(1)}`", chunk)
        for chunk, quoted in segments(text))


def split_assignment(line: str) -> Optional[tuple[str, str]]:
    """`target = expression` → (target, expression), the target unquoted.
    The `=` is the first one outside quotes that isn't part of `==`, `<=`,
    `>=` or `!=`. None when the line assigns nothing."""
    offset = 0
    for chunk, quoted in segments(line):
        if not quoted:
            for i, ch in enumerate(chunk):
                if ch != "=":
                    continue
                at = offset + i
                before = line[at - 1] if at else ""
                after = line[at + 1] if at + 1 < len(line) else ""
                if (before and before in "=<>!") or after == "=":
                    continue
                return unquote(line[:at]), line[at + 1:].strip()
        offset += len(chunk)
    return None
