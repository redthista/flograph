"""The `column operator value` condition language, joined with `and` / `or`.

Shared by Conditional Column (`condition => result` rules) and Filter Rows
(its Advanced *Conditions* box), so the two read a condition the same way.
This only parses: each node decides what an operator does to its cells.

    region = North and units >= 100
    status = open or pending            # the column and operator repeat
    score > 50 and < 80                 # the column repeats
    `unit price` >= 5                   # a name with a space, backticked
    name = "Tom and Jerry"              # quoted: and / or are just text

`and` binds tighter than `or`, so `a and b or c` is *(a and b) or c*.
Pure string work — no pandas, no Qt.
"""
from __future__ import annotations

# Canonical operator names, as `parse_condition` returns them.
SUFFIX_OPS = ["is not empty", "is empty"]
WORD_OPS = [("does not contain", "not contains"),
            ("not contains", "not contains"),
            ("contains", "contains"), ("starts with", "starts"),
            ("ends with", "ends"), ("starts", "starts"),
            ("ends", "ends"), ("matches", "matches")]
SYM_OPS = [("!=", "!="), ("<=", "<="), (">=", ">="), ("==", "="),
           ("=", "="), ("<", "<"), (">", ">")]
# stands in for a backticked column while the operator is looked for, so a
# name with an operator word or symbol in it can't be mistaken for one
_HELD = "\x00"


def find_operator(cond: str):
    """(column, operator, value) for the left-most operator, or None."""
    low = cond.lower()
    for op in SUFFIX_OPS:
        if low == op or low.endswith(f" {op}"):
            return cond[:len(cond) - len(op)].strip(), op, None
    found = []
    for token, canon in WORD_OPS:
        idx = low.find(f" {token} ")
        if idx != -1:
            found.append((idx, -len(token), idx + len(token) + 2, canon))
        elif low.startswith(f"{token} "):
            # `and starts with x`: the column is carried from the last one
            found.append((0, -len(token), len(token) + 1, canon))
    for token, canon in SYM_OPS:
        idx = cond.find(token)
        if idx != -1:
            found.append((idx, -len(token), idx + len(token), canon))
    if not found:
        return None
    # left-most wins, so `note = it contains x` compares note; at one place
    # the longer token, so `<=` is never read as `<`
    idx, _, value_at, canon = min(found)
    return cond[:idx].strip(), canon, cond[value_at:].strip()


def parse_clause(where: str, clause: str, previous):
    """(column, operator, value, quoted) for one clause; `previous` is the
    clause before it, whose column (and operator) a short clause repeats."""
    from flograph.core.column_refs import is_quoted, unquote

    text = clause.strip()
    if not text:
        raise ValueError(f"{where}: nothing between 'and' / 'or'")
    held = None
    probe = text
    if text.startswith("`"):
        end = text.find("`", 1)
        if end == -1:
            raise ValueError(f"{where}: no closing ` in {text!r}")
        held = text[1:end]
        probe = f"{_HELD} {text[end + 1:].strip()}"
    found = find_operator(probe)
    if found is not None and held is not None and found[0] != _HELD:
        raise ValueError(f"{where}: expected an operator straight "
                         f"after `{held}` in {text!r}")
    if found is not None:
        column, op, value = found
        if column == _HELD:
            column = held
        elif not column:
            if previous is None:
                raise ValueError(f"{where}: no column before {op!r} "
                                 f"in {text!r}")
            column = previous[0]
        else:
            column = unquote(column)
    elif previous is not None and previous[2] is not None:
        # a bare value: the column and operator before it, again
        column, op, value = previous[0], previous[1], text
    else:
        raise ValueError(f"{where}: no operator found in condition "
                         f"{text!r}")
    quoted = value is not None and is_quoted(value)
    if value is not None:
        value = unquote(value)
    return (column, op, value, quoted)


def parse_condition(where: str, cond: str, columns=()):
    """A condition as groups to OR, each a list of clauses to AND."""
    from flograph.core.column_refs import quote_bare_columns, split_keyword

    cond = quote_bare_columns(cond, columns)
    groups, previous = [], None
    for alternative in split_keyword(cond, "or"):
        group = []
        for clause in split_keyword(alternative, "and"):
            previous = parse_clause(where, clause, previous)
            group.append(previous)
        groups.append(group)
    return groups
