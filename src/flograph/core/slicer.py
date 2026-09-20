"""The Slicer's selection model — Qt-free, so the node's run(), the engine's
introspection and the three card layouts all agree on one answer.

A slicer filters on one column or on several. With several it becomes a
*hierarchy*: the columns name the levels, and a selection is a **path** down
them — `("north",)` means the whole north region, `("north", "store A")`
means one store inside it. That is the same shape Power BI's multi-field
slicer has, and it is what lets a parent tick stand for every child without
having to enumerate them.

The path is the unit everything here deals in. It travels in the node's
"selected" param as JSON:

    ["north", "south"]                     one column  (the 0.1.x form)
    [["north"], ["north", "store A"]]      several columns

A bare string is read as a one-element path, so every slicer saved before
this existed keeps working with no migration, and a single-column slicer
still writes the flat form — a file only gains the nested one when it
actually needs it.

**Paths may be ragged.** Four columns do not mean every path is four long:
a row whose deeper levels are empty ends where its data does, so a store
with no aisles is the two-level path `("north", "store A")` sitting beside
`("south", "store B", "aisle 1")`. An empty level with data still below it
is a level all the same, drawn and stored as `BLANK` — dropping it would
merge two rows that differ.
"""
from __future__ import annotations

from typing import Any, Iterable, Optional, Sequence

#: what separates the levels of a path typed by hand — in the "Values" box of
#: a standalone slicer, and in a hand-edited "Selected values". Spaces around
#: it are optional, and a value containing ">" is still reachable through the
#: JSON form.
PATH_SEP = ">"

#: what a level with nothing in it is called. It is a real level — a row
#: reading `north > (blank) > aisle 1` has no store, which is not the same
#: as having no store level at all — so it is shown, stored and matched
#: like any other value. Only *trailing* blanks are dropped (see
#: `trim_path`), because a path that runs out of data simply ends. A column
#: whose text genuinely reads "(blank)" is indistinguishable from an empty
#: one; that is the price of keeping a path a plain tuple of strings.
BLANK = "(blank)"

Path = tuple[str, ...]


def slicer_columns(raw: Any) -> list[str]:
    """The column(s) a slicer filters on, in level order. One name is the
    ordinary case; a comma list makes it a hierarchy."""
    text = str(raw or "")
    seen: set[str] = set()
    columns: list[str] = []
    for part in text.split(","):
        part = part.strip()
        if part and part not in seen:
            seen.add(part)
            columns.append(part)
    return columns


def path_label(path: Sequence[str]) -> str:
    """A path as one readable string — what a card, a tooltip or a dropdown
    button shows when it has no tree to show it in."""
    return f" {PATH_SEP} ".join(str(p) for p in path)


def parse_path(text: Any) -> Path:
    """A hand-typed `north > store A` as a path. A line with no separator is
    a one-level path, which is what a single-column slicer wants."""
    parts = [p.strip() for p in str(text or "").split(PATH_SEP)]
    return tuple(p for p in parts if p)


def is_blank(value: Any) -> bool:
    """Is there nothing at this level? True for None, for NaN (which is the
    only value not equal to itself), for text that is empty or all spaces,
    and for the `BLANK` marker itself — so trimming a path that has already
    been marked up gives the same answer as trimming the raw row.

    Deliberately *not* true for the string "nan": by the time a column has
    been stringified that is indistinguishable from data, so blankness is
    tested before the conversion, never after.
    """
    if value is None or value != value:
        return True
    return str(value).strip() in ("", BLANK)


def trim_path(values: Sequence[Any]) -> Path:
    """One row's level values as a path, ending where its data does.

    Trailing blanks are dropped — four columns over a row that only fills
    two is the two-level path, not two values and two holes. A blank with
    something still under it is kept as `BLANK`, because the levels below
    it need somewhere to hang and two rows that differ there are two rows.
    Every level blank is no path at all.
    """
    flags = [is_blank(v) for v in values]
    while flags and flags[-1]:
        flags.pop()
    return tuple(BLANK if blank else str(value)
                 for blank, value in zip(flags, values))


