"""Grouped rows, Qt-free: Excel's outline (Data ▸ Group).

A group is a run of rows that can be folded away under a −/+ button.
Groups nest — a group inside a group is one level deeper, up to
MAX_LEVELS — but never partly overlap. The button sits on the row just
after the group (Excel's "summary rows below detail"), or just before it
when the group runs to the last row; a group can't take in every row, or
there would be nowhere to put its button.

Whether a group is folded is view state, like a filter: it is kept on the
group so it follows the rows through edits, but it is not saved and
folding is not an edit.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Union

MAX_LEVELS = 7


@dataclass
class Group:
    start: int
    end: int                  # inclusive
    collapsed: bool = False

    def contains(self, other: "Group") -> bool:
        return self.start <= other.start and other.end <= self.end

    def covers(self, row: int) -> bool:
        return self.start <= row <= self.end


def _overlap(a: Group, b: Group) -> bool:
    return a.start <= b.end and b.start <= a.end


def level_of(groups: list[Group], group: Group) -> int:
    """1 for an outermost group, 2 for one inside it, … A group over the
    very same rows as another sits inside the one listed first."""
    me = next(i for i, g in enumerate(groups) if g is group)
    level = 1
    for i, g in enumerate(groups):
        if g is group or not g.contains(group):
            continue
        same = (g.start, g.end) == (group.start, group.end)
        if not same or i < me:
            level += 1
    return level


def depth(groups: list[Group]) -> int:
    return max((level_of(groups, g) for g in groups), default=0)


def add_group(groups: list[Group], start: int, end: int,
              n_rows: int) -> Union[list[Group], str]:
    """`groups` with rows start..end grouped, or why that can't be."""
    start, end = sorted((start, end))
    if start < 0 or end >= n_rows:
        return "Those rows are outside the table."
    if start == 0 and end == n_rows - 1:
        return ("A group can't take in every row — leave one outside it "
                "for the group's −/+ button.")
    new = Group(start, end)
    for g in groups:
        if _overlap(g, new) and not (g.contains(new) or new.contains(g)):
            return (f"Rows {start + 1}–{end + 1} cross the group of rows "
                    f"{g.start + 1}–{g.end + 1}. Groups can sit inside one "
                    "another, not partly overlap.")
    out = [Group(g.start, g.end, g.collapsed) for g in groups] + [new]
    if level_of(out, out[-1]) > MAX_LEVELS or depth(out) > MAX_LEVELS:
        return f"Groups go at most {MAX_LEVELS} deep."
    return sorted(out, key=lambda g: (g.start, -g.end))


def remove_group(groups: list[Group], start: int,
                 end: int) -> list[Group]:
    """Ungroup: take off the deepest groups that touch rows start..end —
    one level per call, as Excel's Ungroup does."""
    start, end = sorted((start, end))
    touching = [g for g in groups if _overlap(g, Group(start, end))]
    if not touching:
        return list(groups)
    deepest = max(level_of(groups, g) for g in touching)
    gone = {id(g) for g in touching if level_of(groups, g) == deepest}
    return [g for g in groups if id(g) not in gone]


def button_row(group: Group, n_rows: int) -> int:
    """Where the group's −/+ button sits: the row after, or before when
    the group runs to the end."""
    return group.end + 1 if group.end + 1 < n_rows else group.start - 1


def hidden_rows(groups: list[Group]) -> set[int]:
    """Every row inside a folded group."""
    rows: set[int] = set()
    for g in groups:
        if g.collapsed:
            rows.update(range(g.start, g.end + 1))
    return rows


def innermost_at(groups: list[Group], row: int,
                 n_rows: int) -> Optional[Group]:
    """The deepest group holding `row`, or whose button is on it — what
    Hide Detail / Show Detail act on from the current row."""
    hits = [g for g in groups
            if g.covers(row) or button_row(g, n_rows) == row]
    if not hits:
        return None
    return max(hits, key=lambda g: (level_of(groups, g), -g.start))


# ------------------------------------------------- following the rows

def after_insert(groups: list[Group], at: int, count: int) -> list[Group]:
    """Rows inserted at `at`: groups below shift down; a group they land
    inside grows."""
    out = []
    for g in groups:
        if g.start >= at:
            out.append(Group(g.start + count, g.end + count, g.collapsed))
        elif g.end >= at:
            out.append(Group(g.start, g.end + count, g.collapsed))
        else:
            out.append(g)
    return out


def after_remove(groups: list[Group], row: int) -> list[Group]:
    """One row deleted: groups below shift up, a group holding it shrinks,
    and one left with no rows goes."""
    out = []
    for g in groups:
        if g.start > row:
            out.append(Group(g.start - 1, g.end - 1, g.collapsed))
        elif g.end >= row:
            if g.start == g.end:
                continue
            out.append(Group(g.start, g.end - 1, g.collapsed))
        else:
            out.append(g)
    return out


def clamp(groups: list[Group], n_rows: int) -> list[Group]:
    """Groups that still fit a table of `n_rows` rows (a linked refresh can
    shorten it)."""
    out = []
    for g in groups:
        if g.start >= n_rows:
            continue
        g = Group(g.start, min(g.end, n_rows - 1), g.collapsed)
        if g.start == 0 and g.end == n_rows - 1:
            continue
        out.append(g)
    return out


def parse(raw, n_rows: int) -> list[Group]:
    """Saved groups ([[start, end], …]) made safe: in range, properly
    nested."""
    groups: list[Group] = []
    for entry in raw if isinstance(raw, list) else ():
        if (isinstance(entry, (list, tuple)) and len(entry) >= 2
                and all(isinstance(v, int) and not isinstance(v, bool)
                        for v in entry[:2])):
            added = add_group(groups, entry[0], entry[1], n_rows)
            if not isinstance(added, str):
                groups = added
    return groups


def to_list(groups: list[Group]) -> list[list[int]]:
    return [[g.start, g.end] for g in groups]