def as_leaves(paths: Iterable[Sequence[str]], depth: int) -> list[Path]:
    """Make every path a leaf of the tree it will be nested into.

    Trimming ends a path where its data does, which is right until another
    row runs deeper through the same values: rows with no store at all trim
    to `("north",)`, and that is the parent of every store, so ticking it
    would mean the whole region rather than the storeless rows in it.

    So a path that is also another's prefix gets its blank levels back,
    one at a time, until it is a sibling instead of a parent — `("north",)`
    becomes `("north", "(blank)")` and sits alongside `("north", "store
    A")`, which is a row anyone can tick on its own. Paths nothing runs
    past keep their short form, which is the ordinary ragged case and the
    whole point of trimming.

    Order is preserved, and `depth` (the number of columns) is the ceiling
    — nothing grows past the levels that exist.
    """
    listed = [tuple(str(v) for v in p) for p in paths if p]
    prefixes = {p[:d] for p in listed for d in range(1, len(p))}
    out: list[Path] = []
    for path in listed:
        while len(path) < depth and path in prefixes:
            path += (BLANK,)
        out.append(path)
    return out


def blank_mask(column):
    """Which rows of a DataFrame column count as blank at their level.

    Takes the column rather than importing pandas, so the one definition of
    "blank" lives here with `is_blank` instead of once in the node's run()
    and once in the engine's introspection, where they could drift.
    """
    return column.isna() | (column.astype(str).str.strip() == "")


def level_mask(column, value):
    """Which rows of a column sit at `value` — the one place a path's level
    is turned into a filter, blank levels included."""
    if value == BLANK:
        return blank_mask(column)
    return column.astype(str) == value


def selected_paths(raw: Any) -> list[Path]:
    """The ticked selections of a Slicer's "selected" param, as paths.

    Accepts everything that param can hold: the JSON array the card writes
    (of strings, of arrays, or a mix), and — for hand edits — a plain
    comma-separated list, whose entries may themselves use `>` for depth.
    Order is preserved and duplicates are dropped, so the param round-trips
    through the widget unchanged.
    """
    import json

    text = str(raw or "").strip()
    if not text:
        return []
    try:
        parsed = json.loads(text)
    except ValueError:
        parsed = [part for part in text.split(",")]
    if not isinstance(parsed, list):
        parsed = [parsed]

    seen: set[Path] = set()
    paths: list[Path] = []
    for item in parsed:
        if isinstance(item, (list, tuple)):
            path = tuple(str(p) for p in item if str(p) != "")
        else:
            path = parse_path(item)
        if path and path not in seen:
            seen.add(path)
            paths.append(path)
    return paths


def dump_paths(paths: Iterable[Sequence[str]]) -> str:
    """Paths back into the "selected" param. A selection that is one level
    deep is written flat — the form every earlier build wrote and reads — so
    a single-column slicer's file is byte-for-byte what it always was."""
    import json

    listed = [list(p) for p in paths if p]
    if not listed:
        return ""
    if all(len(p) == 1 for p in listed):
        return json.dumps([p[0] for p in listed])
    return json.dumps(listed)


def leaf_values(paths: Iterable[Sequence[str]]) -> list[str]:
    """The deepest value of each path, deduplicated in order — what the
    node's "selected" output carries, so a hierarchy still chains into the
    next control the way a flat slicer always has."""
    seen: set[str] = set()
    values: list[str] = []
    for path in paths:
        if not path:
            continue
        value = str(path[-1])
        if value not in seen:
            seen.add(value)
            values.append(value)
    return values


def is_descendant(path: Sequence[str], ancestor: Sequence[str]) -> bool:
    """True when `path` sits strictly under `ancestor`."""
    return len(path) > len(ancestor) \
        and tuple(path[:len(ancestor)]) == tuple(ancestor)


def normalise(paths: Iterable[Sequence[str]]) -> list[Path]:
    """Drop selections already covered by a shallower one.

    Ticking "north" after "north > store A" means the whole region, and
    keeping the store beside it would filter identically while making the
    card's tri-state look wrong. Order of what survives is preserved.
    """
    listed = [tuple(str(v) for v in p) for p in paths if p]
    kept: list[Path] = []
    for path in listed:
        if any(is_descendant(path, other) for other in listed):
            continue
        if path not in kept:
            kept.append(path)
    return kept


def matches(row: Sequence[str], paths: Iterable[Sequence[str]]) -> bool:
    """Does a row's level values pass this selection? A selected path keeps
    every row it prefixes, which is what makes a parent tick mean "all of
    it" without the children being listed."""
    for path in paths:
        if len(path) <= len(row) \
                and all(str(row[i]) == str(v) for i, v in enumerate(path)):
            return True
    return False


class TreeNode:
    """One level of the value hierarchy the card draws.

    Deliberately not a dataclass of the *selection*: this is the shape of
    the data, built once per refresh from the options, and the ticks are
    applied over it. A flat, one-column slicer is simply a list of these
    with no children.
    """

    __slots__ = ("value", "path", "children", "count", "row")

    def __init__(self, value: str, path: Path, count: Optional[int] = None):
        self.value = value
        self.path = path
        self.children: list[TreeNode] = []
        self.count = count
        #: is this exact path one of the rows the slicer was given, rather
        #: than only a level on the way to deeper ones? On a tree where
        #: every path is the same length that is the same thing as "has no
        #: children", and nothing has to ask. Ragged data splits the two:
        #: `north > store A` can be a row of its own *and* a branch over
        #: its aisles, and then a tick on its aisles does not stand for it.
        self.row = False

    @property
    def depth(self) -> int:
        return len(self.path)

    def walk(self):
        """This node and every descendant, parents first."""
        yield self
        for child in self.children:
            yield from child.walk()

    def __repr__(self) -> str:      # pragma: no cover - debugging aid
        return f"TreeNode({path_label(self.path)!r}, {len(self.children)} kids)"


def build_tree(paths: Iterable[Sequence[str]],
               counts: Optional[dict] = None) -> list[TreeNode]:
    """Nest a flat list of paths into levels, keeping the order they arrive
    in (introspection hands them over sorted).

    The paths need not all be the same length. Each one marks its own last
    level `row`, so a level that is both a row and a branch says so.
    """
    roots: list[TreeNode] = []
    index: dict[Path, TreeNode] = {}
    for raw in paths:
        path = tuple(str(p) for p in raw)
        for depth in range(1, len(path) + 1):
            prefix = path[:depth]
            node = index.get(prefix)
            if node is None:
                node = TreeNode(prefix[-1], prefix,
                                (counts or {}).get(prefix))
                index[prefix] = node
                if depth == 1:
                    roots.append(node)
                else:
                    index[prefix[:-1]].children.append(node)
            if depth == len(path):
                node.row = True
    return roots


class SlicerOptions:
    """What a slicer card has to draw: the paths available, the levels they
    run through, and — when the values came from a real table — how many
    rows sit under each path.

    One object rather than three parallel returns because the three layouts
    (list/tree, cards, dropdown) each need a different subset and every host
    would otherwise thread the same trio through by hand.
    """

    __slots__ = ("columns", "paths", "counts")

    def __init__(self, columns: Sequence[str],
                 paths: Iterable[Sequence[str]],
                 counts: Optional[dict] = None) -> None:
        self.columns = [str(c) for c in columns]
        self.paths = [tuple(str(v) for v in p) for p in paths]
        self.counts: dict = dict(counts or {})

    @property
    def depth(self) -> int:
        return max(1, len(self.columns))

    def tree(self) -> list[TreeNode]:
        return build_tree(self.paths, self.counts)

    def __len__(self) -> int:
        return len(self.paths)

    def __repr__(self) -> str:      # pragma: no cover - debugging aid
        return f"SlicerOptions({self.columns}, {len(self.paths)} paths)"
